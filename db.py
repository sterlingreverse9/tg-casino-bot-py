import requests
from config import SUPABASE_URL, SUPABASE_SERVICE_KEY

BASE = f"{SUPABASE_URL}/rest/v1"
HEADERS = {
    "apikey": SUPABASE_SERVICE_KEY,
    "Authorization": f"Bearer {SUPABASE_SERVICE_KEY}",
    "Content-Type": "application/json",
    "Prefer": "return=representation",
}


def select(table, filters=None, order=None, desc=False, limit=None, single=False):
    params = {"select": "*"}
    if filters:
        for k, v in filters.items():
            params[k] = f"eq.{v}"
    if order:
        params["order"] = f"{order}.{'desc' if desc else 'asc'}"
    if limit:
        params["limit"] = limit
    resp = requests.get(f"{BASE}/{table}", headers=HEADERS, params=params)
    resp.raise_for_status()
    data = resp.json()
    if single:
        return data[0] if data else None
    return data


def insert(table, row):
    resp = requests.post(f"{BASE}/{table}", headers=HEADERS, json=row)
    resp.raise_for_status()
    data = resp.json()
    return data[0] if data else None


def update(table, filters, values):
    params = {}
    for k, v in filters.items():
        params[k] = f"eq.{v}"
    resp = requests.patch(f"{BASE}/{table}", headers=HEADERS, params=params, json=values)
    resp.raise_for_status()
    data = resp.json()
    return data[0] if data else None


# --- Permission System Helpers ---

def grant_permission(telegram_id: int, permission: str, granted_by: int):
    try:
        insert("user_permissions", {
            "telegram_id": telegram_id,
            "permission": permission.lower(),
            "granted_by": granted_by
        })
        return True
    except Exception:
        return False


def has_permission(telegram_id: int, permission: str) -> bool:
    user = select("users", filters={"telegram_id": telegram_id}, single=True)
    if user and user.get("is_admin"):
        return True
    
    perm = select("user_permissions", filters={"telegram_id": telegram_id, "permission": permission.lower()}, single=True)
    return perm is not None


def get_all_permitted_users(permission: str):
    perm_list = select("user_permissions", filters={"permission": permission.lower()})
    return [p["telegram_id"] for p in perm_list] if perm_list else []
