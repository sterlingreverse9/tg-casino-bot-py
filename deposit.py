import re
import sqlite3
from telebot.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from bot_instance import bot
from wallet import adjust_balance, add_wager_requirement, get_db_connection
from db import has_permission, grant_permission, revoke_permission, get_all_permitted_users, select

MIN_DEPOSIT_AMOUNT = 30.0

# --- USER STATE MANAGEMENT ---

def set_user_state(telegram_id: int, state: str):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS user_states (
            telegram_id INTEGER PRIMARY KEY,
            state TEXT
        )
    """)
    cursor.execute("INSERT OR REPLACE INTO user_states (telegram_id, state) VALUES (?, ?)", (telegram_id, state))
    conn.commit()
    conn.close()


def get_user_state(telegram_id: int) -> str | None:
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT state FROM user_states WHERE telegram_id = ?", (telegram_id,))
        row = cursor.fetchone()
        conn.close()
        return row["state"] if row else None
    except Exception:
        conn.close()
        return None


def clear_user_state(telegram_id: int):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("DELETE FROM user_states WHERE telegram_id = ?", (telegram_id,))
        conn.commit()
    except Exception:
        pass
    conn.close()


# --- DEPOSIT COMMAND ---

@bot.message_handler(commands=["depo", "deposit"])
def start_deposit(message: Message):
    if message.chat.type != "private":
        bot_username = bot.get_me().username
        markup = InlineKeyboardMarkup()
        markup.add(InlineKeyboardButton("➡️ Open in DM", url=f"https://t.me/{bot_username}?start=deposit"))
        bot.reply_to(message, "📩 Click below to start deposit in private messages:", reply_markup=markup)
        return

    set_user_state(message.from_user.id, "WAITING_DEPOSIT_AMOUNT")
    
    bot.reply_to(
        message, 
        f"💳 <b>Send the amount you wish to deposit:</b>\n<i>(Minimum deposit: ₹{int(MIN_DEPOSIT_AMOUNT)})</i>", 
        parse_mode="HTML"
    )


# --- CATCH ALL TEXT MESSAGES IN DM FOR DEPOSIT ---

@bot.message_handler(func=lambda msg: msg.chat.type == "private" and get_user_state(msg.from_user.id) == "WAITING_DEPOSIT_AMOUNT")
def process_deposit_text(message: Message):
    user_id = message.from_user.id
    text = message.text.strip().lower()

    if text.startswith("/"):
        clear_user_state(user_id)
        return

    clean_text = re.sub(r"[^\d.]", "", text)

    try:
        amount = float(clean_text) if clean_text else 0.0
        
        if amount < MIN_DEPOSIT_AMOUNT:
            bot.reply_to(message, f"❌ <b>Minimum deposit is ₹{int(MIN_DEPOSIT_AMOUNT)}.</b> Please enter a valid amount.", parse_mode="HTML")
            return

        clear_user_state(user_id)
        
        bot.reply_to(
            message, 
            f"✅ <b>Deposit Request Received!</b>\n\n💰 Amount: ₹{amount:.2f}\nPlease wait for admin approval.",
            parse_mode="HTML"
        )
        
        notify_deposit_managers(message.from_user, amount)

    except ValueError:
        bot.reply_to(message, "❌ Invalid input. Please enter a valid numeric amount (e.g., 50).")


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


# --- APPROVAL / DECLINE HANDLERS ---

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


# --- HELPER COMPATIBILITY STUBS ---

def get_deposit_by_utr(utr: str):
    """Fallback stub to satisfy imports in helpers.py"""
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT * FROM deposits WHERE utr = ?", (utr,))
        row = cursor.fetchone()
        conn.close()
        return dict(row) if row else None
    except Exception:
        conn.close()
        return None
