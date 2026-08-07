import sqlite3
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton, Message
from bot_instance import bot
from helpers import get_target_user

# Default Wager Multiplier
WAGER_MULTIPLIER = 1.0

# --- CORE WALLET DATABASE & UTILITY FUNCTIONS ---

def get_db_connection():
    conn = sqlite3.connect("database.db")
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    """Creates necessary database tables if they do not exist."""
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            telegram_id INTEGER PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            balance REAL DEFAULT 100.0,
            wager_required REAL DEFAULT 0.0,
            is_bot INTEGER DEFAULT 0
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS bets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            telegram_id INTEGER,
            game TEXT,
            bet_amount REAL,
            payout REAL,
            result TEXT,
            meta TEXT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)

    conn.commit()
    conn.close()

init_db()

def get_or_create_user(telegram_id: int, username: str = None, first_name: str = None):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users WHERE telegram_id = ?", (telegram_id,))
    user = cursor.fetchone()

    if not user:
        cursor.execute(
            "INSERT INTO users (telegram_id, username, first_name, balance, is_bot) VALUES (?, ?, ?, ?, ?)",
            (telegram_id, username, first_name, 100.0, 0)
        )
        conn.commit()
        cursor.execute("SELECT * FROM users WHERE telegram_id = ?", (telegram_id,))
        user = cursor.fetchone()

    conn.close()
    return dict(user) if user else None

def get_balance(user_id: int) -> float:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT balance FROM users WHERE telegram_id = ?", (user_id,))
    row = cursor.fetchone()
    conn.close()
    return float(row["balance"]) if row else 0.0

def adjust_balance(user_id: int, amount: float) -> float:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET balance = balance + ? WHERE telegram_id = ?", (amount, user_id))
    conn.commit()

    cursor.execute("SELECT balance FROM users WHERE telegram_id = ?", (user_id,))
    row = cursor.fetchone()
    new_bal = row["balance"] if row else 0.0
    conn.close()
    return float(new_bal)

def add_wager_requirement(telegram_id: int, amount: float):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "UPDATE users SET wager_required = COALESCE(wager_required, 0) + ? WHERE telegram_id = ?",
            (amount * WAGER_MULTIPLIER, telegram_id)
        )
        conn.commit()
    except sqlite3.OperationalError:
        pass
    conn.close()

def reduce_wager_requirement(telegram_id: int, bet_amount: float):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "UPDATE users SET wager_required = MAX(0.0, COALESCE(wager_required, 0) - ?) WHERE telegram_id = ?",
            (bet_amount, telegram_id)
        )
        conn.commit()
    except sqlite3.OperationalError:
        pass
    conn.close()

def get_wager_remaining(telegram_id: int) -> float:
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT wager_required FROM users WHERE telegram_id = ?", (telegram_id,))
        row = cursor.fetchone()
        conn.close()
        return float(row["wager_required"]) if row and row["wager_required"] else 0.0
    except sqlite3.OperationalError:
        conn.close()
        return 0.0

def get_house_balance() -> float:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT SUM(balance) as house_bal FROM users WHERE is_bot = 1")
    row = cursor.fetchone()
    conn.close()
    return float(row["house_bal"]) if row and row["house_bal"] else 100000.0

def resolve_amount(user_id: int, amount_str: str) -> float | None:
    amount_str = str(amount_str).lower().strip()
    user_bal = get_balance(user_id)

    if amount_str in ["all", "max"]:
        return user_bal
    if amount_str in ["half", "50%"]:
        return user_bal / 2.0

    try:
        val = float(amount_str)
        return val if val > 0 else None
    except ValueError:
        return None

def record_bet(telegram_id: int, game: str, bet_amount: float, payout: float, result: str, meta: dict = None):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO bets (telegram_id, game, bet_amount, payout, result, meta) VALUES (?, ?, ?, ?, ?, ?)",
        (telegram_id, game, bet_amount, payout, result, str(meta) if meta else "")
    )
    conn.commit()
    conn.close()

    res_upper = str(result).upper()
    if res_upper in ["LOSE", "LOSS"] or payout == 0:
        reduce_wager_requirement(telegram_id, bet_amount)


# ---------- COMMAND HANDLERS ----------

# Wallet Commands (/wallet, /bal, /balance)
@bot.message_handler(commands=["wallet", "bal", "balance"])
def handle_wallet(message: Message):
    user = message.from_user
    get_or_create_user(user.id, user.username, user.first_name)
    
    bal = get_balance(user.id)
    wager = get_wager_remaining(user.id)

    text = (
        f"💳 <b>Wallet Balance</b>\n\n"
        f"👤 <b>User:</b> {user.first_name}\n"
        f"💰 <b>Balance:</b> ₹{bal:.2f}\n"
        f"🎯 <b>Wager Needed:</b> ₹{wager:.2f}"
    )

    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(
        InlineKeyboardButton("💳 Deposit", callback_data="deposit"),
        InlineKeyboardButton("🏧 Withdraw", callback_data="withdraw")
    )

    bot.reply_to(message, text, parse_mode="HTML", reply_markup=markup)


# Tip Command (/tip)
@bot.message_handler(commands=["tip"])
def handle_tip(message: Message):
    sender_id = message.from_user.id
    get_or_create_user(sender_id, message.from_user.username, message.from_user.first_name)

    parts = message.text.split()
    target_id = None
    amount_str = None

    if message.reply_to_message:
        if len(parts) < 2:
            bot.reply_to(message, "⚠️ Usage: Reply to a user with <code>/tip <amount|all></code>", parse_mode="HTML")
            return
        target_id = message.reply_to_message.from_user.id
        amount_str = parts[1]
    else:
        if len(parts) < 3:
            bot.reply_to(message, "⚠️ Usage: <code>/tip <@user|id> <amount|all></code> or reply to user.", parse_mode="HTML")
            return
        target_id = get_target_user(message, parts[1])
        amount_str = parts[2]

    if not target_id:
        bot.reply_to(message, "❌ Target user not found.")
        return

    if target_id == sender_id:
        bot.reply_to(message, "❌ You cannot tip yourself.")
        return

    amount = resolve_amount(sender_id, amount_str)
    if amount is None or amount <= 0:
        bot.reply_to(message, "❌ Invalid tip amount or insufficient funds.")
        return

    sender_bal = get_balance(sender_id)
    if sender_bal < amount:
        bot.reply_to(message, f"❌ Insufficient balance. Your balance: ₹{sender_bal:.2f}")
        return

    get_or_create_user(target_id)
    adjust_balance(sender_id, -amount)
    adjust_balance(target_id, amount)

    bot.reply_to(
        message,
        f"💸 <b>Tip Sent!</b>\n\n"
        f"👤 <b>From:</b> {message.from_user.first_name}\n"
        f"🎯 <b>To User:</b> <code>{target_id}</code>\n"
        f"💰 <b>Amount:</b> ₹{amount:.2f}",
        parse_mode="HTML"
    )


# Rakeback Command (/rakeback) - Works in both Group & DM
@bot.message_handler(commands=["rakeback"])
def handle_rakeback(message: Message):
    user_id = message.from_user.id
    get_or_create_user(user_id, message.from_user.username, message.from_user.first_name)

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT SUM(bet_amount) as total_bets FROM bets WHERE telegram_id = ?", (user_id,))
    row = cursor.fetchone()
    conn.close()

    total_wagered = float(row["total_bets"]) if row and row["total_bets"] else 0.0
    # 1% Rakeback calculation
    rakeback_amt = round(total_wagered * 0.01, 2)

    text = (
        f"🎁 <b>Rakeback Rewards</b>\n\n"
        f"👤 <b>Player:</b> {message.from_user.first_name}\n"
        f"📊 <b>Total Wagered:</b> ₹{total_wagered:.2f}\n"
        f"💵 <b>Claimable Rakeback (1%):</b> ₹{rakeback_amt:.2f}\n\n"
        f"<i>Rakeback is auto-accrued from total game participation.</i>"
    )

    bot.reply_to(message, text, parse_mode="HTML")


@bot.message_handler(commands=["setwager"])
def handle_setwager(message: Message):
    from helpers import is_admin
    global WAGER_MULTIPLIER
    if not is_admin(message.from_user.id):
        return

    args = message.text.split()
    if len(args) < 2:
        bot.reply_to(message, f"⚠️ Usage: <code>/setwager &lt;multiplier&gt;</code> (Current: {WAGER_MULTIPLIER}x)", parse_mode="HTML")
        return

    try:
        val = float(args[1].replace("x", ""))
        WAGER_MULTIPLIER = val
        bot.reply_to(message, f"✅ <b>Wager multiplier set to {WAGER_MULTIPLIER}x!</b>", parse_mode="HTML")
    except ValueError:
        bot.reply_to(message, "❌ Invalid number.")

def setup_secret_wallet_handlers(bot=None):
    pass
