from bot_instance import bot
from db import select
from middleware.admin import is_admin
from chats import get_all_chats


@bot.message_handler(commands=["announce"])
def cmd_announce(message):
    if not is_admin(message.from_user.id, message.from_user.username):
        bot.reply_to(message, "You don't have permission to use this command.")
        return

    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        bot.reply_to(message, "⚠️ <b>Usage:</b> <code>/announce &lt;message&gt;</code>", parse_mode="HTML")
        return

    text = parts[1]
    bot.reply_to(message, "🔄 Sending announcement...")

    dm_sent = dm_failed = 0
    group_sent = group_failed = 0
    channel_sent = channel_failed = 0

    # 1. Send to all registered users (DM)
    for u in select("users"):
        uid = int(u["telegram_id"])
        uname = u.get("username")
        greeting = f"Hey @{uname}, " if uname else ""
        try:
            bot.send_message(uid, f"📢 {greeting}{text}")
            dm_sent += 1
        except Exception:
            dm_failed += 1

    # 2. Fetch all channels/groups
    try:
        chats = get_all_chats()
    except Exception as e:
        print(f"[ANNOUNCE] Failed to fetch chats list: {e}")
        chats = []

    # 3. Send to channels & groups
    for c in chats:
        cid = int(c["chat_id"])
        is_channel = c.get("chat_type") == "channel"
        try:
            sent = bot.send_message(cid, f"📢 Announcement:\n{text}")
            try:
                bot.pin_chat_message(cid, sent.message_id)
            except Exception:
                pass
            if is_channel:
                channel_sent += 1
            else:
                group_sent += 1
        except Exception:
            if is_channel:
                channel_failed += 1
            else:
                group_failed += 1

    report = (
        "📊 <b>Announcement Report</b>\n\n"
        f"📢 Channels Sent: {channel_sent} (Failed: {channel_failed})\n"
        f"👥 Groups Sent: {group_sent} (Failed: {group_failed})\n"
        f"💬 DMs Sent: {dm_sent} (Failed: {dm_failed})"
    )
    bot.reply_to(message, report, parse_mode="HTML")


@bot.message_handler(commands=["msg"])
def cmd_msg(message):
    if not is_admin(message.from_user.id, message.from_user.username):
        bot.reply_to(message, "You don't have permission to use this command.")
        return

    parts = message.text.split(maxsplit=2)
    if len(parts) < 3:
        bot.reply_to(message, "⚠️ <b>Usage:</b> <code>/msg &lt;username&gt; &lt;message&gt;</code>", parse_mode="HTML")
        return

    username = parts[1].lstrip("@")
    text = parts[2]
    target = select("users", filters={"username": username}, single=True)
    if target is None:
        bot.reply_to(message, "❌ User not found in database.")
        return

    target_id = int(target["telegram_id"])
    dm_ok = True
    bot.reply_to(message, f"🔄 Sending message to @{username}...")

    # Send Direct Message
    try:
        bot.send_message(target_id, f"📩 <b>Message from Admin:</b>\n{text}", parse_mode="HTML")
    except Exception:
        dm_ok = False

    # Tag user in shared groups
    group_count = 0
    try:
        chats = get_all_chats()
    except Exception as e:
        print(f"[MSG] Failed to fetch chats: {e}")
        chats = []

    for c in chats:
        if c.get("chat_type") == "channel":
            continue
        cid = int(c["chat_id"])
        try:
            member = bot.get_chat_member(cid, target_id)
            if member.status in ("member", "administrator", "creator"):
                bot.send_message(cid, f"@{username} {text}")
                group_count += 1
        except Exception:
            continue

    status_str = "sent" if dm_ok else "failed"
    bot.reply_to(
        message,
        f"✅ DM to @{username}: <b>{status_str}</b>\n👥 Shared groups notified: <b>{group_count}</b>",
        parse_mode="HTML"
    )
