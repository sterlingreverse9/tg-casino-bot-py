import threading
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton

from config import BOT_TOKEN, CASINO_NAME
from db import select, insert, update
from wallet import get_or_create_user, get_balance, adjust_balance, get_house_balance, resolve_amount
from game_status import is_game_enabled, set_game_enabled
from games.coinflip import play_coinflip
from games.dice_roll import play_dice_roll, ALL_CHOICES
from middleware.admin import is_admin

bot = telebot.TeleBot(BOT_TOKEN)
active_rains = {}  # message_id -> {"amount", "chat_id", "participants": set()}


def ensure_user(message):
    get_or_create_user(message.from_user.id, message.from_user.username)


def get_target_user(message, target):
    """Resolve a target user by reply, @username, or telegram_id."""
    if message.reply_to_message:
        user = message.reply_to_message.from_user
        get_or_create_user(user.id, user.username)
        return user.id

    if target.startswith("@"):
        username = target[1:]
        user = select("users", filters={"username": username}, single=True)
        return int(user["telegram_id"]) if user else None

    try:
        return int(target)
    except ValueError:
        return None


# ---------- Basic info commands ----------
@bot.message_handler(commands=["start"])
def cmd_start(message):
    parts = message.text.split()
    if len(parts) >= 2 and is_admin(message.from_user.id):
        game = parts[1].lower()
        set_game_enabled(game, True)
        bot.reply_to(message, f"▶️ '{game}' has been started/enabled.")
        return
    ensure_user(message)
    bot.reply_to(message, f"👋 Welcome to {CASINO_NAME}! Type /me to see your profile.")


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


@bot.message_handler(commands=["wallet"])
def cmd_wallet(message):
    ensure_user(message)
    balance = get_balance(message.from_user.id)
    bot.reply_to(message, f"💰 Your balance: ₹{balance}\nMinimum Withdrawal: ₹70")

@bot.message_handler(commands=["depo", "withdraw"])
def cmd_depo_withdraw(message):
    bot.reply_to(
        message,
        f"⚠️ Deposits and withdrawals are processed by @mrpuppyx . Pls contact him for deposit and withdraw— {CASINO_NAME} runs on manual deposit and withdraw, no automatic system right now.",
    )


@bot.message_handler(commands=["rakeback"])
def cmd_rakeback(message):
    ensure_user(message)
    user = select("users", filters={"telegram_id": message.from_user.id}, single=True)
    rakeback = round(float(user["total_lost"]) * 0.005, 2)
    if rakeback <= 0:
        bot.reply_to(message, "No rakeback available yet — play a bit more first!")
        return
    new_balance = adjust_balance(message.from_user.id, rakeback)
    bot.reply_to(message, f"💸 Rakeback claimed: +{rakeback} coins\nBalance: {new_balance}")


@bot.message_handler(commands=["housebal", "house"])
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
    lines = [f"{i+1}. {u['username'] or 'Anonymous'} — {u['total_won']} coins won" for i, u in enumerate(top)]
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
        bot.reply_to(message, f"You only have {balance} coins.")
        return

    adjust_balance(sender_id, -amount)
    new_balance = adjust_balance(target_id, amount)
    bot.reply_to(message, f"💸 Tip sent!\nTo: {target_name}\nAmount: {amount}\nTheir balance: {new_balance}")


# ---------- Games ----------
@bot.message_handler(commands=["cf"])
def cmd_cf(message):
    ensure_user(message)
    if not is_game_enabled("cf"):
        bot.reply_to(message, "Coinflip is currently disabled.")
        return
    parts = message.text.split()
    if len(parts) != 3 or parts[2] not in ("heads", "tails"):
        bot.reply_to(message, "Usage: /cf <amount|all|half> <heads|tails>")
        return
    bet_amount = resolve_amount(message.from_user.id, parts[1])
    if bet_amount is None:
        bot.reply_to(message, "Amount must be a number, 'all', or 'half'.")
        return
    play_coinflip(bot, message, message.from_user.id, bet_amount, parts[2])


def build_dr_keyboard(telegram_id: int, amount_str: str):
    markup = InlineKeyboardMarkup()
    markup.row(
        InlineKeyboardButton("High (4-6)", callback_data=f"dr:{telegram_id}:{amount_str}:high"),
        InlineKeyboardButton("Low (1-3)", callback_data=f"dr:{telegram_id}:{amount_str}:low"),
    )
    markup.row(
        InlineKeyboardButton("Even", callback_data=f"dr:{telegram_id}:{amount_str}:even"),
        InlineKeyboardButton("Odd", callback_data=f"dr:{telegram_id}:{amount_str}:odd"),
    )
    markup.row(*[
        InlineKeyboardButton(str(n), callback_data=f"dr:{telegram_id}:{amount_str}:{n}")
        for n in range(1, 7)
    ])
    return markup


@bot.message_handler(commands=["dr", "diceroll"])
def cmd_dr(message):
    ensure_user(message)
    if not is_game_enabled("dr"):
        bot.reply_to(message, "Dice Roll is currently disabled.")
        return
    parts = message.text.split()
    telegram_id = message.from_user.id

    if len(parts) >= 3:
        amount_str, choice = parts[1], parts[2].lower()
        bet_amount = resolve_amount(telegram_id, amount_str)
        if bet_amount is None:
            bot.reply_to(message, "Amount must be a number, 'all', or 'half'.")
            return
        play_dice_roll(bot, message.chat.id, telegram_id, bet_amount, choice)
        return

    amount_str = parts[1] if len(parts) == 2 else "10"
    if amount_str.lower() not in ("all", "half"):
        try:
            float(amount_str)
        except ValueError:
            bot.reply_to(message, "Amount must be a number, 'all', or 'half'.")
            return

    markup = build_dr_keyboard(telegram_id, amount_str)
    bot.send_message(message.chat.id, f"🎲 Dice Roll • bet: {amount_str}\nPick your bet:", reply_markup=markup)


@bot.callback_query_handler(func=lambda call: call.data.startswith("dr:"))
def handle_dr_callback(call):
    if not is_game_enabled("dr"):
        bot.answer_callback_query(call.id, "Dice Roll is currently disabled.")
        return
    _, owner_id_str, amount_str, choice = call.data.split(":")
    owner_id = int(owner_id_str)
    if call.from_user.id != owner_id:
        bot.answer_callback_query(call.id, "This isn't your bet.")
        return
    bot.answer_callback_query(call.id)
    bet_amount = resolve_amount(owner_id, amount_str)
    if bet_amount is None:
        bot.send_message(call.message.chat.id, "Amount must be a number, 'all', or 'half'.")
        return
    play_dice_roll(bot, call.message.chat.id, owner_id, bet_amount, choice)


# ---------- Admin: balance ----------
@bot.message_handler(commands=["add"])
def cmd_add(message):
    if not is_admin(message.from_user.id):
        bot.reply_to(message, "You don't have permission to use this command.")
        return
    parts = message.text.split()
    if message.reply_to_message:
        if len(parts) != 2:
            bot.reply_to(message, "Usage (reply): /add <amount>")
            return
        target_id = message.reply_to_message.from_user.id
        amount = float(parts[1])
    else:
        if len(parts) != 3:
            bot.reply_to(message, "Usage:\n/add <@username|telegram_id> <amount>\nOr reply: /add <amount>")
            return
        target_id = get_target_user(message, parts[1])
        if not target_id:
            bot.reply_to(message, "User not found.")
            return
        amount = float(parts[2])

    get_or_create_user(target_id, None)
    new_balance = adjust_balance(target_id, amount)
    insert("admin_actions", {"admin_id": message.from_user.id, "action": "add", "target_id": target_id, "amount": amount})
    bot.reply_to(message, f"✅ Added ₹{amount} \nUser: {target_id}\nNew balance: {new_balance}")


@bot.message_handler(commands=["deduct"])
def cmd_deduct(message):
    if not is_admin(message.from_user.id):
        bot.reply_to(message, "You don't have permission to use this command.")
        return
    parts = message.text.split()
    if message.reply_to_message:
        if len(parts) != 2:
            bot.reply_to(message, "Usage (reply): /deduct <amount|all>")
            return
        target_id = message.reply_to_message.from_user.id
        amount_arg = parts[1]
    else:
        if len(parts) != 3:
            bot.reply_to(message, "Usage: /deduct <@username|telegram_id> <amount|all>")
            return
        target_id = get_target_user(message, parts[1])
        if not target_id:
            bot.reply_to(message, "User not found.")
            return
        amount_arg = parts[2]

    amount = resolve_amount(target_id, amount_arg)
    if amount is None:
        bot.reply_to(message, "Amount must be a number or 'all'.")
        return
    new_balance = adjust_balance(target_id, -amount)
    insert("admin_actions", {"admin_id": message.from_user.id, "action": "deduct", "target_id": target_id, "amount": amount})
    bot.reply_to(message, f"✅ Deducted ₹{amount} \nUser: {target_id}\nBalance: {new_balance}")


# ---------- Admin: promote/demote ----------
@bot.message_handler(commands=["promote"])
def cmd_promote(message):
    if not is_admin(message.from_user.id):
        bot.reply_to(message, "You don't have permission to use this command.")
        return
    parts = message.text.split()
    target_id = get_target_user(message, parts[1]) if len(parts) >= 2 else None
    if not target_id:
        bot.reply_to(message, "Usage: /promote <@username|telegram_id> (or reply to their message)")
        return
    get_or_create_user(target_id, None)
    update("users", {"telegram_id": target_id}, {"is_admin": True})
    insert("admin_actions", {"admin_id": message.from_user.id, "action": "promote", "target_id": target_id})
    bot.reply_to(message, f"👑 {target_id} is now an admin.")


@bot.message_handler(commands=["demote"])
def cmd_demote(message):
    if not is_admin(message.from_user.id):
        bot.reply_to(message, "You don't have permission to use this command.")
        return
    parts = message.text.split()
    target_id = get_target_user(message, parts[1]) if len(parts) >= 2 else None
    if not target_id:
        bot.reply_to(message, "Usage: /demote <@username|telegram_id> (or reply to their message)")
        return
    update("users", {"telegram_id": target_id}, {"is_admin": False})
    insert("admin_actions", {"admin_id": message.from_user.id, "action": "demote", "target_id": target_id})
    bot.reply_to(message, f"⬇️ {target_id} is no longer an admin.")


@bot.message_handler(commands=["updatehb"])
def cmd_updatehb(message):
    if not is_admin(message.from_user.id):
        bot.reply_to(message, "You don't have permission to use this command.")
        return
    parts = message.text.split()
    if len(parts) != 2:
        bot.reply_to(message, "Usage: /updatehb <amount>")
        return
    amount = float(parts[1])
    update("house", {"id": 1}, {"balance": amount})
    insert("admin_actions", {"admin_id": message.from_user.id, "action": "updatehb", "amount": amount})
    bot.reply_to(message, f"🏦 House balance set to {amount}.")


# ---------- Admin: rain ----------
MIN_WAGERED_FOR_RAIN = 1000


@bot.message_handler(commands=["rain"])
def cmd_rain(message):
    if not is_admin(message.from_user.id):
        bot.reply_to(message, "You don't have permission to use this command.")
        return
    parts = message.text.split()
    if len(parts) < 2:
        bot.reply_to(message, "Usage: /rain <amount> [seconds, default 60]")
        return
    try:
        amount = float(parts[1])
    except ValueError:
        bot.reply_to(message, "Amount must be a number.")
        return
    seconds = int(parts[2]) if len(parts) >= 3 else 60

    sent = bot.send_message(
        message.chat.id,
        f"🌧️ Rain of ₹{amount} starting!\nTap to join (min {MIN_WAGERED_FOR_RAIN} total wagered required).\nEnds in {seconds}s.",
    )
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("🌧️ Join Rain", callback_data=f"rainjoin:{sent.message_id}"))
    bot.edit_message_reply_markup(chat_id=sent.chat.id, message_id=sent.message_id, reply_markup=markup)

    try:
        bot.pin_chat_message(sent.chat.id, sent.message_id)
    except Exception:
        pass

    active_rains[sent.message_id] = {"amount": amount, "chat_id": sent.chat.id, "participants": set()}

    def finish_rain():
        rain = active_rains.pop(sent.message_id, None)
        if rain is None:
            return
        participants = rain["participants"]
        if not participants:
            bot.send_message(rain["chat_id"], "🌧️ Rain ended — nobody joined.")
        else:
            share = round(rain["amount"] / len(participants), 2)
            for uid in participants:
                adjust_balance(uid, share)
            bot.send_message(
                rain["chat_id"],
                f"🌧️ Rain of {rain['amount']} rupees ended!\n{share} ruppess each to {len(participants)} users. 🎉",
            )
        try:
            bot.unpin_chat_message(rain["chat_id"], sent.message_id)
        except Exception:
            pass

    threading.Timer(seconds, finish_rain).start()


@bot.callback_query_handler(func=lambda call: call.data.startswith("rainjoin:"))
def handle_rain_join(call):
    msg_id = int(call.data.split(":")[1])
    rain = active_rains.get(msg_id)
    if rain is None:
        bot.answer_callback_query(call.id, "This rain has ended.")
        return

    user_id = call.from_user.id
    get_or_create_user(user_id, call.from_user.username)
    user = select("users", filters={"telegram_id": user_id}, single=True)

    if float(user.get("total_wagered", 0)) < MIN_WAGERED_FOR_RAIN:
        bot.answer_callback_query(call.id, f"You need at least {MIN_WAGERED_FOR_RAIN} total wagered to join.")
        return
    if user_id in rain["participants"]:
        bot.answer_callback_query(call.id, "You already joined!")
        return

    rain["participants"].add(user_id)
    bot.answer_callback_query(call.id, "You joined the rain! 🌧️")


print(f"{CASINO_NAME} bot running...")
bot.infinity_polling()
