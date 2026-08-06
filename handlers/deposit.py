import re
import traceback
import sqlite3
from telebot.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from bot_instance import bot
from wallet import adjust_balance, add_wager_requirement, get_db_connection
from db import has_permission, grant_permission, revoke_permission, get_all_permitted_users, select

MIN_DEPOSIT_AMOUNT = 30.0

# --- USER STATE MANAGEMENT ---

def init_state_db():
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS user_states (
                telegram_id INTEGER PRIMARY KEY,
                state TEXT
            )
        """)
        conn.commit()
        conn.close()
    except Exception:
        print("\n--- RAW ERROR IN init_state_db ---")
        traceback.print_exc()
        print("-----------------------------------\n")

init_state_db()


def set_user_state(telegram_id: int, state: str):
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("INSERT OR REPLACE INTO user_states (telegram_id, state) VALUES (?, ?)", (telegram_id, state))
        conn.commit()
        conn.close()
    except Exception:
        print("\n--- RAW ERROR IN set_user_state ---")
        traceback.print_exc()
        print("-----------------------------------\n")


def get_user_state(telegram_id: int) -> str | None:
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT state FROM user_states WHERE telegram_id = ?", (telegram_id,))
        row = cursor.fetchone()
        conn.close()
        return row["state"] if row else None
    except Exception:
        print("\n--- RAW ERROR IN get_user_state ---")
        traceback.print_exc()
        print("-----------------------------------\n")
        return None


def clear_user_state(telegram_id: int):
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM user_states WHERE telegram_id = ?", (telegram_id,))
        conn.commit()
        conn.close()
    except Exception:
        print("\n--- RAW ERROR IN clear_user_state ---")
        traceback.print_exc()
        print("-------------------------------------\n")


# --- DEPOSIT COMMAND ---

@bot.message_handler(commands=["depo", "deposit"])
def start_deposit(message: Message):
    try:
        if message.chat.type != "private":
            bot_username = bot.get_me().username
            markup = InlineKeyboardMarkup()
            markup.add(InlineKeyboardButton("➡️ Open in DM", url=f"https://t.me/{bot_username}?start=deposit"))
            bot.reply_to(message, "📩 Click below to start deposit in private messages:", reply_markup=markup)
            return

        set_user_state(message.from_user.id, "WAITING_DEPOSIT_AMOUNT")
        
        bot.reply_to(
            message, 
            f"💳 <b>Send the amount you wish to deposit:</b>\n<i>min bet : 30rs</i>", 
            parse_mode="HTML"
        )
    except Exception:
        print("\n--- RAW ERROR IN start_deposit ---")
        traceback.print_exc()
        print("----------------------------------\n")


# --- CATCH TEXT INPUT FOR DEPOSIT IN DM ---

@bot.message_handler(func=lambda msg: msg.chat.type == "private" and get_user_state(msg.from_user.id) == "WAITING_DEPOSIT_AMOUNT")
def process_deposit_text(message: Message):
    try:
        user_id = message.from_user.id
        text = message.text.strip().lower()

        if text.startswith("/"):
            clear_user_state(user_id)
            return

        clean_text = re.sub(r"[^\d.]", "", text)

        amount = float(clean_text) if clean_text else 0.0
        
        if amount < MIN_DEPOSIT_AMOUNT:
            bot.reply_to(message, f"❌ <b>min bet : 30rs</b>. Please enter a valid amount.", parse_mode="HTML")
            return

        clear_user_state(user_id)
        
        bot.reply_to(
            message, 
            f"✅ <b>Deposit Request Received!</b>\n\n💰 Amount: ₹{amount:.2f}\nPlease wait for admin approval.",
            parse_mode="HTML"
        )
        
        notify_deposit_managers(message.from_user, amount)

    except Exception:
        print("\n--- RAW ERROR IN process_deposit_text ---")
        traceback.print_exc()
        print("-----------------------------------------\n")


def notify_deposit_managers(user, amount: float):
    try:
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

    except Exception:
        print("\n--- RAW ERROR IN notify_deposit_managers ---")
        traceback.print_exc()
        print("--------------------------------------------\n")


# --- APPROVAL / DECLINE HANDLERS WITH SELF-APPROVAL PREVENTION ---

@bot.callback_query_handler(func=lambda call: call.data.startswith(("dep_app_", "dep_dec_")))
def handle_deposit_action(call):
    try:
        user_id = call.from_user.id
        
        if not has_permission(user_id, "deposit"):
            bot.answer_callback_query(call.id, "❌ You do not have permission to manage deposits.", show_alert=True)
            return

        parts = call.data.split("_")
        action = parts[1]
        target_user_id = int(parts[2])
        amount = float(parts[3])

        # Self-approval restriction
        if target_user_id == user_id:
            bot.answer_callback_query(call.id, "❌ You cannot approve or decline your own deposit request!", show_alert=True)
            return

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
    except Exception:
        print("\n--- RAW ERROR IN handle_deposit_action ---")
        traceback.print_exc()
        print("------------------------------------------\n")


# --- PERMISSION COMMAND ---

@bot.message_handler(commands=["depositperm"])
def toggle_deposit_perm(message: Message):
    try:
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
    except Exception:
        print("\n--- RAW ERROR IN toggle_deposit_perm ---")
        traceback.print_exc()
        print("----------------------------------------\n")


def get_deposit_by_utr(utr: str):
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM deposits WHERE utr = ?", (utr,))
        row = cursor.fetchone()
        conn.close()
        return dict(row) if row else None
    except Exception:
        return None
