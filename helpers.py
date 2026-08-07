import sys
import html
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton

from bot_instance import bot
from db import select
from wallet import get_or_create_user
from state import PROMO_TAG

# Safe import to handle both root and handlers/ folder structures
try:
    from handlers.deposit import get_deposit_by_utr
except ImportError:
    try:
        from deposit import get_deposit_by_utr
    except ImportError:
        def get_deposit_by_utr(utr):
            return None

WINS_CHANNEL = "@thecassinowins"
PLAY_GROUP_URL = "https://t.me/thecassinogroup"

# Global set to track frozen users in memory
FROZEN_USERS = set()


def is_user_frozen(user_id: int) -> bool:
    """Check if a given user is currently frozen."""
    return user_id in FROZEN_USERS


def set_user_frozen(user_id: int, freeze: bool):
    """Freeze or unfreeze a given user."""
    if freeze:
        FROZEN_USERS.add(user_id)
    else:
        FROZEN_USERS.discard(user_id)


# Expanded to cover all native Telegram animated games & custom mini-games
GAME_EMOJIS = {
    "RPS ✊✌️✋": "✊",
    "Coinflip": "🪙",
    "Dice Roll": "🎲",
    "Darts": "🎯",
    "Basketball": "🏀",
    "Slots": "🎰",
    "Football": "⚽",
    "Bowling": "🎳",
    "Limbo": "🚀",
    "Tower": "🏗️",
    "Dice Duel": "⚔️",
    "Predict Number": "🔮",
}


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

    if not target:
        return None

    if target.startswith("@"):
        username = target[1:]
        user = select("users", filters={"username": username}, single=True)
        return int(user["telegram_id"]) if user else None

    try:
        return int(target)
    except ValueError:
        return None


def get_all_admin_ids():
    """Fetch every admin's telegram_id dynamically from DB."""
    try:
        users = select("users") or []
        return [int(u["telegram_id"]) for u in users if u.get("is_admin")]
    except Exception as e:
        print(f"[HELPERS DEBUG ERROR] Failed to fetch admin IDs: {e}", file=sys.stderr)
        return []


def is_admin(user_id: int) -> bool:
    """Check if user is admin."""
    return user_id in get_all_admin_ids()


def format_display_name(first_name, username):
    if username:
        return f"{first_name or username} (@{username})"
    return first_name or "Player"


def announce_win(*args, **kwargs):
    """
    Flexible win broadcast function.
    Accepts positional/keyword calls from rps_game.py, games, or legacy scripts.
    """
    user_id = kwargs.get("user_id")
    user_name = kwargs.get("user_name")
    game_name = kwargs.get("game_name")
    bet = kwargs.get("bet", 0.0)
    payout = kwargs.get("payout", 0.0)
    multiplier = kwargs.get("multiplier", 1.0)

    # Legacy positional fallback (name, amount, game_label)
    if not user_name and len(args) > 0:
        user_name = args[0]
    if payout == 0.0 and len(args) > 1:
        payout = args[1]
    if not game_name and len(args) > 2:
        game_name = args[2]

    if not user_name:
        user_name = "Player"
    if not game_name:
        game_name = "Casino Game"

    emoji = GAME_EMOJIS.get(game_name, "🎰")
    safe_name = html.escape(str(user_name))

    text = (
        f"🎉 <b>BIG WIN!</b> {emoji}\n\n"
        f"👤 <b>Player:</b> {safe_name}\n"
        f"🎮 <b>Game:</b> {game_name}\n"
        f"💵 <b>Bet:</b> ₹{bet:.2f}\n"
        f"🚀 <b>Multiplier:</b> x{multiplier:.2f}\n"
        f"💰 <b>Payout:</b> ₹{payout:.2f}"
    )

    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("▶️ Play Here", url=PLAY_GROUP_URL))

    try:
        bot.send_message(WINS_CHANNEL, text, reply_markup=markup, parse_mode="HTML")
        print(f"[HELPERS DEBUG] Win announcement successfully posted to {WINS_CHANNEL}", file=sys.stderr)
    except Exception as e:
        print(f"[HELPERS DEBUG ERROR] Failed to post win announcement: {e}", file=sys.stderr)


# Alias functions to ensure full compatibility with dynamic checkers
send_win_update = announce_win
post_win_update = announce_win


def is_member_of(channel: str, telegram_id: int) -> bool:
    try:
        member = bot.get_chat_member(channel, telegram_id)
        return member.status in ("member", "administrator", "creator")
    except Exception:
        return False


def notify_admins_of_deposit(telegram_id, username, utr):
    dep = get_deposit_by_utr(utr)
    if not dep:
        return
    admin_ids = get_all_admin_ids()

    text = (
        f"🆕 <b>Deposit Request Received</b>\n\n"
        f"👤 <b>User:</b> {('@' + username) if username else telegram_id}\n"
        f"💵 <b>Amount Requested:</b> ₹{dep['amount']}\n"
        f"💳 <b>UTR:</b> <code>{utr}</code>\n\n"
        f"✅ <code>/approve {utr}</code>\n"
        f"❌ <code>/decline {utr} &lt;reason&gt;</code>"
    )
    if not admin_ids:
        print("WARNING: no admins found — nobody will be notified. Check is_admin is set to true for someone.")
    for admin_id in admin_ids:
        try:
            bot.send_message(admin_id, text, parse_mode="HTML")
        except Exception as e:
            print(f"Failed to DM admin {admin_id}: {e}")
