import sqlite3
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton, Message
from bot_instance import bot

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
    """Deducts bet_amount from wager_required."""
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

    # ONLY REDUCE WAGER IF THE USER LOST THE BET
    res_upper = str(result).upper()
    if res_upper in ["LOSE", "LOSS"] or payout == 0:
        reduce_wager_requirement(telegram_id, bet_amount)

def setup_secret_wallet_handlers(bot=None):
    pass

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
