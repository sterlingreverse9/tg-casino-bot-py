import random
from db import select, insert, update


def generate_unique_wd_id() -> str:
    """Generates a random unique 4-digit withdrawal ID (#1576, #9482, etc.)."""
    while True:
        code = str(random.randint(1000, 9999))
        existing = select("withdrawals", filters={"wd_id": code}, single=True)
        if not existing:
            return code


def create_withdrawal(telegram_id, username, full_name, amount, fee, net_amount, upi_id):
    code = generate_unique_wd_id()
    return insert("withdrawals", {
        "wd_id": code,
        "telegram_id": telegram_id,
        "username": username,
        "full_name": full_name,
        "amount": amount,
        "fee": fee,
        "net_amount": net_amount,
        "upi_id": upi_id,
        "status": "pending"
    })


def get_withdrawal(wd_id: str):
    clean_id = wd_id.lstrip("#")
    return select("withdrawals", filters={"wd_id": clean_id}, single=True)


def approve_withdrawal(wd_id: str, admin_id: int):
    clean_id = wd_id.lstrip("#")
    return update("withdrawals", {"wd_id": clean_id}, {"status": "approved", "processed_by": admin_id})


def decline_withdrawal(wd_id: str, admin_id: int, reason: str):
    clean_id = wd_id.lstrip("#")
    return update("withdrawals", {"wd_id": clean_id}, {"status": "declined", "processed_by": admin_id, "decline_reason": reason})


def get_pending_withdrawals():
    return select("withdrawals", filters={"status": "pending"}, order="created_at")
