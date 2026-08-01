import threading
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
from bot_instance import bot
from db import select
from wallet import get_or_create_user, adjust_balance
from middleware.admin import is_admin
from state import active_rains, MIN_WAGERED_FOR_RAIN, PROMO_TAG
from helpers import has_promo_tag


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

    rain_timer = threading.Timer(seconds, finish_rain)
    active_rains[sent.message_id]["timer"] = rain_timer
    rain_timer.start()


@bot.callback_query_handler(func=lambda call: call.data.startswith("rainjoin:"))
def handle_rain_join(call):
    msg_id = int(call.data.split(":")[1])
    rain = active_rains.get(msg_id)
    if rain is None:
        bot.answer_callback_query(call.id, "This rain has ended.")
        return

    user_id = call.from_user.id
    get_or_create_user(user_id, call.from_user.username)

    if not has_promo_tag(call.from_user):
        bot.answer_callback_query(call.id, f"Add {PROMO_TAG} to your Telegram name to join rains!", show_alert=True)
        return

    user = select("users", filters={"telegram_id": user_id}, single=True)

    if float(user.get("total_wagered", 0)) < MIN_WAGERED_FOR_RAIN:
        bot.answer_callback_query(call.id, f"You need at least {MIN_WAGERED_FOR_RAIN} total wagered to join.")
        return
    if user_id in rain["participants"]:
        bot.answer_callback_query(call.id, "You already joined!")
        return

    rain["participants"].add(user_id)
    bot.answer_callback_query(call.id, "You joined the rain! 🌧️")


@bot.message_handler(commands=["cancelrain"])
def cmd_cancelrain(message):
    if not is_admin(message.from_user.id):
        bot.reply_to(message, "You don't have permission to use this command.")
        return
    cancelled = 0
    for msg_id, rain in list(active_rains.items()):
        if rain["chat_id"] == message.chat.id:
            rain["timer"].cancel()
            active_rains.pop(msg_id, None)
            try:
                bot.unpin_chat_message(rain["chat_id"], msg_id)
            except Exception:
                pass
            cancelled += 1
    if cancelled:
        bot.reply_to(message, f"🚫 Cancelled {cancelled} ongoing rain(s). No coins were distributed.")
    else:
        bot.reply_to(message, "No ongoing rain in this chat.")

