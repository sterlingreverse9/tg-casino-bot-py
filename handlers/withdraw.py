import datetime
import html
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
from bot_instance import bot
from db import select, has_permission
from wallet import get_balance, adjust_balance, get_wager_remaining
from state import withdraw_states, admin_wd_states
from settings import get_min_withdraw, set_min_withdraw
from helpers import ensure_user, get_all_admin_ids
from withdraw import (
    create_withdrawal,
    get_withdrawal,
    approve_withdrawal,
    decline_withdrawal,
    get_pending_withdrawals,
)

SUPER_ADMIN_USERNAME = "mrpuppyx"
CHANNEL_USERNAME = "@thecassinoupdates"
FEE_PERCENT = 0.025  # 2.5%


def notify_admin_withdrawal(wd_id, amt, fee, net, upi, user_ref, telegram_id):
    """Safely notifies super admin @mrpuppyx and staff members about a new withdrawal."""
    admin_ids = set(get_all_admin_ids())
    
    # Try finding super admin by username case-insensitively if not already in admin_ids
    users = select("users") or []
    for u in users:
        if (u.get("username") or "").lower() == SUPER_ADMIN_USERNAME.lower():
            admin_ids.add(int(u["telegram_id"]))

    admin_msg = (
        f"🚨 <b>NEW WITHDRAWAL REQUEST #{wd_id}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"👤 <b>User:</b> {user_ref} (<code>{telegram_id}</code>)\n"
        f"💵 <b>Requested:</b> ₹{amt:.2f}\n"
        f"💰 <b>Fee (2.5%):</b> ₹{fee:.2f}\n"
        f"💎 <b>Payout Amount:</b> ₹{net:.2f}\n"
        f"💳 <b>UPI ID:</b> <code>{upi}</code>\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"⚡ <b>Quick Actions:</b>\n"
        f"✅ <code>/Approvewd {wd_id}</code>\n"
        f"❌ <code>/Declinewd {wd_id} &lt;reason&gt;</code>"
    )

    for admin_id in admin_ids:
        try:
            bot.send_message(admin_id, admin_msg, parse_mode="HTML")
        except Exception as e:
            print(f"[Withdraw Admin Notify Error] Could not ping {admin_id}: {e}")


@bot.message_handler(commands=["wagerstats"])
def cmd_wagerstats(message):
    ensure_user(message)
    rem = get_wager_remaining(message.from_user.id)
    if rem <= 0:
        bot.reply_to(
            message,
            "✅ <b>Wager Unlocked!</b>\n\nYou have fulfilled all wager requirements and can request withdrawals freely.",
            parse_mode="HTML",
        )
    else:
        bot.reply_to(
            message,
            f"🎯 <b>Wager Progress</b>\n\n"
            f"📊 <b>Remaining Wager:</b> ₹{rem:.2f}\n"
            f"💡 Place bets in any casino game to reduce this requirement.",
            parse_mode="HTML",
        )


@bot.message_handler(commands=["withdraw", "wd"])
def cmd_withdraw(message):
    ensure_user(message)
    if message.chat.type != "private":
        markup = InlineKeyboardMarkup()
        markup.add(
            InlineKeyboardButton(
                "💬 Withdraw in DM",
                url=f"https://t.me/{bot.get_me().username}?start=withdraw",
            )
        )
        bot.reply_to(
            message,
            "🔒 <b>Security Notice</b>\n\nWithdrawals are strictly processed in Direct Messages for your account safety.",
            reply_markup=markup,
            parse_mode="HTML",
        )
        return

    wager_left = get_wager_remaining(message.from_user.id)
    if wager_left > 0:
        bot.reply_to(
            message,
            f"⚠️ <b>Wager Requirement Pending</b>\n\n"
            f"You must wager <b>₹{wager_left:.2f}</b> more before initiating a withdrawal.\n\n"
            f"🔍 Check your progress anytime using /wagerstats.",
            parse_mode="HTML",
        )
        return

    bal = get_balance(message.from_user.id)
    min_wd = get_min_withdraw()

    withdraw_states[message.from_user.id] = {"step": "amount"}

    msg = (
        f"💸 <b>INITIATE WITHDRAWAL</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"💰 <b>Available Balance:</b> ₹{bal:.2f}\n"
        f"🔻 <b>Minimum Cashout:</b> ₹{min_wd:.0f}\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"👇 <b>Type the amount you want to cash out:</b>"
    )
    bot.send_message(message.chat.id, msg, parse_mode="HTML")


@bot.message_handler(
    func=lambda m: m.from_user.id in withdraw_states
    and withdraw_states[m.from_user.id]["step"] == "amount",
    content_types=["text"],
)
def handle_withdraw_amount(message):
    state = withdraw_states[message.from_user.id]
    try:
        amt = float(message.text.strip())
    except ValueError:
        bot.reply_to(
            message,
            "❌ <b>Invalid Input!</b> Please type a valid numeric amount (e.g., 250).",
            parse_mode="HTML",
        )
        return

    bal = get_balance(message.from_user.id)
    min_wd = get_min_withdraw()

    if amt < min_wd:
        bot.reply_to(
            message,
            f"❌ <b>Below Minimum!</b> The minimum withdrawal amount is ₹{min_wd:.2f}.",
            parse_mode="HTML",
        )
        return
    if amt > bal:
        bot.reply_to(
            message,
            f"❌ <b>Insufficient Balance!</b> You only have ₹{bal:.2f} available.",
            parse_mode="HTML",
        )
        return

    state["amount"] = amt
    state["step"] = "upi"

    msg = (
        f"💳 <b>ENTER PAYOUT ADDRESS</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"💵 <b>Selected Amount:</b> ₹{amt:.2f}\n\n"
        f"👇 <b>Please type your UPI ID below:</b>\n"
        f"<i>(Example: name@upi, name@ybl, 9876543210@paytm)</i>"
    )
    bot.send_message(message.chat.id, msg, parse_mode="HTML")


@bot.message_handler(
    func=lambda m: m.from_user.id in withdraw_states
    and withdraw_states[m.from_user.id]["step"] == "upi",
    content_types=["text"],
)
def handle_withdraw_upi(message):
    upi = message.text.strip()
    if "@" not in upi or len(upi) < 5:
        bot.reply_to(
            message,
            "❌ <b>Invalid UPI ID!</b> Please enter a valid UPI address containing '@' (e.g. <code>username@upi</code>):",
            parse_mode="HTML",
        )
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
    markup.add(
        InlineKeyboardButton(
            "Confirm Withdrawal ✅", callback_data="confirm_withdraw"
        )
    )

    msg = (
        f"📄 <b>CONFIRM WITHDRAWAL DETAILS</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"💵 <b>Requested Amount:</b> ₹{amt:.2f}\n"
        f"💰 <b>Service Fee (2.5%):</b> ₹{fee:.2f}\n"
        f"💎 <b>You Receive:</b> ₹{net:.2f}\n"
        f"👨‍💻 <b>UPI Target:</b> <code>{upi}</code>\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"⚠️ <b>Double check your UPI ID before confirming!</b>"
    )
    bot.send_message(
        message.chat.id, msg, parse_mode="HTML", reply_markup=markup
    )


@bot.callback_query_handler(func=lambda call: call.data == "confirm_withdraw")
def handle_withdraw_confirm(call):
    bot.answer_callback_query(call.id)
    user_id = call.from_user.id
    state = withdraw_states.get(user_id)

    if not state or state.get("step") != "confirm":
        bot.send_message(
            call.message.chat.id,
            "⚠️ Session expired. Please run /withdraw again.",
        )
        return

    bal = get_balance(user_id)
    amt = state["amount"]
    if amt > bal:
        bot.send_message(call.message.chat.id, "❌ Insufficient balance.")
        withdraw_states.pop(user_id, None)
        return

    # Deduct balance immediately
    rem_bal = adjust_balance(user_id, -amt)

    wd_rec = create_withdrawal(
        telegram_id=user_id,
        username=call.from_user.username,
        full_name=call.from_user.first_name,
        amount=amt,
        fee=state["fee"],
        net_amount=state["net"],
        upi_id=state["upi"],
    )
    wd_id = wd_rec["wd_id"]

    withdraw_states.pop(user_id, None)

    msg = (
        f"✅ <b>Withdrawal Request #{wd_id} Submitted!</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"💵 <b>Requested:</b> ₹{amt:.2f}\n"
        f"💰 <b>Fee (2.5%):</b> ₹{state['fee']:.2f}\n"
        f"💎 <b>Payout Amount:</b> ₹{state['net']:.2f}\n"
        f"👨‍💻 <b>UPI ID:</b> <code>{state['upi']}</code>\n"
        f"💳 <b>New Balance:</b> ₹{rem_bal:.2f}\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"⌛ <i>Our team will review and process your payout shortly.</i>"
    )
    bot.edit_message_text(
        msg, call.message.chat.id, call.message.message_id, parse_mode="HTML"
    )

    # Trigger Admin Notification
    user_ref = (
        f"@{call.from_user.username}"
        if call.from_user.username
        else html.escape(call.from_user.first_name or "User")
    )
    notify_admin_withdrawal(
        wd_id=wd_id,
        amt=amt,
        fee=state["fee"],
        net=state["net"],
        upi=state["upi"],
        user_ref=user_ref,
        telegram_id=user_id,
    )


# --- Super Admin Commands ---


@bot.message_handler(commands=["Approvewd", "approvewd"])
def cmd_approve_wd(message):
    if (message.from_user.username or "").lower() != SUPER_ADMIN_USERNAME.lower():
        return

    parts = message.text.split()
    if len(parts) != 2:
        bot.reply_to(message, "Usage: <code>/Approvewd &lt;id&gt;</code>", parse_mode="HTML")
        return

    wd_id = parts[1].lstrip("#")
    wd = get_withdrawal(wd_id)
    if not wd or wd["status"] != "pending":
        bot.reply_to(message, "❌ Invalid or non-pending withdrawal ID.")
        return

    admin_wd_states[message.from_user.id] = {"wd_id": wd_id}
    bot.reply_to(
        message,
        f"📸 <b>Send Payment Proof</b>\n\nPlease upload/send the payment screenshot for Withdrawal <b>#{wd_id}</b>:",
        parse_mode="HTML",
    )


@bot.message_handler(
    func=lambda m: m.from_user.id in admin_wd_states,
    content_types=["photo", "document"],
)
def handle_wd_screenshot(message):
    state = admin_wd_states.pop(message.from_user.id)
    wd_id = state["wd_id"]
    wd = get_withdrawal(wd_id)

    if not wd or wd["status"] != "pending":
        bot.reply_to(message, "❌ Withdrawal request no longer active.")
        return

    photo_file_id = (
        message.photo[-1].file_id
        if message.photo
        else message.document.file_id
    )

    approve_withdrawal(wd_id, message.from_user.id)
    bot.reply_to(message, f"✅ <b>Withdrawal #{wd_id} marked as APPROVED!</b>", parse_mode="HTML")

    target_user_id = int(wd["telegram_id"])
    net_amt = float(wd["net_amount"])
    upi = wd["upi_id"]

    # Payout Success Notification to User
    caption = (
        f"🏆 <b>PAYMENT TRANSFERRED!</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"💵 <b>Amount Sent:</b> ₹{net_amt:.2f}\n"
        f"👨‍💻 <b>Destination:</b> <code>{upi}</code>\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"✅ <i>Please check your UPI app statement!</i>"
    )
    try:
        bot.send_photo(
            target_user_id, photo_file_id, caption=caption, parse_mode="HTML"
        )
    except Exception:
        bot.send_message(target_user_id, caption, parse_mode="HTML")

    # Broadcast to Channel
    try:
        u_name = wd.get("full_name") or "Player"
        u_tag = f"@{wd['username']}" if wd.get("username") else u_name
        now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        chan_msg = (
            f"⚡ <b>NEW WITHDRAWAL SENT ✅</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"👤 <b>Winner:</b> {u_name} ({u_tag})\n"
            f"💵 <b>Amount Paid:</b> ₹{net_amt:.2f}\n"
            f"🕒 <b>Time:</b> {now_str}\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"🚀 <b>Play & Win:</b> Use /withdraw to cash out anytime!"
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
        bot.reply_to(message, "Usage: <code>/Declinewd &lt;id&gt; &lt;reason&gt;</code>", parse_mode="HTML")
        return

    wd_id = parts[1].lstrip("#")
    reason = parts[2]
    wd = get_withdrawal(wd_id)

    if not wd or wd["status"] != "pending":
        bot.reply_to(message, "❌ Invalid or non-pending withdrawal ID.")
        return

    decline_withdrawal(wd_id, message.from_user.id, reason)

    # Refund user full requested amount
    target_user_id = int(wd["telegram_id"])
    amt = float(wd["amount"])
    adjust_balance(target_user_id, amt)

    bot.reply_to(
        message,
        f"❌ <b>Declined Withdrawal #{wd_id}</b>\nRefunded ₹{amt:.2f} to user.",
        parse_mode="HTML",
    )

    try:
        bot.send_message(
            target_user_id,
            f"❌ <b>Withdrawal Declined</b>\n\n"
            f"Your withdrawal <b>#{wd_id}</b> was declined.\n"
            f"📝 <b>Reason:</b> {reason}\n\n"
            f"💰 <i>₹{amt:.2f} has been refunded back to your casino balance.</i>",
            parse_mode="HTML",
        )
    except Exception:
        pass


@bot.message_handler(commands=["minwd"])
def cmd_minwd(message):
    if (message.from_user.username or "").lower() != SUPER_ADMIN_USERNAME.lower():
        return
    parts = message.text.split()
    if len(parts) != 2:
        bot.reply_to(message, "Usage: <code>/minwd &lt;amount&gt;</code>", parse_mode="HTML")
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
    lines = [
        f"⏳ <b>#{w['wd_id']}</b> • ₹{w['net_amount']} → <code>{w['upi_id']}</code> (User: <code>{w['telegram_id']}</code>)"
        for w in pending
    ]
    bot.reply_to(
        message,
        "📋 <b>PENDING WITHDRAWALS:</b>\n\n" + "\n".join(lines),
        parse_mode="HTML",
    )


@bot.message_handler(commands=["Info", "info"])
def cmd_wd_info(message):
    if (message.from_user.username or "").lower() != SUPER_ADMIN_USERNAME.lower():
        return
    parts = message.text.split()
    if len(parts) != 2:
        bot.reply_to(message, "Usage: <code>/Info &lt;id&gt;</code>", parse_mode="HTML")
        return
    wd_id = parts[1].lstrip("#")
    wd = get_withdrawal(wd_id)
    if not wd:
        bot.reply_to(message, "❌ Withdrawal ID not found.")
        return
    info_msg = (
        f"ℹ️ <b>WITHDRAWAL INFO #{wd['wd_id']}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"👤 <b>Telegram ID:</b> <code>{wd['telegram_id']}</code>\n"
        f"👤 <b>Username:</b> @{wd.get('username') or 'N/A'}\n"
        f"💵 <b>Gross Amount:</b> ₹{wd['amount']}\n"
        f"💰 <b>Fee:</b> ₹{wd['fee']}\n"
        f"💎 <b>Net Payout:</b> ₹{wd['net_amount']}\n"
        f"👨‍💻 <b>UPI ID:</b> <code>{wd['upi_id']}</code>\n"
        f"📌 <b>Status:</b> {wd['status'].upper()}\n"
        f"📝 <b>Reason:</b> {wd.get('decline_reason') or 'None'}"
    )
    bot.reply_to(message, info_msg, parse_mode="HTML")
