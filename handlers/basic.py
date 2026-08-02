from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
from bot_instance import bot
from config import CASINO_NAME
from db import select
from wallet import get_balance, adjust_balance, get_house_balance, resolve_amount, get_or_create_user
from game_status import set_game_enabled
from middleware.admin import is_admin
from helpers import ensure_user, has_promo_tag, get_target_user
from state import PROMO_TAG
from referral import get_user_by_referral_code, set_referred_by, record_referral_join


def build_welcome_text(name: str) -> str:
    return (
        f"👋 Hello {name}, welcome to {CASINO_NAME}! 🎰\n\n"
        "Please join the channels and group below for the smoothest experience — "
        "you'll catch win announcements, updates, and the main game chat."
    )


def build_welcome_keyboard():
    markup = InlineKeyboardMarkup(row_width=1)
    markup.add(InlineKeyboardButton("🎮 Play Group", url="https://t.me/thecassinogroup"))
    markup.add(InlineKeyboardButton("📢 Updates Channel", url="https://t.me/thecassinoupdates"))
    markup.add(InlineKeyboardButton("🏆 Wins Channel", url="https://t.me/thecassinowins"))
    return markup


@bot.message_handler(commands=["start"])
def cmd_start(message):
    parts = message.text.split()
    name = message.from_user.first_name or (message.from_user.username or "there")

    if len(parts) >= 2 and parts[1].startswith("ref-"):
        code = parts[1][4:]
        existing_user = select("users", filters={"telegram_id": message.from_user.id}, single=True)
        get_or_create_user(message.from_user.id, message.from_user.username)

        if existing_user is None:
            referrer = get_user_by_referral_code(code)
            if referrer and int(referrer["telegram_id"]) != message.from_user.id:
                set_referred_by(message.from_user.id, int(referrer["telegram_id"]))
                record_referral_join(int(referrer["telegram_id"]), message.from_user.id, message.from_user.username)
                referrer_name = referrer.get("username") or str(referrer["telegram_id"])
                bot.reply_to(
                    message,
                    f"You've joined under {referrer_name}'s referral, you can't change it in future.\n\n"
                    + build_welcome_text(name),
                    reply_markup=build_welcome_keyboard(),
                )
                try:
                    joiner_name = message.from_user.first_name or str(message.from_user.id)
                    joiner_tag = f"(@{message.from_user.username})" if message.from_user.username else ""
                    bot.send_message(int(referrer["telegram_id"]), f"{joiner_name}{joiner_tag} has joined through your referral 🎲")
                except Exception:
                    pass
                return

        bot.reply_to(message, build_welcome_text(name), reply_markup=build_welcome_keyboard())
        return

    if len(parts) >= 2 and is_admin(message.from_user.id):
        game = parts[1].lower()
        set_game_enabled(game, True)
        bot.reply_to(message, f"▶️ '{game}' has been started/enabled.")
        return
    ensure_user(message)
    bot.reply_to(message, build_welcome_text(name), reply_markup=build_welcome_keyboard())


@bot.message_handler(commands=["stop"])
def cmd_stop(message):
    if not is_admin(message.from_user.id):
        bot.reply_to(message, "You don't have permission to use this command.")
        return
    parts = message.text.split()
    if len(parts) != 2:
        bot.reply_to(message, "Usage: /stop <gamename>")
        return
    game = parts[1].lower()
    set_game_enabled(game, False)
    bot.reply_to(message, f"⏸️ '{game}' has been stopped/disabled.")


@bot.message_handler(commands=["me", "profile"])
def cmd_me(message):
    ensure_user(message)
    user = select("users", filters={"telegram_id": message.from_user.id}, single=True)
    bot.reply_to(
        message,
        f"👤 {message.from_user.username or message.from_user.first_name} — {CASINO_NAME}\n"
        f"💰 Balance: {user['balance']}\n"
        f"📊 Wagered: {user['total_wagered']}\n"
        f"✅ Won: {user['total_won']}\n"
        f"❌ Lost: {user['total_lost']}",
    )


@bot.message_handler(commands=["wallet" , "balance" , "bal" ])
def cmd_wallet(message):
    ensure_user(message)
    balance = get_balance(message.from_user.id)
    bot.reply_to(message, f"💰 Your balance: ₹{balance} ")


@bot.message_handler(commands=["housebal", "house" , "hb" ])
def cmd_housebal(message):
    bal = get_house_balance()
    bot.reply_to(message, f"🏦 {CASINO_NAME} house balance: ₹{bal}")


@bot.message_handler(commands=["history"])
def cmd_history(message):
    ensure_user(message)
    bets = select(
        "bets",
        filters={"telegram_id": message.from_user.id},
        order="created_at",
        desc=True,
        limit=10,
    )
    if not bets:
        bot.reply_to(message, "No bets yet.")
        return
    lines = [f"{'✅' if b['result'] == 'win' else '❌'} {b['game']} | bet {b['bet_amount']} | payout {b['payout']}" for b in bets]
    bot.reply_to(message, "📜 Last 10 bets:\n" + "\n".join(lines))


@bot.message_handler(commands=["leaderboard", "ld"])
def cmd_leaderboard(message):
    top = select("users", order="total_won", desc=True, limit=10)
    lines = [f"{i+1}. {u['username'] or 'Anonymous'} — {u['total_won']} rupees won" for i, u in enumerate(top)]
    bot.reply_to(message, f"🏆 {CASINO_NAME} Leaderboard:\n" + "\n".join(lines))


# ---------- Tip ----------


@bot.message_handler(commands=["tip"])
def cmd_tip(message):
    ensure_user(message)
    parts = message.text.split()
    sender_id = message.from_user.id

    if message.reply_to_message:
        if len(parts) != 2:
            bot.reply_to(message, "Usage (reply): /tip <amount|all|half>")
            return
        recipient = message.reply_to_message.from_user
        target_id, target_name, amount_arg = recipient.id, (recipient.username or recipient.first_name), parts[1]
    else:
        if len(parts) != 3:
            bot.reply_to(message, "Usage:\n/tip @username <amount|all|half>\n/tip <telegram_id> <amount|all|half>\nOr reply: /tip <amount|all|half>")
            return
        target_id = get_target_user(message, parts[1])
        if not target_id:
            bot.reply_to(message, "User not found.")
            return
        user = select("users", filters={"telegram_id": target_id}, single=True)
        target_name = (user["username"] if user else None) or str(target_id)
        amount_arg = parts[2]

    if target_id == sender_id:
        bot.reply_to(message, "You can't tip yourself.")
        return

    get_or_create_user(target_id, target_name)
    amount = resolve_amount(sender_id, amount_arg)
    if amount is None:
        bot.reply_to(message, "Amount must be a number, 'all', or 'half'.")
        return
    if amount <= 0:
        bot.reply_to(message, "Amount must be greater than 0.")
        return

    balance = get_balance(sender_id)
    if amount > balance:
        bot.reply_to(message, f"You only have ₹{balance} .")
        return

    adjust_balance(sender_id, -amount)
    new_balance = adjust_balance(target_id, amount)
    bot.reply_to(message, f"💸 Tip sent!\nTo: {target_name}\nAmount: ₹{amount}\nTheir balance: ₹{new_balance}")

