import html
import threading
import time
from bot_instance import bot
from games.tictactoe import TicTacToeGame
from telebot.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)
from wallet import adjust_balance, get_balance, record_bet

MIN_BET = 5.0
MAX_BET = 50.0
WINS_CHANNEL = "@thecassinowins"  # Replace with actual wins channel
CASINO_GROUP = "thecassinogroup"

ACTIVE_CHALLENGES = {}  # challenge_id -> dict data
ACTIVE_GAMES = {}  # game_id -> TicTacToeGame instance
GAME_METADATA = {}  # game_id -> dict {"chat_id": int, "msg_id": int}


def build_board_markup(game_id: str, board: list, is_finished: bool = False):
    markup = InlineKeyboardMarkup(row_width=3)
    buttons = []
    for idx, spot in enumerate(board):
        btn_text = spot
        cb_data = (
            "ignore"
            if is_finished or spot != "⬜"
            else f"ttt_move:{game_id}:{idx}"
        )
        buttons.append(
            InlineKeyboardButton(text=btn_text, callback_data=cb_data)
        )

    markup.add(buttons[0], buttons[1], buttons[2])
    markup.add(buttons[3], buttons[4], buttons[5])
    markup.add(buttons[6], buttons[7], buttons[8])
    return markup


# Background worker thread to monitor 30-second turn timeouts
def _turn_timeout_monitor():
    while True:
        time.sleep(3)  # Check all active games every 3 seconds
        game_ids = list(ACTIVE_GAMES.keys())

        for game_id in game_ids:
            game = ACTIVE_GAMES.get(game_id)
            if not game or game.is_finished:
                continue

            timed_out, timeout_msg = game.check_timeout()
            if timed_out:
                ACTIVE_GAMES.pop(game_id, None)
                meta = GAME_METADATA.pop(game_id, {})

                winner_id, winner_name = (
                    game.x_player if game.winner == "X" else game.o_player
                )
                loser_id, loser_name = (
                    game.o_player if game.winner == "X" else game.x_player
                )

                # Award 1.90x Payout to Winner
                payout = game.get_payout()
                profit = payout - game.bet_amount

                adjust_balance(winner_id, payout)
                record_bet(
                    winner_id, "tictactoe", game.bet_amount, payout, "win"
                )
                record_bet(loser_id, "tictactoe", game.bet_amount, 0.0, "loss")

                summary = (
                    f"⏰ <b>MATCH RESULT: TIMEOUT FORFEIT!</b>\n"
                    f"────────────────────────\n"
                    f"🥇 <b>Winner:</b> {winner_name}\n"
                    f"🥈 <b>Opponent:</b> {loser_name} (Timed Out)\n"
                    f"💰 <b>Total Payout:</b> ₹{payout:.2f} (Profit: +₹{profit:.2f})\n\n"
                    f"<i>{timeout_msg}</i>"
                )

                if meta and "chat_id" in meta and "msg_id" in meta:
                    try:
                        bot.edit_message_text(
                            summary,
                            chat_id=meta["chat_id"],
                            message_id=meta["msg_id"],
                            parse_mode="HTML",
                            reply_markup=build_board_markup(
                                game_id, game.board, is_finished=True
                            ),
                        )
                    except Exception as e:
                        print(f"[TTT Timeout Edit Error]: {e}")


# Start timeout monitoring loop on module import
threading.Thread(target=_turn_timeout_monitor, daemon=True).start()


@bot.message_handler(commands=["ttt", "tictactoe"])
def handle_ttt_challenge(message: Message):
    try:
        if message.chat.type == "private":
            markup = InlineKeyboardMarkup()
            markup.add(
                InlineKeyboardButton(
                    "Play in Group 🎰", url=f"https://t.me/{CASINO_GROUP}"
                )
            )
            bot.reply_to(
                message,
                "⚠️ Tic-Tac-Toe is a multiplayer game. Please use this command in our group chat!",
                reply_markup=markup,
            )
            return

        args = message.text.split()[1:]
        if len(args) < 2:
            bot.reply_to(
                message,
                "⚠️ Usage: <code>/ttt &lt;amt&gt; &lt;@username&gt;</code> or <code>/ttt &lt;@username&gt; &lt;amt&gt;</code>",
                parse_mode="HTML",
            )
            return

        bet_amount = None
        target_username = None

        for arg in args:
            clean_arg = arg.strip()
            if clean_arg.startswith("@"):
                target_username = clean_arg[1:]
            else:
                try:
                    bet_amount = float(clean_arg)
                except ValueError:
                    pass

        if not target_username or bet_amount is None:
            bot.reply_to(
                message,
                "⚠️ Invalid command syntax. Example: <code>/ttt 10 @DarkAurora083</code>",
                parse_mode="HTML",
            )
            return

        if bet_amount < MIN_BET or bet_amount > MAX_BET:
            bot.reply_to(
                message,
                f"⚠️ Bet amount must be between ₹{MIN_BET:.2f} and ₹{MAX_BET:.2f}.",
            )
            return

        p1_id = message.from_user.id
        p1_name = (
            f"@{message.from_user.username}"
            if message.from_user.username
            else message.from_user.first_name
        )

        if p1_name.lower().replace("@", "") == target_username.lower():
            bot.reply_to(message, "❌ You cannot challenge yourself!")
            return

        p1_bal = get_balance(p1_id)
        if p1_bal < bet_amount:
            bot.reply_to(
                message,
                f"❌ Insufficient balance. Your balance: ₹{p1_bal:.2f}",
            )
            return

        challenge_id = f"ch_{p1_id}_{int(time.time())}"

        markup = InlineKeyboardMarkup()
        markup.add(
            InlineKeyboardButton(
                "✅ Accept", callback_data=f"ttt_accept:{challenge_id}"
            ),
            InlineKeyboardButton(
                "❌ Decline", callback_data=f"ttt_decline:{challenge_id}"
            ),
        )

        msg_text = (
            f"⚔️ <b>TIC-TAC-TOE CHALLENGE</b>\n\n"
            f"👤 <b>Challenger:</b> {p1_name}\n"
            f"🎯 <b>Challenged:</b> @{target_username}\n"
            f"💰 <b>Stake Amount:</b> ₹{bet_amount:.2f}\n\n"
            f"⏱️ <i>You have 60 seconds to accept this challenge!</i>"
        )

        sent_msg = bot.send_message(
            message.chat.id, msg_text, parse_mode="HTML", reply_markup=markup
        )

        ACTIVE_CHALLENGES[challenge_id] = {
            "p1_id": p1_id,
            "p1_name": p1_name,
            "p2_username": target_username.lower(),
            "bet": bet_amount,
            "msg_id": sent_msg.message_id,
            "chat_id": message.chat.id,
            "accepted": False,
        }

        threading.Thread(
            target=_challenge_timeout, args=(challenge_id,), daemon=True
        ).start()

    except Exception as e:
        print(f"[TTT Command Error]: {e}")
        bot.reply_to(
            message, "⚠️ Something went wrong while starting the challenge."
        )


def _challenge_timeout(challenge_id: str):
    time.sleep(60)
    data = ACTIVE_CHALLENGES.pop(challenge_id, None)
    if data and not data["accepted"]:
        try:
            bot.edit_message_text(
                f"⏱️ <b>Challenge Expired!</b>\nThe challenge from {data['p1_name']} to @{data['p2_username']} was not accepted in time.",
                chat_id=data["chat_id"],
                message_id=data["msg_id"],
                parse_mode="HTML",
            )
        except Exception:
            pass


@bot.callback_query_handler(
    func=lambda q: q.data.startswith("ttt_accept:")
    or q.data.startswith("ttt_decline:")
)
def handle_challenge_callback(call: CallbackQuery):
    action, challenge_id = call.data.split(":")
    data = ACTIVE_CHALLENGES.get(challenge_id)

    if not data:
        bot.answer_callback_query(
            call.id,
            "This challenge has expired or no longer exists.",
            show_alert=True,
        )
        return

    p2_username = call.from_user.username or ""
    if p2_username.lower() != data["p2_username"]:
        bot.answer_callback_query(
            call.id, "This challenge was not sent to you!", show_alert=True
        )
        return

    if action == "ttt_decline":
        ACTIVE_CHALLENGES.pop(challenge_id, None)
        bot.edit_message_text(
            f"❌ @{p2_username} declined the challenge.",
            chat_id=data["chat_id"],
            message_id=data["msg_id"],
        )
        return

    p2_id = call.from_user.id
    p2_name = f"@{p2_username}"
    bet = data["bet"]

    if get_balance(data["p1_id"]) < bet:
        bot.answer_callback_query(
            call.id,
            "Challenger no longer has sufficient funds!",
            show_alert=True,
        )
        return

    if get_balance(p2_id) < bet:
        bot.answer_callback_query(
            call.id,
            f"You don't have enough balance (₹{bet:.2f}) to accept!",
            show_alert=True,
        )
        return

    adjust_balance(data["p1_id"], -bet)
    adjust_balance(p2_id, -bet)

    data["accepted"] = True
    ACTIVE_CHALLENGES.pop(challenge_id, None)

    game_id = f"game_{data['p1_id']}_{p2_id}_{int(time.time())}"
    game = TicTacToeGame(
        game_id,
        data["p1_id"],
        data["p1_name"],
        p2_id,
        p2_name,
        bet,
        payout_multiplier=1.90,
    )

    ACTIVE_GAMES[game_id] = game
    GAME_METADATA[game_id] = {
        "chat_id": data["chat_id"],
        "msg_id": data["msg_id"],
    }

    start_text = (
        f"🎮 <b>TIC-TAC-TOE MATCH STARTED!</b>\n"
        f"────────────────────────\n"
        f"❌ <b>X:</b> {game.x_player[1]}\n"
        f"⭕ <b>O:</b> {game.o_player[1]}\n"
        f"💰 <b>Stake:</b> ₹{bet:.2f} each\n\n"
        f"👉 <b>First Move:</b> {game.current_player_name()} ({game.turn})"
    )

    bot.edit_message_text(
        start_text,
        chat_id=data["chat_id"],
        message_id=data["msg_id"],
        parse_mode="HTML",
        reply_markup=build_board_markup(game_id, game.board),
    )


@bot.callback_query_handler(func=lambda q: q.data.startswith("ttt_move:"))
def handle_ttt_move(call: CallbackQuery):
    _, game_id, pos_str = call.data.split(":")
    pos = int(pos_str)
    game = ACTIVE_GAMES.get(game_id)

    if not game:
        bot.answer_callback_query(
            call.id, "Game session not found or expired.", show_alert=True
        )
        return

    if call.from_user.id != game.current_player_id():
        bot.answer_callback_query(
            call.id,
            f"It's not your turn! Waiting for {game.current_player_name()}.",
            show_alert=True,
        )
        return

    success, status = game.make_move(pos, call.from_user.id)
    if not success:
        bot.answer_callback_query(call.id, status, show_alert=True)
        return

    if status == "CONTINUE":
        text = (
            f"🎮 <b>TIC-TAC-TOE MATCH</b>\n"
            f"❌ <b>X:</b> {game.x_player[1]}\n"
            f"⭕ <b>O:</b> {game.o_player[1]}\n\n"
            f"👉 <b>Turn:</b> {game.current_player_name()} ({'❌' if game.turn == 'X' else '⭕'})"
        )
        bot.edit_message_text(
            text,
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            parse_mode="HTML",
            reply_markup=build_board_markup(game_id, game.board),
        )
        return

    # Match Complete (Win or Tie)
    ACTIVE_GAMES.pop(game_id, None)
    GAME_METADATA.pop(game_id, None)

    if status == "TIE":
        adjust_balance(game.player1_id, game.bet_amount)
        adjust_balance(game.player2_id, game.bet_amount)
        record_bet(
            game.player1_id, "tictactoe", game.bet_amount, game.bet_amount, "push"
        )
        record_bet(
            game.player2_id, "tictactoe", game.bet_amount, game.bet_amount, "push"
        )

        summary = (
            f"🤝 <b>MATCH RESULT: TIE!</b>\n"
            f"────────────────────────\n"
            f"👥 <b>Players:</b> {game.player1_name} vs {game.player2_name}\n"
            f"💰 <b>Bets Refunded:</b> ₹{game.bet_amount:.2f} each"
        )

    else:  # WIN
        winner_id, winner_name = (
            game.x_player if game.winner == "X" else game.o_player
        )
        loser_id, loser_name = (
            game.o_player if game.winner == "X" else game.x_player
        )

        # Uses 1.90x payout calculation from get_payout()
        payout = game.get_payout()
        profit = payout - game.bet_amount

        adjust_balance(winner_id, payout)
        record_bet(winner_id, "tictactoe", game.bet_amount, payout, "win")
        record_bet(loser_id, "tictactoe", game.bet_amount, 0.0, "loss")

        summary = (
            f"🏆 <b>MATCH RESULT: WINNER!</b>\n"
            f"────────────────────────\n"
            f"🥇 <b>Winner:</b> {winner_name}\n"
            f"🥈 <b>Opponent:</b> {loser_name}\n"
            f"💰 <b>Total Payout:</b> ₹{payout:.2f} (Profit: +₹{profit:.2f})"
        )

        win_channel_msg = (
            f"🎉 <b>TIC-TAC-TOE MULTIPLAYER WIN</b>\n\n"
            f"👤 <b>Winner:</b> {winner_name}\n"
            f"🎯 <b>Defeated:</b> {loser_name}\n"
            f"💵 <b>Bet:</b> ₹{game.bet_amount:.2f}\n"
            f"🏆 <b>Payout:</b> ₹{payout:.2f}"
        )
        try:
            bot.send_message(WINS_CHANNEL, win_channel_msg, parse_mode="HTML")
        except Exception as e:
            print(f"[Wins Channel Error]: {e}")

    bot.edit_message_text(
        summary,
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
        parse_mode="HTML",
        reply_markup=build_board_markup(game_id, game.board, is_finished=True),
    )
