from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
from bot_instance import bot
from db import select, update
from wallet import adjust_balance
from helpers import ensure_user, has_promo_tag, is_member_of, PROMO_TAG
from datetime import datetime, timezone

WINS_CHANNEL_URL = "https://t.me/thecassinowins"
UPDATES_CHANNEL_URL = "https://t.me/thecassinoupdates"
CLAIM_COOLDOWN_HOURS = 12


def build_rakeback_text(user) -> str:
    balance = round(float(user.get("rakeback_balance", 0)), 2)
    return (
        "💸 Rakeback\n\n"
        "You get 0.5% of your losses back as rakeback, claimable every 12 hours.\n"
        f"Add {PROMO_TAG} to your Telegram name and join the channels below to bump that to 1%!\n\n"
        f"💰 Rakeback balance: ₹{balance} "
    )


def build_rakeback_keyboard(telegram_id: int):
    markup = InlineKeyboardMarkup(row_width=1)
    markup.add(InlineKeyboardButton("🏆 Join Wins Channel", url=WINS_CHANNEL_URL))
    markup.add(InlineKeyboardButton("📢 Join Updates Channel", url=UPDATES_CHANNEL_URL))
    markup.add(InlineKeyboardButton("💵 Claim Balance", callback_data=f"rbclaim:{telegram_id}"))
    return markup


@bot.message_handler(commands=["rakeback"])
def cmd_rakeback(message):
    ensure_user(message)
    user = select("users", filters={"telegram_id": message.from_user.id}, single=True)
    bot.reply_to(message, build_rakeback_text(user), reply_markup=build_rakeback_keyboard(message.from_user.id))


@bot.callback_query_handler(func=lambda call: call.data.startswith("rbclaim:"))
def handle_rakeback_claim(call):
    telegram_id = int(call.data.split(":")[1])
    if call.from_user.id != telegram_id:
        bot.answer_callback_query(call.id, "Not your rakeback panel.")
        return

    user = select("users", filters={"telegram_id": telegram_id}, single=True)
    if user is None:
        bot.answer_callback_query(call.id, "User not found.")
        return

    balance = round(float(user.get("rakeback_balance", 0)), 2)
    if balance <= 0:
        bot.answer_callback_query(call.id, "Nothing to claim yet — keep playing!", show_alert=True)
        return

    last_claim = user.get("last_rakeback_claim")
    if last_claim:
        last_dt = datetime.fromisoformat(last_claim.replace("Z", "+00:00"))
        elapsed_hours = (datetime.now(timezone.utc) - last_dt).total_seconds() / 3600
        if elapsed_hours < CLAIM_COOLDOWN_HOURS:
            remaining = round(CLAIM_COOLDOWN_HOURS - elapsed_hours, 1)
            bot.answer_callback_query(call.id, f"Cooldown active. Try again in {remaining}h.", show_alert=True)
            return

    has_tag = has_promo_tag(call.from_user)
    in_wins = is_member_of("@thecassinowins", telegram_id)
    in_updates = is_member_of("@thecassinoupdates", telegram_id)
    eligible_for_bonus = has_tag and in_wins and in_updates

    payout = round(balance * 2, 2) if eligible_for_bonus else balance
    rate_label = "1%" if eligible_for_bonus else "0.5%"

    update("users", {"telegram_id": telegram_id}, {
        "rakeback_balance": 0,
        "last_rakeback_claim": datetime.now(timezone.utc).isoformat(),
    })
    new_balance = adjust_balance(telegram_id, payout)

    bot.answer_callback_query(call.id, f"Claimed ₹{payout} ({rate_label})!")
    bot.send_message(call.message.chat.id, f"✅ Claimed ₹{payout} in rakeback ({rate_label} rate)!\nBalance: {new_balance}")
