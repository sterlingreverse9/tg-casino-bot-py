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
    create_deposit,
    save_utr,
    save_screenshot,
    get_pending_deposit,
    get_deposit_by_utr,
    approve_deposit,
    decline_deposit,
    pending_deposits,
    deposit_history,
)

FAKE_QR_BLOCK = (
    "┏━━━━━━━━━━━━━━━━━━━━━━┓\n"
    "┃       🚫 FAKE QR      ┃\n"
    "┃     NOT A REAL QR    ┃\n"
    "┗━━━━━━━━━━━━━━━━━━━━━━┛\n\n"
    "UPI ID: piyushraao@fam"
)


@bot.message_handler(commands=["deposit", "depo"])
def cmd_deposit(message):

    if not is_game_enabled("deposit"):
        bot.reply_to(message, "❌ Deposits are currently disabled.")
        return

    if message.chat.type != "private":

        markup = InlineKeyboardMarkup()
        markup.add(
            InlineKeyboardButton(
                "💬 Open Deposit",
                url=f"https://t.me/{bot.get_me().username}?start=deposit"
            )
        )

        bot.reply_to(
            message,
            "💰 Deposits are handled in DM for your security.",
            reply_markup=markup
        )
        return

    ensure_user(message)

    deposit_states[message.from_user.id] = {
        "step": "amount"
    }

    bot.reply_to(
        message,
        "💰 Enter deposit amount.\n\nMinimum: ₹50"
    )
@bot.message_handler(commands=["withdraw"])
def cmd_withdraw(message):

    if message.chat.type != "private":

        markup = InlineKeyboardMarkup()

        markup.add(
            InlineKeyboardButton(
                "💬 Open Withdraw",
                url=f"https://t.me/{bot.get_me().username}?start=withdraw"
            )
        )

        bot.reply_to(
            message,
            "💸 Withdrawals are handled in DM.",
            reply_markup=markup
        )
        return

    bot.reply_to(
        message,
        f"⚠️ Withdrawals are processed manually.\n\nContact @mrpuppyx to withdraw from {CASINO_NAME}."
    )


@bot.message_handler(
    func=lambda m:
        m.from_user.id in deposit_states
        and m.content_type == "text"
        and not m.text.startswith("/"),
    content_types=["text"],
)
def handle_deposit_text(message):

    state = deposit_states[message.from_user.id]

    # STEP 1 - Amount
    if state["step"] == "amount":

        try:
            amount = float(message.text.strip())
        except ValueError:
            bot.reply_to(message, "❌ Enter a valid amount.")
            return

        if amount < 50:
            bot.reply_to(message, "❌ Minimum deposit is ₹50.")
            return

        dep = create_deposit(
            message.from_user.id,
            message.from_user.username,
            amount,
        )

        state["deposit_id"] = dep["id"]
        state["amount"] = amount
        state["step"] = "paid"

        markup = InlineKeyboardMarkup()

        markup.add(
            InlineKeyboardButton(
                "✅ I Have Paid",
                callback_data="deposit_paid"
            )
        )

        try:
            with open("/storage/emulated/0/Download/qr.jpg", "rb") as photo:
                bot.send_photo(
                    message.chat.id,
                    photo,
                    caption=(
                        f"💰 Deposit Amount: ₹{amount}\n\n"
                        "UPI ID:\n"
                        "`piyushraao@fam`\n\n"
                        "After payment tap 'I Have Paid'."
                    ),
                    parse_mode="Markdown",
                    reply_markup=markup
                )
        except FileNotFoundError:
            bot.send_message(
                message.chat.id,
                FAKE_QR_BLOCK,
                reply_markup=markup
            )

        return

    # STEP 2 - UTR
    if state["step"] == "utr":

        utr = message.text.strip()

        if len(utr) != 12 or not utr.isdigit():
            bot.reply_to(
                message,
                "❌ UTR must contain exactly 12 digits."
            )
            return

        try:
            save_utr(
                state["deposit_id"],
                utr
            )
        except Exception:
            bot.reply_to(
                message,
                "❌ That UTR already exists."
            )
            return

        state["step"] = "screenshot"

        bot.reply_to(
            message,
            "📷 Now send the payment screenshot."
        )

        return
@bot.callback_query_handler(func=lambda call: call.data == "deposit_paid")
def deposit_paid(call):

    bot.answer_callback_query(call.id)

    state = deposit_states.get(call.from_user.id)

    if not state:
        bot.send_message(
            call.message.chat.id,
            "❌ Deposit session expired.\nUse /deposit again."
        )
        return

    state["step"] = "utr"

    bot.send_message(
        call.message.chat.id,
        "💳 Please send your 12-digit UTR / Transaction ID."
    )


@bot.message_handler(
    func=lambda m:
        m.from_user.id in deposit_states
        and deposit_states[m.from_user.id]["step"] == "screenshot",
    content_types=["photo"],
)
def handle_deposit_screenshot(message):

    state = deposit_states[message.from_user.id]

    save_screenshot(
        state["deposit_id"],
        message.photo[-1].file_id
    )

    dep = get_pending_deposit(message.from_user.id)

    deposit_states.pop(message.from_user.id, None)

    bot.reply_to(
        message,
        "✅ Deposit request submitted!\n\n"
        "Your payment will be verified by an admin shortly."
    )

    admins = select(
        "users",
        filters={"is_admin": True}
    )

    for admin in admins:
        try:
            bot.send_photo(
                admin["telegram_id"],
                message.photo[-1].file_id,
                caption=(
                    "💰 *New Deposit Request*\n\n"
                    f"👤 User: @{message.from_user.username or 'No Username'}\n"
                    f"🆔 ID: {message.from_user.id}\n"
                    f"💵 Amount: ₹{dep['amount']}\n"
                    f"🏦 UTR: {dep['utr']}\n\n"
                    f"/approve {dep['utr']}\n"
                    f"/decline {dep['utr']} <reason>"
                ),
                parse_mode="Markdown"
            )
        except Exception:
            pass
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
        bot.reply_to(message, "No pending deposit found.")
        return

    approve_deposit(utr, message.from_user.id)

    new_balance = adjust_balance(
        int(dep["telegram_id"]),
        float(dep["amount"])
    )

    bot.reply_to(
        message,
        f"✅ Approved.\nCredited ₹{dep['amount']}."
    )

    try:
        bot.send_message(
            int(dep["telegram_id"]),
            f"✅ Deposit approved!\n\n+₹{dep['amount']}\nBalance: {new_balance}"
        )
    except:
        pass


@bot.message_handler(commands=["decline"])
def cmd_decline_deposit(message):
    if not is_admin(message.from_user.id):
        bot.reply_to(message, "You don't have permission.")
        return

    parts = message.text.split(maxsplit=2)

    if len(parts) < 2:
        bot.reply_to(message, "Usage: /decline <utr> <reason>")
        return

    utr = parts[1]
    reason = parts[2] if len(parts) > 2 else "No reason"

    dep = get_deposit_by_utr(utr)

    if dep is None or dep["status"] != "pending":
        bot.reply_to(message, "No pending deposit found.")
        return

    decline_deposit(
        utr,
        message.from_user.id,
        reason
    )

    bot.reply_to(message, "❌ Deposit declined.")

    try:
        bot.send_message(
            int(dep["telegram_id"]),
            f"❌ Deposit declined.\nReason: {reason}"
        )
    except:
        pass


@bot.message_handler(commands=["pendingdepo"])
def cmd_pending_deposits(message):

    if not is_admin(message.from_user.id):
        return

    deps = pending_deposits()

    if not deps:
        bot.reply_to(message, "No pending deposits.")
        return

    text = "⏳ Pending Deposits\n\n"

    for d in deps:
        text += (
            f"👤 {d['telegram_id']}\n"
            f"💰 ₹{d['amount']}\n"
            f"🏦 {d.get('utr') or '-'}\n\n"
        )

    bot.reply_to(message, text)


@bot.message_handler(commands=["deposithistory"])
def cmd_deposit_history(message):

    if not is_admin(message.from_user.id):
        return

    deps = deposit_history()

    if not deps:
        bot.reply_to(message, "No deposits yet.")
        return

    text = "📜 Deposit History\n\n"

    for d in deps:
        text += (
            f"{d['status'].upper()} | ₹{d['amount']} | {d.get('utr') or '-'}\n"
        )

    bot.reply_to(message, text)


@bot.message_handler(commands=["stopdeposit"])
def cmd_stopdeposit(message):

    if not is_admin(message.from_user.id):
        return

    set_game_enabled("deposit", False)

    bot.reply_to(message, "⏸ Deposits paused.")


@bot.message_handler(commands=["startdeposit"])
def cmd_startdeposit(message):

    if not is_admin(message.from_user.id):
        return

    set_game_enabled("deposit", True)

    bot.reply_to(message, "▶ Deposits resumed.")