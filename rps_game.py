import random
import time
import sys
import traceback
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton, Message, CallbackQuery

from bot_instance import bot
from wallet import (
    get_balance,
    adjust_balance,
    resolve_amount,
    record_bet,
    get_or_create_user
)
from config_rps import RPS_MIN_BET, RPS_MAX_BET, RPS_DEFAULT_MULTIPLIER, EMOJI_MAP, COUNTER_WIN, COUNTER_LOSE

active_rps_games = {}


def fetch_configured_win_rate(user_id: int) -> float | None:
    rate = None

    # Check admin module
    try:
        import admin
        if hasattr(admin, "get_user_win_rate"):
            rate = admin.get_user_win_rate(user_id)
            print(f"[RPS DEBUG] admin.get_user_win_rate({user_id}) returned: {rate}", file=sys.stderr)
        elif hasattr(admin, "WIN_RATES") and user_id in admin.WIN_RATES:
            rate = admin.WIN_RATES[user_id]
            print(f"[RPS DEBUG] admin.WIN_RATES[{user_id}] returned: {rate}", file=sys.stderr)
        elif hasattr(admin, "WIN_RATES") and "all" in admin.WIN_RATES:
            rate = admin.WIN_RATES["all"]
            print(f"[RPS DEBUG] admin.WIN_RATES['all'] returned: {rate}", file=sys.stderr)
    except Exception as e:
        print(f"[RPS DEBUG ERROR] Admin check failed: {e}", file=sys.stderr)

    # Check helpers module
    if rate is None:
        try:
            import helpers
            if hasattr(helpers, "get_user_win_rate"):
                rate = helpers.get_user_win_rate(user_id)
                print(f"[RPS DEBUG] helpers.get_user_win_rate({user_id}) returned: {rate}", file=sys.stderr)
            elif hasattr(helpers, "WIN_RATES") and user_id in helpers.WIN_RATES:
                rate = helpers.WIN_RATES[user_id]
                print(f"[RPS DEBUG] helpers.WIN_RATES[{user_id}] returned: {rate}", file=sys.stderr)
            elif hasattr(helpers, "WIN_RATES") and "all" in helpers.WIN_RATES:
                rate = helpers.WIN_RATES["all"]
                print(f"[RPS DEBUG] helpers.WIN_RATES['all'] returned: {rate}", file=sys.stderr)
        except Exception as e:
            print(f"[RPS DEBUG ERROR] Helpers check failed: {e}", file=sys.stderr)

    # Check SQLite Database
    if rate is None:
        try:
            import sqlite3
            conn = sqlite3.connect("database.db")
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("SELECT win_rate FROM users WHERE telegram_id = ?", (user_id,))
            row = cursor.fetchone()
            conn.close()
            if row and row["win_rate"] is not None:
                rate = row["win_rate"]
                print(f"[RPS DEBUG] DB win_rate for {user_id} returned: {rate}", file=sys.stderr)
        except Exception as e:
            print(f"[RPS DEBUG ERROR] DB check failed: {e}", file=sys.stderr)

    if rate is None:
        print(f"[RPS DEBUG] No setwin found for user {user_id}. Defaulting to random.", file=sys.stderr)
        return None

    try:
        rate = float(rate)
        if rate > 1.0:
            rate = rate / 100.0
        print(f"[RPS DEBUG] Final normalized win rate: {rate}", file=sys.stderr)
        return rate
    except ValueError as e:
        print(f"[RPS DEBUG ERROR] Rate conversion failed for {rate}: {e}", file=sys.stderr)
        return None


@bot.message_handler(commands=["rps"])
def handle_rps_command(message: Message):
    user = message.from_user
    get_or_create_user(user.id, user.username, user.first_name)

    parts = message.text.split()
    bet_amount = RPS_MIN_BET

    if len(parts) > 1:
        resolved = resolve_amount(user.id, parts[1])
        if resolved is not None:
            bet_amount = resolved

    if bet_amount < RPS_MIN_BET:
        bot.reply_to(message, f"⚠️ The bet cannot be lower than ₹{RPS_MIN_BET:.2f}")
        return

    if bet_amount > RPS_MAX_BET:
        bot.reply_to(message, f"⚠️ The bet cannot be higher than ₹{RPS_MAX_BET:.2f}")
        return

    user_bal = get_balance(user.id)
    if user_bal < bet_amount:
        bot.reply_to(message, f"⚠️ Insufficient balance! Your balance: ₹{user_bal:.2f}")
        return

    text = (
        f"🌐 <b>Game in ✊✌️✋ RPS by {user.first_name}</b>\n\n"
        f"<b>Bet:</b> ₹{bet_amount:.2f}\n"
        f"<b>Multiplier:</b> ×{RPS_DEFAULT_MULTIPLIER:.2f}"
    )

    markup = InlineKeyboardMarkup(row_width=1)
    markup.add(
        InlineKeyboardButton("Accept game", callback_data=f"rps_accept:{user.id}:{bet_amount}"),
        InlineKeyboardButton("🤖 Play against bot", callback_data=f"rps_bot:{user.id}:{bet_amount}"),
        InlineKeyboardButton("🚫 Cancel game", callback_data=f"rps_cancel:{user.id}")
    )

    sent = bot.reply_to(message, text, parse_mode="HTML", reply_markup=markup)

    active_rps_games[sent.message_id] = {
        "host_id": user.id,
        "host_name": user.first_name,
        "opponent_id": None,
        "opponent_name": None,
        "is_bot": False,
        "bet": bet_amount,
        "host_choice": None,
        "opponent_choice": None,
        "status": "WAITING"
    }


@bot.callback_query_handler(func=lambda call: call.data.startswith("rps_cancel:"))
def callback_cancel_rps(call: CallbackQuery):
    host_id = int(call.data.split(":")[1])
    if call.from_user.id != host_id:
        bot.answer_callback_query(call.id, "❌ Only the creator can cancel this game!", show_alert=True)
        return

    msg_id = call.message.message_id
    if msg_id in active_rps_games:
        del active_rps_games[msg_id]

    bot.edit_message_text("🚫 <b>Game cancelled.</b>", chat_id=call.message.chat.id, message_id=msg_id, parse_mode="HTML")


@bot.callback_query_handler(func=lambda call: call.data.startswith("rps_bot:"))
def callback_play_bot(call: CallbackQuery):
    parts = call.data.split(":")
    host_id = int(parts[1])
    bet_amount = float(parts[2])

    if call.from_user.id != host_id:
        bot.answer_callback_query(call.id, "❌ You did not create this game!", show_alert=True)
        return

    user_bal = get_balance(host_id)
    if user_bal < bet_amount:
        bot.answer_callback_query(call.id, "❌ Insufficient balance to start!", show_alert=True)
        return

    adjust_balance(host_id, -bet_amount)

    msg_id = call.message.message_id
    bot_name = bot.get_me().first_name

    active_rps_games[msg_id] = {
        "host_id": host_id,
        "host_name": call.from_user.first_name,
        "opponent_id": 0,
        "opponent_name": f"🤖 {bot_name}",
        "is_bot": True,
        "bet": bet_amount,
        "host_choice": None,
        "opponent_choice": None,
        "status": "PLAYING"
    }

    start_game_ui(call.message.chat.id, msg_id)


@bot.callback_query_handler(func=lambda call: call.data.startswith("rps_accept:"))
def callback_accept_pvp(call: CallbackQuery):
    parts = call.data.split(":")
    host_id = int(parts[1])
    bet_amount = float(parts[2])
    opponent = call.from_user

    if opponent.id == host_id:
        bot.answer_callback_query(call.id, "❌ You cannot play against yourself!", show_alert=True)
        return

    opp_bal = get_balance(opponent.id)
    if opp_bal < bet_amount:
        bot.answer_callback_query(call.id, "❌ You do not have enough balance to accept!", show_alert=True)
        return

    host_bal = get_balance(host_id)
    if host_bal < bet_amount:
        bot.answer_callback_query(call.id, "❌ Host no longer has enough balance!", show_alert=True)
        return

    adjust_balance(host_id, -bet_amount)
    adjust_balance(opponent.id, -bet_amount)

    msg_id = call.message.message_id
    game = active_rps_games.get(msg_id, {})
    game.update({
        "opponent_id": opponent.id,
        "opponent_name": opponent.first_name,
        "is_bot": False,
        "status": "PLAYING"
    })

    start_game_ui(call.message.chat.id, msg_id)


def start_game_ui(chat_id: int, message_id: int):
    game = active_rps_games.get(message_id)
    if not game:
        return

    text = (
        f"🌐 <b>The game has started</b>\n\n"
        f"<b>Player 1:</b> {game['host_name']}\n"
        f"<b>Player 2:</b> {game['opponent_name']}\n"
        f"<b>Bet:</b> ₹{game['bet']:.2f}\n\n"
        f"<i>Select an action using the buttons below.\n"
        f"If a player does not choose within 30 seconds, the choice will be made automatically.</i>"
    )

    markup = InlineKeyboardMarkup(row_width=3)
    markup.add(
        InlineKeyboardButton("✊", callback_data=f"rps_move:{message_id}:rock"),
        InlineKeyboardButton("✌️", callback_data=f"rps_move:{message_id}:scissors"),
        InlineKeyboardButton("✋", callback_data=f"rps_move:{message_id}:paper")
    )

    bot.edit_message_text(text, chat_id=chat_id, message_id=message_id, parse_mode="HTML", reply_markup=markup)


@bot.callback_query_handler(func=lambda call: call.data.startswith("rps_move:"))
def callback_make_move(call: CallbackQuery):
    parts = call.data.split(":")
    message_id = int(parts[1])
    move = parts[2]
    user_id = call.from_user.id

    game = active_rps_games.get(message_id)
    if not game or game["status"] != "PLAYING":
        bot.answer_callback_query(call.id, "⚠️ Game session expired or invalid.")
        return

    if user_id not in [game["host_id"], game["opponent_id"]]:
        bot.answer_callback_query(call.id, "❌ You are not part of this game!", show_alert=True)
        return

    if user_id == game["host_id"]:
        if game["host_choice"] is not None:
            bot.answer_callback_query(call.id, "⚠️ You already picked!", show_alert=True)
            return
        game["host_choice"] = move
    elif user_id == game["opponent_id"]:
        if game["opponent_choice"] is not None:
            bot.answer_callback_query(call.id, "⚠️ You already picked!", show_alert=True)
            return
        game["opponent_choice"] = move

    bot.answer_callback_query(call.id, f"You chose {EMOJI_MAP[move]}")

    if game["is_bot"]:
        win_rate = fetch_configured_win_rate(game["host_id"])

        if win_rate is not None:
            if win_rate <= 0.0:
                game["opponent_choice"] = COUNTER_WIN[move]
                print(f"[RPS DEBUG] FORCED LOSS: User chose {move}, Bot picked {game['opponent_choice']}", file=sys.stderr)
            elif win_rate >= 1.0:
                game["opponent_choice"] = COUNTER_LOSE[move]
                print(f"[RPS DEBUG] FORCED WIN: User chose {move}, Bot picked {game['opponent_choice']}", file=sys.stderr)
            else:
                if random.random() < win_rate:
                    game["opponent_choice"] = COUNTER_LOSE[move]
                else:
                    game["opponent_choice"] = COUNTER_WIN[move]
                print(f"[RPS DEBUG] PROBABILITY RESULT ({win_rate}): Bot picked {game['opponent_choice']}", file=sys.stderr)
        else:
            game["opponent_choice"] = random.choice(["rock", "scissors", "paper"])
            print(f"[RPS DEBUG] RANDOM CHOICE: Bot picked {game['opponent_choice']}", file=sys.stderr)

    if game["host_choice"] and game["opponent_choice"]:
        resolve_rps_game(call.message.chat.id, message_id)


def resolve_rps_game(chat_id: int, message_id: int):
    game = active_rps_games.pop(message_id, None)
    if not game:
        return

    c1 = game["host_choice"]
    c2 = game["opponent_choice"]
    bet = game["bet"]
    payout = bet * RPS_DEFAULT_MULTIPLIER

    if c1 == c2:
        adjust_balance(game["host_id"], bet)
        if not game["is_bot"]:
            adjust_balance(game["opponent_id"], bet)

        res_text = (
            f"🌐 <b>The game has ended</b>\n\n"
            f"🤝 <b>Draw! Both chose {EMOJI_MAP[c1]}</b>\n"
            f"💰 <b>Bets refunded: ₹{bet:.2f}</b>"
        )
    else:
        host_won = (COUNTER_WIN[c2] == c1)

        if host_won:
            winner_id, winner_name, winner_choice = game["host_id"], game["host_name"], c1
            loser_id, loser_name, loser_choice = game["opponent_id"], game["opponent_name"], c2
        else:
            winner_id, winner_name, winner_choice = game["opponent_id"], game["opponent_name"], c2
            loser_id, loser_name, loser_choice = game["host_id"], game["host_name"], c1

        if winner_id != 0:
            adjust_balance(winner_id, payout)
            record_bet(winner_id, "rps", bet, payout, "WIN")

            # Debug win updates channel sending
            try:
                import helpers
                found_func = False
                for func_name in ["send_win_update", "post_win", "broadcast_win"]:
                    if hasattr(helpers, func_name):
                        getattr(helpers, func_name)(
                            user_id=winner_id,
                            user_name=winner_name,
                            game_name="RPS ✊✌️✋",
                            bet=bet,
                            payout=payout,
                            multiplier=RPS_DEFAULT_MULTIPLIER
                        )
                        print(f"[RPS DEBUG] Called helpers.{func_name}() successfully!", file=sys.stderr)
                        found_func = True
                        break

                if not found_func:
                    print("[RPS DEBUG ERROR] Could not find win broadcast function in helpers.py!", file=sys.stderr)
            except Exception as e:
                print(f"[RPS DEBUG ERROR] Exception while broadcasting win: {e}", file=sys.stderr)
                traceback.print_exc()

        if loser_id != 0:
            record_bet(loser_id, "rps", bet, 0.0, "LOSE")

        display_winnings = payout if winner_id != 0 else 0.0

        res_text = (
            f"🌐 <b>The game has ended</b>\n\n"
            f"👑 <b>Winner:</b> {winner_name} - {EMOJI_MAP[winner_choice]}\n"
            f"👎 <b>Loser:</b> {loser_name} - {EMOJI_MAP[loser_choice]}\n"
            f"💰 <b>Winnings: ₹{display_winnings:.2f}</b>"
        )

    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(
        InlineKeyboardButton("🔄 Repeat", callback_data=f"rps_repeat:{game['host_id']}:{bet}"),
        InlineKeyboardButton("×2 Double", callback_data=f"rps_repeat:{game['host_id']}:{bet * 2}")
    )

    bot.edit_message_text(res_text, chat_id=chat_id, message_id=message_id, parse_mode="HTML", reply_markup=markup)


@bot.callback_query_handler(func=lambda call: call.data.startswith("rps_repeat:"))
def callback_repeat_rps(call: CallbackQuery):
    parts = call.data.split(":")
    user_id = int(parts[1])
    bet_amount = float(parts[2])

    if call.from_user.id != user_id:
        bot.answer_callback_query(call.id, "❌ Create your own game using /rps", show_alert=True)
        return

    call.message.from_user = call.from_user
    call.message.text = f"/rps {bet_amount}"
    handle_rps_command(call.message)
