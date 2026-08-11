import asyncio
import re
import threading
import time
from telebot.types import InlineKeyboardButton, InlineKeyboardMarkup

from bot_instance import bot
from db import select
from helpers import has_promo_tag
from state import MIN_WAGERED_FOR_RAIN, PROMO_TAG, active_rains
from wallet import adjust_balance, get_balance, get_or_create_user

# Temporary session state for user rain creation flows
USER_RAIN_FLOW = {}


def parse_time_input(time_str: str) -> int:
    """Parses time strings like '50s', '2m', '4h' into total seconds."""
    time_str = time_str.strip().lower()
    match = re.match(r"^(\d+)\s*([smh])?$", time_str)
    if not match:
        return None
    value, unit = match.groups()
    value = int(value)
    if unit == "s" or not unit:
        return value
    elif unit == "m":
        return value * 60
    elif unit == "h":
        return value * 3600
    return None


def format_remaining_time(seconds: int) -> str:
    """Formats remaining seconds into a human-readable display."""
    if seconds >= 3600:
        hrs = seconds // 3600
        mins = (seconds % 3600) // 60
        return f"{hrs}h {mins}m"
    elif seconds >= 60:
        mins = seconds // 60
        secs = seconds % 60
        return f"{mins}m {secs}s"
    return f"{seconds}s"


@bot.message_handler(commands=["rain"])
def cmd_rain(message):
    user_id = message.from_user.id
    get_or_create_user(user_id, message.from_user.username)

    # Initialize Rain Flow
    USER_RAIN_FLOW[user_id] = {"step": "AMOUNT", "chat_id": message.chat.id}

    bot.reply_to(
        message,
        "🌧️ <b>Rain Setup — Step 1/4</b>\n\n"
        "Enter the total amount of coins you want to rain:\n"
        "<i>Note: A 2.5% host fee will be added to this amount.</i>",
        parse_mode="HTML",
    )


@bot.message_handler(
    func=lambda m: m.from_user.id in USER_RAIN_FLOW and m.content_type == "text"
)
def process_rain_setup(message):
    user_id = message.from_user.id
    session = USER_RAIN_FLOW[user_id]
    step = session.get("step")

    # Step 1: Parse Amount
    if step == "AMOUNT":
        try:
            amount = float(message.text.strip())
            if amount <= 0:
                raise ValueError
        except ValueError:
            bot.reply_to(
                message, "❌ Invalid amount. Please enter a positive number."
            )
            return

        # Check total cost (Amount + 2.5% fee)
        total_cost = round(amount * 1.025, 2)
        user_bal = get_balance(user_id)

        if user_bal < total_cost:
            bot.reply_to(
                message,
                f"❌ Insufficient balance!\nRequired: <b>{total_cost}</b> (includes 2.5% fee)\nYour balance: <b>{user_bal:.2f}</b>",
                parse_mode="HTML",
            )
            del USER_RAIN_FLOW[user_id]
            return

        session["amount"] = amount
        session["total_cost"] = total_cost
        session["step"] = "DURATION"

        bot.reply_to(
            message,
            "🌧️ <b>Rain Setup — Step 2/4</b>\n\n"
            "Enter duration for the rain:\n"
            "• Examples: <code>50s</code> (seconds), <code>2m</code> (minutes), <code>4h</code> (hours)",
            parse_mode="HTML",
        )

    # Step 2: Parse Duration
    elif step == "DURATION":
        duration = parse_time_input(message.text)
        if not duration or duration < 10:
            bot.reply_to(
                message,
                "❌ Invalid time! Minimum duration is 10 seconds (e.g., 50s, 2m, 1h).",
            )
            return

        session["duration"] = duration
        session["step"] = "MIN_DEPOSIT"

        bot.reply_to(
            message,
            "🌧️ <b>Rain Setup — Step 3/4</b>\n\n"
            "Set minimum deposits required to join (e.g. <code>0</code>, <code>1</code>, <code>2</code>):",
            parse_mode="HTML",
        )

    # Step 3: Parse Minimum Deposits
    elif step == "MIN_DEPOSIT":
        try:
            min_dep = int(message.text.strip())
            if min_dep < 0:
                raise ValueError
        except ValueError:
            bot.reply_to(
                message, "❌ Enter a valid non-negative integer (e.g., 0, 1, 5)."
            )
            return

        session["min_deposit"] = min_dep
        session["step"] = "MIN_WAGER"

        bot.reply_to(
            message,
            "🌧️ <b>Rain Setup — Step 4/4</b>\n\n"
            "Set minimum total wagered required to join:\n"
            "Send <code>0</code> or <code>skip</code> if no wager requirement is needed.",
            parse_mode="HTML",
        )

    # Step 4: Parse Minimum Wager & Execute Rain
    elif step == "MIN_WAGER":
        text = message.text.strip().lower()
        if text in ["0", "skip"]:
            min_wager = 0.0
        else:
            try:
                min_wager = float(text)
                if min_wager < 0:
                    raise ValueError
            except ValueError:
                bot.reply_to(
                    message,
                    "❌ Invalid wager! Enter a valid number or send <code>skip</code>.",
                    parse_mode="HTML",
                )
                return

        session["min_wager"] = min_wager

        # Final Deduct check
        amount = session["amount"]
        total_cost = session["total_cost"]
        duration = session["duration"]
        min_dep = session["min_deposit"]
        chat_id = session["chat_id"]

        user_bal = get_balance(user_id)
        if user_bal < total_cost:
            bot.reply_to(
                message,
                "❌ Transaction failed. Balance changed during setup.",
            )
            del USER_RAIN_FLOW[user_id]
            return

        # Deduct coins from Host
        adjust_balance(user_id, -total_cost)
        del USER_RAIN_FLOW[user_id]

        # Send Rain Announcement Banner
        host_name = message.from_user.first_name or "Player"
        ends_at = time.time() + duration

        sent = bot.send_message(
            chat_id,
            build_rain_caption(
                host_name,
                amount,
                duration,
                min_dep,
                min_wager,
                0,
                ends_at - time.time(),
            ),
            parse_mode="HTML",
        )

        markup = InlineKeyboardMarkup()
        markup.add(
            InlineKeyboardButton(
                "🌧️ Join Rain", callback_data=f"rainjoin:{sent.message_id}"
            )
        )
        bot.edit_message_reply_markup(
            chat_id=sent.chat.id,
            message_id=sent.message_id,
            reply_markup=markup,
        )

        try:
            bot.pin_chat_message(sent.chat.id, sent.message_id)
        except Exception:
            pass

        # Register active rain object
        rain_data = {
            "host_id": user_id,
            "host_name": host_name,
            "amount": amount,
            "chat_id": sent.chat.id,
            "message_id": sent.message_id,
            "min_deposit": min_dep,
            "min_wager": min_wager,
            "ends_at": ends_at,
            "participants": {},  # {user_id: display_name}
            "is_ended": False,
        }
        active_rains[sent.message_id] = rain_data

        # Start live background updating thread
        threading.Thread(
            target=manage_rain_lifecycle, args=(rain_data,), daemon=True
        ).start()


def build_rain_caption(
    host_name, amount, duration, min_dep, min_wager, participant_cnt, rem_seconds
) -> str:
    rem_str = format_remaining_time(max(0, int(rem_seconds)))
    req_str = f"• Min Deposits: <b>{min_dep}</b>\n"
    if min_wager > 0:
        req_str += f"• Min Wager: <b>{min_wager}</b>\n"

    return (
        f"🌧️ <b>RAIN IN PROGRESS!</b> 🌧️\n\n"
        f"👤 <b>Host:</b> {host_name}\n"
        f"💰 <b>Pool Amount:</b> {amount} coins\n"
        f"⏳ <b>Ends In:</b> {rem_str}\n"
        f"👥 <b>Joined:</b> {participant_cnt} players\n\n"
        f"📋 <b>Requirements:</b>\n"
        f"{req_str}"
        f"<i>Tap the button below to join!</i>"
    )


def manage_rain_lifecycle(rain):
    """Background lifecycle thread that updates remaining time live and finishes rain."""
    msg_id = rain["message_id"]
    chat_id = rain["chat_id"]

    while time.time() < rain["ends_at"]:
        time.sleep(5)  # Live update interval
        rem_sec = rain["ends_at"] - time.time()
        if rem_sec <= 0:
            break

        try:
            updated_text = build_rain_caption(
                rain["host_name"],
                rain["amount"],
                int(rain["ends_at"] - time.time()),
                rain["min_deposit"],
                rain["min_wager"],
                len(rain["participants"]),
                rem_sec,
            )
            markup = InlineKeyboardMarkup()
            markup.add(
                InlineKeyboardButton(
                    "🌧️ Join Rain", callback_data=f"rainjoin:{msg_id}"
                )
            )
            bot.edit_message_text(
                updated_text,
                chat_id=chat_id,
                message_id=msg_id,
                parse_mode="HTML",
                reply_markup=markup,
            )
        except Exception:
            pass

    # Rain Timer Ended -> Execute Payout
    rain["is_ended"] = True
    active_rains.pop(msg_id, None)

    try:
        bot.unpin_chat_message(chat_id, msg_id)
    except Exception:
        pass

    participants = rain["participants"]  # dict of {uid: name}
    if not participants:
        bot.send_message(
            chat_id,
            f"🌧️ <b>Rain Ended</b>\n\nNobody joined the rain hosted by {rain['host_name']}. Coins refunded.",
            parse_mode="HTML",
        )
        adjust_balance(rain["host_id"], rain["amount"])
    else:
        share = round(rain["amount"] / len(participants), 2)
        winners_list = []

        for uid, name in participants.items():
            adjust_balance(uid, share)
            winners_list.append(f"• <b>{name}</b> ➔ +{share} coins")

        winners_formatted = "\n".join(winners_list)

        final_msg = (
            f"🎉 <b>RAIN ENDED!</b> 🎉\n\n"
            f"💰 <b>Total Pool:</b> {rain['amount']} coins\n"
            f"👥 <b>Total Winners:</b> {len(participants)}\n"
            f"💵 <b>Share Each:</b> {share} coins\n\n"
            f"📜 <b>Winners List:</b>\n"
            f"{winners_formatted}"
        )
        bot.send_message(chat_id, final_msg, parse_mode="HTML")


@bot.callback_query_handler(
    func=lambda call: call.data.startswith("rainjoin:")
)
def handle_rain_join(call):
    msg_id = int(call.data.split(":")[1])
    rain = active_rains.get(msg_id)

    if rain is None or rain.get("is_ended"):
        bot.answer_callback_query(
            call.id, "This rain has already ended.", show_alert=True
        )
        return

    user_id = call.from_user.id
    user_name = (
        f"@{call.from_user.username}"
        if call.from_user.username
        else call.from_user.first_name
    )
    get_or_create_user(user_id, call.from_user.username)

    if not has_promo_tag(call.from_user):
        bot.answer_callback_query(
            call.id,
            f"Add {PROMO_TAG} to your Telegram name to join rains!",
            show_alert=True,
        )
        return

    user = select("users", filters={"telegram_id": user_id}, single=True)
    if not user:
        bot.answer_callback_query(
            call.id, "User record not found.", show_alert=True
        )
        return

    # Check Deposit Requirement
    total_deposits = int(
        user.get("total_deposits", 0) or user.get("deposit_count", 0)
    )
    if total_deposits < rain["min_deposit"]:
        bot.answer_callback_query(
            call.id,
            f"❌ Requires at least {rain['min_deposit']} deposit(s) to join!",
            show_alert=True,
        )
        return

    # Check Wager Requirement
    total_wagered = float(user.get("total_wagered", 0))
    if rain["min_wager"] > 0 and total_wagered < rain["min_wager"]:
        bot.answer_callback_query(
            call.id,
            f"❌ Requires at least {rain['min_wager']} wagered to join!",
            show_alert=True,
        )
        return

    if user_id in rain["participants"]:
        bot.answer_callback_query(
            call.id, "You have already joined this rain!", show_alert=True
        )
        return

    rain["participants"][user_id] = user_name
    bot.answer_callback_query(
        call.id, "You successfully joined the rain! 🌧️"
    )
