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
