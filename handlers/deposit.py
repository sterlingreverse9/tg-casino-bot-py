import re
import traceback
import sqlite3
from telebot.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from bot_instance import bot
from wallet import adjust_balance, add_wager_requirement, get_db_connection
from db import select

MIN_DEPOSIT_AMOUNT = 50.0
UPI_ID = "piyushraao@fam"  # Apni UPI ID yahan check/update kar lein

# --- DATABASE SETUP ---

def init_deposit_db():
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS deposit_states (
                telegram_id INTEGER PRIMARY KEY,
                state TEXT,
                amount REAL,
                utr TEXT
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS deposits (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                telegram_id INTEGER,
                amount REAL,
                utr TEXT UNIQUE,
                status TEXT DEFAULT 'PENDING',
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.commit()
        conn.close()
    except Exception:
        traceback.print_exc()

init_deposit_db()

# --- STATE MANAGERS & COMPATIBILITY ALIASES ---

def set_dep_state(telegram_id: int, state: str, amount: float = 0.0, utr: str = None):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO deposit_states (telegram_id, state, amount, utr)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(telegram_id) DO UPDATE SET
            state=excluded.state,
            amount=CASE WHEN excluded.amount != 0 THEN excluded.amount ELSE deposit_states.amount END,
            utr=CASE WHEN excluded.utr IS NOT NULL THEN excluded.utr ELSE deposit_states.utr END
    """, (telegram_id, state, amount, utr))
    conn.commit()
    conn.close()

def get_dep_state(telegram_id: int):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT state, amount, utr FROM deposit_states WHERE telegram_id = ?", (telegram_id,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None

def clear_dep_state(telegram_id: int):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM deposit_states WHERE telegram_id = ?", (telegram_id,))
    conn.commit()
    conn.close()

# Functions for basic.py compatibility
def get_user_state(telegram_id: int):
    st = get_dep_state(telegram_id)
    return st["state"] if st else None

def set_user_state(telegram_id: int, state: str):
    set_dep_state(telegram_id, state)

def clear_user_state(telegram_id: int):
    clear_dep_state(telegram_id)

def get_deposit_by_utr(utr: str):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM deposits WHERE utr = ?", (utr,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None

# --- DEPOSIT HANDLERS ---

@bot.message_handler(commands=["depo", "deposit"])
def start_deposit(message: Message):
    if message.chat.type != "private":
        bot_username = bot.get_me().username
        markup = InlineKeyboardMarkup()
        markup.add(InlineKeyboardButton("➡️ Open in DM", url=f"https://t.me/{bot_username}?start=deposit"))
        bot.reply_to(message, "📩 Click below to start deposit in private messages:", reply_markup=markup)
        return

    set_dep_state(message.from_user.id, "WAITING_AMOUNT")
    bot.reply_to(
        message,
        f"How many INR(₹) would you like to request? (min {int(MIN_DEPOSIT_AMOUNT)}, enter a number)"
    )

@bot.message_handler(func=lambda m: m.chat.type == "private" and get_dep_state(m.from_user.id) and get_dep_state(m.from_user.id)["state"] == "WAITING_AMOUNT")
def process_amount(message: Message):
    if message.text.startswith("/"):
        clear_dep_state(message.from_user.id)
        return

    clean_text = re.sub(r"[^\d.]", "", message.text)
    try:
        amount = float(clean_text)
    except ValueError:
        bot.reply_to(message, "❌ Invalid number. Enter a valid amount.")
        return

    if amount < MIN_DEPOSIT_AMOUNT:
        bot.reply_to(message, f"❌ Minimum deposit amount is ₹{MIN_DEPOSIT_AMOUNT:.0f}.")
        return

    set_dep_state(message.from_user.id, "WAITING_PAYMENT_CONFIRM", amount=amount)

    qr_url = f"https://api.qrserver.com/v1/create-qr-code/?size=300x300&data=upi://pay?pa={UPI_ID}%26pn=Casino%26am={amount}%26cu=INR"
    
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("✅ I Have Paid", callback_data="dep_paid"))

    caption = (
        f"💰 <b>Requested amount: ₹{amount:.2f}</b>\n\n"
        f"📍 <b>UPI ID:</b> <code>{UPI_ID}</code>\n\n"
        f"Tap the button below once you have paid."
    )

    bot.send_photo(message.chat.id, photo=qr_url, caption=caption, parse_mode="HTML", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data == "dep_paid")
def on_paid_click(call):
    st = get_dep_state(call.from_user.id)
    if not st or st["state"] != "WAITING_PAYMENT_CONFIRM":
        bot.answer_callback_query(call.id, "Session expired. Start again with /deposit.", show_alert=True)
        return

    set_dep_state(call.from_user.id, "WAITING_UTR")
    bot.answer_callback_query(call.id)
    bot.send_message(call.message.chat.id, "Now enter your 12-digit UTR code:")

@bot.message_handler(func=lambda m: m.chat.type == "private" and get_dep_state(m.from_user.id) and get_dep_state(m.from_user.id)["state"] == "WAITING_UTR")
def process_utr(message: Message):
    if message.text.startswith("/"):
        clear_dep_state(message.from_user.id)
        return

    utr = message.text.strip()
    if not utr.isdigit() or len(utr) != 12:
        bot.reply_to(message, "❌ Invalid UTR. UTR must be exactly 12 digits. Try again:")
        return

    set_dep_state(message.from_user.id, "WAITING_SCREENSHOT", utr=utr)
    bot.reply_to(message, "📸 Now send a screenshot to prove your payment.")

@bot.message_handler(content_types=['photo'], func=lambda m: m.chat.type == "private" and get_dep_state(m.from_user.id) and get_dep_state(m.from_user.id)["state"] == "WAITING_SCREENSHOT")
def process_screenshot(message: Message):
    st = get_dep_state(message.from_user.id)
    user = message.from_user
    amount = st["amount"]
    utr = st["utr"]

    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "INSERT INTO deposits (telegram_id, amount, utr, status) VALUES (?, ?, ?, 'PENDING')",
            (user.id, amount, utr)
        )
        conn.commit()
    except sqlite3.IntegrityError:
        bot.reply_to(message, "❌ This UTR has already been submitted!")
        conn.close()
        return
    conn.close()

    clear_dep_state(user.id)

    bot.reply_to(message, "⏳ <b>Your deposit request has been sent to the admins for approval.</b>", parse_mode="HTML")

    import helpers
    admin_ids = helpers.get_all_admin_ids()
    photo_file_id = message.photo[-1].file_id

    admin_msg = (
        f"🆕 <b>Deposit request</b>\n"
        f"<b>User:</b> @{user.username or user.first_name}\n"
        f"<b>Amount requested:</b> {amount} rupees\n"
        f"<b>UTR:</b> <code>{utr}</code>\n\n"
        f"<code>/approve {utr}</code>\n"
        f"<code>/decline {utr} &lt;reason&gt;</code>"
    )

    for admin_id in admin_ids:
        try:
            bot.send_photo(admin_id, photo=photo_file_id, caption=admin_msg, parse_mode="HTML")
        except Exception:
            pass

@bot.message_handler(commands=["approve"])
def approve_deposit(message: Message):
    import helpers
    if not helpers.is_admin(message.from_user.id):
        return

    args = message.text.split()
    if len(args) < 2:
        bot.reply_to(message, "Usage: <code>/approve &lt;UTR&gt;</code>", parse_mode="HTML")
        return

    utr = args[1].strip()

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM deposits WHERE utr = ? AND status = 'PENDING'", (utr,))
    dep = cursor.fetchone()

    if not dep:
        bot.reply_to(message, "❌ Invalid or already processed UTR.")
        conn.close()
        return

    target_user_id = dep["telegram_id"]
    amount = float(dep["amount"])

    cursor.execute("UPDATE deposits SET status = 'APPROVED' WHERE utr = ?", (utr,))
    conn.commit()
    conn.close()

    new_bal = adjust_balance(target_user_id, amount)
    add_wager_requirement(target_user_id, amount)

    bot.reply_to(message, f"✅ Approved. Credited ₹{amount} to user {target_user_id}.")

    try:
        user_text = (
            f"✅ <b>Your deposit request was approved!</b>\n"
            f"+₹{amount}\n"
            f"<b>New Balance:</b> ₹{new_bal:.2f}"
        )
        bot.send_message(target_user_id, user_text, parse_mode="HTML")
    except Exception:
        pass

@bot.message_handler(commands=["decline"])
def decline_deposit(message: Message):
    import helpers
    if not helpers.is_admin(message.from_user.id):
        return

    args = message.text.split(maxsplit=2)
    if len(args) < 2:
        bot.reply_to(message, "Usage: <code>/decline &lt;UTR&gt; [reason]</code>", parse_mode="HTML")
        return

    utr = args[1].strip()
    reason = args[2] if len(args) > 2 else "Invalid payment details"

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM deposits WHERE utr = ? AND status = 'PENDING'", (utr,))
    dep = cursor.fetchone()

    if not dep:
        bot.reply_to(message, "❌ Invalid or already processed UTR.")
        conn.close()
        return

    target_user_id = dep["telegram_id"]
    cursor.execute("UPDATE deposits SET status = 'DECLINED' WHERE utr = ?", (utr,))
    conn.commit()
    conn.close()

    bot.reply_to(message, f"❌ Deposit UTR {utr} declined.")

    try:
        bot.send_message(target_user_id, f"❌ <b>Your deposit request was declined.</b>\nReason: {reason}", parse_mode="HTML")
    except Exception:
        pass
