from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
from bot_instance import bot
from db import select
from config import CASINO_NAME
from wallet import adjust_balance
from game_status import is_game_enabled, set_game_enabled
from middleware.admin import is_admin
from helpers import ensure_user, notify_admins_of_deposit
from state import deposit_states
from deposit import (
    create_deposit, save_utr, save_screenshot,
    get_deposit_by_utr, approve_deposit, decline_deposit, pending_deposits, deposit_history,
)


FAKE_QR_BLOCK = (
    "┏━━━━━━━━━━━━━━━━┓\n"
    "┃   🚫 FAKE QR   ┃\n"
    "┃  NOT A REAL   ┃\n"
    "┃ PAYMENT CODE  ┃\n"
    "┗━━━━━━━━━━━━━━━━┛\n\n"
    "UPI ID: piyushraao@fam)\n\n"
)


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
    caption = (
        f"💰 Enter deposit amount.

Minimum: 50)"
    )
    try:
        with open("/storage/emulated/0/Download/qr.jpg", "rb") as photo:
            bot.send_photo(message.chat.id, photo, caption=caption)
    except FileNotFoundError:
        bot.reply_to(message, FAKE_QR_BLOCK + caption)


@bot.message_handler(commands=["withdraw"])
def cmd_withdraw(message):
    bot.reply_to(message, f"⚠️ Withdrawals are processed by @mrpuppyx , contact him to get withdraw — {CASINO_NAME} runs on manual withdraw for now.")


@bot.message_handler(
    func=lambda m: m.from_user.id in deposit_states and m.content_type == "text" and not m.text.startswith("/"),
    content_types=["text"],
)
def handle_deposit_text(message):
    state = deposit_states[message.from_user.id]

    if state["step"] == "amount":
        try:
            amount = float(message.text.strip())
        except ValueError:
            bot.reply_to(message, "Enter a valid number of coins.")
            return
        if amount < 50:
            bot.reply_to(message, "Minimum deposit is 50 coins.")
            return
        dep = create_deposit(message.from_user.id, message.from_user.username, amount)
        state["deposit_id"] = dep["id"]
        state["step"] = "screenshot"
        bot.reply_to(message, "📸 Now send a screenshot of the payment to prove your payment.")
        return

    if state["step"] == "utr":
        utr = message.text.strip()
        if len(utr) != 12 or not utr.isdigit():
            bot.reply_to(message, "UTR should be exactly 12 digits. It's fake anyway — just type any 12 digits:")
            return
        try:
            save_utr(state["deposit_id"], utr)
        except Exception:
            bot.reply_to(message, "That UTR was already used by someone else. Try a different 12 digits:")
            return
        deposit_states.pop(message.from_user.id, None)
        bot.reply_to(
            message,
            "✅ Deposit proof submitted!
⌛ Admin will verify and credit your wallet shortly.",
        )
        notify_admins_of_deposit(message.from_user.id, message.from_user.username, utr)


@bot.message_handler(
    func=lambda m: m.from_user.id in deposit_states and deposit_states[m.from_user.id]["step"] == "screenshot",
    content_types=["photo"],
)
def handle_deposit_screenshot(message):
    state = deposit_states[message.from_user.id]
    save_screenshot(state["deposit_id"], message.photo[-1].file_id)
    state["step"] = "utr"
    bot.reply_to(message, "Got it! Now enter your 12-digit UTR code:")


@bot.message_handler(commands=["approve"])
def cmd_approve_deposit(message):
    if not is_admin(message.from_user.id):
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
    approve_deposit(utr, message.from_user.id)
    new_balance = adjust_balance(int(dep["telegram_id"]), float(dep["amount"]))
    bot.reply_to(message, f"✅ Approved. Credited {dep['amount']} rupess to {dep['telegram_id']}.")
    try:
        bot.send_message(int(dep["telegram_id"]), f"✅ Your deposit request was approved!\n+{dep['amount']} rupess\nBalance: {new_balance}")
    except Exception:
        pass


@bot.message_handler(commands=["decline"])
def cmd_decline_deposit(message):
    if not is_admin(message.from_user.id):
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
    decline_deposit(utr, message.from_user.id, reason)
    bot.reply_to(message, f"❌ Declined deposit {utr}.")
    try:
        bot.send_message(int(dep["telegram_id"]), f"❌ Your deposit request was declined.\nReason: {reason}")
    except Exception:
        pass


@bot.message_handler(commands=["pendingdepo"])
def cmd_pending_deposits(message):
    if not is_admin(message.from_user.id):
        bot.reply_to(message, "You don't have permission to use this command.")
        return
    deps = pending_deposits()
    if not deps:
        bot.reply_to(message, "No pending deposit requests.")
        return
    lines = [
        f"⏳ {d['amount']} coins • {('@' + d['username']) if d['username'] else d['telegram_id']} • UTR {d.get('utr') or '—'}\n"
        f"   /approve {d.get('utr') or ''}  |  /decline {d.get('utr') or ''} <reason>"
        for d in deps
    ]
    bot.reply_to(message, f"⏳ Pending deposits ({len(deps)}):\n\n" + "\n\n".join(lines))


@bot.message_handler(commands=["deposithistory"])
def cmd_deposit_history(message):
    if not is_admin(message.from_user.id):
        bot.reply_to(message, "You don't have permission to use this command.")
        return
    deps = deposit_history(limit=20)
    if not deps:
        bot.reply_to(message, "No deposit requests yet.")
        return
    icons = {"pending": "⏳", "approved": "✅", "declined": "❌"}
    lines = [
        f"{icons.get(d['status'], '❔')} {d['amount']} coins • {('@' + d['username']) if d['username'] else d['telegram_id']} • UTR {d.get('utr') or '—'}"
        for d in deps
    ]
    bot.reply_to(message, "📜 Deposit history (last 20):\n" + "\n".join(lines))


@bot.message_handler(commands=["stopdeposit"])
def cmd_stopdeposit(message):
    if not is_admin(message.from_user.id):
        bot.reply_to(message, "You don't have permission to use this command.")
        return
    set_game_enabled("deposit", False)
    bot.reply_to(message, "⏸️ Deposits paused.")


@bot.message_handler(commands=["startdeposit"])
def cmd_startdeposit(message):
    if not is_admin(message.from_user.id):
        bot.reply_to(message, "You don't have permission to use this command.")
        return
    set_game_enabled("deposit", True)
    bot.reply_to(message, "▶️ Deposits resumed.")

