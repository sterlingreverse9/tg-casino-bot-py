from db import select

# Replace with your Telegram numeric user ID
OWNER_ID = 8639544409

def is_admin(telegram_id: int) -> bool:
    # Always allow the owner
    if telegram_id == OWNER_ID:
        return True

    # Also allow users marked as admin in the database
    user = select("users", filters={"telegram_id": telegram_id}, single=True)
    return bool(user and user.get("is_admin"))