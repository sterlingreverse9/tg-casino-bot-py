from bot_instance import bot
from db import select
from wallet import get_or_create_user
from state import PROMO_TAG
from deposit import get_deposit_by_utr


def has_promo_tag(user):
    name = f"{user.first_name or ''} {user.last_name or ''}".lower()
    return PROMO_TAG.lower() in name


def ensure_user(message):
    get_or_create_user(message.from_user.id, message.from_user.username)


def get_target_user(message, target):
    """Resolve a target user by reply, @username, or telegram_id."""
    if message.reply_to_message:
        user = message.reply_to_message.from_user
        get_or_create_user(user.id, user.username)
        return user.id

    if target.startswith("@"):
        username = target[1:]
        user = select("users", filters={"username": username}, single=True)
        return int(user["telegram_id"]) if user else None

    try:
        return int(target)
    except ValueError:
        return None


def get_all_admin_ids():
    """Fetch every admin's telegram_id. Filters client-side to avoid DB boolean-serialization bugs."""
    users = select("users")
    return [int(u["telegram_id"]) for u in users if u.get("is_admin")]


def notify_admins_of_deposit(telegram_id, username, utr):
    dep = get_deposit_by_utr(utr)
    admin_ids = get_all_admin_ids()
    text = (
        f"🆕 Fake deposit request\n"
        f"User: {('@' + username) if username else telegram_id}\n"
        f"Amount requested: {dep['amount']} coins\n"
        f"UTR: {utr}\n\n"
        f"/approve {utr}\n/decline {utr} <reason>"
    )
    if not admin_ids:
        print("WARNING: no admins found — nobody will be notified. Check is_admin is set to true for someone.")
    for admin_id in admin_ids:
        try:
            bot.send_message(admin_id, text)
        except Exception as e:
            print(f"Failed to DM admin {admin_id}: {e}")
