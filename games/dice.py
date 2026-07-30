import random
from wallet import get_balance, adjust_balance, record_bet
from game_math import payout_for


async def play_dice(message, telegram_id: int, bet_amount: float, target: float):
    balance = get_balance(telegram_id)
    if bet_amount <= 0 or bet_amount > balance:
        await message.reply(f"Invalid bet. Your balance: {balance} coins.")
        return
    if target < 2 or target > 98:
        await message.reply("Target must be between 2 and 98.")
        return

    win_chance = target / 100
    roll = round(random.uniform(0, 100), 2)
    won = roll < target
    payout = payout_for(bet_amount, win_chance) if won else 0
    net_delta = (payout - bet_amount) if won else -bet_amount

    new_balance = adjust_balance(telegram_id, net_delta)
    record_bet(
        telegram_id=telegram_id,
        game="dice",
        bet_amount=bet_amount,
        payout=payout,
        result="win" if won else "loss",
        meta={"target": target, "roll": roll},
    )

    if won:
        await message.reply(f"🎲 Rolled {roll} (under {target})\nYou won {payout} coins! 🎉\nBalance: {new_balance}")
    else:
        await message.reply(f"🎲 Rolled {roll} (needed under {target})\nYou lost {bet_amount} coins.\nBalance: {new_balance}")