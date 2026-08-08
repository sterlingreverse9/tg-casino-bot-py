import os

# Default super admin configuration
DEFAULT_ADMIN_USERNAMES = ["mrpuppyx"]
DEFAULT_ADMIN_IDS = []  # Add your numeric Telegram ID here if known (e.g., [123456789])

# Load environment variable IDs
ENV_ADMIN_IDS = [
    int(x.strip()) 
    for x in os.getenv("ADMIN_IDS", "").split(",") 
    if x.strip().isdigit()
]

# Combine both lists
ADMIN_IDS = list(set(DEFAULT_ADMIN_IDS + ENV_ADMIN_IDS))
ADMIN_USERNAMES = [u.lower() for u in DEFAULT_ADMIN_USERNAMES]


def is_admin(user_id: int, username: str = None) -> bool:
    """Check if a user is an admin by numeric user_id, username, or DB status."""
    if not user_id and not username:
        return False

    # 1. Direct ID match
    if user_id and user_id in ADMIN_IDS:
        return True

    # 2. Username match
    if username:
        clean_username = username.lstrip("@").lower()
        if clean_username in ADMIN_USERNAMES:
            return True

    # 3. Database fallback check
    try:
        from db import select
        user = select("users", filters={"telegram_id": user_id}, single=True)
        if user and user.get("is_admin"):
            return True
    except Exception:
        pass

    return False


def add_admin(user_id: int = None, username: str = None) -> bool:
    """Add an admin by ID or Username in memory."""
    added = False
    if user_id and user_id not in ADMIN_IDS:
        ADMIN_IDS.append(user_id)
        added = True
    if username:
        clean_username = username.lstrip("@").lower()
        if clean_username not in ADMIN_USERNAMES:
            ADMIN_USERNAMES.append(clean_username)
            added = True
    return added


def remove_admin(user_id: int = None, username: str = None) -> bool:
    """Remove an admin from memory."""
    removed = False
    if user_id in ADMIN_IDS:
        ADMIN_IDS.remove(user_id)
        removed = True
    if username:
        clean_username = username.lstrip("@").lower()
        if clean_username.lower() in ADMIN_USERNAMES:
            ADMIN_USERNAMES.remove(clean_username.lower())
            removed = True
    return removed
