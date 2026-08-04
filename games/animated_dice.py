import time
from wallet import get_balance, adjust_balance, record_bet, get_house_balance
from settings import get_min_bet, get_max_bet


def play_animated_game(bot, message, telegram_id: int, bet_amount: float, game_type: str, user_name: str = None):
    balance = get_balance(telegram_id)
    min_bet = get_min_bet()
    max_bet = get_max_bet(get_house_balance())

    if bet_amount < min_bet:
        bot.reply_to(message, f"Minimum bet is ₹{min_bet}.")
        return
    if bet_amount > max_bet:
        bot.reply_to(message, f"Maximum bet is ₹{round(max_bet, 2)}.")
        return
    if bet_amount > balance:
        bot.reply_to(message, f"Not enough balance. Your balance: ₹{balance:.2f}")
        return

    # Deduct bet upfront
    adjust_balance(telegram_id, -bet_amount)

    emoji_map = {
        "football": "⚽",
        "basket": "🏀",
        "darts": "🎯",
        "slots": "🎰"
    }
    emoji = emoji_map.get(game_type, "⚽")

    # Send the interactive animated emoji and capture the roll value
    sent_dice = bot.send_dice(message.chat.id, emoji=emoji)
    dice_value = sent_dice.dice.value

    # Evaluate win conditions based on Telegram dice outcome values
    won = False
    multiplier = 0.0

    if game_type == "football":
        # Telegram football dice: values 3, 4, 5 are goals
        if dice_value in (3, 4, 5):
            won = True
            multiplier = 1.8
    elif game_type == "basket":
        # Telegram basketball dice: values 4, 5 are shots made
        if dice_value in (4, 5):
            won = True
            multiplier = 1.9
    elif game_type == "darts":
        # Telegram darts: 6 is bullseye (3x), 5 is inner ring (1.5x)
        if dice_value == 6:
            won = True
            multiplier = 3.0
        elif dice_value == 5:
            won = True
            multiplier = 1.5
    elif game_type == "slots":
        # Telegram slots: 64 is triple 7s (777)
        if dice_value == 64:
            won = True
            multiplier = 10.0
        elif dice_value in (1, 22, 43):  # 2 matching symbols
            won = True
            multiplier = 2.0

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

    # Wait for animation to complete on client screen before sending outcome
    time.sleep(3)

    new_balance = get_balance(telegram_id)
    if won:
        bot.reply_to(
            message,
            f"🎉 <b>GOAL / HIT!</b>\n"
            f"Result: {dice_value} | Multiplier: {multiplier}×\n"
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
