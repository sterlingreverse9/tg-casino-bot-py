from db import supabase
from config import STARTING_BALANCE


def get_or_create_user(telegram_id: int, username: str | None):
    result = supabase.table("users").select("*").eq("telegram_id", telegram_id).execute()
    if result.data:
        return result.data[0]

    created = supabase.table("users").insert({
        "telegram_id": telegram_id,
        "username": username,
        "balance": STARTING_BALANCE,
    }).execute()
    return created.data[0]


def get_balance(telegram_id: int) -> float:
    result = supabase.table("users").select("balance").eq("telegram_id", telegram_id).execute()
    return float(result.data[0]["balance"]) if result.data else 0.0


def adjust_balance(telegram_id: int, delta: float) -> float:
    result = supabase.table("users").select("balance").eq("telegram_id", telegram_id).execute()
    current = float(result.data[0]["balance"])
    new_balance = current + delta
    supabase.table("users").update({"balance": new_balance}).eq("telegram_id", telegram_id).execute()
    return new_balance


def record_bet(telegram_id: int, game: str, bet_amount: float, payout: float, result: str, meta: dict | None = None):
    supabase.table("bets").insert({
        "telegram_id": telegram_id,
        "game": game,
        "bet_amount": bet_amount,
        "payout": payout,
        "result": result,
        "meta": meta or {},
    }).execute()

    user = supabase.table("users").select("total_wagered,total_won,total_lost").eq("telegram_id", telegram_id).execute().data[0]
    supabase.table("users").update({
        "total_wagered": float(user["total_wagered"]) + bet_amount,
        "total_won": float(user["total_won"]) + (payout if result == "win" else 0),
        "total_lost": float(user["total_lost"]) + (bet_amount if result == "loss" else 0),
    }).eq("telegram_id", telegram_id).execute()

    # house gains the bet on a loss, pays out the profit on a win
    house_delta = -(payout - bet_amount) if result == "win" else bet_amount
    house = supabase.table("house").select("balance").eq("id", 1).execute().data[0]
    supabase.table("house").update({"balance": float(house["balance"]) + house_delta}).eq("id", 1).execute()


def get_house_balance() -> float:
    result = supabase.table("house").select("balance").eq("id", 1).execute()
    return float(result.data[0]["balance"]) if result.data else 0.0
