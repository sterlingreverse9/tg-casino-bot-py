import datetime
import html
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
from bot_instance import bot
from db import select
from wallet import get_balance, adjust_balance, get_wager_remaining
from state import withdraw_states, admin_wd_states
from settings import get_min_withdraw, set_min_withdraw
from helpers import ensure_user
from withdraw import create_withdrawal, get_withdrawal, approve_withdrawal, decline_withdrawal, get_pending_withdrawals

SUPER_ADMIN_USERNAME = "mrpuppyx"
CHANNEL_USERNAME = "@thecassinoupdates"
FEE_PERCENT = 0.025  # 2.5%


@bot.message_handler(commands=["wagerstats"])
def cmd_wagerstats(message):
    ensure_user(message)
    rem = get_wager_remaining(message.from_user.id)
    if rem <= 0:
        bot.reply_to(message, "✅ <b>Wager Complete!</b> You have fulfilled all wager requirements and can withdraw freely.", parse_mode="HTML")
    else:
        bot.reply_to(message, f"🎯 <b>Wager Progress</b>\n\nYou need to wager <b>₹{rem:.2f}</b> more to unlock withdrawals.", parse_mode="HTML")


@bot.message_handler(commands=["withdraw", "wd"])
def cmd_withdraw(message):
    ensure_user(message)
    if message.chat.type != "private":
        markup = InlineKeyboardMarkup()
        markup.add(InlineKeyboardButton("🔒 Withdraw in DM", url=f"https://t.me/{bot.get_me().username}?start=withdraw"))
        bot.reply_to(message, "🔒 Withdrawals are handled in DM for security purposes.", reply_markup=markup)
        return

    wager_left = get_wager_remaining(message.from_user.id)
    if wager_left > 0:
        bot.reply_to(message, f"❌ You can't withdraw, you have to wager ₹{wager_left:.2f} more to withdraw.\n\nYou can also check wager status using /wagerstats")
        return

    bal = get_balance(message.from_user.id)
    min_wd = get_min_withdraw()

    withdraw_states[message.from_user.id] = {"step": "amount"}

    msg = (
        f"💸 <b>Withdraw</b>\n\n"
        f"💵 <b>Your balance:</b> ₹{bal:.2f}\n\n"
        f"How much do you want to withdraw?\n"
        f"Min: ₹{min_wd:.0f} — Type the amount:"
    )
    bot.send_message(message.chat.id, msg, parse_mode="HTML")


@bot.message_handler(
    func=lambda m: m.from_user.id in withdraw_states and withdraw_states[m.from_user.id]["step"] == "amount",
    content_types=["text"]
)
def handle_withdraw_amount(message):
    state = withdraw_states[message.from_user.id]
    try:
        amt = float(message.text.strip())
    except ValueError:
        bot.reply_to(message, "Please enter a valid numeric amount.")
        return

    bal = get_balance(message.from_user.id)
    min_wd = get_min_withdraw()

    if amt < min_wd:
        bot.reply_to(message, f"Minimum withdrawal amount is ₹{min_wd:.2f}.")
        return
    if amt > bal:
        bot.reply_to(message, f"Insufficient balance. Your balance: ₹{bal:.2f}")
        return

    state["amount"] = amt
    state["step"] = "upi"
    bot.reply_to(message, "Pls enter upi id :")


@bot.message_handler(
    func=lambda m: m.from_user.id in withdraw_states and withdraw_states[m.from_user.id]["step"] == "upi",
    content_types=["text"]
)
def handle_withdraw_upi(message):
    upi = message.text.strip()
    if "@" not in upi or len(upi) < 5:
        bot.reply_to(message, "Please enter a valid UPI ID (e.g., user@upi):")
        return

    state = withdraw_states[message.from_user.id]
    amt = state["amount"]
    fee = round(amt * FEE_PERCENT, 2)
    net = round(amt - fee, 2)

    state["upi"] = upi
    state["fee"] = fee
    state["net"] = net
    state["step"] = "confirm"

    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("I confirm ✅", callback_data="confirm_withdraw"))

    msg = (
        f"<b>Confirm Withdrawal Request</b>\n\n"
        f"💵 Requested: ₹{amt:.2f}\n"
        f"💰 Fee (2.5%): ₹{fee:.2f}\n"
        f"💵 You receive: ₹{net:.2f}\n"
        f"👨‍💻 UPI: <code>{upi}</code>\n\n"
        f"Please confirm withdrawal request using button below:"
    )
    bot.send_message(message.chat.id, msg, parse_mode="HTML", reply_markup=markup)


@bot.callback_query_handler(func=lambda call: call.data == "confirm_withdraw")
def handle_withdraw_confirm(call):
    bot.answer_callback_query(call.id)
    user_id = call.from_user.id
    state = withdraw_states.get(user_id)

    if not state or state.get("step") != "confirm":
        bot.send_message(call.message.chat.id, "Session expired. Please run /withdraw again.")
        return

    bal = get_balance(user_id)
    amt = state["amount"]
    if amt > bal:
        bot.send_message(call.message.chat.id, "Insufficient balance.")
        withdraw_states.pop(user_id, None)
        return

    # Deduct balance immediately upon request submission
    rem_bal = adjust_balance(user_id, -amt)

    wd_rec = create_withdrawal(
        telegram_id=user_id,
        username=call.from_user.username,
        full_name=call.from_user.first_name,
        amount=amt,
        fee=state["fee"],
        net_amount=state["net"],
        upi_id=state["upi"]
    )
    wd_id = wd_rec["wd_id"]

    withdraw_states.pop(user_id, None)

    msg = (
        f"✅ Withdrawal Request #{wd_id} Submitted!\n\n"
        f"💵 Requested: ₹{amt:.2f}\n"
        f"💰 Fee: ₹{state['fee']:.2f} (2.50%)\n"
        f"💵 You receive: ₹{state['net']:.2f}\n"
        f"👨‍💻 UPI: {state['upi']}\n"
        f"💰 Remaining Balance: ₹{rem_bal:.2f}\n\n"
        f"⌛ Admin will process your payment shortly."
    )
    bot.edit_message_text(msg, call.message.chat.id, call.message.message_id)

    # Notify @mrpuppyx directly
    try:
        user_db = select("users", filters={"username": SUPER_ADMIN_USERNAME}, single=True)
        if user_db:
            super_admin_id = int(user_db["telegram_id"])
            user_ref = f"@{call.from_user.username}" if call.from_user.username else f"<code>{user_id}</code>"
            admin_msg = (
                f"🆕 <b>New Withdrawal Request #{wd_id}</b>\n\n"
                f"👤 User: {user_ref}\n"
                f"💵 Requested: ₹{amt:.2f}\n"
                f"💰 Fee: ₹{state['fee']:.2f}\n"
                f"💵 Pay Out: ₹{state['net']:.2f}\n"
                f"👨‍💻 UPI: <code>{state['upi']}</code>\n\n"
                f"To approve: <code>/Approvewd {wd_id}</code>\n"
                f"To decline: <code>/Declinewd {wd_id} &lt;reason&gt;</code>"
            )
            bot.send_message(super_admin_id, admin_msg, parse_mode="HTML")
    except Exception as e:
        print(f"Failed to ping super admin for withdrawal: {e}")


# --- Super Admin Commands ---

@bot.message_handler(commands=["Approvewd", "approvewd"])
def cmd_approve_wd(message):
    if (message.from_user.username or "").lower() != SUPER_ADMIN_USERNAME.lower():
        return

    parts = message.text.split()
    if len(parts) != 2:
        bot.reply_to(message, "Usage: /Approvewd <withdrawal_id>")
        return

    wd_id = parts[1].lstrip("#")
    wd = get_withdrawal(wd_id)
    if not wd or wd["status"] != "pending":
        bot.reply_to(message, "Invalid or non-pending withdrawal ID.")
        return

    admin_wd_states[message.from_user.id] = {"wd_id": wd_id}
    bot.reply_to(message, f"📸 Please send the payment screenshot for Withdrawal #{wd_id}:")


@bot.message_handler(
    func=lambda m: m.from_user.id in admin_wd_states,
    content_types=["photo", "document"]
)
def handle_wd_screenshot(message):
    state = admin_wd_states.pop(message.from_user.id)
    wd_id = state["wd_id"]
    wd = get_withdrawal(wd_id)

    if not wd or wd["status"] != "pending":
        bot.reply_to(message, "Withdrawal request no longer active.")
        return

    photo_file_id = message.photo[-1].file_id if message.photo else message.document.file_id

    approve_withdrawal(wd_id, message.from_user.id)
    bot.reply_to(message, f"✅ Withdrawal #{wd_id} approved and process completed!")

    target_user_id = int(wd["telegram_id"])
    net_amt = float(wd["net_amount"])
    upi = wd["upi_id"]

    # Notification to User
    caption = (
        f"🏆 <b>Payment Done!</b>\n\n"
        f"₹{net_amt:.2f} sent to:\n"
        f"👨‍💻 {upi}\n\n"
        f"✅ Check your UPI app!"
    )
    try:
        bot.send_photo(target_user_id, photo_file_id, caption=caption, parse_mode="HTML")
    except Exception:
        bot.send_message(target_user_id, caption, parse_mode="HTML")

    # Broadcast to Channel
    try:
        u_name = wd.get("full_name") or "Player"
        u_tag = f"@{wd['username']}" if wd.get("username") else u_name
        now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        chan_msg = (
            f"<b>New withdrawal sent ✅</b>\n\n"
            f"<b>Withdrawer name :</b> {u_name} ({u_tag})\n"
            f"<b>Amount:</b> ₹{net_amt:.2f}\n"
            f"<b>Time of withdraw:</b> {now_str}\n\n"
            f"You can also withdraw using /withdraw. Keep playing keep winning 🚀"
        )
        bot.send_message(CHANNEL_USERNAME, chan_msg, parse_mode="HTML")
    except Exception as e:
        print(f"Failed to post to channel: {e}")


@bot.message_handler(commands=["Declinewd", "declinewd"])
def cmd_decline_wd(message):
    if (message.from_user.username or "").lower() != SUPER_ADMIN_USERNAME.lower():
        return

    parts = message.text.split(maxsplit=2)
    if len(parts) < 3:
        bot.reply_to(message, "Usage: /Declinewd <withdrawal_id> <reason>")
        return

    wd_id = parts[1].lstrip("#")
    reason = parts[2]
    wd = get_withdrawal(wd_id)

    if not wd or wd["status"] != "pending":
        bot.reply_to(message, "Invalid or non-pending withdrawal ID.")
        return

    decline_withdrawal(wd_id, message.from_user.id, reason)

    # Refund user full original requested amount
    target_user_id = int(wd["telegram_id"])
    amt = float(wd["amount"])
    adjust_balance(target_user_id, amt)

    bot.reply_to(message, f"❌ Declined withdrawal #{wd_id} and refunded ₹{amt:.2f}.")

    try:
        bot.send_message(target_user_id, f"❌ Your withdrawal #{wd_id} was declined.\nReason: {reason}\n\n₹{amt:.2f} has been refunded to your account balance.")
    except Exception:
        pass


@bot.message_handler(commands=["minwd"])
def cmd_minwd(message):
    if (message.from_user.username or "").lower() != SUPER_ADMIN_USERNAME.lower():
        return
    parts = message.text.split()
    if len(parts) != 2:
        bot.reply_to(message, "Usage: /minwd <amount>")
        return
    try:
        val = float(parts[1])
        set_min_withdraw(val)
        bot.reply_to(message, f"✅ Minimum withdrawal updated to ₹{val:.2f}")
    except ValueError:
        bot.reply_to(message, "Invalid number format.")


@bot.message_handler(commands=["Pendingwd", "pendingwd"])
def cmd_pending_wd(message):
    if (message.from_user.username or "").lower() != SUPER_ADMIN_USERNAME.lower():
        return
    pending = get_pending_withdrawals()
    if not pending:
        bot.reply_to(message, "No pending withdrawal requests.")
        return
    lines = [f"⏳ <b>#{w['wd_id']}</b> - ₹{w['net_amount']} to <code>{w['upi_id']}</code> (User: {w['telegram_id']})" for w in pending]
    bot.reply_to(message, "<b>Pending Withdrawals:</b>\n\n" + "\n".join(lines), parse_mode="HTML")


@bot.message_handler(commands=["Info", "info"])
def cmd_wd_info(message):
    if (message.from_user.username or "").lower() != SUPER_ADMIN_USERNAME.lower():
        return
    parts = message.text.split()
    if len(parts) != 2:
        bot.reply_to(message, "Usage: /Info <withdrawal_id>")
        return
    wd_id = parts[1].lstrip("#")
    wd = get_withdrawal(wd_id)
    if not wd:
        bot.reply_to(message, "Withdrawal ID not found.")
        return
    info_msg = (
        f"<b>Withdrawal Info #{wd['wd_id']}</b>\n\n"
        f"👤 Telegram ID: <code>{wd['telegram_id']}</code>\n"
        f"👤 Username: @{wd.get('username') or 'N/A'}\n"
        f"💵 Requested Amount: ₹{wd['amount']}\n"
        f"💰 Fee (2.5%): ₹{wd['fee']}\n"
        f"💵 Net Amount: ₹{wd['net_amount']}\n"
        f"👨‍💻 UPI ID: <code>{wd['upi_id']}</code>\n"
        f"📌 Status: {wd['status'].upper()}\n"
        f"📝 Reason: {wd.get('decline_reason') or 'None'}"
    )
    bot.reply_to(message, info_msg, parse_mode="HTML")
