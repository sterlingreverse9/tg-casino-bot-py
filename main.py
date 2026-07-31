import threading
import time
import uuid
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton

from config import BOT_TOKEN, CASINO_NAME
from db import select, insert, update
from wallet import get_or_create_user, get_balance, adjust_balance, get_house_balance, resolve_amount, record_bet
from game_status import is_game_enabled, set_game_enabled
from games.coinflip import play_coinflip
from games.dice_roll import play_dice_roll, ALL_CHOICES
from games.limbo import play_limbo, parse_multiplier
from games.dice_duel import parse_dice_code, decide_round_winner, MIN_BET as DUEL_MIN_BET
from middleware.admin import is_admin

bot = telebot.TeleBot(BOT_TOKEN)
active_rains = {}  # message_id -> {"amount", "chat_id", "participants": set()}
dice_setups = {}  # setup_id -> in-progress wizard state
active_matches = {}  # match_id -> live match state
dice_waiters = {}  # (chat_id, telegram_id) -> match_id
HOUSE_EDGE_RAKE = 0.10


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
    bot.reply_to(message, f"💰 Your balance: {balance} coins")


@bot.message_handler(commands=["depo", "withdraw"])
def cmd_depo_withdraw(message):
    bot.reply_to(
        message,
        f"⚠️ Deposits and withdrawals aren't available — {CASINO_NAME} runs on fun coins only, no real money.",
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
    bot.reply_to(message, f"🏦 {CASINO_NAME} house balance: {bal} coins")


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
    bot.reply_to(message, f"✅ Added {amount} coins\nUser: {target_id}\nNew balance: {new_balance}")


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
    bot.reply_to(message, f"✅ Deducted {amount} coins\nUser: {target_id}\nBalance: {new_balance}")


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
        f"🌧️ Rain of {amount} coins starting!\nTap to join (min {MIN_WAGERED_FOR_RAIN} total wagered required).\nEnds in {seconds}s.",
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
                f"🌧️ Rain of {rain['amount']} coins ended!\n{share} coins each to {len(participants)} users. 🎉",
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


# ---------- Dice Duel (vs bot or vs player, real Telegram dice) ----------
CASINO_LABEL = "The Casino"


def display_name(user):
    if user.username:
        return f"@{user.username}"
    return user.first_name or "Player"


def parse_dice_command(text: str, reply_msg):
    """Returns (amount_str, code_or_None, opponent_username, opponent_id, opponent_name)."""
    tokens = text.split()[1:]
    amount_str, code, opponent_username = None, None, None
    for tok in tokens:
        if tok.startswith("@"):
            opponent_username = tok[1:]
        elif parse_dice_code(tok.lower()):
            code = tok.lower()
        elif amount_str is None:
            amount_str = tok

    opponent_id, opponent_name = None, None
    if reply_msg:
        opponent_id = reply_msg.from_user.id
        opponent_name = display_name(reply_msg.from_user)
        get_or_create_user(opponent_id, reply_msg.from_user.username)
    elif opponent_username:
        opponent = select("users", filters={"username": opponent_username}, single=True)
        if opponent:
            opponent_id = int(opponent["telegram_id"])
            opponent_name = f"@{opponent_username}"

    return amount_str, code, opponent_username, opponent_id, opponent_name


def rounds_keyboard(setup_id):
    markup = InlineKeyboardMarkup()
    markup.row(*[InlineKeyboardButton(str(n), callback_data=f"dround:{setup_id}:{n}") for n in (1, 2, 3)])
    return markup


def rolls_keyboard(setup_id):
    markup = InlineKeyboardMarkup()
    markup.row(*[InlineKeyboardButton(str(n), callback_data=f"droll:{setup_id}:{n}") for n in (1, 2, 3)])
    return markup


def mode_keyboard(setup_id):
    markup = InlineKeyboardMarkup()
    markup.row(
        InlineKeyboardButton("Normal (highest sum wins)", callback_data=f"dsmode:{setup_id}:normal"),
        InlineKeyboardButton("Crazy (lowest sum wins)", callback_data=f"dsmode:{setup_id}:crazy"),
    )
    return markup


def advance_setup(setup_id):
    setup = dice_setups.get(setup_id)
    if setup is None:
        return
    chat_id = setup["chat_id"]
    if setup["rounds"] is None:
        bot.send_message(chat_id, "🎲 How many rounds?", reply_markup=rounds_keyboard(setup_id))
    elif setup["dice_count"] is None:
        bot.send_message(chat_id, "🎲 How many dice per round?", reply_markup=rolls_keyboard(setup_id))
    elif setup["mode"] is None:
        bot.send_message(chat_id, "🎲 Choose your game mode:", reply_markup=mode_keyboard(setup_id))
    else:
        finalize_setup(setup_id)

def finalize_setup(setup_id):
    setup = dice_setups.pop(setup_id, None)
    if setup is None:
        return
    chat_id = setup["chat_id"]

    if setup["opponent_id"] is None:
        amount = resolve_amount(setup["initiator_id"], setup["amount_str"])
        if amount is None:
            bot.send_message(chat_id, "Amount must be a number, 'all', or 'half'.")
            return
        if amount < DUEL_MIN_BET:
            bot.send_message(chat_id, f"Minimum bet is {DUEL_MIN_BET} coins.")
            return
        if amount > get_balance(setup["initiator_id"]):
            bot.send_message(chat_id, f"Not enough balance. Your balance: {get_balance(setup['initiator_id'])}")
            return
        adjust_balance(setup["initiator_id"], -amount)
        start_match(
            chat_id=chat_id,
            player_a=setup["initiator_id"], player_a_name=setup["initiator_name"], bet_a=amount,
            player_b=None, player_b_name=CASINO_LABEL, bet_b=0,
            dice_count=setup["dice_count"], rounds=setup["rounds"], mode=setup["mode"],
        )
        return

    markup = InlineKeyboardMarkup()
    markup.row(
        InlineKeyboardButton("✅ Accept", callback_data=f"daccept:{setup_id}"),
        InlineKeyboardButton("❌ Decline", callback_data=f"ddecline:{setup_id}"),
    )
    dice_setups[setup_id] = setup
    setup["status"] = "awaiting_accept"
    bot.send_message(
        chat_id,
        f"⚔️ {setup['initiator_name']} challenges {setup['opponent_name']} to a Dice Duel!\n"
        f"{setup['dice_count']} dice, {setup['rounds']} round(s), {setup['mode']} mode, bet: {setup['amount_str']} coins each.\n"
        f"{setup['opponent_name']} has 120 seconds to accept.",
        reply_markup=markup,
    )

    def expire_setup():
        d = dice_setups.get(setup_id)
        if d and d.get("status") == "awaiting_accept":
            dice_setups.pop(setup_id, None)
            bot.send_message(d["chat_id"], f"⌛ The challenge to {d['opponent_name']} expired.")

    threading.Timer(120, expire_setup).start()


@bot.message_handler(commands=["dice"])
def cmd_dice(message):
    ensure_user(message)
    if not is_game_enabled("dice"):
        bot.reply_to(message, "Dice Duel is currently disabled.")
        return

    amount_str, code, opponent_username, opponent_id, opponent_name = parse_dice_command(message.text, message.reply_to_message)
    if amount_str is None:
        bot.reply_to(message, "Usage: /dice <amount|all|half> [<dice>d<rounds>w] [@opponent]\nOr reply to someone's message with /dice <amount> [...]")
        return
    if opponent_username and opponent_id is None:
        bot.reply_to(message, f"That user needs to message this bot at least once (e.g. /me) before they can be challenged.")
        return
    if opponent_id == message.from_user.id:
        bot.reply_to(message, "You can't challenge yourself.")
        return

    dice_count, rounds = (None, None)
    if code:
        parsed = parse_dice_code(code)
        if parsed is None:
            bot.reply_to(message, "Invalid dice code. Format is <dice>d<rounds>w, e.g. 3d1w (max 3 dice, 3 rounds).")
            return
        dice_count, rounds = parsed

    setup_id = uuid.uuid4().hex[:10]
    dice_setups[setup_id] = {
        "initiator_id": message.from_user.id,
        "initiator_name": display_name(message.from_user),
        "amount_str": amount_str,
        "dice_count": dice_count,
        "rounds": rounds,
        "mode": None,
        "opponent_id": opponent_id,
        "opponent_name": opponent_name,
        "chat_id": message.chat.id,
        "status": "setup",
    }
    advance_setup(setup_id)


@bot.callback_query_handler(func=lambda call: call.data.startswith("dround:"))
def handle_dround(call):
    _, setup_id, n = call.data.split(":")
    setup = dice_setups.get(setup_id)
    if setup is None or call.from_user.id != setup["initiator_id"]:
        bot.answer_callback_query(call.id, "Not your setup.")
        return
    bot.answer_callback_query(call.id)
    setup["rounds"] = int(n)
    advance_setup(setup_id)


@bot.callback_query_handler(func=lambda call: call.data.startswith("droll:"))
def handle_droll(call):
    _, setup_id, n = call.data.split(":")
    setup = dice_setups.get(setup_id)
    if setup is None or call.from_user.id != setup["initiator_id"]:
        bot.answer_callback_query(call.id, "Not your setup.")
        return
    bot.answer_callback_query(call.id)
    setup["dice_count"] = int(n)
    advance_setup(setup_id)


@bot.callback_query_handler(func=lambda call: call.data.startswith("dsmode:"))
def handle_dsmode(call):
    _, setup_id, mode = call.data.split(":")
    setup = dice_setups.get(setup_id)
    if setup is None or call.from_user.id != setup["initiator_id"]:
        bot.answer_callback_query(call.id, "Not your setup.")
        return
    bot.answer_callback_query(call.id)
    setup["mode"] = mode
    advance_setup(setup_id)


@bot.callback_query_handler(func=lambda call: call.data.startswith("daccept:") or call.data.startswith("ddecline:"))
def handle_dice_response(call):
    action, setup_id = call.data.split(":")
    setup = dice_setups.get(setup_id)
    if setup is None or setup.get("status") != "awaiting_accept":
        bot.answer_callback_query(call.id, "This challenge is no longer active.")
        return
    if call.from_user.id != setup["opponent_id"]:
        bot.answer_callback_query(call.id, "This challenge isn't for you.")
        return

    if action == "ddecline":
        dice_setups.pop(setup_id, None)
        bot.answer_callback_query(call.id, "Challenge declined.")
        bot.send_message(setup["chat_id"], f"❌ {setup['opponent_name']} declined the challenge.")
        return

    bot.answer_callback_query(call.id)
    dice_setups.pop(setup_id, None)

    initiator_id, opponent_id = setup["initiator_id"], setup["opponent_id"]
    initiator_amount = resolve_amount(initiator_id, setup["amount_str"])
    opponent_amount = resolve_amount(opponent_id, setup["amount_str"])

    if initiator_amount is None or opponent_amount is None:
        bot.send_message(setup["chat_id"], "Amount must be a number, 'all', or 'half'.")
        return
    if initiator_amount < DUEL_MIN_BET or opponent_amount < DUEL_MIN_BET:
        bot.send_message(setup["chat_id"], f"Minimum bet is {DUEL_MIN_BET} coins for both players.")
        return
    if initiator_amount > get_balance(initiator_id):
        bot.send_message(setup["chat_id"], f"{setup['initiator_name']} doesn't have enough balance anymore.")
        return
    if opponent_amount > get_balance(opponent_id):
        bot.send_message(setup["chat_id"], f"{setup['opponent_name']} doesn't have enough balance anymore.")
        return

    adjust_balance(initiator_id, -initiator_amount)
    adjust_balance(opponent_id, -opponent_amount)

    start_match(
        chat_id=setup["chat_id"],
        player_a=initiator_id, player_a_name=setup["initiator_name"], bet_a=initiator_amount,
        player_b=opponent_id, player_b_name=setup["opponent_name"], bet_b=opponent_amount,
        dice_count=setup["dice_count"], rounds=setup["rounds"], mode=setup["mode"],
    )


def start_match(chat_id, player_a, player_a_name, bet_a, player_b, player_b_name, bet_b, dice_count, rounds, mode):
    match_id = uuid.uuid4().hex[:10]
    active_matches[match_id] = {
        "chat_id": chat_id,
        "player_a": player_a, "player_a_name": player_a_name, "bet_a": bet_a,
        "player_b": player_b, "player_b_name": player_b_name, "bet_b": bet_b,
        "dice_count": dice_count, "rounds": rounds, "mode": mode,
        "current_round": 1, "a_wins": 0, "b_wins": 0,
        "a_current": [], "b_current": [], "round_log": [],
    }
    dice_waiters[(chat_id, player_a)] = match_id
    if player_b is not None:
        dice_waiters[(chat_id, player_b)] = match_id

    bot.send_message(
        chat_id,
        f"⚔️ Dice Duel started! {player_a_name} vs {player_b_name} • {dice_count} dice/round • {rounds} round(s) • {mode} mode\n"
        f"{player_a_name}, send your 🎲 dice now!",
    )
    if player_b is not None:
        schedule_afk_timers(match_id, 1, "a")
        schedule_afk_timers(match_id, 1, "b")


@bot.message_handler(content_types=["dice"])
def handle_incoming_dice(message):
    key = (message.chat.id, message.from_user.id)
    match_id = dice_waiters.get(key)
    if match_id is None:
        return
    match = active_matches.get(match_id)
    if match is None:
        return

    side = "a" if message.from_user.id == match["player_a"] else "b"
    match[f"{side}_current"].append(message.dice.value)

    remaining = match["dice_count"] - len(match[f"{side}_current"])
    if remaining > 0:
        bot.reply_to(message, f"Got it! Send {remaining} more dice.")
        return

    if match["player_b"] is None and side == "a":
        match["b_current"] = [
            bot.send_dice(match["chat_id"], emoji="🎲", reply_to_message_id=message.message_id).dice.value
            for _ in range(match["dice_count"])
        ]
    else:
        bot.reply_to(message, "Got your dice for this round!")

    if len(match["a_current"]) == match["dice_count"] and len(match["b_current"]) == match["dice_count"]:
        resolve_round(match_id)
    else:
        waiting_name = match["player_b_name"] if side == "a" else match["player_a_name"]
        bot.send_message(match["chat_id"], f"Waiting on {waiting_name} to send their dice...")


def resolve_round(match_id):
    match = active_matches.get(match_id)
    if match is None:
        return
    chat_id = match["chat_id"]
    a_sum, b_sum = sum(match["a_current"]), sum(match["b_current"])

    if a_sum == b_sum:
        bot.send_message(chat_id, f"Round tied ({a_sum} vs {b_sum})! Reroll this round — send your dice again.")
        match["a_current"], match["b_current"] = [], []
        prompt_reroll(match)
        if match["player_b"] is not None:
            schedule_afk_timers(match_id, match["current_round"], "a")
            schedule_afk_timers(match_id, match["current_round"], "b")
        return

    winner_side = decide_round_winner(a_sum, b_sum, match["mode"])
    match[f"{winner_side}_wins"] += 1
    winner_name = match["player_a_name"] if winner_side == "a" else match["player_b_name"]

    match["round_log"].append(
        f"Round {match['current_round']}: {match['player_a_name']} {match['a_current']} ({a_sum}) vs "
        f"{match['player_b_name']} {match['b_current']} ({b_sum}) — {winner_name} won"
    )
    bot.send_message(chat_id, match["round_log"][-1])

    needed = match["rounds"] // 2 + 1
    if match["a_wins"] >= needed or match["b_wins"] >= needed:
        finalize_match(match_id)
    else:
        match["current_round"] += 1
        match["a_current"], match["b_current"] = [], []
        prompt_reroll(match)
        if match["player_b"] is not None:
            schedule_afk_timers(match_id, match["current_round"], "a")
            schedule_afk_timers(match_id, match["current_round"], "b")


def prompt_reroll(match):
    chat_id = match["chat_id"]
    if match["player_b"] is None:
        bot.send_message(chat_id, f"{match['player_a_name']}, send your 🎲 dice for the next round!")
    else:
        bot.send_message(chat_id, f"{match['player_a_name']} and {match['player_b_name']}, send your 🎲 dice for the next round!")


def schedule_afk_timers(match_id, round_number, side):
    def warn():
        match = active_matches.get(match_id)
        if not match or match["current_round"] != round_number:
            return
        if len(match[f"{side}_current"]) >= match["dice_count"]:
            return
        name = match["player_a_name"] if side == "a" else match["player_b_name"]
        bot.send_message(match["chat_id"], f"⏰ {name}, you'll forfeit the match in 30 seconds if you don't roll!")

    def forfeit():
        match = active_matches.get(match_id)
        if not match or match["current_round"] != round_number:
            return
        if len(match[f"{side}_current"]) >= match["dice_count"]:
            return
        forfeit_player(match_id, side)

    threading.Timer(60, warn).start()
    threading.Timer(90, forfeit).start()


def forfeit_player(match_id, afk_side):
    match = active_matches.pop(match_id, None)
    if match is None:
        return
    chat_id = match["chat_id"]
    dice_waiters.pop((chat_id, match["player_a"]), None)
    if match["player_b"] is not None:
        dice_waiters.pop((chat_id, match["player_b"]), None)

    afk_name = match["player_a_name"] if afk_side == "a" else match["player_b_name"]
    afk_id = match["player_a"] if afk_side == "a" else match["player_b"]
    other_id = match["player_b"] if afk_side == "a" else match["player_a"]
    other_name = match["player_b_name"] if afk_side == "a" else match["player_a_name"]
    afk_bet = match["bet_a"] if afk_side == "a" else match["bet_b"]
    other_bet = match["bet_b"] if afk_side == "a" else match["bet_a"]

    half = round(afk_bet / 2, 2)
    to_house = round(afk_bet - half, 2)

    adjust_balance(other_id, other_bet + half)  # refund their own stake + half of the forfeiter's
    house = select("house", filters={"id": 1}, single=True)
    update("house", {"id": 1}, {"balance": float(house["balance"]) + to_house})

    record_bet(telegram_id=afk_id, game="dice_duel_pvp", bet_amount=afk_bet, payout=0, result="loss", meta={"forfeit": True})
    record_bet(telegram_id=other_id, game="dice_duel_pvp", bet_amount=other_bet, payout=other_bet + half, result="win", meta={"opponent_forfeited": True})

    bot.send_message(
        chat_id,
        f"⌛ {afk_name} didn't roll in time and forfeited.\n"
        f"{other_name} gets their {other_bet} coins back plus {half} coins.\n"
        f"{half} coins go to the house.",
    )


def finalize_match(match_id):
    match = active_matches.pop(match_id, None)
    if match is None:
        return
    dice_waiters.pop((match["chat_id"], match["player_a"]), None)
    if match["player_b"] is not None:
        dice_waiters.pop((match["chat_id"], match["player_b"]), None)

    winner_side = "a" if match["a_wins"] > match["b_wins"] else "b"
    summary = "\n".join(match["round_log"])

    if match["player_b"] is None:
        won = winner_side == "a"
        payout = payout_for_50_50(match["bet_a"]) if won else 0
        if won:
            adjust_balance(match["player_a"], payout)
        record_bet(
            telegram_id=match["player_a"], game="dice_duel_bot", bet_amount=match["bet_a"], payout=payout,
            result="win" if won else "loss", meta={"mode": match["mode"]},
        )
        outcome = (
            f"🏆 You won the duel! +{payout} coins.\nBalance: {get_balance(match['player_a'])}"
            if won else
            f"❌ You lost the duel. -{match['bet_a']} coins.\nBalance: {get_balance(match['player_a'])}"
        )
        bot.send_message(match["chat_id"], f"📋 Match Summary:\n{summary}\n\n{outcome}")
        return

    pot = match["bet_a"] + match["bet_b"]
    rake = round(pot * HOUSE_EDGE_RAKE, 2)
    winner_payout = round(pot - rake, 2)
    winner_id = match["player_a"] if winner_side == "a" else match["player_b"]
    winner_name = match["player_a_name"] if winner_side == "a" else match["player_b_name"]
    loser_name = match["player_b_name"] if winner_side == "a" else match["player_a_name"]
    loser_bet = match["bet_b"] if winner_side == "a" else match["bet_a"]

    adjust_balance(winner_id, winner_payout)
    record_bet(telegram_id=match["player_a"], game="dice_duel_pvp", bet_amount=match["bet_a"],
               payout=winner_payout if winner_side == "a" else 0, result="win" if winner_side == "a" else "loss",
               meta={"opponent": match["player_b_name"], "mode": match["mode"]})
    record_bet(telegram_id=match["player_b"], game="dice_duel_pvp", bet_amount=match["bet_b"],
               payout=winner_payout if winner_side == "b" else 0, result="win" if winner_side == "b" else "loss",
               meta={"opponent": match["player_a_name"], "mode": match["mode"]})

    house = select("house", filters={"id": 1}, single=True)
    update("house", {"id": 1}, {"balance": float(house["balance"]) + rake})

    bot.send_message(
        match["chat_id"],
        f"📋 Match Summary:\n{summary}\n\n"
        f"🏆 {winner_name} wins the duel!\n"
        f"{winner_name}: +{winner_payout} coins\n"
        f"{loser_name}: -{loser_bet} coins",
    )


def payout_for_50_50(bet_amount):
    from game_math import payout_for
    return payout_for(bet_amount, 0.5)


print(f"{CASINO_NAME} bot running...")
bot.infinity_polling()
