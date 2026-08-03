import time
import html
from wallet import get_balance, add_wager
from db import select, update
from state import house_edge
from helpers import announce_win


def adjust_balance(telegram_id: int, amount: float):
    """Safely updates user balance in the database."""
    user = select("users", filters={"telegram_id": telegram_id}, single=True)
    if user:
        current_bal = float(user.get("balance", 0.0))
        new_bal = current_bal + amount
        update("users", {"balance": new_bal}, filters={"telegram_id": telegram_id})


def start_dice_game_step(
    bot, chat_id, telegram_id, bet_amount, rounds=1, username="", first_name="User", emoji="🎲"
):
    """
    Executes a single or multi-round native Telegram dice/emoji game vs Bot.
    """
    try:
        current_bal = get_balance(telegram_id)
        if current_bal < bet_amount:
            bot.send_message(chat_id, "❌ Insufficient balance for this bet.")
            return

        # Deduct wager and record wager stats
        adjust_balance(telegram_id, -bet_amount)
        add_wager(telegram_id, bet_amount)

        player_total = 0
        bot_total = 0

        for r in range(1, rounds + 1):
            if rounds > 1:
                bot.send_message(chat_id, f"<b>--- Round {r} of {rounds} ---</b>", parse_mode="HTML")

            # Player roll
            bot.send_message(chat_id, f"🎲 <b>{html.escape(first_name)}</b> is rolling...", parse_mode="HTML")
            msg_player = bot.send_dice(chat_id, emoji=emoji)
            p_val = msg_player.dice.value
            player_total += p_val
            time.sleep(2.5)

            # Bot roll
            bot.send_message(chat_id, "🤖 <b>Bot</b> is rolling...", parse_mode="HTML")
            msg_bot = bot.send_dice(chat_id, emoji=emoji)
            b_val = msg_bot.dice.value
            bot_total += b_val
            time.sleep(2.5)

        # Outcome evaluation
        if player_total > bot_total:
            payout_multiplier = 2.0 - house_edge
            win_amount = bet_amount * payout_multiplier
            adjust_balance(telegram_id, win_amount)
            net_profit = win_amount - bet_amount

            result_text = (
                f"🎉 <b>YOU WON!</b>\n\n"
                f"👤 <b>Your Score:</b> {player_total}\n"
                f"🤖 <b>Bot Score:</b> {bot_total}\n"
                f"💵 <b>Payout:</b> ₹{win_amount:.2f} (Profit: ₹{net_profit:.2f})"
            )
            bot.send_message(chat_id, result_text, parse_mode="HTML")
            announce_win(first_name or username or "Player", win_amount, "Dice Duel")

        elif player_total < bot_total:
            result_text = (
                f"💥 <b>YOU LOST!</b>\n\n"
                f"👤 <b>Your Score:</b> {player_total}\n"
                f"🤖 <b>Bot Score:</b> {bot_total}\n"
                f"💸 <b>Loss:</b> ₹{bet_amount:.2f}"
            )
            bot.send_message(chat_id, result_text, parse_mode="HTML")

        else:
            # Tie - Return original bet
            adjust_balance(telegram_id, bet_amount)
            result_text = (
                f"🤝 <b>IT'S A TIE!</b>\n\n"
                f"👤 <b>Your Score:</b> {player_total}\n"
                f"🤖 <b>Bot Score:</b> {bot_total}\n"
                f"🔄 Your bet of ₹{bet_amount:.2f} was returned."
            )
            bot.send_message(chat_id, result_text, parse_mode="HTML")

    except Exception as e:
        print(f"Error executing dice duel game step: {e}")
        bot.send_message(chat_id, "⚠️ An error occurred while processing your game request.")
