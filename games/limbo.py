import random
from wallet import get_balance, adjust_balance, record_bet, get_house_balance
from settings import get_min_bet, get_max_bet
from helpers import announce_win

MIN_MULTIPLIER = 1.01
MAX_MULTIPLIER = 1000

# (low, high, probability) — probabilities sum to 1.0
BUCKETS = [
    (1.00, 1.00, 0.20),      # 20% (strictly 1.00x)
    (1.01, 1.50, 0.23),      # 18%
    (1.50, 2.00, 0.36),      # 36%
    (2.00, 3.00, 0.15),      # 15%
    (3.00, 5.00, 0.08),      # 8%
    (5.00, 10.00, 0.04),     # 4%
    (10.00, 50.00, 0.03),    # 3%
    (50.00, MAX_MULTIPLIER, 0.01),  # 1%
]


def parse_multiplier(text: str):
    """'2x', '2X', or '2' -> 2.0. Returns None if invalid."""
    s = text.lower().rstrip("x").strip()
    try:
        value = float(s)
    except ValueError:
        return None
    if value < MIN_MULTIPLIER or value > MAX_MULTIPLIER:
        return None
    return value


def roll_result() -> float:
    r = random.random()
    cumulative = 0.0
    for low, high, prob in BUCKETS:
        cumulative += prob
        if r <= cumulative:
            if low == high:
                return float(low)
            return round(random.uniform(low, high), 2)
    low, high, _ = BUCKETS[-1]
    return round(random.uniform(low, high), 2)


def play_limbo(bot, chat_id, telegram_id: int, bet_amount: float, target_multiplier: float, user_name: str = None):
    balance = get_balance(telegram_id)
    min_bet = get_min_bet()
    max_bet = get_max_bet(get_house_balance())

    if bet_amount < min_bet:
        bot.send_message(chat_id, f"⚠️ Minimum bet is ₹{min_bet:.2f}")
        return
    if bet_amount > max_bet:
        bot.send_message(chat_id, f"⚠️ Maximum bet is ₹{max_bet:.2f}")
        return
    if bet_amount > balance:
        bot.send_message(chat_id, f"❌ Insufficient balance! Your balance: ₹{balance:.2f}")
        return

    adjust_balance(telegram_id, -bet_amount)

    result = roll_result()
    won = result >= target_multiplier

    payout = round(bet_amount * target_multiplier, 2) if won else 0.0
    if won:
        adjust_balance(telegram_id, payout)

    record_bet(
        telegram_id=telegram_id,
        game="limbo",
        bet_amount=bet_amount,
        payout=payout,
        result="win" if won else "loss",
        meta={"target": target_multiplier, "result": result},
    )

    user_label = user_name or f"ID: {telegram_id}"

    # Announce win to public group/channel if configured
    if won:
        try:
            announce_win(
                bot=bot,
                user_id=telegram_id,
                display_name=user_label,
                game_name="Limbo",
                bet_amount=bet_amount,
                payout=payout,
            )
        except Exception as e:
            print(f"[LIMBO WIN ANNOUNCE ERROR] {e}", flush=True)

    # 20% Chance on Win to display a high 10x-50x multiplier instead of real result
    display_result = result
    if won and random.random() < 0.20:
        fake_high = round(random.uniform(10.00, 50.00), 2)
        display_result = max(fake_high, target_multiplier)

    # UI Formatting
    header_arrow = "⬆️" if won else "⬇️"
    mult_arrow = "⬆️" if won else "⬇️"

    message = (
        f"{header_arrow} <b>Limbo</b>\n\n"
        f"₹{bet_amount:.2f} → ₹{payout:.2f} ({display_result:.2f}×)\n\n"
        f"Multiplier: {target_multiplier:.2f}× {mult_arrow}"
    )

    bot.send_message(chat_id, message, parse_mode="HTML")
