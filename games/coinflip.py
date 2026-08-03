import random
import time

from wallet import get_balance, adjust_balance, record_bet, get_house_balance
from helpers import announce_win, format_display_name
from settings import get_min_bet, get_max_bet, get_house_edge
from bot_instance import bot

# Set win chance to 48% (feels 50-50, but house wins over time)
WIN_CHANCE = 0.48

HEADS_STICKER = "CAACAgQAAxkBAAFQ0lBqb0WwRqG7K3hRKZXSTKB9rnreEAACtCAAAgG_0VKYWqCdNDm4Nz0E"
TAILS_STICKER = "CAACAgQAAxkBAAFQ0lRqb0XcyDCzfRrYxgvVk89rMD8U7gACWTwAAq7X0FLUZLVck-M2CT0E"


def play_coinflip(bot, message, telegram_id: int, bet_amount: float, choice: str):
    balance = get_balance(telegram_id)
    house_balance = get_house_balance()

    min_bet = get_min_bet()
    max_bet = get_max_bet(house_balance)

    # Enforce min/max bet caps
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

    # Determine outcome
    choice = choice.lower().strip()
    if choice not in ["heads", "head", "tails", "tail", "h", "t"]:
        bot.reply_to(message, "Please choose either 'heads' or 'tails'.")
        return

    normalized_choice = "heads" if choice in ["heads", "head", "h"] else "tails"
    other_choice = "tails" if normalized_choice == "heads" else "heads"

    outcome = random.choices(
        population=[normalized_choice, other_choice],
        weights=[WIN_CHANCE, 1 - WIN_CHANCE]
    )[0]

    won = outcome == normalized_choice

    # Calculate payout considering House Edge (2.0x minus house edge percentage)
    house_edge = get_house_edge()  # e.g., 0.05 for 5% edge
    multiplier = 2.0 * (1.0 - house_edge)  # 2.0 * (1 - 0.05) = 1.9x
    
    payout = round(bet_amount * multiplier, 2) if won else 0
    net_delta = (payout - bet_amount) if won else -bet_amount

    new_balance = adjust_balance(telegram_id, net_delta)

    record_bet(
        telegram_id=telegram_id,
        game="coinflip",
        bet_amount=bet_amount,
        payout=payout,
        result="win" if won else "loss",
        meta={
            "choice": normalized_choice,
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


# --- Command Handlers for /coinflip, /coin, /cf ---

@bot.message_handler(commands=["coinflip", "coin", "cf"])
def handle_coinflip_command(message):
    parts = message.text.split()
    if len(parts) < 3:
        bot.reply_to(
            message,
            "Usage: /cf <amount> <heads|tails>\nExample: /cf 10 heads"
        )
        return

    try:
        bet_amount = float(parts[1])
    except ValueError:
        bot.reply_to(message, "Invalid bet amount. Enter a valid number.")
        return

    choice = parts[2]
    play_coinflip(bot, message, message.from_user.id, bet_amount, choice)
