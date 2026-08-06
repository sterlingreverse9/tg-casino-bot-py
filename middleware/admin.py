import os

ADMIN_IDS = [
    int(x.strip()) 
    for x in os.getenv("ADMIN_IDS", "").split(",") 
    if x.strip().isdigit()
]

def is_admin(user_id: int) -> bool:
    if not user_id:
        return False
    return user_id in ADMIN_IDS

def add_admin(user_id: int) -> bool:
    if user_id and user_id not in ADMIN_IDS:
        ADMIN_IDS.append(user_id)
        return True
    return False

def remove_admin(user_id: int) -> bool:
    if user_id in ADMIN_IDS:
        ADMIN_IDS.remove(user_id)
        return True
    return False
