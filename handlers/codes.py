import html
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
from bot_instance import bot
from wallet import get_balance, adjust_balance
from helpers import ensure_user, is_user_frozen, format_display_name
from codes import (
    CODE_CREATION_STATES,
    get_code_data,
    create_promo_code,
    record_claim,
)

SUPER_ADMIN_USERNAME = "mrpuppyx"
CODE_FEE_PERCENT = 0.025  # 2.5%


@bot.message_handler(commands=["makecode"])
def cmd_makecode(message):
    ensure_user(message)
    telegram_id = message.from_user.id

    if is_user_frozen(telegram_id):
        bot.reply_to(message, "❄️ Your account is currently frozen. You cannot create promo codes.")
        return

    # Check if command is used in a group / supergroup
    if message.chat.type != "private":
        markup = InlineKeyboardMarkup()
        markup.add(
            InlineKeyboardButton(
                "🎁 Create Code in DM",
                url=f"https://t.me/{bot.get_me().username}?start=makecode",
            )
        )
        bot.reply_to(
            message,
            "<b>🎁 Code Creation</b>\n\nPromo codes can only be configured in Direct Messages for privacy.",
            reply_markup=markup,
            parse_mode="HTML",
        )
        return

    CODE_CREATION_STATES[telegram_id] = {"step": "name", "data": {}}

    msg = (
        "<b>🎁 CREATE A PROMO CODE</b>\n"
        "────────────────────────\n"
        "Please enter your desired <b>Code Name</b>.\n\n"
        "<i>Rules:</i>\n"
        "• At least 4 characters long\n"
        "• No spaces or special characters\n"
        "• Example: <code>Happy39</code>, <code>Everest32</code>"
    )
    bot.send_message(message.chat.id, msg, parse_mode="HTML")


@bot.message_handler(
    func=lambda m: m.from_user.id in CODE_CREATION_STATES
    and CODE_CREATION_STATES[m.from_user.id]["step"] == "name",
    content_types=["text"],
)
def handle_code_name_input(message):
    telegram_id = message.from_user.id
    if is_user_frozen(telegram_id):
        CODE_CREATION_STATES.pop(telegram_id, None)
        bot.reply_to(message, "❄️ Your account is currently frozen. Code creation cancelled.")
        return

    code_name = message.text.strip()

    if len(code_name) < 4:
        bot.reply_to(message, "⚠️ Code name must be at least 4 characters long. Try again:")
        return

    if not code_name.isalnum():
        bot.reply_to(message, "⚠️ Code name cannot contain spaces or special characters. Try again:")
        return

    if get_code_data(code_name) is not None:
        bot.reply_to(message, "⚠️ This code name is already taken. Please pick another name:")
        return

    state = CODE_CREATION_STATES[telegram_id]
    state["data"]["code_name"] = code_name
    state["step"] = "users"

    bot.send_message(
        message.chat.id,
        f"✅ Code Name set to: <code>{html.escape(code_name)}</code>\n\n"
        f"👇 Enter <b>max users</b> who can claim this code (e.g., 4, 10):",
        parse_mode="HTML",
    )


@bot.message_handler(
    func=lambda m: m.from_user.id in CODE_CREATION_STATES
    and CODE_CREATION_STATES[m.from_user.id]["step"] == "users",
    content_types=["text"],
)
def handle_code_users_input(message):
    telegram_id = message.from_user.id
    if is_user_frozen(telegram_id):
        CODE_CREATION_STATES.pop(telegram_id, None)
        bot.reply_to(message, "❄️ Your account is currently frozen. Code creation cancelled.")
        return

    try:
        max_users = int(message.text.strip())
        if max_users < 1:
            raise ValueError
    except ValueError:
        bot.reply_to(message, "⚠️ Please enter a valid whole number of max users (at least 1):")
        return

    state = CODE_CREATION_STATES[telegram_id]
    state["data"]["max_users"] = max_users
    state["step"] = "amount"

    bot.send_message(
        message.chat.id,
        f"👥 Max Users: <b>{max_users}</b>\n\n"
        f"👇 Enter <b>amount per user</b> (Min: ₹10):",
        parse_mode="HTML",
    )


@bot.message_handler(
    func=lambda m: m.from_user.id in CODE_CREATION_STATES
    and CODE_CREATION_STATES[m.from_user.id]["step"] == "amount",
    content_types=["text"],
)
def handle_code_amount_input(message):
    telegram_id = message.from_user.id
    if is_user_frozen(telegram_id):
        CODE_CREATION_STATES.pop(telegram_id, None)
        bot.reply_to(message, "❄️ Your account is currently frozen. Code creation cancelled.")
        return

    try:
        amt_per_user = float(message.text.strip())
        if amt_per_user < 10:
            bot.reply_to(message, "⚠️ Minimum amount per user is ₹10. Try again:")
            return
    except ValueError:
        bot.reply_to(message, "⚠️ Please enter a valid numeric amount:")
        return

    state = CODE_CREATION_STATES[telegram_id]
    data = state["data"]
    data["amount_per_user"] = amt_per_user

    max_users = data["max_users"]
    raw_total = max_users * amt_per_user
    fee = round(raw_total * CODE_FEE_PERCENT, 2)
    total_cost = round(raw_total + fee, 2)

    data["fee"] = fee
    data["total_cost"] = total_cost
    state["step"] = "confirm"

    user_bal = get_balance(telegram_id)

    markup = InlineKeyboardMarkup()
    markup.add(
        InlineKeyboardButton("I Confirm to Create ✅", callback_data="confirm_makecode"),
        InlineKeyboardButton("❌ Cancel", callback_data="cancel_makecode"),
    )

    overview_msg = (
        "📋 <b>PROMO CODE OVERVIEW</b>\n"
        "────────────────────────\n"
        f"🏷️ <b>Code:</b> <code>{html.escape(data['code_name'])}</code>\n"
        f"👥 <b>Max Users:</b> {max_users}\n"
        f"💵 <b>Amount Per User:</b> ₹{amt_per_user:.2f}\n"
        f"💰 <b>Subtotal:</b> ₹{raw_total:.2f}\n"
        f"📊 <b>Creation Fee (2.5%):</b> ₹{fee:.2f}\n"
        f"💳 <b>Total Deducted:</b> ₹{total_cost:.2f}\n"
        "────────────────────────\n"
        f"💼 <b>Your Balance:</b> ₹{user_bal:.2f}\n\n"
        "<i>Click below to finalize and activate this code.</i>"
    )
    bot.send_message(message.chat.id, overview_msg, parse_mode="HTML", reply_markup=markup)


@bot.callback_query_handler(func=lambda call: call.data in ("confirm_makecode", "cancel_makecode"))
def handle_makecode_confirmation(call):
    telegram_id = call.from_user.id
    state = CODE_CREATION_STATES.get(telegram_id)

    if not state or state.get("step") != "confirm":
        bot.answer_callback_query(call.id, "Session expired.", show_alert=True)
        return

    if call.data == "cancel_makecode":
        CODE_CREATION_STATES.pop(telegram_id, None)
        bot.answer_callback_query(call.id, "Cancelled.")
        bot.edit_message_text("❌ Code creation cancelled.", call.message.chat.id, call.message.message_id)
        return

    if is_user_frozen(telegram_id):
        CODE_CREATION_STATES.pop(telegram_id, None)
        bot.answer_callback_query(call.id, "❄️ Your account is currently frozen.", show_alert=True)
        return

    data = state["data"]
    total_cost = data["total_cost"]
    user_bal = get_balance(telegram_id)

    if user_bal < total_cost:
        bot.answer_callback_query(call.id, "Insufficient balance!", show_alert=True)
        bot.send_message(
            call.message.chat.id,
            f"❌ <b>Insufficient Balance!</b> You need ₹{total_cost:.2f} but only have ₹{user_bal:.2f}.",
            parse_mode="HTML",
        )
        CODE_CREATION_STATES.pop(telegram_id, None)
        return

    bot.answer_callback_query(call.id)

    # Deduct balance & save code
    adjust_balance(telegram_id, -total_cost)
    code_rec = create_promo_code(
        creator_id=telegram_id,
        creator_username=call.from_user.username or "",
        code_name=data["code_name"],
        max_users=data["max_users"],
        amount_per_user=data["amount_per_user"],
        total_cost=total_cost,
    )

    CODE_CREATION_STATES.pop(telegram_id, None)

    # Confirmation msg to user
    success_msg = (
        "CODE MADE 🎉\n"
        f"<b>CODE :</b> <code>{html.escape(data['code_name'])}</code>\n"
        f"<b>AMOUNT PER USER :</b> ₹{data['amount_per_user']:.2f}\n"
        f"<b>MAX CLAIMABLE USERS :</b> {data['max_users']}\n\n"
        f"use <code>/claim {data['code_name']}</code> to claim"
    )
    bot.edit_message_text(success_msg, call.message.chat.id, call.message.message_id, parse_mode="HTML")

    # Notify Super Admin (@mrpuppyx)
    try:
        user_ref = f"@{call.from_user.username}" if call.from_user.username else html.escape(call.from_user.first_name)
        admin_alert = (
            f"🚨 <b>NEW PROMO CODE CREATED</b>\n"
            f"👤 <b>Creator:</b> {user_ref} (<code>{telegram_id}</code>)\n"
            f"🏷️ <b>Code:</b> <code>{data['code_name']}</code>\n"
            f"💵 <b>Amount/User:</b> ₹{data['amount_per_user']:.2f}\n"
            f"👥 <b>Max Users:</b> {data['max_users']}\n"
            f"💰 <b>Total Deducted:</b> ₹{total_cost:.2f}"
        )
        # Import DB select locally to notify admin
        from db import select
        users = select("users") or []
        for u in users:
            if (u.get("username") or "").lower() == SUPER_ADMIN_USERNAME.lower():
                bot.send_message(int(u["telegram_id"]), admin_alert, parse_mode="HTML")
                break
    except Exception as e:
        print(f"[Code Admin Alert Error]: {e}")


@bot.message_handler(commands=["claim"])
def cmd_claim_code(message):
    ensure_user(message)
    telegram_id = message.from_user.id

    if is_user_frozen(telegram_id):
        bot.reply_to(message, "❄️ Your account is currently frozen. You cannot claim promo codes.")
        return

    parts = message.text.split()
    if len(parts) < 2:
        bot.reply_to(message, "Usage: <code>/claim &lt;code&gt;</code>", parse_mode="HTML")
        return

    input_code = parts[1].strip()
    code_data = get_code_data(input_code)

    if not code_data:
        bot.reply_to(message, "❌ Invalid promo code!")
        return

    claimed_list = code_data.get("claimed_by", [])
    max_users = int(code_data["max_users"])

    # 1. Check if limit hit
    if len(claimed_list) >= max_users:
        bot.reply_to(message, "Code is claimed by max users 🎉")
        return

    # 2. Check if already claimed by user
    if telegram_id in claimed_list:
        bot.reply_to(message, "⚠️ You have already claimed this code!")
        return

    # Grant balance & register claim
    amt = float(code_data["amount_per_user"])
    adjust_balance(telegram_id, amt)
    record_claim(code_data["code_id"], telegram_id)

    claimer_name = format_display_name(message.from_user.first_name, message.from_user.username)
    bot.reply_to(
        message,
        f"🎉 <b>Code Claimed Successfully!</b>\n\n₹{amt:.2f} has been added to your balance.",
        parse_mode="HTML",
    )

    # Notify Code Maker
    try:
        creator_id = int(code_data["creator_id"])
        notify_msg = (
            f"🎁 <b>Code Claim Notification!</b>\n\n"
            f"User <b>{html.escape(claimer_name)}</b> just claimed your code "
            f"<code>{html.escape(code_data['code_name'])}</code> (₹{amt:.2f})!"
        )
        bot.send_message(creator_id, notify_msg, parse_mode="HTML")
    except Exception as e:
        print(f"[Code Owner Notify Error]: {e}")
