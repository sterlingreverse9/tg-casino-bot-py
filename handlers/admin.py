import time
import html
from bot_instance import bot
from db import select, update, get_all_groups, register_group, has_permission

# Auto-capture group interactions
@bot.message_handler(func=lambda m: m.chat.type in ["group", "supergroup"])
def track_group_chat(message):
    register_group(message.chat.id, message.chat.title)


def safe_send_broadcast(chat_id, text):
    """Attempt sending as HTML; fallback to raw text if HTML parsing fails."""
    try:
        bot.send_message(chat_id, text, parse_mode="HTML")
        return True
    except Exception as e:
        # If HTML tags caused a parse error, fallback to raw plain text
        try:
            bot.send_message(chat_id, text, parse_mode=None)
            return True
        except Exception as err:
            print(f"[Broadcast Fail for {chat_id}]: {err}")
            return False


@bot.message_handler(commands=["announce"])
def cmd_announce(message):
    telegram_id = message.from_user.id
    if not has_permission(telegram_id, "announce"):
        bot.reply_to(message, "❌ You do not have permission to send announcements.")
        return

    raw_text = message.text.partition(" ")[2].strip()
    if not raw_text:
        bot.reply_to(message, "Usage: <code>/announce <message></code>", parse_mode="HTML")
        return

    status_msg = bot.reply_to(message, "⏳ Sending announcement to all DMs and Groups...")

    # Escape raw text to convert < and > into safe HTML entities
    formatted_text = f"📢 <b>ANNOUNCEMENT</b>\n\n{raw_text}"

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

    # DM Broadcast Loop
    for uid in dm_targets:
        if safe_send_broadcast(uid, formatted_text):
            stats["dm_success"] += 1
        else:
            stats["dm_failed"] += 1
        time.sleep(0.04)

    # Group Broadcast Loop
    for gid in group_targets:
        if safe_send_broadcast(gid, formatted_text):
            stats["group_success"] += 1
        else:
            stats["group_failed"] += 1
            update("groups", {"chat_id": gid}, {"is_active": False})
        time.sleep(0.04)

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
