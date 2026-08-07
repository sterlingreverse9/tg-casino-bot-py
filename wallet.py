import sqlite3
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton, Message
from bot_instance import bot

CARD_IMAGE_URL = "https://i.ibb.co/L9vXGzq/casino-wallet-banner.jpg"
WAGER_MULTIPLIER = 1.0

# --- CORE DATABASE FUNCTIONS ---

def get_db_connection():
    conn = sqlite3.connect("database.db")
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            telegram_id INTEGER PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            balance REAL DEFAULT 100.0,
            wager_required REAL DEFAULT 0.0,
            rakeback_claimed REAL DEFAULT 0.0,
            is_bot INTEGER DEFAULT 0,
            is_admin INTEGER DEFAULT 0
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
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS house (
            id INTEGER PRIMARY KEY,
            balance REAL DEFAULT 100000.0
        )
    """)
    cursor.execute("INSERT OR IGNORE INTO house (id, balance) VALUES (1, 100000.0)")
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
    try:
        cursor.execute("SELECT balance FROM house WHERE id = 1")
        row = cursor.fetchone()
        conn.close()
        return float(row["balance"]) if row and row["balance"] is not None else 100000.0
    except Exception:
        conn.close()
        return 100000.0

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

def add_wager_requirement(telegram_id: int, amount: float):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "UPDATE users SET wager_required = COALESCE(wager_required, 0) + ? WHERE telegram_id = ?",
            (amount, telegram_id)
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


# ---------- HANDLERS & CALLBACKS ----------

@bot.message_handler(commands=["wallet", "bal", "balance"])
def handle_wallet(message: Message):
    user = message.from_user
    get_or_create_user(user.id, user.username, user.first_name)

    bal = get_balance(user.id)
    wager = get_wager_remaining(user.id)
    bot_info = bot.get_me()

    text = (
        f"💳 <b>Wallet Balance</b>\n\n"
        f"👤 <b>User:</b> {user.first_name}\n"
        f"💰 <b>Balance:</b> ₹{bal:.2f}\n"
        f"🎯 <b>Wager Needed:</b> ₹{wager:.2f}"
    )

    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(
        InlineKeyboardButton("💳 Deposit", url=f"https://t.me/{bot_info.username}?start=deposit"),
        InlineKeyboardButton("🏧 Withdraw", url=f"https://t.me/{bot_info.username}?start=withdraw")
    )

    try:
        bot.send_photo(message.chat.id, photo=CARD_IMAGE_URL, caption=text, parse_mode="HTML", reply_markup=markup)
    except Exception:
        bot.reply_to(message, text, parse_mode="HTML", reply_markup=markup)


@bot.message_handler(commands=["rakeback"])
def handle_rakeback(message: Message):
    user_id = message.from_user.id
    get_or_create_user(user_id, message.from_user.username, message.from_user.first_name)

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT SUM(bet_amount) as total_bets FROM bets WHERE telegram_id = ?", (user_id,))
    row = cursor.fetchone()
    
    cursor.execute("SELECT COALESCE(rakeback_claimed, 0) as claimed FROM users WHERE telegram_id = ?", (user_id,))
    user_row = cursor.fetchone()

    total_wagered = float(row["total_bets"]) if row and row["total_bets"] else 0.0
    claimed = float(user_row["claimed"]) if user_row and user_row["claimed"] else 0.0

    total_rakeback = round(total_wagered * 0.01, 2)
    claimable = round(total_rakeback - claimed, 2)

    if claimable <= 0:
        bot.reply_to(message, "🎁 <b>Rakeback Status</b>\n\nNo claimable rakeback available right now. Keep playing to earn more!", parse_mode="HTML")
        conn.close()
        return

    # Add claimable rakeback to user balance
    adjust_balance(user_id, claimable)
    
    # Update total claimed rakeback
    cursor.execute("UPDATE users SET rakeback_claimed = COALESCE(rakeback_claimed, 0) + ? WHERE telegram_id = ?", (claimable, user_id))
    conn.commit()
    conn.close()

    new_bal = get_balance(user_id)
    text = (
        f"🎁 <b>Rakeback Claimed!</b>\n\n"
        f"👤 <b>Player:</b> {message.from_user.first_name}\n"
        f"📊 <b>Total Wagered:</b> ₹{total_wagered:.2f}\n"
        f"💵 <b>Claimed (1%):</b> ₹{claimable:.2f}\n"
        f"💰 <b>New Balance:</b> ₹{new_bal:.2f}"
    )

    bot.reply_to(message, text, parse_mode="HTML")


@bot.message_handler(commands=["tip"])
def handle_tip(message: Message):
    from helpers import get_target_user

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
            bot.reply_to(message, "⚠️ Usage: <code>/tip <@user|id> <amount|all></code>", parse_mode="HTML")
            return
        target_id = get_target_user(message, parts[1])
        amount_str = parts[2]

    if not target_id or target_id == sender_id:
        bot.reply_to(message, "❌ Invalid target user.")
        return

    amount = resolve_amount(sender_id, amount_str)
    if amount is None or amount <= 0:
        bot.reply_to(message, "❌ Invalid amount.")
        return

    sender_bal = get_balance(sender_id)
    if sender_bal < amount:
        bot.reply_to(message, f"❌ Insufficient balance (₹{sender_bal:.2f}).")
        return

    get_or_create_user(target_id)
    adjust_balance(sender_id, -amount)
    adjust_balance(target_id, amount)

    bot.reply_to(
        message,
        f"💸 <b>Tip Sent!</b>\n\n"
        f"👤 <b>From:</b> {message.from_user.first_name}\n"
        f"🎯 <b>To:</b> <code>{target_id}</code>\n"
        f"💰 <b>Amount:</b> ₹{amount:.2f}",
        parse_mode="HTML"
    )


@bot.message_handler(commands=["setwager"])
def handle_setwager(message: Message):
    from helpers import is_admin
    global WAGER_MULTIPLIER
    if not is_admin(message.from_user.id):
        return

    args = message.text.split()
    if len(args) < 2:
        bot.reply_to(message, f"⚠️ Usage: <code>/setwager &lt;multiplier&gt;</code>", parse_mode="HTML")
        return

    try:
        val = float(args[1].replace("x", ""))
        WAGER_MULTIPLIER = val
        bot.reply_to(message, f"✅ Wager multiplier set to {WAGER_MULTIPLIER}x!", parse_mode="HTML")
    except ValueError:
        bot.reply_to(message, "❌ Invalid number.")

def setup_secret_wallet_handlers(bot=None):
    pass
