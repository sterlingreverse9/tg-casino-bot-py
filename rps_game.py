import random
import time
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

# Import your win updates broadcaster function if available (e.g., from helpers or admin)
try:
    from helpers import send_win_update  # Adjust module/function name as per your project
except ImportError:
    def send_win_update(*args, **kwargs):
        pass

active_rps_games = {}


def fetch_configured_win_rate(user_id: int) -> float | None:
    rate = None

    # Check admin module
    try:
        import admin
        if hasattr(admin, "get_user_win_rate"):
            rate = admin.get_user_win_rate(user_id)
        elif hasattr(admin, "WIN_RATES") and user_id in admin.WIN_RATES:
            rate = admin.WIN_RATES[user_id]
    except Exception:
        pass

    # Check helpers module
    if rate is None:
        try:
            import helpers
            if hasattr(helpers, "get_user_win_rate"):
                rate = helpers.get_user_win_rate(user_id)
            elif hasattr(helpers, "WIN_RATES") and user_id in helpers.WIN_RATES:
                rate = helpers.WIN_RATES[user_id]
        except Exception:
            pass

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
        except Exception:
            pass

    if rate is None:
        return None

    rate = float(rate)
    # Convert percentage (e.g., 100 or 50) to decimal scale (1.0 or 0.5) if needed
    if rate > 1.0:
        rate = rate / 100.0

    return rate


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

    # Handle bot choice with fixed win rate check
    if game["is_bot"]:
        win_rate = fetch_configured_win_rate(game["host_id"])

        if win_rate is not None:
            if win_rate <= 0.0:
                # Force user to LOSE: Bot picks move that beats user choice
                game["opponent_choice"] = COUNTER_WIN[move]
            elif win_rate >= 1.0:
                # Force user to WIN: Bot picks move that loses to user choice
                game["opponent_choice"] = COUNTER_LOSE[move]
            else:
                if random.random() < win_rate:
                    game["opponent_choice"] = COUNTER_LOSE[move]
                else:
                    game["opponent_choice"] = COUNTER_WIN[move]
        else:
            game["opponent_choice"] = random.choice(["rock", "scissors", "paper"])

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

    # Tie Condition
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

        # Adjust balances and record bets
        if winner_id != 0:
            adjust_balance(winner_id, payout)
            record_bet(winner_id, "rps", bet, payout, "WIN")
            
            # Trigger Win Channel Update for real user wins
            try:
                send_win_update(
                    user_id=winner_id,
                    user_name=winner_name,
                    game_name="RPS ✊✌️✋",
                    bet=bet,
                    payout=payout,
                    multiplier=RPS_DEFAULT_MULTIPLIER
                )
            except Exception:
                pass

        if loser_id != 0:
            record_bet(loser_id, "rps", bet, 0.0, "LOSE")

        # Fixed display text: Only show profit payout for user, or 0.00 for loss
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
