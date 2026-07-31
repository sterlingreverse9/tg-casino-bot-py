from db import select, insert, update
from config import HOUSE_EDGE as DEFAULT_HOUSE_EDGE

DEFAULT_MIN_BET = 10
DEFAULT_MAX_BET_PCT = 0.05  # 5% of house balance if never set


def _get(key, default):
    row = select("settings", filters={"key": key}, single=True)
    return row["value"] if row else default


def _set(key, value):
    row = select("settings", filters={"key": key}, single=True)
    if row is None:
        insert("settings", {"key": key, "value": str(value)})
    else:
        update("settings", {"key": key}, {"value": str(value)})


def get_min_bet() -> float:
    return float(_get("min_bet", DEFAULT_MIN_BET))


def set_min_bet(amount: float):
    _set("min_bet", amount)


def get_max_bet(house_balance: float) -> float:
    raw = _get("max_bet", None)
    if raw is None:
        return house_balance * DEFAULT_MAX_BET_PCT
    raw = str(raw)
    if raw.endswith("%"):
        return house_balance * (float(raw.rstrip("%")) / 100)
    return float(raw)


def set_max_bet(raw_value: str):
    """raw_value like '100' or '5%'"""
    _set("max_bet", raw_value)


def get_house_edge() -> float:
    return float(_get("house_edge", DEFAULT_HOUSE_EDGE))


def set_house_edge(value: float):
    _set("house_edge", value)
