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

def get_or_create_user(telegram_id: int, username: str = None, first_name: str = None):
    """Retrieves or registers a user in the database."""
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
    """Adds to a user's required wagering balance upon deposit."""
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "UPDATE users SET wager_required = COALESCE(wager_required, 0) + ? WHERE telegram_id = ?",
            (amount * WAGER_MULTIPLIER, telegram_id)
        )
        conn.commit()
    except sqlite3.OperationalError:
        # Fallback if wager_required column doesn't exist in DB schema yet
        pass
    conn.close()

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


# --- TELEGRAM COMMAND HANDLERS ---

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


@bot.message_handler(commands=["bal", "wallet", "balance"])
def handle_balance(message: Message):
    from helpers import ensure_user
    ensure_user(message)
    user_id = message.from_user.id
    bal = get_balance(user_id)

    bot_username = bot.get_me().username
    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(
        InlineKeyboardButton("💳 Deposit", url=f"https://t.me/{bot_username}?start=deposit"),
        InlineKeyboardButton("💸 Withdraw", url=f"https://t.me/{bot_username}?start=withdraw")
    )

    bot.reply_to(
        message,
        f"💳 <b>YOUR WALLET</b>\n\n💰 <b>Balance:</b> ₹{bal:.2f}",
        parse_mode="HTML",
        reply_markup=markup
    )


@bot.message_handler(commands=["depo", "deposit", "withdraw"])
def handle_wallet_redirect(message: Message):
    bot_username = bot.get_me().username
    cmd = message.text.split()[0].replace("/", "").lower()

    if message.chat.type != "private":
        markup = InlineKeyboardMarkup()
        markup.add(InlineKeyboardButton("➡️ Open in DM", url=f"https://t.me/{bot_username}?start={cmd}"))
        bot.reply_to(message, "📩 Click below to continue in private messages:", reply_markup=markup)
        return

    if cmd in ["depo", "deposit"]:
        bot.reply_to(message, "💳 <b>Send the amount you wish to deposit:</b>", parse_mode="HTML")
    else:
        bot.reply_to(message, "💸 <b>Send the amount you wish to withdraw:</b>", parse_mode="HTML")
