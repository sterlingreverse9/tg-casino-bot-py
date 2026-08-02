import random
import time

from wallet import get_balance, adjust_balance, record_bet
from game_math import payout_for
from helpers import announce_win, format_display_name
from wallet import get_house_balance
from settings import get_min_bet, get_max_bet

WIN_CHANCE = 0.40  # Set win probability to 40%

HEADS_STICKER = "CAACAgQAAxkBAAFQ0lBqb0WwRqG7K3hRKZXSTKB9rnreEAACtCAAAgG_0VKYWqCdNDm4Nz0E"
TAILS_STICKER = "CAACAgQAAxkBAAFQ0lRqb0XcyDCzfRrYxgvVk89rMD8U7gACWTwAAq7X0FLUZLVck-M2CT0E"


def play_coinflip(bot, message, telegram_id: int, bet_amount: float, choice: str):
    balance = get_balance(telegram_id)
    min_bet = get_min_bet()
    max_bet = get_max_bet()

    # Enforce bet limit constraints and balance check
    if bet_amount < min_bet or bet_amount > max_bet:
        bot.reply_to(
            message,
            f"Bet amount must be between ₹{min_bet} and ₹{max_bet}."
        )
        return

    if bet_amount > balance:
        bot.reply_to(
            message,
            f"Insufficient funds. Your balance: ₹{balance} rupees."
        )
        return

    # Determine outcome based on 40% win probability for user's choice
    other_choice = "tails" if choice == "heads" else "heads"
    outcome = random.choices(
        population=[choice, other_choice],
        weights=[WIN_CHANCE, 1 - WIN_CHANCE]
    )[0]

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
        meta={
            "choice": choice,
            "outcome": outcome,
        },
    )

    # Send animated sticker first
    if outcome == "heads":
        bot.send_sticker(message.chat.id, HEADS_STICKER)
    else:
        bot.send_sticker(message.chat.id, TAILS_STICKER)

    # Wait for animation
    time.sleep(3)

    flip_label = "🪙 Heads" if outcome == "heads" else "🪙 Tails"

    if won:
        bot.reply_to(
            message,
            f"{flip_label}!\n\n"
            f"🎉 You won ₹{payout}!\n"
            f"💰 Balance: ₹{new_balance}"
        )

        name = format_display_name(
            message.from_user.first_name,
            message.from_user.username
        )

        announce_win(
            name,
            payout,
            "Coinflip"
        )

    else:
        bot.reply_to(
            message,
            f"{flip_label}!\n\n"
            f"😔 You lost ₹{bet_amount}.\n"
            f"💰 Balance: ₹{new_balance}"
        )
