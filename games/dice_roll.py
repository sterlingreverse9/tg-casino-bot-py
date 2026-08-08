import time
from wallet import get_balance, adjust_balance, record_bet, get_house_balance
from game_math import payout_for
from settings import get_min_bet, get_max_bet
from helpers import announce_win


def play_dice_roll(
    bot,
    chat_id,
    telegram_id: int,
    bet_amount: float,
    choice: str,
    display_name: str = None,
):
    user_label = display_name or f"ID: {telegram_id}"
    raw_choice = str(choice).lower().strip()

    # Map shortcut aliases to standard choices
    choice_map = {
        # High / Low
        "high": "high",
        "h": "high",
        "low": "low",
        "l": "low",
        # Even / Odd
        "even": "even",
        "e": "even",
        "odd": "odd",
        "o": "odd",
        # Direct numbers
        "1": "1",
        "2": "2",
        "3": "3",
        "4": "4",
        "5": "5",
        "6": "6",
    }

    if raw_choice not in choice_map:
        print(
            f"[DR LOG] Invalid choice '{raw_choice}' from user {user_label}",
            flush=True,
        )
        bot.send_message(
            chat_id,
            "⚠️ Invalid choice. Use high (h), low (l), even (e), odd (o), or 1-6.",
        )
        return

    choice = choice_map[raw_choice]

    balance = get_balance(telegram_id)
    min_bet = get_min_bet()
    max_bet = get_max_bet(get_house_balance())

    if bet_amount < min_bet or bet_amount > max_bet or bet_amount > balance:
        print(
            f"[DR LOG] Rejected bet ₹{bet_amount:.2f} for {user_label} (Bal: ₹{balance:.2f})",
            flush=True,
        )
        bot.send_message(
            chat_id, "❌ Invalid bet amount or insufficient balance."
        )
        return

    # Balance Deduct
    adjust_balance(telegram_id, -bet_amount)
    print(
        f"[DR LOG] Game started | Player: {user_label} | Bet: ₹{bet_amount:.2f} | Choice: {choice}",
        flush=True,
    )

    # Send Dice Animation
    dice_msg = bot.send_dice(chat_id, emoji="🎲")

    # Wait 3 seconds for Telegram animation to complete
    time.sleep(3)

    # Read official rolled value AFTER animation lock
    roll = int(dice_msg.dice.value)

    # Evaluation Logic
    won = False
    win_chance = 0.5
    label = choice.upper()

    if choice == "high":
        won = roll in [4, 5, 6]
        label = "High (4-6)"
    elif choice == "low":
        won = roll in [1, 2, 3]
        label = "Low (1-3)"
    elif choice == "even":
        won = roll % 2 == 0
        label = "Even (2,4,6)"
    elif choice == "odd":
        won = roll % 2 != 0
        label = "Odd (1,3,5)"
    elif choice in {"1", "2", "3", "4", "5", "6"}:
        won = roll == int(choice)
        win_chance = 1 / 6
        label = f"Number {choice}"

    # Payout Handling
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

    # Print Termux Terminal Logs
    res_str = "WON" if won else "LOST"
    print(
        f"[DR LOG] Result: {res_str} | Rolled: {roll} | Target: {label} | Payout: ₹{payout:.2f} | New Bal: ₹{new_balance:.2f}",
        flush=True,
    )

    # Telegram Message Output
    if won:
        msg = (
            f"⚡ <b>Dice Roll (DR) • ₹{bet_amount:.2f}</b>\n\n"
            f"👤 <b>Player:</b> {user_label} 🎲\n"
            f"🎯 <b>Choice:</b> {label}\n"
            f"🎲 <b>Outcome:</b> {roll}\n\n"
            f"🎉 <b>You Won ₹{payout:.2f}!</b>\n"
            f"💰 <b>Balance:</b> ₹{new_balance:.2f}"
        )
    else:
        msg = (
            f"⚡ <b>Dice Roll (DR) • ₹{bet_amount:.2f}</b>\n\n"
            f"👤 <b>Player:</b> {user_label} 🎲\n"
            f"🎯 <b>Choice:</b> {label}\n"
            f"🎲 <b>Outcome:</b> {roll}\n\n"
            f"❌ <b>You Lost ₹{bet_amount:.2f}</b>\n"
            f"💰 <b>Balance:</b> ₹{new_balance:.2f}"
        )

    bot.send_message(chat_id, msg, parse_mode="HTML")
