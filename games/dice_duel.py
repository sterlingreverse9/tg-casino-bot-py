import time
import html
from wallet import get_balance, adjust_balance, record_bet
from settings import get_house_edge
from helpers import announce_win


def process_user_roll(
    bot, chat_id, telegram_id, bet_amount, rounds, username, first_name, emoji, user_dice_val
):
    """
    Processes game outcome after user sends their emoji roll manually.
    """
    try:
        current_bal = get_balance(telegram_id)
        if current_bal < bet_amount:
            bot.send_message(chat_id, "❌ Insufficient balance for this bet.")
            return

        # Deduct initial bet
        adjust_balance(telegram_id, -bet_amount)

        safe_name = html.escape(first_name or "User")
        user_mention = f"@{username}" if username else f'<a href="tg://user?id={telegram_id}">{safe_name}</a>'

        player_total = user_dice_val
        bot_total = 0

        # Bot rolls to respond
        time.sleep(1.0)
        bot.send_message(chat_id, f"🤖 <b>Bot</b> is rolling against {user_mention}...", parse_mode="HTML")
        msg_bot = bot.send_dice(chat_id, emoji=emoji)
        b_val = msg_bot.dice.value
        bot_total += b_val
        time.sleep(2.0)

        # Outcome evaluation
        house_edge = get_house_edge() if callable(get_house_edge) else 0.05

        if player_total > bot_total:
            payout_multiplier = 2.0 - house_edge
            win_amount = round(bet_amount * payout_multiplier, 2)
            adjust_balance(telegram_id, win_amount)
            record_bet(telegram_id, "dice_duel", bet_amount, win_amount, "win")
            net_profit = win_amount - bet_amount

            result_text = (
                f"🎉 {user_mention} <b>YOU WON!</b>\n\n"
                f"👤 <b>Your Score:</b> {player_total}\n"
                f"🤖 <b>Bot Score:</b> {bot_total}\n"
                f"💵 <b>Payout:</b> ₹{win_amount:.2f} (Profit: ₹{net_profit:.2f})"
            )
            bot.send_message(chat_id, result_text, parse_mode="HTML")
            announce_win(username or first_name or "Player", win_amount, "Dice Duel")

        elif player_total < bot_total:
            record_bet(telegram_id, "dice_duel", bet_amount, 0.0, "loss")
            result_text = (
                f"💥 {user_mention} <b>YOU LOST!</b>\n\n"
                f"👤 <b>Your Score:</b> {player_total}\n"
                f"🤖 <b>Bot Score:</b> {bot_total}\n"
                f"💸 <b>Loss:</b> ₹{bet_amount:.2f}"
            )
            bot.send_message(chat_id, result_text, parse_mode="HTML")

        else:
            # Tie - Return original bet
            adjust_balance(telegram_id, bet_amount)
            record_bet(telegram_id, "dice_duel", bet_amount, bet_amount, "push")
            result_text = (
                f"🤝 {user_mention} <b>IT'S A TIE!</b>\n\n"
                f"👤 <b>Your Score:</b> {player_total}\n"
                f"🤖 <b>Bot Score:</b> {bot_total}\n"
                f"🔄 Your bet of ₹{bet_amount:.2f} was returned."
            )
            bot.send_message(chat_id, result_text, parse_mode="HTML")

    except Exception as e:
        print(f"Error executing dice duel game step: {e}")
        bot.send_message(chat_id, "⚠️ An error occurred while processing your game request.")
