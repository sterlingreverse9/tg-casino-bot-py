import threading
import time
import uuid
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton

from config import BOT_TOKEN, CASINO_NAME
from db import select, insert, update
from wallet import get_or_create_user, get_balance, adjust_balance, get_house_balance, resolve_amount
from game_status import is_game_enabled, set_game_enabled
from games.coinflip import play_coinflip
from games.dice_roll import play_dice_roll, ALL_CHOICES
from games.dice_duel import parse_dice_code, play_match, play_vs_bot, format_match_log, MIN_BET as DUEL_MIN_BET
from middleware.admin import is_admin

bot = telebot.TeleBot(BOT_TOKEN)
active_rains = {}  # message_id -> {"amount", "chat_id", "participants": set()}
pending_duels = {}  # match_id -> duel state dict
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


@bot.message_handler(commands=["wallet" , "bal" , "balance" ])
def cmd_wallet(message):
    ensure_user(message)
    balance = get_balance(message.from_user.id)
    bot.reply_to(message, f"💰 Your balance: ₹{balance} \nMinimum Withdrawal : ₹70")


@bot.message_handler(commands=["depo", "withdraw" , "deposit" ])
def cmd_depo_withdraw(message):
    bot.reply_to(
        message,
        f"⚠️ Deposits and withdrawals are processed by @mrpuppyx , Pls contact him for deposit and withdraw — {CASINO_NAME} runs on manual deposit and withdraw no automatic system right now.",
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


@bot.message_handler(commands=["housebal", "house" , "hb" ])
def cmd_housebal(message):
    bal = get_house_balance()
    bot.reply_to(message, f"🏦 {CASINO_NAME} house balance: ₹{bal} ")


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
@bot.message_handler(commands=["cf" , "coinflip" ])
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
    bot.reply_to(message, f"✅ Added {amount} ruppess\nUser: {target_id}\nNew balance: {new_balance}")


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
    bot.reply_to(message, f"✅ Deducted {amount} rupees\nUser: {target_id}\nBalance: {new_balance}")


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
    bot.reply_to(message, f"🏦 House balance set to ₹{amount}.")


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
                f"🌧️ Rain of {rain['amount']} coins ended!\n{share} ruppess each to {len(participants)} users. 🎉",
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


# ---------- Dice Duel (vs bot or vs player) ----------
def parse_dice_command(text: str):
    """Returns (amount_str, code, opponent_username) from the raw command text, any order."""
    tokens = text.split()[1:]
    amount_str, code, opponent_username = None, "1d1w", None
    for tok in tokens:
        if tok.startswith("@"):
            opponent_username = tok[1:]
        elif parse_dice_code(tok.lower()):
            code = tok.lower()
        elif amount_str is None:
            amount_str = tok
    return amount_str, code, opponent_username


def build_mode_keyboard(match_id: str):
    markup = InlineKeyboardMarkup()
    markup.row(
        InlineKeyboardButton("Normal (highest sum wins)", callback_data=f"dmode:{match_id}:normal"),
        InlineKeyboardButton("Crazy (lowest sum wins)", callback_data=f"dmode:{match_id}:crazy"),
    )
    return markup


@bot.message_handler(commands=["dice"])
def cmd_dice(message):
    ensure_user(message)
    if not is_game_enabled("dice"):
        bot.reply_to(message, "Dice Duel is currently disabled.")
        return

    amount_str, code, opponent_username = parse_dice_command(message.text)
    if amount_str is None:
        bot.reply_to(message, "Usage: /dice <amount|all|half> [<dice>d<rounds>w] [@opponent]\nExample: /dice 10 3d1w  or  /dice half @user 2d1w")
        return

    parsed = parse_dice_code(code)
    if parsed is None:
        bot.reply_to(message, "Invalid dice code. Format is <dice>d<rounds>w, e.g. 3d1w (max 5 dice, 9 rounds).")
        return
    dice_count, rounds = parsed

    opponent_id = None
    if opponent_username:
        opponent = select("users", filters={"username": opponent_username}, single=True)
        if not opponent:
            bot.reply_to(message, f"@{opponent_username} needs to message this bot at least once (e.g. /me) before they can be challenged.")
            return
        opponent_id = int(opponent["telegram_id"])
        if opponent_id == message.from_user.id:
            bot.reply_to(message, "You can't challenge yourself.")
            return

    match_id = uuid.uuid4().hex[:10]
    pending_duels[match_id] = {
        "initiator_id": message.from_user.id,
        "initiator_name": message.from_user.username or message.from_user.first_name,
        "amount_str": amount_str,
        "dice_count": dice_count,
        "rounds": rounds,
        "opponent_id": opponent_id,
        "opponent_username": opponent_username,
        "chat_id": message.chat.id,
        "mode": None,
        "status": "choosing_mode",
    }

    bot.reply_to(message, "🎲 Choose your game mode:", reply_markup=build_mode_keyboard(match_id))
@bot.callback_query_handler(func=lambda call: call.data.startswith("dmode:"))
def handle_dice_mode(call):
    _, match_id, mode = call.data.split(":")
    duel = pending_duels.get(match_id)
    if duel is None:
        bot.answer_callback_query(call.id, "This challenge has expired.")
        return
    if call.from_user.id != duel["initiator_id"]:
        bot.answer_callback_query(call.id, "This isn't your game.")
        return

    bot.answer_callback_query(call.id)
    duel["mode"] = mode

    if duel["opponent_id"] is None:
        # vs bot: resolve amount and play immediately
        amount = resolve_amount(duel["initiator_id"], duel["amount_str"])
        if amount is None:
            bot.send_message(duel["chat_id"], "Amount must be a number, 'all', or 'half'.")
            pending_duels.pop(match_id, None)
            return
        pending_duels.pop(match_id, None)
        play_vs_bot(bot, duel["chat_id"], duel["initiator_id"], amount, duel["dice_count"], duel["rounds"], mode)
        return

    # vs player: send challenge with accept/decline, 120s expiry
    duel["status"] = "awaiting_accept"
    markup = InlineKeyboardMarkup()
    markup.row(
        InlineKeyboardButton("✅ Accept", callback_data=f"daccept:{match_id}"),
        InlineKeyboardButton("❌ Decline", callback_data=f"ddecline:{match_id}"),
    )
    bot.send_message(
        duel["chat_id"],
        f"⚔️ {duel['initiator_name']} challenges @{duel['opponent_username']} to a Dice Duel!\n"
        f"{duel['dice_count']} dice, {duel['rounds']} round(s), {mode} mode, bet: {duel['amount_str']} coins each.\n"
        f"@{duel['opponent_username']} has 120 seconds to accept.",
        reply_markup=markup,
    )

    def expire_duel():
        d = pending_duels.get(match_id)
        if d and d["status"] == "awaiting_accept":
            pending_duels.pop(match_id, None)
            bot.send_message(d["chat_id"], f"⌛ The challenge to @{d['opponent_username']} expired.")

    threading.Timer(120, expire_duel).start()


@bot.callback_query_handler(func=lambda call: call.data.startswith("daccept:") or call.data.startswith("ddecline:"))
def handle_dice_response(call):
    action, match_id = call.data.split(":")
    duel = pending_duels.get(match_id)
    if duel is None or duel["status"] != "awaiting_accept":
        bot.answer_callback_query(call.id, "This challenge is no longer active.")
        return
    if call.from_user.id != duel["opponent_id"]:
        bot.answer_callback_query(call.id, "This challenge isn't for you.")
        return

    if action == "ddecline":
        pending_duels.pop(match_id, None)
        bot.answer_callback_query(call.id, "Challenge declined.")
        bot.send_message(duel["chat_id"], f"❌ @{duel['opponent_username']} declined the challenge.")
        return

    bot.answer_callback_query(call.id)
    pending_duels.pop(match_id, None)

    initiator_id, opponent_id = duel["initiator_id"], duel["opponent_id"]
    initiator_amount = resolve_amount(initiator_id, duel["amount_str"])
    opponent_amount = resolve_amount(opponent_id, duel["amount_str"])

    if initiator_amount is None or opponent_amount is None:
        bot.send_message(duel["chat_id"], "Amount must be a number, 'all', or 'half'.")
        return
    if initiator_amount < DUEL_MIN_BET or opponent_amount < DUEL_MIN_BET:
        bot.send_message(duel["chat_id"], f"Minimum bet is {DUEL_MIN_BET} coins for both players.")
        return
    if initiator_amount > get_balance(initiator_id):
        bot.send_message(duel["chat_id"], f"{duel['initiator_name']} doesn't have enough balance anymore.")
        return
    if opponent_amount > get_balance(opponent_id):
        bot.send_message(duel["chat_id"], f"@{duel['opponent_username']} doesn't have enough balance anymore.")
        return

    adjust_balance(initiator_id, -initiator_amount)
    adjust_balance(opponent_id, -opponent_amount)

    winner, round_log = play_match(duel["dice_count"], duel["rounds"], duel["mode"])
    pot = initiator_amount + opponent_amount
    rake = round(pot * HOUSE_EDGE_RAKE, 2)
    winner_payout = round(pot - rake, 2)

    winner_id = initiator_id if winner == "a" else opponent_id
    loser_id = opponent_id if winner == "a" else initiator_id
    winner_name = duel["initiator_name"] if winner == "a" else duel["opponent_username"]

    adjust_balance(winner_id, winner_payout)

    record_bet(telegram_id=initiator_id, game="dice_duel_pvp", bet_amount=initiator_amount,
               payout=winner_payout if winner == "a" else 0, result="win" if winner == "a" else "loss",
               meta={"opponent": duel["opponent_username"], "mode": duel["mode"]})
    record_bet(telegram_id=opponent_id, game="dice_duel_pvp", bet_amount=opponent_amount,
               payout=winner_payout if winner == "b" else 0, result="win" if winner == "b" else "loss",
               meta={"opponent": duel["initiator_name"], "mode": duel["mode"]})

    house = select("house", filters={"id": 1}, single=True)
    update("house", {"id": 1}, {"balance": float(house["balance"]) + rake})

    text = (
        f"⚔️ Dice Duel • {duel['mode']} mode\n"
        + format_match_log(round_log, duel["initiator_name"], duel["opponent_username"])
        + f"\n\n🏆 {winner_name} wins {winner_payout} rupees!"
    )
    bot.send_message(duel["chat_id"], text)


print(f"{CASINO_NAME} bot running...")
bot.infinity_polling()