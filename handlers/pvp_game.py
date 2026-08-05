# handlers/pvp_game.py
import time
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
from bot_instance import bot
from wallet import get_balance, adjust_balance, resolve_amount
from helpers import ensure_user
from pvp_state import create_challenge, get_challenge, remove_challenge

# Emoji mapping for game types
GAME_EMOJIS = {
    "dice": "🎲",
    "dart": "🎯",
    "bowling": "🎳",
    "basket": "🏀"
}

@bot.message_handler(commands=["pvp", "duel"])
def cmd_pvp_challenge(message):
    ensure_user(message)
    sender_id = message.from_user.id
    parts = message.text.split()

    if len(parts) < 2:
        bot.reply_to(
            message,
            "⚠️ <b>Usage:</b> <code>/pvp <amount> [dice|dart|bowling|basket]</code>\n"
            "<i>Example: /pvp 50 dice</i>",
            parse_mode="HTML"
        )
        return

    amount_arg = parts[1]
    game_type = parts[2].lower() if len(parts) >= 3 else "dice"

    if game_type not in GAME_EMOJIS:
        bot.reply_to(message, "❌ Invalid game type! Use: <code>dice</code>, <code>dart</code>, <code>bowling</code>, or <code>basket</code>.", parse_mode="HTML")
        return

    amount = resolve_amount(sender_id, amount_arg)
    if amount is None or amount <= 0:
        bot.reply_to(message, "❌ Invalid bet amount.")
        return

    user_bal = get_balance(sender_id)
    if amount > user_bal:
        bot.reply_to(message, f"❌ Insufficient balance! You have ₹{user_bal:.2f}.")
        return

    # Lock challenger's balance
    adjust_balance(sender_id, -amount)

    challenge_id = create_challenge(sender_id, amount, game_type)
    emoji = GAME_EMOJIS[game_type]

    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton(f"⚔️ Accept Challenge (₹{amount:.2f})", callback_data=f"accept_pvp:{challenge_id}"))

    challenger_name = message.from_user.first_name or "Player"
    bot.reply_to(
        message,
        f"🎮 <b>PVP {game_type.upper()} DUEL CREATED!</b> {emoji}\n\n"
        f"👤 <b>Host:</b> {challenger_name}\n"
        f"💰 <b>Bet Amount:</b> ₹{amount:.2f}\n"
        f"🏆 <b>Winner Takes:</b> ₹{amount * 2:.2f}\n\n"
        f"<i>Click the button below to accept the duel!</i>",
        parse_mode="HTML",
        reply_markup=markup
    )


@bot.callback_query_handler(func=lambda call: call.data.startswith("accept_pvp:"))
def handle_accept_pvp(call):
    challenge_id = call.data.split(":")[1]
    challenge = get_challenge(challenge_id)

    if not challenge:
        bot.answer_callback_query(call.id, "❌ This challenge has expired or already ended.", show_alert=True)
        return

    acceptor_id = call.from_user.id
    challenger_id = challenge["challenger_id"]

    if acceptor_id == challenger_id:
        bot.answer_callback_query(call.id, "❌ You cannot accept your own challenge!", show_alert=True)
        return

    amount = challenge["amount"]
    game_type = challenge["game_type"]
    emoji = GAME_EMOJIS[game_type]

    # Verify acceptor balance
    acceptor_bal = get_balance(acceptor_id)
    if acceptor_bal < amount:
        bot.answer_callback_query(call.id, f"❌ You need at least ₹{amount:.2f} to accept!", show_alert=True)
        return

    # Deduct bet from acceptor & remove challenge from memory
    adjust_balance(acceptor_id, -amount)
    remove_challenge(challenge_id)

    bot.answer_callback_query(call.id, "⚔️ Challenge accepted! Rolling...")
    chat_id = call.message.chat.id

    # Edit message to reflect game in progress
    acceptor_name = call.from_user.first_name or "Opponent"
    bot.edit_message_text(
        f"⚔️ <b>DUEL IN PROGRESS!</b> {emoji}\n\n"
        f"Rolling for both players...",
        chat_id=chat_id,
        message_id=call.message.message_id,
        parse_mode="HTML"
    )

    # Roll 1: Challenger
    msg_1 = bot.send_dice(chat_id, emoji=emoji)
    score_1 = msg_1.dice.value
    time.sleep(3)

    # Roll 2: Acceptor
    msg_2 = bot.send_dice(chat_id, emoji=emoji)
    score_2 = msg_2.dice.value
    time.sleep(3)

    total_prize = amount * 2

    # Determine outcome
    if score_1 > score_2:
        adjust_balance(challenger_id, total_prize)
        winner_text = f"🏆 <b>Challenger Wins ₹{total_prize:.2f}!</b>"
    elif score_2 > score_1:
        adjust_balance(acceptor_id, total_prize)
        winner_text = f"🏆 <b>{acceptor_name} Wins ₹{total_prize:.2f}!</b>"
    else:
        # Refund on tie
        adjust_balance(challenger_id, amount)
        adjust_balance(acceptor_id, amount)
        winner_text = "🤝 <b>It's a TIE! Both bets refunded.</b>"

    bot.send_message(
        chat_id,
        f"🎯 <b>MATCH RESULTS</b> {emoji}\n\n"
        f"👤 Host Score: <b>{score_1}</b>\n"
        f"👤 Opponent Score: <b>{score_2}</b>\n\n"
        f"{winner_text}",
        parse_mode="HTML"
    )
