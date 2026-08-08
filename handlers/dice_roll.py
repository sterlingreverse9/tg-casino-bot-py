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

    # Choice mapping & aliases
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
            f"[DR LOG] Invalid choice '{raw_choice}' from {user_label}",
            flush=True,
        )
        bot.send_message(
            chat_id,
            "⚠️ Invalid choice. Use high (h), low (l), even (e), odd (o), or 1-6.",
        )
        return

    choice = choice_map[raw_choice]

    # Validate limits and balance
    balance = get_balance(telegram_id)
    min_bet = get_min_bet()
    max_bet = get_max_bet(get_house_balance())

    if bet_amount < min_bet:
        bot.send_message(
            chat_id, f"⚠️ Minimum bet amount is ₹{min_bet:.2f}."
        )
        print(
            f"[DR LOG] Rejected bet ₹{bet_amount:.2f} (< Min ₹{min_bet:.2f}) for {user_label}",
            flush=True,
        )
        return

    if bet_amount > max_bet:
        bot.send_message(
            chat_id, f"⚠️ Maximum bet amount is ₹{max_bet:.2f}."
        )
        print(
            f"[DR LOG] Rejected bet ₹{bet_amount:.2f} (> Max ₹{max_bet:.2f}) for {user_label}",
            flush=True,
        )
        return

    if bet_amount > balance:
        bot.send_message(
            chat_id,
            f"❌ Insufficient balance! Your balance: ₹{balance:.2f}",
        )
        print(
            f"[DR LOG] Rejected bet ₹{bet_amount:.2f} (Insufficient Bal ₹{balance:.2f}) for {user_label}",
            flush=True,
        )
        return

    # Deduct bet balance
    adjust_balance(telegram_id, -bet_amount)
    print(
        f"[DR LOG] Game started | Player: {user_label} | Bet: ₹{bet_amount:.2f} | Choice: {choice}",
        flush=True,
    )

    # Send native dice animation
    dice_msg = bot.send_dice(chat_id, emoji="🎲")

    # Wait 3s for animation to complete
    time.sleep(3)

    # Read rolled value
    roll = int(dice_msg.dice.value)

    # Outcome evaluation
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

    # Calculate payout
    payout = payout_for(bet_amount, win_chance) if won else 0.0
    if won:
        adjust_balance(telegram_id, payout)

    # Record wager/bet history
    record_bet(
        telegram_id=telegram_id,
        game="dice_roll",
        bet_amount=bet_amount,
        payout=payout,
        result="win" if won else "loss",
        meta={"choice": choice, "roll": roll},
    )

    new_balance = get_balance(telegram_id)

    # Console logging for Termux
    res_str = "WON" if won else "LOST"
    print(
        f"[DR LOG] Result: {res_str} | Rolled: {roll} | Target: {label} | Payout: ₹{payout:.2f} | New Bal: ₹{new_balance:.2f}",
        flush=True,
    )

    # Output message
    if won:
        msg = (
            f"⚡ <b>Dice Roll (DR) • ₹{bet_amount:.2f}</b>\n\n"
            f"👤 <b>Player:</b> {user_label} 🎲\n"
            f"🎯 <b>Choice:</b> {label}\n"
            f"🎲 <b>Outcome:</b> {roll}\n\n"
            f"🎉 <b>You Won ₹{payout:.2f}!</b>\n"
            f"💰 <b>Balance:</b> ₹{new_balance:.2f}"
        )

        try:
            announce_win(
                bot=bot,
                user_id=telegram_id,
                display_name=user_label,
                game_name="Dice Roll",
                bet_amount=bet_amount,
                payout=payout,
            )
        except Exception as e:
            print(f"[DR LOG] announce_win error: {e}", flush=True)

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
