from db import select, insert, update
from config import HOUSE_EDGE as DEFAULT_HOUSE_EDGE

DEFAULT_MIN_BET = 10
DEFAULT_MAX_BET_PCT = 0.05  # 5% of house balance if never set
DEFAULT_MIN_WITHDRAW = 100.0
DEFAULT_HOUSE_BALANCE = 10000.0  # Fallback house balance


def _get(key, default):
    row = select("settings", filters={"key": key}, single=True)
    return row["value"] if row else default


def _set(key, value):
    row = select("settings", filters={"key": key}, single=True)
    if row is None:
        insert("settings", {"key": key, "value": str(value)})
    else:
        update("settings", {"key": key}, {"value": str(value)})


# --- House Balance Helpers ---

def get_house_balance() -> float:
    """Retrieves current house balance from DB or returns default fallback."""
    return float(_get("house_balance", DEFAULT_HOUSE_BALANCE))


def set_house_balance(amount: float):
    """Sets/updates the house balance in DB."""
    _set("house_balance", amount)


# --- Bet Limits & Settings ---

def get_min_bet() -> float:
    return float(_get("min_bet", DEFAULT_MIN_BET))


def set_min_bet(amount: float):
    _set("min_bet", amount)


def get_max_bet(house_balance: float = None) -> float:
    if house_balance is None:
        house_balance = get_house_balance()

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


def get_deposit_upi() -> str:
    return _get("deposit_upi", "not-real@fakebank")


def set_deposit_upi(upi: str):
    _set("deposit_upi", upi)


def get_referral_deposit_pct() -> float:
    return float(_get("referral_deposit_pct", 10))


def set_referral_deposit_pct(value: float):
    _set("referral_deposit_pct", value)


def get_referral_deposit_count() -> int:
    return int(float(_get("referral_deposit_count", 3)))


def set_referral_deposit_count(value: int):
    _set("referral_deposit_count", value)


def get_referral_loss_pct() -> float:
    return float(_get("referral_loss_pct", 1))


def set_referral_loss_pct(value: float):
    _set("referral_loss_pct", value)


def get_min_withdraw() -> float:
    return float(_get("min_withdraw", DEFAULT_MIN_WITHDRAW))


def set_min_withdraw(amount: float):
    _set("min_withdraw", amount)
