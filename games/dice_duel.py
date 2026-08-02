import re
import time
from wallet import get_balance, adjust_balance, record_bet, get_house_balance
from settings import get_min_bet, get_max_bet
from helpers import announce_win

MIN_BET = 10
CODE_PATTERN = re.compile(r"^(\d+)d(\d+)w$", re.IGNORECASE)


def parse_dice_code(code: str):
    """'3d1w' -> (rolls_per_round=3, rounds=1). Returns None if invalid."""
    match = CODE_PATTERN.match(code)
    if not match:
        return None
    dice_count, rounds = int(match.group(1)), int(match.group(2))
    if dice_count < 1 or dice_count > 3 or rounds < 1 or rounds > 3:
        return None
    return dice_count, rounds


def decide_round_winner(a_sum: int, b_sum: int, mode: str = "classic"):
    if a_sum == b_sum:
        return None  # tie -> reroll
    if mode == "crazy":
        return "a" if a_sum < b_sum else "b"
    return "a" if a_sum > b_sum else "b"


def run_dice_vs_bot(bot, chat_id, telegram_id: int, bet_amount: float, rounds: int, username: str = None):
    """Executes the game loop against the Bot."""
    adjust_balance(telegram_id, -bet_amount)

    user_ref = f"@{username}" if username else f'<a href="tg://user?id={telegram_id}">User</a>'
    formatted_bet = int(bet_amount) if bet_amount.is_integer() else bet_amount

    # Send Prompt Message
    prompt_text = (
        f"<b>🎲 Dice vs Bot ₹{formatted_bet}</b>\n\n"
        f"👤 {user_ref} — send/copy this emoji now: 🎲"
    )
    bot.send_message(chat_id, prompt_text, parse_mode="HTML")

    player_wins = 0
    bot_wins = 0

    for current_round in range(1, rounds + 1):
        if rounds > 1:
            bot.send_message(chat_id, f"--- <b>Round {current_round} of {rounds}</b> ---", parse_mode="HTML")

        # Player's Roll
        p_dice = bot.send_dice(chat_id, emoji="🎲")
        p_roll = p_dice.dice.value

        # Bot's Roll
        b_dice = bot.send_dice(chat_id, emoji="🎲")
        b_roll = b_dice.dice.value

        time.sleep(3)  # Wait for dice animation

        winner = decide_round_winner(p_roll, b_roll, mode="classic")
        while winner is None:
            # Tie re-rolls
            p_dice = bot.send_dice(chat_id, emoji="🎲")
            p_roll = p_dice.dice.value
            b_dice = bot.send_dice(chat_id, emoji="🎲")
            b_roll = b_dice.dice.value
            time.sleep(3)
            winner = decide_round_winner(p_roll, b_roll, mode="classic")

        if winner == "a":
            player_wins += 1
        else:
            bot_wins += 1

    won = player_wins > bot_wins
    payout = (bet_amount * 2) if won else 0

    if won:
        adjust_balance(telegram_id, payout)
        announce_win(username or str(telegram_id), payout, "Dice vs Bot")

    record_bet(
        telegram_id=telegram_id,
        game="dice_vs_bot",
        bet_amount=bet_amount,
        payout=payout,
        result="win" if won else "loss",
        meta={"rounds": rounds, "player_score": player_wins, "bot_score": bot_wins},
    )

    if won:
        formatted_payout = int(payout) if payout.is_integer() else payout
        bot.send_message(
            chat_id,
            f"🎉 <b>You won! Score: {player_wins}-{bot_wins}</b>\n💰 <b>Payout: ₹{formatted_payout}</b>",
            parse_mode="HTML"
        )
    else:
        bot.send_message(
            chat_id,
            f"❌ <b>Bot won! Score: {bot_wins}-{player_wins}</b>\n💸 <b>You lost ₹{formatted_bet}</b>",
            parse_mode="HTML"
        )
