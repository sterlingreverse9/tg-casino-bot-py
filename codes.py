import uuid
import datetime
from db import select, insert, update

# --- In-Memory State for Active Multi-Step Code Creation ---
CODE_CREATION_STATES = {}


def get_code_data(code_name: str):
    """Fetch code data case-insensitively from the 'codes' table."""
    codes = select("codes") or []
    code_clean = code_name.strip().upper()
    for c in codes:
        if c.get("code", "").strip().upper() == code_clean:
            return c
    return None


def create_promo_code(creator_id: int, creator_username: str, code_name: str, max_users: int, amount_per_user: float, total_cost: float):
    """Store a newly created promo code in the database 'codes' table."""
    record = {
        "code_id": uuid.uuid4().hex[:10],
        "created_by": creator_id,
        "creator_username": creator_username,
        "code": code_name.strip().upper(),
        "max_claims": max_users,
        "reward_amount": amount_per_user,
        "total_cost": total_cost,
        "claimed_count": 0,
        "is_active": True,
        "created_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    insert("codes", record)
    return record


def record_claim(code_name: str, telegram_id: int, reward_amount: float):
    """Record user claim history in 'code_claims' and update 'codes' table."""
    promo_code = code_name.strip().upper()
    code_data = select("codes", filters={"code": promo_code}, single=True)
    
    if not code_data:
        return False

    already_claimed = select("code_claims", filters={"code": promo_code, "user_id": telegram_id}, single=True)
    if already_claimed:
        return False

    claim_entry = insert("code_claims", {
        "code": promo_code,
        "user_id": telegram_id,
        "reward": reward_amount
    })

    if claim_entry:
        new_count = code_data.get("claimed_count", 0) + 1
        update_data = {"claimed_count": new_count}
        if new_count >= code_data.get("max_claims", 1):
            update_data["is_active"] = False
        
        update("codes", filters={"code": promo_code}, values=update_data)
        return True

    return False
