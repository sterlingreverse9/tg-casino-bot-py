import uuid
from datetime import datetime, timezone
from db import select, insert, update
from settings import get_referral_deposit_pct, get_referral_deposit_count

CLAIM_MIN = 10
CLAIM_COOLDOWN_HOURS = 12


def get_or_create_referral_code(telegram_id: int) -> str:
    user = select("users", filters={"telegram_id": telegram_id}, single=True)
    if user and user.get("referral_code"):
        return user["referral_code"]
    code = uuid.uuid4().hex[:8]
    update("users", {"telegram_id": telegram_id}, {"referral_code": code})
    return code


def get_user_by_referral_code(code: str):
    return select("users", filters={"referral_code": code}, single=True)


def set_referred_by(telegram_id: int, referrer_id: int):
    update("users", {"telegram_id": telegram_id}, {"referred_by": referrer_id})


def record_referral_join(referrer_id: int, referred_id: int, referred_username: str):
    insert("referrals", {
        "referrer_id": referrer_id,
        "referred_id": referred_id,
        "referred_username": referred_username,
    })


def get_referral_stats(telegram_id: int):
    user = select("users", filters={"telegram_id": telegram_id}, single=True)
    referrals = select("referrals", filters={"referrer_id": telegram_id})
    return {
        "invited_count": len(referrals),
        "total_earned": float(user.get("referral_total_earned", 0)) if user else 0,
        "referral_balance": float(user.get("referral_balance", 0)) if user else 0,
    }


def add_referral_earning(referrer_id: int, amount: float):
    user = select("users", filters={"telegram_id": referrer_id}, single=True)
    if user is None:
        return
    update("users", {"telegram_id": referrer_id}, {
        "referral_balance": round(float(user.get("referral_balance", 0)) + amount, 2),
        "referral_total_earned": round(float(user.get("referral_total_earned", 0)) + amount, 2),
    })


def claim_referral_balance(telegram_id: int):
    """Returns (amount, error_message). amount is None if claim failed."""
    user = select("users", filters={"telegram_id": telegram_id}, single=True)
    if user is None:
        return None, "No user found."

    balance = float(user.get("referral_balance", 0))
    if balance < CLAIM_MIN:
        return None, f"Minimum claimable balance is {CLAIM_MIN} coins. You have {balance}."

    last_claim = user.get("last_referral_claim")
    if last_claim:
        last_dt = datetime.fromisoformat(last_claim.replace("Z", "+00:00"))
        elapsed_hours = (datetime.now(timezone.utc) - last_dt).total_seconds() / 3600
        if elapsed_hours < CLAIM_COOLDOWN_HOURS:
            remaining = round(CLAIM_COOLDOWN_HOURS - elapsed_hours, 1)
            return None, f"Cooldown active. Try again in {remaining}h."

    update("users", {"telegram_id": telegram_id}, {
        "referral_balance": 0,
        "last_referral_claim": datetime.now(timezone.utc).isoformat(),
    })
    return balance, None


def get_referral_history(telegram_id: int, limit: int = 20):
    return select("referrals", filters={"referrer_id": telegram_id}, order="joined_at", desc=True, limit=limit)


def get_referred_users(telegram_id: int):
    return select("referrals", filters={"referrer_id": telegram_id})


def get_referred_deposit_totals(telegram_id: int):
    results = []
    for r in get_referred_users(telegram_id):
        rid = int(r["referred_id"])
        deposits = select("deposits", filters={"telegram_id": rid, "status": "approved"})
        total = round(sum(float(d["amount"]) for d in deposits), 2)
        name = r.get("referred_username") or str(rid)
        results.append((name, total))
    results.sort(key=lambda x: x[1], reverse=True)
    return results


def get_referred_loss_totals(telegram_id: int):
    results = []
    for r in get_referred_users(telegram_id):
        rid = int(r["referred_id"])
        u = select("users", filters={"telegram_id": rid}, single=True)
        total_lost = float(u["total_lost"]) if u else 0
        name = r.get("referred_username") or str(rid)
        results.append((name, total_lost))
    results.sort(key=lambda x: x[1], reverse=True)
    return results


def apply_deposit_reward(depositor_id: int, deposit_amount: float):
    """Call after a deposit is approved — credits the referrer if within the first-N-deposits window."""
    depositor = select("users", filters={"telegram_id": depositor_id}, single=True)
    if depositor is None or not depositor.get("referred_by"):
        return
    referrer_id = int(depositor["referred_by"])
    approved = select("deposits", filters={"telegram_id": depositor_id, "status": "approved"})
    if len(approved) <= get_referral_deposit_count():
        earning = round(deposit_amount * get_referral_deposit_pct() / 100, 2)
        add_referral_earning(referrer_id, earning)
