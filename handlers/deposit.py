from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
from bot_instance import bot
from db import select
from config import CASINO_NAME
from wallet import adjust_balance
from game_status import is_game_enabled, set_game_enabled
from middleware.admin import is_admin
from helpers import ensure_user, notify_admins_of_deposit
from state import deposit_states
from settings import get_deposit_upi, set_deposit_upi
from deposit import (
    create_deposit, save_utr, save_screenshot,
    get_deposit_by_utr, approve_deposit, decline_deposit, pending_deposits, deposit_history,
)
from referral import apply_deposit_reward

MIN_DEPOSIT = 30


@bot.message_handler(commands=["changeupi"])
def cmd_changeupi(message):
    if not is_admin(message.from_user.id):
        bot.reply_to(message, "You don't have permission to use this command.")
        return
    parts = message.text.split()
    if len(parts) != 2:
        bot.reply_to(message, "Usage: /changeupi <upi_id>")
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
        markup.add(InlineKeyboardButton("💬 Open in DM", url=f"https://t.me/{bot.get_me().username}?start=deposit"))
        bot.reply_to(message, "💳 Deposits are handled in DM — tap below to continue.", reply_markup=markup)
        return

    ensure_user(message)
    deposit_states[message.from_user.id] = {"step": "amount"}
    bot.reply_to(message, f"💳 Enter deposit amount.\n\nMinimum: {MIN_DEPOSIT} coins")


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
            bot.reply_to(message, "Enter a valid amount.")
            return
        if amount < MIN_DEPOSIT:
            bot.reply_to(message, f"Minimum deposit is {MIN_DEPOSIT} coins.")
            return

        dep = create_deposit(message.from_user.id, message.from_user.username, amount)
        state["deposit_id"] = dep["id"]
        state["amount"] = amount
        state["step"] = "paid"

        caption = (
            f"💰 Deposit Amount: {amount} coins\n\n"
            f"UPI ID: {get_deposit_upi()}\n"
            "(fun-coins only — no real money accepted here)\n\n"
            "After payment, tap 'I Have Paid'."
        )
        markup = InlineKeyboardMarkup()
        markup.add(InlineKeyboardButton("✅ I Have Paid", callback_data="deposit_paid"))

        try:
            with open("/storage/emulated/0/Download/qr.jpg", "rb") as photo:
                bot.send_photo(message.chat.id, photo, caption=caption, reply_markup=markup)
        except FileNotFoundError:
            bot.send_message(message.chat.id, caption, reply_markup=markup)
        return

    if state["step"] == "utr":
        utr = message.text.strip()
        if len(utr) != 12 or not utr.isdigit():
            bot.reply_to(message, "UTR must be exactly 12 digits.")
            return
        try:
            save_utr(state["deposit_id"], utr)
        except Exception:
            bot.reply_to(message, "That UTR was already used. Try a different 12 digits:")
            return
        state["step"] = "screenshot"
        bot.reply_to(message, "📸 Now send the payment screenshot.")
        return


@bot.callback_query_handler(func=lambda call: call.data == "deposit_paid")
def handle_deposit_paid(call):
    bot.answer_callback_query(call.id)
    state = deposit_states.get(call.from_user.id)
    if not state:
        bot.send_message(call.message.chat.id, "Session expired — use /deposit again.")
        return
    state["step"] = "utr"
    bot.send_message(call.message.chat.id, "💳 Please send your 12-digit UTR / Transaction ID.")


@bot.message_handler(
    func=lambda m: m.from_user.id in deposit_states and deposit_states[m.from_user.id]["step"] == "screenshot",
    content_types=["photo"],
)
def handle_deposit_screenshot(message):
    state = deposit_states[message.from_user.id]
    save_screenshot(state["deposit_id"], message.photo[-1].file_id)
    dep = select("deposits", filters={"id": state["deposit_id"]}, single=True)
    deposit_states.pop(message.from_user.id, None)

    bot.reply_to(
        message,
        "✅ Deposit request submitted!\n\nYour payment will be verified by an admin shortly.",
    )
    if dep:
        notify_admins_of_deposit(message.from_user.id, message.from_user.username, dep["utr"])


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
    apply_deposit_reward(int(dep["telegram_id"]), float(dep["amount"]))
    bot.reply_to(message, f"✅ Approved. Credited {dep['amount']} coins to {dep['telegram_id']}.")
    try:
        bot.send_message(int(dep["telegram_id"]), f"✅ Deposit approved!\n\n+{dep['amount']} coins\nBalance: {new_balance}")
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
    bot.reply_to(message, "❌ Deposit declined.")
    try:
        bot.send_message(int(dep["telegram_id"]), f"❌ Deposit declined.\nReason: {reason}")
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
        f"👤 {d['telegram_id']} • {d['amount']} coins • UTR {d.get('utr') or '-'}\n"
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
        bot.reply_to(message, "No deposits yet.")
        return
    lines = [f"{d['status'].upper()} | {d['amount']} coins | {d.get('utr') or '-'}" for d in deps]
    bot.reply_to(message, "📜 Deposit History:\n\n" + "\n".join(lines))


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
