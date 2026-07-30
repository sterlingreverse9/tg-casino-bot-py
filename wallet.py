from db import select, insert, update
from config import STARTING_BALANCE


def get_or_create_user(telegram_id: int, username):
    user = select("users", filters={"telegram_id": telegram_id}, single=True)
    if user:
        return user
    return insert("users", {
        "telegram_id": telegram_id,
        "username": username,
        "balance": STARTING_BALANCE,
    })


def get_balance(telegram_id: int) -> float:
    user = select("users", filters={"telegram_id": telegram_id}, single=True)
    return float(user["balance"]) if user else 0.0


def adjust_balance(telegram_id: int, delta: float) -> float:
    user = select("users", filters={"telegram_id": telegram_id}, single=True)
    new_balance = float(user["balance"]) + delta
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
        "total_wagered": float(user["total_wagered"]) + bet_amount,
        "total_won": float(user["total_won"]) + (payout if result == "win" else 0),
        "total_lost": float(user["total_lost"]) + (bet_amount if result == "loss" else 0),
    })

    house_delta = -(payout - bet_amount) if result == "win" else bet_amount
    house = select("house", filters={"id": 1}, single=True)
    update("house", {"id": 1}, {"balance": float(house["balance"]) + house_delta})


def get_house_balance() -> float:
    house = select("house", filters={"id": 1}, single=True)
    return float(house["balance"]) if house else 0.0


def resolve_amount(telegram_id: int, amount_str: str):
    """Turn 'all', 'half', or a plain number into a float bet amount."""
    s = amount_str.lower()
    if s == "all":
        return get_balance(telegram_id)
    if s == "half":
        return round(get_balance(telegram_id) / 2, 2)
    try:
        return float(amount_str)
    except ValueError:
        return None
