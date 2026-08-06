import re
from telebot.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from bot_instance import bot
from wallet import adjust_balance, add_wager_requirement
from db import has_permission, grant_permission, revoke_permission, get_all_permitted_users, select

MIN_DEPOSIT_AMOUNT = 30.0

# --- DEPOSIT FLOW ---

@bot.message_handler(commands=["depo", "deposit"])
def start_deposit(message: Message):
    if message.chat.type != "private":
        bot_username = bot.get_me().username
        markup = InlineKeyboardMarkup()
        markup.add(InlineKeyboardButton("➡️ Open in DM", url=f"https://t.me/{bot_username}?start=deposit"))
        bot.reply_to(message, "📩 Click below to start deposit in private messages:", reply_markup=markup)
        return

    sent_msg = bot.reply_to(
        message, 
        f"💳 <b>Send the amount you wish to deposit:</b>\n<i>(Minimum deposit: ₹{int(MIN_DEPOSIT_AMOUNT)})</i>", 
        parse_mode="HTML"
    )
    bot.register_next_step_handler(sent_msg, process_deposit_amount)


def process_deposit_amount(message: Message):
    text = message.text.strip().lower()
    
    # Extract numerical digits (handles "50", "₹50", "50rs", "50.0")
    clean_text = re.sub(r"[^\d.]", "", text)

    try:
        amount = float(clean_text) if clean_text else 0.0
        
        if amount < MIN_DEPOSIT_AMOUNT:
            bot.reply_to(message, f"❌ <b>Minimum deposit is ₹{int(MIN_DEPOSIT_AMOUNT)}.</b> Please try /deposit again.", parse_mode="HTML")
            return

        bot.reply_to(
            message, 
            f"✅ <b>Deposit Request Received!</b>\n\n💰 Amount: ₹{amount:.2f}\nPlease wait for admin approval.",
            parse_mode="HTML"
        )
        
        notify_deposit_managers(message.from_user, amount)

    except ValueError:
        bot.reply_to(message, "❌ Invalid input. Please run /deposit and enter a valid numeric amount.")


def notify_deposit_managers(user, amount: float):
    permitted = get_all_permitted_users("deposit")

    from helpers import ADMIN_IDS
    all_managers = list(set(permitted + list(ADMIN_IDS)))

    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(
        InlineKeyboardButton("✅ Approve", callback_data=f"dep_app_{user.id}_{amount}"),
        InlineKeyboardButton("❌ Decline", callback_data=f"dep_dec_{user.id}_{amount}")
    )

    msg_text = (
        f"📥 <b>NEW DEPOSIT REQUEST</b>\n\n"
        f"👤 <b>User:</b> {user.first_name} (@{user.username or 'N/A'})\n"
        f"🆔 <b>ID:</b> <code>{user.id}</code>\n"
        f"💰 <b>Amount:</b> ₹{amount:.2f}"
    )

    for admin_id in all_managers:
        try:
            bot.send_message(admin_id, msg_text, parse_mode="HTML", reply_markup=markup)
        except Exception:
            pass


# --- APPROVAL & DECLINE CALLBACK HANDLERS ---

@bot.callback_query_handler(func=lambda call: call.data.startswith(("dep_app_", "dep_dec_")))
def handle_deposit_action(call):
    user_id = call.from_user.id
    
    if not has_permission(user_id, "deposit"):
        bot.answer_callback_query(call.id, "❌ You do not have permission to manage deposits.", show_alert=True)
        return

    parts = call.data.split("_")
    action = parts[1]
    target_user_id = int(parts[2])
    amount = float(parts[3])

    if action == "app":
        adjust_balance(target_user_id, amount)
        add_wager_requirement(target_user_id, amount)

        bot.edit_message_text(
            f"{call.message.text}\n\n✅ <b>APPROVED by @{call.from_user.username or user_id}</b>",
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            parse_mode="HTML"
        )
        try:
            bot.send_message(target_user_id, f"🎉 <b>Deposit Approved!</b>\n₹{amount:.2f} has been added to your balance.", parse_mode="HTML")
        except Exception:
            pass

    elif action == "dec":
        bot.edit_message_text(
            f"{call.message.text}\n\n❌ <b>DECLINED by @{call.from_user.username or user_id}</b>",
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            parse_mode="HTML"
        )
        try:
            bot.send_message(target_user_id, f"❌ Your deposit request for ₹{amount:.2f} was declined.", parse_mode="HTML")
        except Exception:
            pass


# --- PERMISSION COMMAND ---

@bot.message_handler(commands=["depositperm"])
def toggle_deposit_perm(message: Message):
    from helpers import is_admin
    if not is_admin(message.from_user.id):
        return

    args = message.text.split()
    if len(args) < 2:
        bot.reply_to(message, "⚠️ <b>Usage:</b> <code>/depositperm @username</code> or <code>/depositperm <telegram_id></code>", parse_mode="HTML")
        return

    target = args[1].replace("@", "")

    if target.isdigit():
        target_id = int(target)
    else:
        user_row = select("users", filters={"username": target}, single=True)
        target_id = user_row["telegram_id"] if user_row else None

    if not target_id:
        bot.reply_to(message, "❌ User not found in database.")
        return

    if has_permission(target_id, "deposit"):
        revoke_permission(target_id, "deposit")
        bot.reply_to(message, f"❌ Deposit permission <b>revoked</b> for <code>{target_id}</code>.", parse_mode="HTML")
    else:
        grant_permission(target_id, "deposit", granted_by=message.from_user.id)
        bot.reply_to(message, f"✅ Deposit permission <b>granted</b> for <code>{target_id}</code>.", parse_mode="HTML")
