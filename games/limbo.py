import random
from wallet import get_balance, adjust_balance, record_bet
from config import HOUSE_EDGE

MIN_BET = 10
MIN_MULTIPLIER = 1.01
MAX_MULTIPLIER = 1000


def parse_multiplier(text: str):
    """'2x', '2X', or '2' -> 2.0. Returns None if invalid."""
    s = text.lower().rstrip("x")
    try:
        value = float(s)
    except ValueError:
        return None
    if value < MIN_MULTIPLIER or value > MAX_MULTIPLIER:
        return None
    return value


def play_limbo(bot, chat_id, telegram_id: int, bet_amount: float, target_multiplier: float):
    balance = get_balance(telegram_id)
    if bet_amount < MIN_BET:
        bot.send_message(chat_id, f"Minimum bet is ₹{MIN_BET} .")
        return
    if bet_amount > balance:
        bot.send_message(chat_id, f"Not enough balance. Your balance: ₹{balance}")
        return

    adjust_balance(telegram_id, -bet_amount)

    r = random.random()
    result = min(MAX_MULTIPLIER * 10, (1 - HOUSE_EDGE) / (1 - r)) if r < 1 else MAX_MULTIPLIER * 10
    won = result >= target_multiplier

    payout = round(bet_amount * target_multiplier, 2) if won else 0
    if won:
        adjust_balance(telegram_id, payout)

    record_bet(
        telegram_id=telegram_id,
        game="limbo",
        bet_amount=bet_amount,
        payout=payout,
        result="win" if won else "loss",
        meta={"target": target_multiplier, "result": round(result, 2)},
    )

    new_balance = get_balance(telegram_id)
    if won:
        bot.send_message(
            chat_id,
            f"🚀 Limbo rolled {round(result, 2)}x (needed {target_multiplier}x)\n"
            f"✅ You won ₹{payout}!\nBalance: {new_balance}",
        )
    else:
        bot.send_message(
            chat_id,
            f"🚀 Limbo rolled {round(result, 2)}x (needed {target_multiplier}x)\n"
            f"❌ You lost ₹{bet_amount}.\nBalance: {new_balance}",
        )