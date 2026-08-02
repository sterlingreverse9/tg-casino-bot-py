from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
from bot_instance import bot
from db import select
from config import CASINO_NAME
from wallet import adjust_balance
from game_status import is_game_enabled, set_game_enabled
from middleware.admin import is_admin
from helpers import ensure_user
from state import deposit_states
from settings import get_deposit_upi, set_deposit_upi
from referral import apply_deposit_reward
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


@bot.message_handler(commands=["changeupi"])
def cmd_changeupi(message):

    if not is_admin(message.from_user.id):
        bot.reply_to(message, "You don't have permission.")
        return

    parts = message.text.split(maxsplit=1)

    if len(parts) != 2:
        bot.reply_to(
            message,
            "Usage:\n/changeupi <upi_id>"
        )
        return

    set_deposit_upi(parts[1])

    bot.reply_to(
        message,
        f"✅ Deposit UPI updated to:\n`{parts[1]}`",
        parse_mode="Markdown"
    )


@bot.message_handler(commands=["deposit", "depo"])
def cmd_deposit(message):

    if not is_game_enabled("deposit"):
        bot.reply_to(message, "❌ Deposits are currently paused.")
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
        "💰 Enter the amount you want to deposit.\n\n"
        "Minimum deposit: ₹50"
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
        f"⚠️ Withdrawals are processed manually.\n\n"
        f"Contact @mrpuppyx to withdraw from {CASINO_NAME}."
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

    if state["step"] == "amount":

        try:
            amount = float(message.text.strip())
        except ValueError:
            bot.reply_to(message, "❌ Please enter a valid amount.")
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
                callback_data="deposit_paid",
            )
        )

        upi = get_deposit_upi()

        try:
            with open("/storage/emulated/0/Download/qr.jpg", "rb") as photo:

                bot.send_photo(
                    message.chat.id,
                    photo,
                    caption=(
                        f"💰 *Deposit Amount:* ₹{amount}\n\n"
                        f"🏦 *UPI ID:*\n"
                        f"`{upi}`\n\n"
                        "After payment press *I Have Paid*."
                    ),
                    parse_mode="Markdown",
                    reply_markup=markup,
                )

        except FileNotFoundError:

            bot.send_message(
                message.chat.id,
                (
                    f"💰 Deposit Amount: ₹{amount}\n\n"
                    f"UPI ID:\n`{upi}`"
                ),
                parse_mode="Markdown",
                reply_markup=markup,
            )

        return

    if state["step"] == "utr":

        utr = message.text.strip()

        if not utr.isdigit() or len(utr) != 12:

            bot.reply_to(
                message,
                "❌ UTR must contain exactly 12 digits."
            )
            return

        try:
            save_utr(
                state["deposit_id"],
                utr,
            )

        except Exception:

            bot.reply_to(
                message,
                "❌ This UTR already exists."
            )
            return

        state["step"] = "screenshot"

        bot.reply_to(
            message,
            "📷 Now send your payment screenshot."
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

    if state["step"] != "paid":
        bot.send_message(
            call.message.chat.id,
            "❌ Invalid deposit state."
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
        message.photo[-1].file_id,
    )

    dep = get_pending_deposit(message.from_user.id)

    deposit_states.pop(message.from_user.id, None)

    bot.reply_to(
        message,
        "✅ Deposit request submitted!\n\n"
        "Your payment will be reviewed by an admin shortly."
    )

    admins = select(
        "users",
        filters={"is_admin": True},
    )

    for admin in admins:

        try:

            markup = InlineKeyboardMarkup()

            markup.row(
                InlineKeyboardButton(
                    "✅ Approve",
                    callback_data=f"approve_{dep['utr']}"
                ),
                InlineKeyboardButton(
                    "❌ Decline",
                    callback_data=f"decline_{dep['utr']}"
                )
            )

            bot.send_photo(
                admin["telegram_id"],
                message.photo[-1].file_id,
                caption=(
                    "💰 *NEW DEPOSIT REQUEST*\n\n"
                    f"👤 User: @{message.from_user.username or 'No Username'}\n"
                    f"🆔 ID: `{message.from_user.id}`\n"
                    f"💵 Amount: ₹{dep['amount']}\n"
                    f"🏦 UTR: `{dep['utr']}`"
                ),
                parse_mode="Markdown",
                reply_markup=markup,
            )

        except Exception:
            pass
