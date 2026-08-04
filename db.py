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
    try:
        resp = requests.get(f"{BASE}/{table}", headers=HEADERS, params=params)
        resp.raise_for_status()
        data = resp.json()
        if single:
            return data[0] if data else None
        return data
    except Exception as e:
        print(f"[Supabase Select Error on {table}]: {e}")
        return None if single else []


def insert(table, row):
    try:
        resp = requests.post(f"{BASE}/{table}", headers=HEADERS, json=row)
        resp.raise_for_status()
        data = resp.json()
        return data[0] if data else None
    except Exception as e:
        print(f"[Supabase Insert Error on {table}]: {e}")
        return None


def update(table, filters, values):
    params = {}
    for k, v in filters.items():
        params[k] = f"eq.{v}"
    try:
        resp = requests.patch(f"{BASE}/{table}", headers=HEADERS, params=params, json=values)
        resp.raise_for_status()
        data = resp.json()
        return data[0] if data else None
    except Exception as e:
        print(f"[Supabase Update Error on {table}]: {e}")
        return None


def upsert(table, row, on_conflict="chat_id"):
    """Insert or update on primary key conflict using Supabase resolution headers."""
    headers = HEADERS.copy()
    headers["Prefer"] = f"resolution=merge-duplicates,return=representation"
    try:
        resp = requests.post(f"{BASE}/{table}", headers=headers, json=row)
        resp.raise_for_status()
        data = resp.json()
        return data[0] if data else None
    except Exception as e:
        print(f"[Supabase Upsert Error on {table}]: {e}")
        return None


# --- Group Tracking Helpers ---

def register_group(chat_id: int, title: str):
    """Automatically record or update active group info."""
    row = {
        "chat_id": chat_id,
        "title": title or "Telegram Group",
        "is_active": True
    }
    upsert("groups", row, on_conflict="chat_id")


def get_all_groups():
    """Retrieve all active groups."""
    groups = select("groups", filters={"is_active": True})
    return groups if isinstance(groups, list) else []


# --- Permission System Helpers ---

def grant_permission(telegram_id: int, permission: str, granted_by: int):
    return insert("user_permissions", {
        "telegram_id": telegram_id,
        "permission": permission.lower(),
        "granted_by": granted_by
    }) is not None


def has_permission(telegram_id: int, permission: str) -> bool:
    user = select("users", filters={"telegram_id": telegram_id}, single=True)
    if user and user.get("is_admin"):
        return True

    perm = select("user_permissions", filters={"telegram_id": telegram_id, "permission": permission.lower()}, single=True)
    return perm is not None


def get_all_permitted_users(permission: str):
    perm_list = select("user_permissions", filters={"permission": permission.lower()})
    return [p["telegram_id"] for p in perm_list if "telegram_id" in p] if isinstance(perm_list, list) else []
