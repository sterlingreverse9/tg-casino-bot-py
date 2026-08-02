from db import select, insert, update
from config import STARTING_BALANCE
from settings import get_referral_loss_pct


def get_or_create_user(telegram_id: int, username):
    user = select("users", filters={"telegram_id": telegram_id}, single=True)
    if user:
        return user
    return insert("users", {
        "telegram_id": telegram_id,
        "username": username,
        "balance": round(STARTING_BALANCE, 2),
    })


def get_balance(telegram_id: int) -> float:
    user = select("users", filters={"telegram_id": telegram_id}, single=True)
    return round(float(user["balance"]), 2) if user else 0.0


def adjust_balance(telegram_id: int, delta: float) -> float:
    user = select("users", filters={"telegram_id": telegram_id}, single=True)
    new_balance = round(float(user["balance"]) + delta, 2)
    update("users", {"telegram_id": telegram_id}, {"balance": new_balance})
    return new_balance


def record_bet(telegram_id: int, game: str, bet_amount: float, payout: float, result: str, meta=None):
    insert("bets", {
        "telegram_id": telegram_id,
        "game": game,
        "bet_amount": bet_amount,
        "payout": payout,
        "result": result,
        "meta": meta or {},
    })

    user = select("users", filters={"telegram_id": telegram_id}, single=True)
    update("users", {"telegram_id": telegram_id}, {
        "total_wagered": round(float(user["total_wagered"]) + bet_amount, 2),
        "total_won": round(float(user["total_won"]) + (payout if result == "win" else 0), 2),
        "total_lost": round(float(user["total_lost"]) + (bet_amount if result == "loss" else 0), 2),
    })

    house_delta = -(payout - bet_amount) if result == "win" else bet_amount
    house = select("house", filters={"id": 1}, single=True)
    update("house", {"id": 1}, {"balance": round(float(house["balance"]) + house_delta, 2)})

    if result == "loss" and user.get("referred_by"):
        referrer_id = int(user["referred_by"])
        pct = get_referral_loss_pct()
        earning = round(bet_amount * pct / 100, 2)
        if earning > 0:
            referrer = select("users", filters={"telegram_id": referrer_id}, single=True)
            if referrer:
                update("users", {"telegram_id": referrer_id}, {
                    "referral_balance": round(float(referrer.get("referral_balance", 0)) + earning, 2),
                    "referral_total_earned": round(float(referrer.get("referral_total_earned", 0)) + earning, 2),
                })


def get_house_balance() -> float:
    house = select("house", filters={"id": 1}, single=True)
    return round(float(house["balance"]), 2) if house else 0.0


def resolve_amount(telegram_id: int, amount_str: str):
    """Turn 'all', 'half', or a plain number into a float bet amount."""
    s = amount_str.lower()
    if s == "all":
        return get_balance(telegram_id)
    if s == "half":
        return round(get_balance(telegram_id) / 2, 2)
    try:
        return round(float(amount_str), 2)
    except ValueError:
        return None
