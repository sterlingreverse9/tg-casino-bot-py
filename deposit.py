from db import insert, select, update


def create_deposit(telegram_id, username, amount):
    return insert("deposits", {
        "telegram_id": telegram_id,
        "username": username,
        "amount": amount,
        "status": "pending"
    })


def save_utr(deposit_id, utr):
    return update(
        "deposits",
        {"id": deposit_id},
        {"utr": utr}
    )


def save_screenshot(deposit_id, file_id):
    return update(
        "deposits",
        {"id": deposit_id},
        {"screenshot": file_id}
    )


def get_pending_deposit(telegram_id):
    return select(
        "deposits",
        filters={
            "telegram_id": telegram_id,
            "status": "pending"
        },
        order="created_at",
        desc=True,
        limit=1,
        single=True
    )


def get_deposit_by_utr(utr):
    return select(
        "deposits",
        filters={"utr": utr},
        single=True
    )


def approve_deposit(utr, admin_id):
    return update(
        "deposits",
        {"utr": utr},
        {
            "status": "approved",
            "approved_by": admin_id
        }
    )


def decline_deposit(utr, admin_id, reason):
    return update(
        "deposits",
        {"utr": utr},
        {
            "status": "declined",
            "approved_by": admin_id,
            "decline_reason": reason
        }
    )


def pending_deposits():
    return select(
        "deposits",
        filters={"status": "pending"},
        order="created_at"
    )


def deposit_history(limit=20):
    return select(
        "deposits",
        order="created_at",
        desc=True,
        limit=limit
    )