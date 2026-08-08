import html
import time
from helpers import announce_win
from pvp_state import clear_active_duel, update_duel_activity
from settings import get_house_edge
from wallet import adjust_balance, get_balance, record_bet


def process_user_roll(
    bot, chat_id, telegram_id, game_data, user_dice_val
):
    """Processes single round roll and manages multi-round progression.

    Returns True when all rounds are completed, False if more rounds remain.
    """
    try:
        update_duel_activity(telegram_id)

        bet_amount = game_data["bet_amount"]
        rounds = game_data["rounds"]
        curr_round = game_data["current_round"]
        username = game_data.get("username")
        first_name = game_data.get("first_name")
        emoji = game_data.get("emoji", "🎲")

        safe_name = html.escape(first_name or "User")
        user_mention = (
            f"@{username}"
            if username
            else f'<a href="tg://user?id={telegram_id}">{safe_name}</a>'
        )

        # Round 1 Setup: Balance Deduction & Wager Verification
        if curr_round == 1:
            current_bal = get_balance(telegram_id)
            if current_bal < bet_amount:
                bot.send_message(
                    chat_id,
                    f"❌ {user_mention}, insufficient balance for this bet.",
                    parse_mode="HTML",
                )
                print(
                    f"[DUEL LOG] Insufficient funds for {telegram_id}",
                    flush=True,
                )
                clear_active_duel(telegram_id)
                return True

            adjust_balance(telegram_id, -bet_amount)
            print(
                f"[DUEL LOG] Game Started | User: {telegram_id} | Bet: ₹{bet_amount:.2f} | Rounds: {rounds}",
                flush=True,
            )

        # Accumulate score for player
        game_data["player_total"] += user_dice_val

        # Bot rolls back purely unrigged roll via standard Telegram send_dice
        time.sleep(1.0)
        bot.send_message(
            chat_id,
            f"🤖 <b>Bot</b> is rolling {emoji} against {user_mention}...",
            parse_mode="HTML",
        )
        msg_bot = bot.send_dice(chat_id, emoji=emoji)

        # Wait 3 seconds for Telegram animation
        time.sleep(3.0)
        b_val = msg_bot.dice.value
        game_data["bot_total"] += b_val

        # Prompt for next round if unfinished
        if curr_round < rounds:
            game_data["current_round"] += 1
            next_round = game_data["current_round"]
            bot.send_message(
                chat_id,
                f"📊 <b>Score so far:</b> You {game_data['player_total']} - {game_data['bot_total']} Bot\n"
                f"🎯 {user_mention}, send <b>{emoji}</b> for <b>Round {next_round} of {rounds}</b>!",
                parse_mode="HTML",
            )
            update_duel_activity(telegram_id)
            return False

        # Match Finished -> Compute Result
        player_total = game_data["player_total"]
        bot_total = game_data["bot_total"]

        raw_edge = (
            get_house_edge() if callable(get_house_edge) else get_house_edge
        )
        house_edge = raw_edge if isinstance(raw_edge, (int, float)) else 0.05

        if player_total > bot_total:
            payout_multiplier = 2.0 - house_edge
            win_amount = round(bet_amount * payout_multiplier, 2)
            adjust_balance(telegram_id, win_amount)
            record_bet(
                telegram_id, "dice_duel", bet_amount, win_amount, "win"
            )
            net_profit = win_amount - bet_amount

            result_text = (
                f"🎉 {user_mention} <b>YOU WON!</b>\n\n"
                f"👤 <b>Your Total Score:</b> {player_total}\n"
                f"🤖 <b>Bot Total Score:</b> {bot_total}\n"
                f"💵 <b>Payout:</b> ₹{win_amount:.2f} (Profit: ₹{net_profit:.2f})"
            )
            bot.send_message(chat_id, result_text, parse_mode="HTML")

            print(
                f"[DUEL LOG] Result: WIN | Player: {player_total} vs Bot: {bot_total} | Payout: ₹{win_amount:.2f}",
                flush=True,
            )

            display_name = (
                f"@{username}" if username else (first_name or "Player")
            )
            try:
                announce_win(
                    bot=bot,
                    user_id=telegram_id,
                    display_name=display_name,
                    game_name=f"{emoji} Dice Duel",
                    bet_amount=bet_amount,
                    payout=win_amount,
                )
            except Exception as e:
                print(f"[DUEL LOG] announce_win error: {e}", flush=True)

        elif player_total < bot_total:
            record_bet(telegram_id, "dice_duel", bet_amount, 0.0, "loss")
            result_text = (
                f"💥 {user_mention} <b>YOU LOST!</b>\n\n"
                f"👤 <b>Your Total Score:</b> {player_total}\n"
                f"🤖 <b>Bot Total Score:</b> {bot_total}\n"
                f"💸 <b>Loss:</b> ₹{bet_amount:.2f}"
            )
            bot.send_message(chat_id, result_text, parse_mode="HTML")

            print(
                f"[DUEL LOG] Result: LOSS | Player: {player_total} vs Bot: {bot_total} | Lost: ₹{bet_amount:.2f}",
                flush=True,
            )

        else:
            # Tie / Push
            adjust_balance(telegram_id, bet_amount)
            record_bet(
                telegram_id, "dice_duel", bet_amount, bet_amount, "push"
            )
            result_text = (
                f"🤝 {user_mention} <b>IT'S A TIE!</b>\n\n"
                f"👤 <b>Your Total Score:</b> {player_total}\n"
                f"🤖 <b>Bot Total Score:</b> {bot_total}\n"
                f"🔄 Your bet of ₹{bet_amount:.2f} was returned."
            )
            bot.send_message(chat_id, result_text, parse_mode="HTML")

            print(
                f"[DUEL LOG] Result: TIE | Player: {player_total} vs Bot: {bot_total} | Refunded ₹{bet_amount:.2f}",
                flush=True,
            )

        # Clear session upon successful match conclusion
        clear_active_duel(telegram_id)
        return True

    except Exception as e:
        print(f"[Dice Game Execution Error]: {e}", flush=True)
        bot.send_message(
            chat_id,
            "⚠️ An error occurred while processing your game request.",
        )
        clear_active_duel(telegram_id)
        return True
