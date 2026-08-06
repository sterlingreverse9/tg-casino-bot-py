from bot_instance import bot
from db import insert, update
from wallet import get_or_create_user, adjust_balance, resolve_amount
from settings import (
    get_min_bet, set_min_bet,
    get_max_bet, set_max_bet,
    get_house_edge, set_house_edge
)
from helpers import get_target_user
from middleware.admin import is_admin, add_admin, remove_admin

# ---------- Balance Management ----------

@bot.message_handler(commands=["add"])
def cmd_add(message):
    if not is_admin(message.from_user.id):
        bot.reply_to(message, "You don't have permission to use this command.")
        return

    parts = message.text.split()

    if message.reply_to_message:
        if len(parts) < 2:
            bot.reply_to(message, "⚠️ Usage (reply): /add <amount>")
            return
        target_id = message.reply_to_message.from_user.id
        amount_str = parts[1]
    else:
        if len(parts) < 3:
            bot.reply_to(message, "⚠️ Usage:\n/add <@username|telegram_id> <amount>\nOr reply: /add <amount>")
            return
        target_id = get_target_user(message, parts[1])
        amount_str = parts[2]

    if not target_id:
        bot.reply_to(message, "❌ User not found.")
        return

    try:
        amount = float(amount_str)
        if amount <= 0:
            bot.reply_to(message, "❌ Amount must be positive.")
            return
    except ValueError:
        bot.reply_to(message, "❌ Amount must be a valid number.")
        return

    get_or_create_user(target_id, None)
    new_balance = adjust_balance(target_id, amount)
    insert("admin_actions", {"admin_id": message.from_user.id, "action": "add", "target_id": target_id, "amount": amount})
    bot.reply_to(message, f"✅ Added {amount} coins\nUser: <code>{target_id}</code>\nNew balance: {new_balance}", parse_mode="HTML")


@bot.message_handler(commands=["deduct"])
def cmd_deduct(message):
    if not is_admin(message.from_user.id):
        bot.reply_to(message, "You don't have permission to use this command.")
        return

    parts = message.text.split()

    if message.reply_to_message:
        if len(parts) < 2:
            bot.reply_to(message, "⚠️ Usage (reply): /deduct <amount|all>")
            return
        target_id = message.reply_to_message.from_user.id
        amount_arg = parts[1]
    else:
        if len(parts) < 3:
            bot.reply_to(message, "⚠️ Usage: /deduct <@username|telegram_id> <amount|all>")
            return
        target_id = get_target_user(message, parts[1])
        amount_arg = parts[2]

    if not target_id:
        bot.reply_to(message, "❌ User not found.")
        return

    amount = resolve_amount(target_id, amount_arg)
    if amount is None or amount <= 0:
        bot.reply_to(message, "❌ Amount must be a valid number or 'all'.")
        return

    new_balance = adjust_balance(target_id, -amount)
    insert("admin_actions", {"admin_id": message.from_user.id, "action": "deduct", "target_id": target_id, "amount": amount})
    bot.reply_to(message, f"✅ Deducted {amount} coins\nUser: <code>{target_id}</code>\nNew balance: {new_balance}", parse_mode="HTML")


# ---------- Admin: Promote / Demote ----------

@bot.message_handler(commands=["promote"])
def cmd_promote(message):
    if not is_admin(message.from_user.id):
        bot.reply_to(message, "You don't have permission to use this command.")
        return

    parts = message.text.split()
    if message.reply_to_message:
        target_id = message.reply_to_message.from_user.id
    elif len(parts) >= 2:
        target_id = get_target_user(message, parts[1])
    else:
        target_id = None

    if not target_id:
        bot.reply_to(message, "⚠️ Usage: /promote <@username|telegram_id> (or reply to their message)")
        return

    get_or_create_user(target_id, None)
    update("users", {"telegram_id": target_id}, {"is_admin": True})
    add_admin(target_id)
    insert("admin_actions", {"admin_id": message.from_user.id, "action": "promote", "target_id": target_id})
    bot.reply_to(message, f"👑 <code>{target_id}</code> is now an admin.", parse_mode="HTML")


@bot.message_handler(commands=["demote"])
def cmd_demote(message):
    if not is_admin(message.from_user.id):
        bot.reply_to(message, "You don't have permission to use this command.")
        return

    parts = message.text.split()
    if message.reply_to_message:
        target_id = message.reply_to_message.from_user.id
    elif len(parts) >= 2:
        target_id = get_target_user(message, parts[1])
    else:
        target_id = None

    if not target_id:
        bot.reply_to(message, "⚠️ Usage: /demote <@username|telegram_id> (or reply to their message)")
        return

    update("users", {"telegram_id": target_id}, {"is_admin": False})
    remove_admin(target_id)
    insert("admin_actions", {"admin_id": message.from_user.id, "action": "demote", "target_id": target_id})
    bot.reply_to(message, f"⬇️ <code>{target_id}</code> is no longer an admin.", parse_mode="HTML")


# ---------- House & Bet Configuration ----------

@bot.message_handler(commands=["updatehb"])
def cmd_updatehb(message):
    if not is_admin(message.from_user.id):
        bot.reply_to(message, "You don't have permission to use this command.")
        return

    parts = message.text.split()
    if len(parts) != 2:
        bot.reply_to(message, "Usage: /updatehb <amount>")
        return

    try:
        amount = float(parts[1])
    except ValueError:
        bot.reply_to(message, "❌ Invalid amount.")
        return

    update("house", {"id": 1}, {"balance": amount})
    insert("admin_actions", {"admin_id": message.from_user.id, "action": "updatehb", "amount": amount})
    bot.reply_to(message, f"🏦 House balance set to {amount}.")


@bot.message_handler(commands=["minbet"])
def cmd_minbet(message):
    if not is_admin(message.from_user.id):
        bot.reply_to(message, "You don't have permission to use this command.")
        return

    parts = message.text.split()
    if len(parts) != 2:
        bot.reply_to(message, "Usage: /minbet <amount>")
        return

    try:
        amt = float(parts[1])
    except ValueError:
        bot.reply_to(message, "Amount must be a number.")
        return

    set_min_bet(amt)
    bot.reply_to(message, f"✅ Minimum bet set to {amt} coins.")


@bot.message_handler(commands=["maxbet"])
def cmd_maxbet(message):
    if not is_admin(message.from_user.id):
        bot.reply_to(message, "You don't have permission to use this command.")
        return

    parts = message.text.split()
    if len(parts) != 2:
        bot.reply_to(message, "Usage: /maxbet <amount> or /maxbet <percent>%\nExample: /maxbet 100  or  /maxbet 5%")
        return

    raw = parts[1]
    try:
        float(raw.rstrip("%"))
    except ValueError:
        bot.reply_to(message, "Invalid value. Use a number or a percent like 5%.")
        return

    set_max_bet(raw)
    label = raw if raw.endswith("%") else f"{raw} coins"
    bot.reply_to(message, f"✅ Maximum bet set to {label}.")


@bot.message_handler(commands=["sethousedge"])
def cmd_sethousedge(message):
    if not is_admin(message.from_user.id):
        bot.reply_to(message, "You don't have permission to use this command.")
        return

    parts = message.text.split()
    if len(parts) != 2:
        bot.reply_to(message, "Usage: /sethousedge <value>\nExample: /sethousedge .10  (10% edge)")
        return

    try:
        val = float(parts[1])
    except ValueError:
        bot.reply_to(message, "Value must be a number, e.g. .10 for 10%.")
        return

    if val < 0 or val >= 1:
        bot.reply_to(message, "House edge must be between 0 and 1 (e.g. .10 = 10%).")
        return

    set_house_edge(val)
    bot.reply_to(message, f"✅ House edge set to {val} ({val * 100:.1f}%). Applies to all games immediately.")


# ---------- Reset Controls ----------

@bot.message_handler(commands=["resetld"])
def cmd_resetld(message):
    if not is_admin(message.from_user.id):
        bot.reply_to(message, "You don't have permission to use this command.")
        return

    update("users", {}, {"total_wagered": 0, "total_won": 0, "total_lost": 0})
    bot.reply_to(message, "🔄 Leaderboard/wager stats reset for everyone.")


@bot.message_handler(commands=["killbal"])
def cmd_killbal(message):
    if not is_admin(message.from_user.id):
        bot.reply_to(message, "You don't have permission to use this command.")
        return

    update("users", {}, {"balance": 0})
    bot.reply_to(message, "💀 Every user's balance has been reset to 0.")
