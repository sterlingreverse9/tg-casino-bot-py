from wallet import get_balance, adjust_balance, record_bet, get_house_balance
from game_math import payout_for

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

MIN_BET = 10


def play_dice_roll(bot, chat_id, telegram_id: int, bet_amount: float, choice: str):
    choice = choice.lower()
    if choice not in ALL_CHOICES:
        bot.send_message(chat_id, "Invalid choice. Use high, low, even, odd, or a number 1-6.")
        return

    balance = get_balance(telegram_id)
    house_balance = get_house_balance()
    max_bet = house_balance * 0.05

    if bet_amount < MIN_BET:
        bot.send_message(chat_id, f"Minimum bet is {MIN_BET} ruppess.")
        return
    if bet_amount > max_bet:
        bot.send_message(chat_id, f"Maximum bet is {round(max_bet, 2)} coins (5% of house balance).")
        return
    if bet_amount > balance:
        bot.send_message(chat_id, f"Not enough balance. Your balance: {balance}")
        return

    adjust_balance(telegram_id, -bet_amount)

    dice_message = bot.send_dice(chat_id, emoji="🎲")
    roll = dice_message.dice.value

    if choice in EVEN_MONEY_CHOICES:
        won = roll in EVEN_MONEY_CHOICES[choice]
        win_chance = 0.5
        label = LABELS[choice]
    else:
        won = roll == int(choice)
        win_chance = 1 / 6
        label = f"Number {choice}"

    payout = payout_for(bet_amount, win_chance) if won else 0
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
    if won:
        bot.send_message(
            chat_id,
            f"🎲 Rolled {roll}!\nYou bet on {label}\n✅ You won {payout} ruppess!\nBalance: {new_balance}",
        )
    else:
        bot.send_message(
            chat_id,
            f"🎲 Rolled {roll}!\nYou bet on {label}\n❌ You lost {bet_amount} ruppess.\nBalance: {new_balance}",
        )
