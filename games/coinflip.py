import random
from wallet import get_balance, adjust_balance, record_bet
from game_math import payout_for
from helpers import announce_win, format_display_name

WIN_CHANCE = 0.5


def play_coinflip(bot, message, telegram_id: int, bet_amount: float, choice: str):
    balance = get_balance(telegram_id)
    if bet_amount <= 0 or bet_amount > balance:
        bot.reply_to(message, f"Invalid bet. Your balance: ₹{balance} rupess.")
        return

    outcome = random.choice(["heads", "tails"])
    won = outcome == choice
    payout = payout_for(bet_amount, WIN_CHANCE) if won else 0
    net_delta = (payout - bet_amount) if won else -bet_amount

    new_balance = adjust_balance(telegram_id, net_delta)
    record_bet(
        telegram_id=telegram_id,
        game="coinflip",
        bet_amount=bet_amount,
        payout=payout,
        result="win" if won else "loss",
        meta={"choice": choice, "outcome": outcome},
    )

    flip_label = "🪙 Heads" if outcome == "heads" else "🪙 Tails"
    if won:
        bot.reply_to(message, f"{flip_label}!\nYou won ₹{payout} ! 🎉\nBalance: ₹{new_balance}")
        name = format_display_name(message.from_user.first_name, message.from_user.username)
        announce_win(name, payout, "Coinflip")
    else:
        bot.reply_to(message, f"{flip_label}!\nYou lost ₹{bet_amount} rupess.\nBalance: ₹{new_balance}")
