import random
from wallet import get_balance, adjust_balance, record_bet
from settings import get_min_bet, get_max_bet
from wallet import get_house_balance
from helpers import announce_win

PAYOUT_MULTIPLIER = 70


def play_predict_number(bot, chat_id, telegram_id: int, bet_amount: float, guess: int, display_name: str = None):
    if guess < 1 or guess > 100:
        bot.send_message(chat_id, "Pick a number between 1 and 100.")
        return

    balance = get_balance(telegram_id)
    min_bet = get_min_bet()
    max_bet = get_max_bet(get_house_balance())

    if bet_amount < min_bet:
        bot.send_message(chat_id, f"Minimum bet is {min_bet} coins.")
        return
    if bet_amount > max_bet:
        bot.send_message(chat_id, f"Maximum bet is {round(max_bet, 2)} coins.")
        return
    if bet_amount > balance:
        bot.send_message(chat_id, f"Not enough balance. Your balance: {balance}")
        return

    adjust_balance(telegram_id, -bet_amount)

    number = random.randint(1, 100)
    won = number == guess
    payout = round(bet_amount * PAYOUT_MULTIPLIER, 2) if won else 0
    if won:
        adjust_balance(telegram_id, payout)

    record_bet(
        telegram_id=telegram_id,
        game="predict_number",
        bet_amount=bet_amount,
        payout=payout,
        result="win" if won else "loss",
        meta={"guess": guess, "number": number},
    )

    new_balance = get_balance(telegram_id)
    if won:
        bot.send_message(
            chat_id,
            f"🔮 The number was {number}! You guessed {guess} — spot on!\n"
            f"✅ You won ₹{payout} ! ({PAYOUT_MULTIPLIER}x)\nBalance: {new_balance}",
        )
        announce_win(display_name or str(telegram_id), payout, "Predict Number")
    else:
        bot.send_message(
            chat_id,
            f"🔮 The number was {number}. You guessed {guess}.\n"
            f"❌ You lost {bet_amount} coins.\nBalance: ₹{new_balance}",
        )
