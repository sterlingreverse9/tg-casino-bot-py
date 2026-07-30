import telebot

from config import BOT_TOKEN, CASINO_NAME
from db import select, insert, update
from wallet import get_or_create_user, get_balance, adjust_balance, get_house_balance
from games.coinflip import play_coinflip
from games.dice import play_dice
from middleware.admin import is_admin

bot = telebot.TeleBot(BOT_TOKEN)


def ensure_user(message):
    get_or_create_user(message.from_user.id, message.from_user.username)


# ---------- Basic info commands ----------
@bot.message_handler(commands=["me", "profile" , "stats" , "mystats" ])
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
    bot.reply_to(
    message,
    f"💵 Balance: ₹{balance}\n"
    f"Min withdrawal: ₹70"
)


@bot.message_handler(commands=["depo","deposit" , "withdraw"])
def cmd_depo_withdraw(message):
    bot.reply_to(
        message,
        f"⚠️ Deposits and withdrawals are processed by @mrpuppyx , contact him to deposit and withdraw — {CASINO_NAME} runs on manual deposit and withdraw only.",
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

    target_id = None
    target_name = None

    # Reply mode
    if message.reply_to_message:
        if len(parts) != 2:
            bot.reply_to(message, "Usage (reply): /tip <amount|all>")
            return

        recipient = message.reply_to_message.from_user
        target_id = recipient.id
        target_name = recipient.username or recipient.first_name
        amount_arg = parts[1]

    # Username / ID mode
    else:
        if len(parts) != 3:
            bot.reply_to(
                message,
                "Usage:\n"
                "/tip @username <amount|all>\n"
                "/tip <telegram_id> <amount|all>\n"
                "Reply: /tip <amount|all>"
            )
            return

        target = parts[1]
        amount_arg = parts[2]

        if target.startswith("@"):
            user = select("users", filters={"username": target[1:]}, single=True)
            if not user:
                bot.reply_to(message, "User not found.")
                return

            target_id = int(user["telegram_id"])
            target_name = user["username"]

        else:
            try:
                target_id = int(target)
            except:
                bot.reply_to(message, "Invalid Telegram ID.")
                return

            user = select("users", filters={"telegram_id": target_id}, single=True)

            if not user:
                bot.reply_to(message, "User not found.")
                return

            target_name = user["username"] or str(target_id)

    if target_id == sender_id:
        bot.reply_to(message, "You can't tip yourself.")
        return

    get_or_create_user(target_id, target_name)

    balance = get_balance(sender_id)

    if amount_arg.lower() == "all":
        amount = balance
    else:
        try:
            amount = float(amount_arg)
        except:
            bot.reply_to(message, "Amount must be a number or 'all'.")
            return

    if amount <= 0:
        bot.reply_to(message, "Amount must be greater than 0.")
        return

    if amount > balance:
        bot.reply_to(message, f"You only have ₹{balance}.")
        return

    adjust_balance(sender_id, -amount)
    new_balance = adjust_balance(target_id, amount)

    bot.reply_to(
        message,
        f"💸 Tip Sent!\n\n"
        f"To: {target_name}\n"
        f"Amount: ₹{amount}\n"
        f"Their Balance: ₹{new_balance}"
    )
 
# ---------- Games ----------
@bot.message_handler(commands=["cf"])
def cmd_cf(message):
    ensure_user(message)
    parts = message.text.split()
    if len(parts) != 3 or parts[2] not in ("heads", "tails"):
        bot.reply_to(message, "Usage: /cf <amount> <heads|tails>")
        return
    try:
        bet_amount = float(parts[1])
    except ValueError:
        bot.reply_to(message, "Amount must be a number.")
        return
    play_coinflip(bot, message, message.from_user.id, bet_amount, parts[2])


@bot.message_handler(commands=["dice", "dr"])
def cmd_dice(message):
    ensure_user(message)
    parts = message.text.split()
    if len(parts) != 3:
        bot.reply_to(message, "Usage: /dice <amount> <target 2-98>")
        return
    try:
        bet_amount = float(parts[1])
        target = float(parts[2])
    except ValueError:
        bot.reply_to(message, "Amount and target must be numbers.")
        return
    play_dice(bot, message, message.from_user.id, bet_amount, target)
def get_target_user(message, target):
    # Reply method
    if message.reply_to_message:
        user = message.reply_to_message.from_user
        get_or_create_user(user.id, user.username)
        return user.id

    # Username method
    if target.startswith("@"):
        username = target[1:]
        user = select("users", filters={"username": username}, single=True)
        if user:
            return int(user["telegram_id"])
        return None

    # Telegram ID method
    try:
        return int(target)
    except:
        return None


# ---------- Admin ----------
@bot.message_handler(commands=["add"])
def cmd_add(message):
    if not is_admin(message.from_user.id):
        bot.reply_to(message, "You don't have permission to use this command.")
        return

    parts = message.text.split()

    try:
        # Reply mode
        if message.reply_to_message:
            if len(parts) != 2:
                bot.reply_to(message, "Usage (reply): /add <amount>")
                return

            target_id = message.reply_to_message.from_user.id
            amount = float(parts[1])

        # Username / ID mode
        else:
            if len(parts) != 3:
                bot.reply_to(message, "Usage:\n/add <@username> <amount>\n/add <telegram_id> <amount>\nReply: /add <amount>")
                return

            target_id = get_target_user(message, parts[1])

            if not target_id:
                bot.reply_to(message, "User not found.")
                return

            amount = float(parts[2])

        get_or_create_user(target_id, None)

        new_balance = adjust_balance(target_id, amount)

        insert("admin_actions", {
            "admin_id": message.from_user.id,
            "action": "add",
            "target_id": target_id,
            "amount": amount
        })

        bot.reply_to(
            message,
            f"✅ Added ₹{amount}\n"
            f"User ID: {target_id}\n"
            f"New Balance: ₹{new_balance}"
        )

    except:
        bot.reply_to(message, "Invalid command.")

@bot.message_handler(commands=["deduct"])
def cmd_deduct(message):
    if not is_admin(message.from_user.id):
        bot.reply_to(message, "❌ You don't have permission.")
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
            bot.reply_to(message, "Usage: /deduct <@user|telegram_id> <amount|all>")
            return

        target_id = get_target_user(message, parts[1])

        if not target_id:
            bot.reply_to(message, "❌ User not found.")
            return

        amount_arg = parts[2]

    if amount_arg.lower() == "all":
        amount = get_balance(target_id)
    else:
        amount = float(amount_arg)

    new_balance = adjust_balance(target_id, -amount)

    insert("admin_actions", {
        "admin_id": message.from_user.id,
        "action": "deduct",
        "target_id": target_id,
        "amount": amount
    })

    bot.reply_to(
        message,
        f"✅ Deducted ₹{amount}\n👤 User: {target_id}\n💰 Balance: ₹{new_balance}"
    )


@bot.message_handler(commands=["rain"])
def cmd_rain(message):
    if not is_admin(message.from_user.id):
        bot.reply_to(message, "You don't have permission to use this command.")
        return
    parts = message.text.split()
    if len(parts) != 2:
        bot.reply_to(message, "Usage: /rain <amount>")
        return
    amount = float(parts[1])
    users = select("users")
    for u in users:
        adjust_balance(u["telegram_id"], amount)
    insert("admin_actions", {"admin_id": message.from_user.id, "action": "rain", "amount": amount})
    bot.reply_to(message, f"🌧️ Rained {amount} coins to {len(users)} users.")


@bot.message_handler(commands=["promote"])
def cmd_promote(message):
    if not is_admin(message.from_user.id):
        bot.reply_to(message, "You don't have permission to use this command.")
        return
    parts = message.text.split()
    if len(parts) != 2:
        bot.reply_to(message, "Usage: /promote <telegram_id>")
        return
    target_id = int(parts[1])
    get_or_create_user(target_id, None)
    update("users", {"telegram_id": target_id}, {"is_admin": True})
    insert("admin_actions", {"admin_id": message.from_user.id, "action": "promote", "target_id": target_id})
    bot.reply_to(message, f"👑 {target_id} is now an admin.")


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


print(f"{CASINO_NAME} bot running...")
bot.infinity_polling()
