from wallet import get_balance, adjust_balance, record_bet, get_house_balance
from game_math import payout_for
from settings import get_min_bet, get_max_bet
from helpers import announce_win

EVEN_MONEY_CHOICES = {
    "high": {4, 5, 6},
    "low": {1, 2, 3},
    "even": {2, 4, 6},
    "odd": {1, 3, 5},
}
NUMBER_CHOICES = {"1", "2", "3", "4", "5", "6"}
ALL_CHOICES = set(EVEN_MONEY_CHOICES.keys()) | NUMBER_CHOICES

LABELS = {
    "high": "High (4-6)",
    "low": "Low (1-3)",
    "even": "Even",
    "odd": "Odd",
}


def play_dice_roll(bot, chat_id, telegram_id: int, bet_amount: float, choice: str, display_name: str = None):
    choice = str(choice).lower().strip()
    if choice not in ALL_CHOICES:
        bot.send_message(chat_id, "⚠️ Invalid choice. Use high, low, even, odd, or a number 1-6.")
        return

    balance = get_balance(telegram_id)
    min_bet = get_min_bet()
    max_bet = get_max_bet(get_house_balance())

    if bet_amount < min_bet:
        bot.send_message(chat_id, f"⚠️ Minimum bet is ₹{min_bet:.2f}.")
        return
    if bet_amount > max_bet:
        bot.send_message(chat_id, f"⚠️ Maximum bet is ₹{round(max_bet, 2):.2f}.")
        return
    if bet_amount > balance:
        bot.send_message(chat_id, f"❌ Insufficient balance! Your balance: ₹{balance:.2f}")
        return

    adjust_balance(telegram_id, -bet_amount)

    dice_message = bot.send_dice(chat_id, emoji="🎲")
    roll = int(dice_message.dice.value)

    won = False
    if choice in EVEN_MONEY_CHOICES:
        won = roll in EVEN_MONEY_CHOICES[choice]
        win_chance = 0.5
        label = LABELS[choice]
    else:
        won = (roll == int(choice))
        win_chance = 1 / 6
        label = f"Number {choice}"

    payout = payout_for(bet_amount, win_chance) if won else 0.0
    if won:
        adjust_balance(telegram_id, payout)

    record_bet(
        telegram_id=telegram_id,
        game="dice_roll",
        bet_amount=bet_amount,
        payout=payout,
        result="win" if won else "loss",
        meta={"choice": choice, "roll": roll},
    )

    new_balance = get_balance(telegram_id)
    user_label = display_name or f"ID: {telegram_id}"

    if won:
        bot.send_message(
            chat_id,
            f"⚡ <b>Dice Roll (DR) • ₹{bet_amount:.2f}</b>\n\n"
            f"👤 <b>Player:</b> {user_label} 🎲\n"
            f"🎯 <b>Choice:</b> {label}\n"
            f"🎲 <b>Outcome:</b> {roll}\n\n"
            f"🎉 <b>You Won ₹{payout:.2f}!</b>\n"
            f"💰 <b>Balance:</b> ₹{new_balance:.2f}",
            parse_mode="HTML"
        )
        try:
            announce_win(display_name or str(telegram_id), payout, "Dice Roll")
        except Exception:
            pass
    else:
        bot.send_message(
            chat_id,
            f"⚡ <b>Dice Roll (DR) • ₹{bet_amount:.2f}</b>\n\n"
            f"👤 <b>Player:</b> {user_label} 🎲\n"
            f"🎯 <b>Choice:</b> {label}\n"
            f"🎲 <b>Outcome:</b> {roll}\n\n"
            f"❌ <b>You Lost ₹{bet_amount:.2f}</b>\n"
            f"💰 <b>Balance:</b> ₹{new_balance:.2f}",
            parse_mode="HTML"
        )
