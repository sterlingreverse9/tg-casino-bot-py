from bot_instance import bot
from db import select
from middleware.admin import is_admin
from chats import get_all_chats


@bot.message_handler(commands=["announce"])
def cmd_announce(message):
    if not is_admin(message.from_user.id):
        bot.reply_to(message, "You don't have permission to use this command.")
        return
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        bot.reply_to(message, "Usage: /announce <message>")
        return
    text = parts[1]

    dm_sent = dm_failed = 0
    group_sent = group_failed = 0
    channel_sent = channel_failed = 0

    for u in select("users"):
        uid = int(u["telegram_id"])
        uname = u.get("username")
        greeting = f"Hey @{uname}, " if uname else ""
        try:
            bot.send_message(uid, f"📢 {greeting}{text}")
            dm_sent += 1
        except Exception:
            dm_failed += 1

    for c in get_all_chats():
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
        "📊 Announcement Report\n\n"
        f"Total channels sent: {channel_sent}\n"
        f"Failed to send channel: {channel_failed}\n"
        f"Total group send: {group_sent}\n"
        f"Failed to send group: {group_failed}\n"
        f"Total dm send: {dm_sent}\n"
        f"Failed to send dm: {dm_failed}"
    )
    bot.reply_to(message, report)


@bot.message_handler(commands=["msg"])
def cmd_msg(message):
    if not is_admin(message.from_user.id):
        bot.reply_to(message, "You don't have permission to use this command.")
        return
    parts = message.text.split(maxsplit=2)
    if len(parts) < 3:
        bot.reply_to(message, "Usage: /msg <username> <message>")
        return

    username = parts[1].lstrip("@")
    text = parts[2]
    target = select("users", filters={"username": username}, single=True)
    if target is None:
        bot.reply_to(message, "User not found.")
        return
    target_id = int(target["telegram_id"])

    dm_ok = True
    try:
        bot.send_message(target_id, f"📩 Message from admin:\n{text}")
    except Exception:
        dm_ok = False

    group_count = 0
    for c in get_all_chats():
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

    bot.reply_to(message, f"✅ Sent to @{username}'s DM ({'ok' if dm_ok else 'failed'}) and {group_count} shared group(s).")
