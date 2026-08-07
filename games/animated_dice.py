import time
from wallet import get_balance, adjust_balance, record_bet, get_house_balance
from settings import get_min_bet, get_max_bet


def play_animated_game(bot, message, telegram_id: int, bet_amount: float, game_type: str, user_name: str = None):
    balance = get_balance(telegram_id)
    min_bet = get_min_bet()
    max_bet = get_max_bet(get_house_balance())

    if bet_amount < min_bet:
        bot.reply_to(message, f"⚠️ Minimum bet is ₹{min_bet:.2f}.")
        return
    if bet_amount > max_bet:
        bot.reply_to(message, f"⚠️ Maximum bet is ₹{round(max_bet, 2):.2f}.")
        return
    if bet_amount > balance:
        bot.reply_to(message, f"❌ Insufficient balance. Your balance: ₹{balance:.2f}")
        return

    adjust_balance(telegram_id, -bet_amount)

    emoji_map = {
        "football": "⚽",
        "basket": "🏀",
        "darts": "🎯",
        "slots": "🎰",
        "bowling": "🎳"
    }
    emoji = emoji_map.get(game_type, "⚽")

    sent_dice = bot.send_dice(message.chat.id, emoji=emoji)
    dice_value = sent_dice.dice.value

    won = False
    multiplier = 0.0

    if game_type == "football":
        if dice_value in (3, 4, 5):
            won = True
            multiplier = 1.8
    elif game_type == "basket":
        if dice_value in (4, 5):
            won = True
            multiplier = 1.9
    elif game_type == "darts":
        if dice_value == 6:
            won = True
            multiplier = 3.0
        elif dice_value == 5:
            won = True
            multiplier = 1.5
    elif game_type == "slots":
        if dice_value == 64:
            won = True
            multiplier = 10.0
        elif dice_value in (1, 22, 43):
            won = True
            multiplier = 2.0
    elif game_type == "bowling":
        if dice_value == 6:
            won = True
            multiplier = 3.0
        elif dice_value in (4, 5):
            won = True
            multiplier = 1.5

    payout = round(bet_amount * multiplier, 2) if won else 0.0
    if won:
        adjust_balance(telegram_id, payout)

    record_bet(
        telegram_id=telegram_id,
        game=game_type,
        bet_amount=bet_amount,
        payout=payout,
        result="win" if won else "loss",
        meta={"dice_value": dice_value, "multiplier": multiplier},
    )

    # Allow animation to complete on Telegram client UI
    time.sleep(3)

    new_balance = get_balance(telegram_id)
    if won:
        bot.reply_to(
            message,
            f"🎉 <b>WIN / HIT!</b>\n"
            f"Score: {dice_value} | Multiplier: {multiplier}×\n"
            f"Won: ₹{payout:.2f} | Balance: ₹{new_balance:.2f}",
            parse_mode="HTML"
        )
    else:
        bot.reply_to(
            message,
            f"❌ <b>MISSED!</b>\n"
            f"Lost: ₹{bet_amount:.2f} | Balance: ₹{new_balance:.2f}",
            parse_mode="HTML"
        )
