import sqlite3
from telebot.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from bot_instance import bot
from wallet import get_db_connection

def is_deposit_admin(telegram_id: int) -> bool:
    """Checks if user is main admin or has deposit permissions."""
    from helpers import is_admin
    if is_admin(telegram_id):
        return True
    
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT can_manage_deposits FROM users WHERE telegram_id = ?", (telegram_id,))
    row = cursor.fetchone()
    conn.close()
    return bool(row["can_manage_deposits"]) if row else False


# --- DEPOSIT FLOW ---

@bot.message_handler(commands=["depo", "deposit"])
def start_deposit(message: Message):
    if message.chat.type != "private":
        bot_username = bot.get_me().username
        markup = InlineKeyboardMarkup()
        markup.add(InlineKeyboardButton("➡️ Open in DM", url=f"https://t.me/{bot_username}?start=deposit"))
        bot.reply_to(message, "📩 Click below to start deposit in private messages:", reply_markup=markup)
        return

    msg = bot.reply_to(message, "💳 <b>Send the amount you wish to deposit:</b>", parse_mode="HTML")
    bot.register_next_step_handler(msg, process_deposit_amount)


def process_deposit_amount(message: Message):
    try:
        amount = float(message.text.strip())
        if amount <= 0:
            bot.reply_to(message, "❌ Amount must be greater than 0. Try /deposit again.")
            return
        
        bot.reply_to(
            message, 
            f"✅ <b>Deposit Request Received!</b>\n\nAmount: ₹{amount:.2f}\nPlease wait for admin approval.",
            parse_mode="HTML"
        )
        
        # Notify deposit managers (Admins & permitted users)
        notify_deposit_managers(message.from_user, amount)

    except (ValueError, TypeError):
        bot.reply_to(message, "❌ Invalid amount. Please run /deposit and enter a valid number.")


def notify_deposit_managers(user, amount: float):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT telegram_id FROM users WHERE can_manage_deposits = 1")
    managers = [row["telegram_id"] for row in cursor.fetchall()]
    conn.close()

    # Always include main admins
    from helpers import ADMIN_IDS
    all_managers = list(set(managers + list(ADMIN_IDS)))

    markup = InlineKeyboardMarkup()
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


# --- DEPOSIT PERMISSION COMMAND ---

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
    conn = get_db_connection()
    cursor = conn.cursor()

    if target.isdigit():
        cursor.execute("SELECT telegram_id, username, can_manage_deposits FROM users WHERE telegram_id = ?", (int(target),))
    else:
        cursor.execute("SELECT telegram_id, username, can_manage_deposits FROM users WHERE LOWER(username) = LOWER(?)", (target,))

    user = cursor.fetchone()

    if not user:
        conn.close()
        bot.reply_to(message, "❌ User not found in database. Make sure they have started the bot.")
        return

    new_perm = 0 if user["can_manage_deposits"] else 1
    cursor.execute("UPDATE users SET can_manage_deposits = ? WHERE telegram_id = ?", (new_perm, user["telegram_id"]))
    conn.commit()
    conn.close()

    status = "granted ✅" if new_perm else "revoked ❌"
    bot.reply_to(message, f"👤 Deposit permissions for @{user['username'] or user['telegram_id']} have been <b>{status}</b>.", parse_mode="HTML")
