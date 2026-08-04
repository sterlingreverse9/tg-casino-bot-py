import time
from bot_instance import bot
from db import select, update, get_all_groups, register_group, has_permission

# Auto-capture any group chat interaction to keep database updated
@bot.message_handler(func=lambda m: m.chat.type in ["group", "supergroup"])
def track_group_chat(message):
    register_group(message.chat.id, message.chat.title)


@bot.message_handler(commands=["announce"])
def cmd_announce(message):
    telegram_id = message.from_user.id
    if not has_permission(telegram_id, "announce"):
        bot.reply_to(message, "❌ You do not have permission to send announcements.")
        return

    text = message.text.partition(" ")[2].strip()
    if not text:
        bot.reply_to(message, "Usage: <code>/announce <message></code>", parse_mode="HTML")
        return

    status_msg = bot.reply_to(message, "⏳ Sending announcement to all DMs and Groups...")

    # Fetch targets
    users = select("users") or []
    groups = get_all_groups()

    dm_targets = [u["telegram_id"] for u in users if u.get("telegram_id")]
    group_targets = [g["chat_id"] for g in groups if g.get("chat_id")]

    stats = {
        "total_attempted": len(dm_targets) + len(group_targets),
        "dm_success": 0,
        "dm_failed": 0,
        "group_success": 0,
        "group_failed": 0,
    }

    # Broadcast to DMs
    for uid in dm_targets:
        try:
            bot.send_message(uid, f"📢 <b>ANNOUNCEMENT</b>\n\n{text}", parse_mode="HTML")
            stats["dm_success"] += 1
            time.sleep(0.05)
        except Exception:
            stats["dm_failed"] += 1

    # Broadcast to Groups
    for gid in group_targets:
        try:
            bot.send_message(gid, f"📢 <b>ANNOUNCEMENT</b>\n\n{text}", parse_mode="HTML")
            stats["group_success"] += 1
            time.sleep(0.05)
        except Exception:
            stats["group_failed"] += 1
            # Mark inactive if bot was kicked
            update("groups", {"chat_id": gid}, {"is_active": False})

    # Detailed Summary
    summary = (
        "📊 <b>ANNOUNCEMENT REPORT</b>\n"
        "────────────────────────\n"
        f"🎯 <b>Total Targets:</b> {stats['total_attempted']}\n\n"
        f"👤 <b>DMs Sent:</b> {stats['dm_success']} ✅ | Failed: {stats['dm_failed']} ❌\n"
        f"👥 <b>Groups Sent:</b> {stats['group_success']} ✅ | Failed: {stats['group_failed']} ❌\n"
        "────────────────────────\n"
        "✅ <i>Broadcast completed!</i>"
    )
    bot.edit_message_text(summary, status_msg.chat.id, status_msg.message_id, parse_mode="HTML")


@bot.message_handler(commands=["msg"])
def cmd_msg(message):
    telegram_id = message.from_user.id
    if not has_permission(telegram_id, "msg"):
        bot.reply_to(message, "❌ You do not have permission to use /msg.")
        return

    text = message.text.partition(" ")[2].strip()
    if not text:
        bot.reply_to(message, "Usage: <code>/msg <message></code>", parse_mode="HTML")
        return

    status_msg = bot.reply_to(message, "⏳ Dispatching message across DMs and Groups...")

    users = select("users") or []
    groups = get_all_groups()

    dm_targets = [u["telegram_id"] for u in users if u.get("telegram_id")]
    group_targets = [g["chat_id"] for g in groups if g.get("chat_id")]

    stats = {
        "total_attempted": len(dm_targets) + len(group_targets),
        "dm_success": 0,
        "dm_failed": 0,
        "group_success": 0,
        "group_failed": 0,
    }

    # Send to DMs
    for uid in dm_targets:
        try:
            bot.send_message(uid, text, parse_mode="HTML")
            stats["dm_success"] += 1
            time.sleep(0.05)
        except Exception:
            stats["dm_failed"] += 1

    # Send to Groups
    for gid in group_targets:
        try:
            bot.send_message(gid, text, parse_mode="HTML")
            stats["group_success"] += 1
            time.sleep(0.05)
        except Exception:
            stats["group_failed"] += 1
            update("groups", {"chat_id": gid}, {"is_active": False})

    # Summary Output
    summary = (
        "📊 <b>BROADCAST REPORT (/msg)</b>\n"
        "────────────────────────\n"
        f"🎯 <b>Total Targets:</b> {stats['total_attempted']}\n\n"
        f"👤 <b>DMs Delivered:</b> {stats['dm_success']} ✅ | Failed: {stats['dm_failed']} ❌\n"
        f"👥 <b>Groups Delivered:</b> {stats['group_success']} ✅ | Failed: {stats['group_failed']} ❌\n"
        "────────────────────────\n"
        "✅ <i>Broadcast completed!</i>"
    )
    bot.edit_message_text(summary, status_msg.chat.id, status_msg.message_id, parse_mode="HTML")
