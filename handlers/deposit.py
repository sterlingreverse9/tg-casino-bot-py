import html
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
from bot_instance import bot
from db import select, has_permission, get_all_permitted_users
from config import CASINO_NAME
from wallet import adjust_balance
from game_status import is_game_enabled, set_game_enabled
from middleware.admin import is_admin
from helpers import ensure_user, get_all_admin_ids
from state import deposit_states
from settings import get_deposit_upi, set_deposit_upi
from deposit import (
    create_deposit, save_utr, save_screenshot,
    get_deposit_by_utr, approve_deposit, decline_deposit, pending_deposits, deposit_history,
)
from referral import apply_deposit_reward

SUPER_ADMIN_USERNAME = "mrpuppyx"
WARNING = "‎"

FAKE_QR_BLOCK_TEMPLATE = (
    "┏━━━━━━━━━━━━━━━━┓\n"
    "┃   🚫 FAKE QR   ┃\n"
    "┃  NOT A REAL   ┃\n"
    "┃ PAYMENT CODE  ┃\n"
    "┗━━━━━━━━━━━━━━━━┛\n\n"
    "UPI ID: {upi} (NOT REAL — do not send money to it)\n\n"
)


def notify_admins_of_deposit(user_id, username, utr, amount, photo_file_id=None):
    """Sends deposit ping with screenshot photo to all staff/admins."""
    admin_ids = set(get_all_admin_ids())
    permitted_staff = set(get_all_permitted_users("deposit"))
    all_targets = admin_ids.union(permitted_staff)

    user_ref = f"@{username}" if username else f"<code>{user_id}</code>"
    
    caption = (
        f"🆕 <b>Deposit request</b>\n"
        f"User: {user_ref}\n"
        f"Amount requested: {amount} rupess\n"
        f"UTR: <code>{utr}</code>\n\n"
        f"/approve {utr}\n"
        f"/decline {utr} &lt;reason&gt;"
    )

    for target_id in all_targets:
        try:
            if photo_file_id:
                bot.send_photo(
                    chat_id=target_id,
                    photo=photo_file_id,
                    caption=caption,
                    parse_mode="HTML"
                )
            else:
                bot.send_message(
                    chat_id=target_id,
                    text=caption,
                    parse_mode="HTML"
                )
        except Exception as e:
            print(f"[Deposit Notification Error] Failed to send photo to {target_id}: {e}")
            # Fallback to text message if send_photo throws an API exception
            try:
                bot.send_message(
                    chat_id=target_id,
                    text=caption + "\n\n⚠️ <i>(Screenshot failed to attach)</i>",
                    parse_mode="HTML"
                )
            except Exception:
                pass


def notify_super_admin(action_user, deposit_user_id, utr, amount, status, reason=None):
    """Notifies @mrpuppyx whenever a staff member approves or declines a deposit."""
    try:
        user = select("users", filters={"username": SUPER_ADMIN_USERNAME}, single=True)
        if not user:
            return

        super_admin_id = int(user["telegram_id"])
        staff_ref = f"@{action_user.username}" if action_user.username else action_user.id
        
        status_emoji = "✅" if status == "approved" else "❌"
        msg = (
            f"🔔 <b>Deposit Action Notification</b>\n\n"
            f"👤 <b>Staff:</b> {staff_ref}\n"
            f"📌 <b>Action:</b> {status.upper()} {status_emoji}\n"
            f"💵 <b>Amount:</b> ₹{amount}\n"
            f"💳 <b>UTR:</b> <code>{utr}</code>\n"
            f"🎯 <b>Target User ID:</b> <code>{deposit_user_id}</code>"
        )
        if reason:
            msg += f"\n📝 <b>Reason:</b> {reason}"

        bot.send_message(super_admin_id, msg, parse_mode="HTML")
    except Exception as e:
        print(f"Failed to notify super admin: {e}")


def is_staff_user(telegram_id: int) -> bool:
    return is_admin(telegram_id) or has_permission(telegram_id, "deposit")


@bot.message_handler(commands=["changeupi"])
def cmd_changeupi(message):
    if not is_admin(message.from_user.id) and not has_permission(message.from_user.id, "deposit"):
        bot.reply_to(message, "You don't have permission to use this command.")
        return
    parts = message.text.split()
    if len(parts) != 2:
        bot.reply_to(message, "Usage: /changeupi <fake_upi_id>")
        return
    set_deposit_upi(parts[1])
    bot.reply_to(message, f"✅ Deposit UPI changed to {parts[1]}")


@bot.message_handler(commands=["deposit", "depo"])
def cmd_deposit(message):
    if not is_game_enabled("deposit"):
        bot.reply_to(message, "Deposits are currently paused.")
        return

    if message.chat.type != "private":
        markup = InlineKeyboardMarkup()
        markup.add(InlineKeyboardButton("💬 Open Deposit", url=f"https://t.me/{bot.get_me().username}?start=deposit"))
        bot.reply_to(message, "💰 Deposits are handled in DM for the bit — tap below.", reply_markup=markup)
        return

    ensure_user(message)
    deposit_states[message.from_user.id] = {"step": "amount"}
    bot.reply_to(
        message,
        f"{WARNING}\n\nHow many inr(₹) would you like to request? (min 50, enter a number)",
    )


@bot.message_handler(
    func=lambda m: m.from_user.id in deposit_states and deposit_states[m.from_user.id]["step"] == "amount",
    content_types=["text"],
)
def handle_deposit_amount(message):
    state = deposit_states[message.from_user.id]
    try:
        amount = float(message.text.strip())
    except ValueError:
        bot.reply_to(message, "Enter a valid number of inr.")
        return
    if amount < 50:
        bot.reply_to(message, "Minimum deposit is ₹50.")
        return

    dep = create_deposit(message.from_user.id, message.from_user.username, amount)
    state["deposit_id"] = dep["id"]
    state["amount"] = amount
    state["step"] = "paid"

    caption = (
        f"💰 Requested amount: ₹{amount}\n\n"
        f"UPI ID: {get_deposit_upi()}\n\n"
        f"{WARNING}\n\n"
        "Tap the button below once you've 'paid'."
    )
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("✅ I Have 'Paid'", callback_data="deposit_paid"))

    try:
        with open("/storage/emulated/0/Download/qr.jpg", "rb") as photo:
            bot.send_photo(message.chat.id, photo, caption=caption, reply_markup=markup)
    except FileNotFoundError:
        bot.send_message(message.chat.id, FAKE_QR_BLOCK_TEMPLATE.format(upi=get_deposit_upi()) + caption, reply_markup=markup)


@bot.callback_query_handler(func=lambda call: call.data == "deposit_paid")
def handle_deposit_paid(call):
    bot.answer_callback_query(call.id)
    state = deposit_states.get(call.from_user.id)
    if not state:
        bot.send_message(call.message.chat.id, "Session expired — use /deposit again.")
        return
    state["step"] = "utr"
    bot.send_message(call.message.chat.id, f"{WARNING}\n\nNow enter your 12-digit UTR code :")


@bot.message_handler(
    func=lambda m: m.from_user.id in deposit_states and deposit_states[m.from_user.id]["step"] == "utr",
    content_types=["text"],
)
def handle_deposit_utr(message):
    state = deposit_states[message.from_user.id]
    utr = message.text.strip()
    if len(utr) != 12 or not utr.isdigit():
        bot.reply_to(message, "UTR should be exactly 12 digits:")
        return
    try:
        save_utr(state["deposit_id"], utr)
        state["utr"] = utr
    except Exception:
        bot.reply_to(message, "That UTR was already used by someone else. Try a different 12 digits:")
        return

    state["step"] = "screenshot"
    bot.reply_to(message, "📸 Now send a screenshot to 'prove' your payment.")


@bot.message_handler(
    func=lambda m: m.from_user.id in deposit_states and deposit_states[m.from_user.id]["step"] == "screenshot",
    content_types=["photo", "document"],
)
def handle_deposit_screenshot(message):
    state = deposit_states.get(message.from_user.id)
    if not state:
        bot.reply_to(message, "Session expired — please run /deposit again.")
        return

    photo_file_id = None

    if message.photo:
        photo_file_id = message.photo[-1].file_id
    elif message.document and message.document.mime_type and message.document.mime_type.startswith("image/"):
        photo_file_id = message.document.file_id
    else:
        bot.reply_to(message, "Please send a valid image/screenshot.")
        return

    try:
        save_screenshot(state["deposit_id"], photo_file_id)
    except Exception as e:
        print(f"[DB Error] Failed to save screenshot ID: {e}")

    # Notify admins with screenshot
    notify_admins_of_deposit(
        user_id=message.from_user.id,
        username=message.from_user.username,
        utr=state["utr"],
        amount=state["amount"],
        photo_file_id=photo_file_id
    )

    deposit_states.pop(message.from_user.id, None)
    bot.reply_to(
        message,
        "🤨 Your request has been sent to the admins for approval. Kindly wait sometime.",
    )


@bot.message_handler(commands=["approve"])
def cmd_approve_deposit(message):
    caller_id = message.from_user.id
    caller_username = (message.from_user.username or "").lower()

    if not is_admin(caller_id) and not has_permission(caller_id, "deposit"):
        bot.reply_to(message, "You don't have permission to use this command.")
        return

    parts = message.text.split()
    if len(parts) != 2:
        bot.reply_to(message, "Usage: /approve <utr>")
        return
    utr = parts[1]
    dep = get_deposit_by_utr(utr)
    if dep is None or dep["status"] != "pending":
        bot.reply_to(message, "No pending deposit found with that UTR.")
        return

    dep_user_id = int(dep["telegram_id"])

    # Strict Staff Rules: Cannot approve self or another staff member unless @mrpuppyx
    if caller_username != SUPER_ADMIN_USERNAME.lower():
        if caller_id == dep_user_id:
            bot.reply_to(message, "❌ You cannot approve your own deposit request.")
            return
        if is_staff_user(dep_user_id):
            bot.reply_to(message, "❌ You cannot approve another staff member's deposit request. Only @mrpuppyx can.")
            return

    approve_deposit(utr, caller_id)
    new_balance = adjust_balance(dep_user_id, float(dep["amount"]))
    apply_deposit_reward(dep_user_id, float(dep["amount"]))

    bot.reply_to(message, f"✅ Approved. Credited {dep['amount']} rupees to {dep_user_id}.")

    # Direct Notification to @mrpuppyx
    notify_super_admin(message.from_user, dep_user_id, utr, dep["amount"], "approved")

    try:
        bot.send_message(dep_user_id, f"✅ Your deposit request was approved!\n+{dep['amount']} rupees\nBalance: {new_balance}")
    except Exception:
        pass


@bot.message_handler(commands=["decline"])
def cmd_decline_deposit(message):
    caller_id = message.from_user.id
    caller_username = (message.from_user.username or "").lower()

    if not is_admin(caller_id) and not has_permission(caller_id, "deposit"):
        bot.reply_to(message, "You don't have permission to use this command.")
        return

    parts = message.text.split(maxsplit=2)
    if len(parts) < 2:
        bot.reply_to(message, "Usage: /decline <utr> <reason>")
        return
    utr = parts[1]
    reason = parts[2] if len(parts) > 2 else "No reason given"
    dep = get_deposit_by_utr(utr)
    if dep is None or dep["status"] != "pending":
        bot.reply_to(message, "No pending deposit found with that UTR.")
        return

    dep_user_id = int(dep["telegram_id"])

    # Strict Staff Rules: Cannot decline self or another staff member unless @mrpuppyx
    if caller_username != SUPER_ADMIN_USERNAME.lower():
        if caller_id == dep_user_id:
            bot.reply_to(message, "❌ You cannot decline your own deposit request.")
            return
        if is_staff_user(dep_user_id):
            bot.reply_to(message, "❌ You cannot decline another staff member's deposit request. Only @mrpuppyx can.")
            return

    decline_deposit(utr, caller_id, reason)
    bot.reply_to(message, f"❌ Declined deposit {utr}.")

    # Direct Notification to @mrpuppyx
    notify_super_admin(message.from_user, dep_user_id, utr, dep["amount"], "declined", reason)

    try:
        bot.send_message(dep_user_id, f"❌ Your deposit request was declined.\nReason: {reason}")
    except Exception:
        pass


@bot.message_handler(commands=["pendingdepo"])
def cmd_pending_deposits(message):
    if not is_admin(message.from_user.id) and not has_permission(message.from_user.id, "deposit"):
        bot.reply_to(message, "You don't have permission to use this command.")
        return
    deps = pending_deposits()
    if not deps:
        bot.reply_to(message, "No pending deposit requests.")
        return
    icons_lines = [
        f"⏳ {d['amount']} ruppess • {('@' + d['username']) if d.get('username') else d['telegram_id']} • UTR {d.get('utr') or '—'}\n"
        f"   /approve {d.get('utr') or ''}  |  /decline {d.get('utr') or ''} <reason>"
        for d in deps
    ]
    bot.reply_to(message, f"⏳ Pending deposits ({len(deps)}):\n\n" + "\n\n".join(icons_lines))


@bot.message_handler(commands=["deposithistory"])
def cmd_deposit_history(message):
    if not is_admin(message.from_user.id) and not has_permission(message.from_user.id, "deposit"):
        bot.reply_to(message, "You don't have permission to use this command.")
        return
    deps = deposit_history(limit=20)
    if not deps:
        bot.reply_to(message, "No deposit requests yet.")
        return
    icons = {"pending": "⏳", "approved": "✅", "declined": "❌"}
    lines = [
        f"{icons.get(d['status'], '~) ')} {d['amount']} coins • {('@' + d['username']) if d.get('username') else d['telegram_id']} • UTR {d.get('utr') or '—'}"
        for d in deps
    ]
    bot.reply_to(message, "📜 Deposit history (last 20):\n" + "\n".join(lines))


@bot.message_handler(commands=["stopdeposit"])
def cmd_stopdeposit(message):
    if not is_admin(message.from_user.id) and not has_permission(message.from_user.id, "deposit"):
        bot.reply_to(message, "You don't have permission to use this command.")
        return
    set_game_enabled("deposit", False)
    bot.reply_to(message, "⏸️ Deposits paused.")


@bot.message_handler(commands=["startdeposit"])
def cmd_startdeposit(message):
    if not is_admin(message.from_user.id) and not has_permission(message.from_user.id, "deposit"):
        bot.reply_to(message, "You don't have permission to use this command.")
        return
    set_game_enabled("deposit", True)
    bot.reply_to(message, "▶️ Deposits resumed.")
