import uuid
import datetime
from db import select, insert, update

# --- In-Memory State for Active Multi-Step Code Creation ---
# Format: { telegram_id: { "step": "name"|"users"|"amount"|"confirm", "data": {} } }
CODE_CREATION_STATES = {}


def get_code_data(code_name: str):
    """Fetch code data case-insensitively."""
    codes = select("promo_codes") or []
    code_clean = code_name.strip().lower()
    for c in codes:
        if c.get("code_name", "").strip().lower() == code_clean:
            return c
    return None


def create_promo_code(creator_id: int, creator_username: str, code_name: str, max_users: int, amount_per_user: float, total_cost: float):
    """Store a newly created promo code in the database."""
    record = {
        "code_id": uuid.uuid4().hex[:10],
        "creator_id": creator_id,
        "creator_username": creator_username,
        "code_name": code_name.strip(),
        "max_users": max_users,
        "amount_per_user": amount_per_user,
        "total_cost": total_cost,
        "claimed_by": [],  # List of telegram_ids who claimed
        "created_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    insert("promo_codes", record)
    return record


def record_claim(code_id: str, telegram_id: int):
    """Add telegram_id to claimed_by list."""
    codes = select("promo_codes") or []
    for c in codes:
        if c.get("code_id") == code_id:
            claimed = c.get("claimed_by", [])
            if telegram_id not in claimed:
                claimed.append(telegram_id)
                update("promo_codes", {"code_id": code_id}, {"claimed_by": claimed})
                return True
    return False
