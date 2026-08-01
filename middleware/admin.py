# admin permission check
from db import select


def is_admin(telegram_id: int) -> bool:
    user = select("users", filters={"telegram_id": telegram_id}, single=True)
    return bool(user and user.get("is_admin"))
