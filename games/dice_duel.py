import time
import html
from wallet import get_balance, adjust_balance, record_bet
from settings import get_house_edge
from helpers import announce_win


def process_user_roll(bot, chat_id, telegram_id, game_data, user_dice_val):
    """
    Processes single round roll and manages multi-round progression.
    Returns True when all rounds are completed, False if more rounds remain.
    """
    try:
        bet_amount = game_data["bet_amount"]
        rounds = game_data["rounds"]
        curr_round = game_data["current_round"]
        username = game_data["username"]
        first_name = game_data["first_name"]
        emoji = game_data["emoji"]

        safe_name = html.escape(first_name or "User")
        user_mention = f"@{username}" if username else f'<a href="tg://user?id={telegram_id}">{safe_name}</a>'

        # Deduct bet only on Round 1
        if curr_round == 1:
            current_bal = get_balance(telegram_id)
            if current_bal < bet_amount:
                bot.send_message(chat_id, f"❌ {user_mention}, insufficient balance for this bet.", parse_mode="HTML")
                return True
            adjust_balance(telegram_id, -bet_amount)

        # Accumulate score for player
        game_data["player_total"] += user_dice_val

        # Bot rolls in response
        time.sleep(1.0)
        bot.send_message(chat_id, f"🤖 <b>Bot</b> is rolling against {user_mention}...", parse_mode="HTML")
        msg_bot = bot.send_dice(chat_id, emoji=emoji)
        b_val = msg_bot.dice.value
        game_data["bot_total"] += b_val
        time.sleep(2.0)

        # If more rounds left, prompt for next roll
        if curr_round < rounds:
            game_data["current_round"] += 1
            next_round = game_data["current_round"]
            bot.send_message(
                chat_id,
                f"📊 <b>Score so far:</b> You {game_data['player_total']} - {game_data['bot_total']} Bot\n"
                f"🎯 {user_mention}, send <b>{emoji}</b> for <b>Round {next_round} of {rounds}</b>!",
                parse_mode="HTML"
            )
            return False

        # All rounds completed -> Evaluate Final Outcome
        player_total = game_data["player_total"]
        bot_total = game_data["bot_total"]
        house_edge = get_house_edge() if callable(get_house_edge) else 0.05

        if player_total > bot_total:
            payout_multiplier = 2.0 - house_edge
            win_amount = round(bet_amount * payout_multiplier, 2)
            adjust_balance(telegram_id, win_amount)
            record_bet(telegram_id, "dice_duel", bet_amount, win_amount, "win")
            net_profit = win_amount - bet_amount

            result_text = (
                f"🎉 {user_mention} <b>YOU WON!</b>\n\n"
                f"👤 <b>Your Total Score:</b> {player_total}\n"
                f"🤖 <b>Bot Total Score:</b> {bot_total}\n"
                f"💵 <b>Payout:</b> ₹{win_amount:.2f} (Profit: ₹{net_profit:.2f})"
            )
            bot.send_message(chat_id, result_text, parse_mode="HTML")
            announce_win(username or first_name or "Player", win_amount, "Dice Duel")

        elif player_total < bot_total:
            record_bet(telegram_id, "dice_duel", bet_amount, 0.0, "loss")
            result_text = (
                f"💥 {user_mention} <b>YOU LOST!</b>\n\n"
                f"👤 <b>Your Total Score:</b> {player_total}\n"
                f"🤖 <b>Bot Total Score:</b> {bot_total}\n"
                f"💸 <b>Loss:</b> ₹{bet_amount:.2f}"
            )
            bot.send_message(chat_id, result_text, parse_mode="HTML")

        else:
            # Tie - Return original bet
            adjust_balance(telegram_id, bet_amount)
            record_bet(telegram_id, "dice_duel", bet_amount, bet_amount, "push")
            result_text = (
                f"🤝 {user_mention} <b>IT'S A TIE!</b>\n\n"
                f"👤 <b>Your Total Score:</b> {player_total}\n"
                f"🤖 <b>Bot Total Score:</b> {bot_total}\n"
                f"🔄 Your bet of ₹{bet_amount:.2f} was returned."
            )
            bot.send_message(chat_id, result_text, parse_mode="HTML")

        return True

    except Exception as e:
        print(f"Error executing dice duel game step: {e}")
        bot.send_message(chat_id, "⚠️ An error occurred while processing your game request.")
        return True
