import random
from wallet import adjust_balance, get_balance, get_house_balance, record_bet
from settings import get_max_bet, get_min_bet
from helpers import announce_win

PAYOUT_MULTIPLIER = 7


def play_predict_number(
    bot,
    chat_id,
    telegram_id: int,
    bet_amount: float,
    guess: int,
    display_name: str = None,
    username: str = None,
):
    if guess < 1 or guess > 10:
        bot.send_message(chat_id, "Pick a number between 1 and 10.")
        return

    balance = get_balance(telegram_id)
    min_bet = get_min_bet()
    max_bet = get_max_bet(get_house_balance())

    if bet_amount < min_bet:
        bot.send_message(chat_id, f"Minimum bet is ₹{min_bet}.")
        return
    if bet_amount > max_bet:
        bot.send_message(chat_id, f"Maximum bet is ₹{round(max_bet, 2)}.")
        return
    if bet_amount > balance:
        bot.send_message(
            chat_id, f"Not enough balance. Your balance: ₹{balance}"
        )
        return

    adjust_balance(telegram_id, -bet_amount)

    number = random.randint(1, 10)
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

    # Format user tag handle
    if username:
        user_ref = f"@{username}"
    elif display_name:
        user_ref = display_name
    else:
        user_ref = f'<a href="tg://user?id={telegram_id}">User</a>'

    formatted_bet = int(bet_amount) if bet_amount.is_integer() else bet_amount

    if won:
        formatted_payout = int(payout) if payout.is_integer() else payout
        result_text = (
            f"<b>PN ♠️ | {user_ref}</b>\n"
            f"<b>You choose : {guess}</b>\n"
            f"<b>Current number: {number}</b>\n\n"
            f"<b>🎉 ₹{formatted_bet} ----&gt; ₹{formatted_payout} ({PAYOUT_MULTIPLIER}x)</b>\n"
            f"<b>✅ YOU WON</b>"
        )
        bot.send_message(chat_id, result_text, parse_mode="HTML")
        announce_win(username or str(telegram_id), payout, "Predict Number")
    else:
        result_text = (
            f"<b>PN ♠️ | {user_ref}</b>\n"
            f"<b>You choose : {guess}</b>\n"
            f"<b>Current number: {number}</b>\n\n"
            f"<b>❌ ₹{formatted_bet} ----&gt; ₹0</b>\n"
            f"<b>❌ YOU LOST</b>"
        )
        bot.send_message(chat_id, result_text, parse_mode="HTML")
