def play_limbo(
    bot,
    chat_id,
    telegram_id: int,
    bet_amount: float,
    target_multiplier: float,
    user_name: str = None,
):
    balance = get_balance(telegram_id)
    min_bet = get_min_bet()
    max_bet = get_max_bet(get_house_balance())

    if bet_amount < min_bet:
        bot.send_message(chat_id, f"Minimum bet is {min_bet} coins.")
        return
    if bet_amount > max_bet:
        bot.send_message(chat_id, f"Maximum bet is {round(max_bet, 2)} coins.")
        return
    if bet_amount > balance:
        bot.send_message(chat_id, f"Not enough balance. Your balance: ₹{balance:.2f}")
        return

    adjust_balance(telegram_id, -bet_amount)

    result = roll_result()
    won = result >= target_multiplier

    payout = round(bet_amount * target_multiplier, 2) if won else 0.0
    if won:
        adjust_balance(telegram_id, payout)

    record_bet(
        telegram_id=telegram_id,
        game="limbo",
        bet_amount=bet_amount,
        payout=payout,
        result="win" if won else "loss",
        meta={"target": target_multiplier, "result": result},
    )

    # UI Formatting
    arrow = "⬆️" if won else "⬇️"
    mult_arrow = "⬆️" if won else "⬇️"

    # Message structure matching requested UI
    message = (
        f"{arrow} Limbo\n\n"
        f"₹{bet_amount:.2f} → ₹{payout:.2f} ({result:.2f}×)\n\n"
        f"Multiplier: {target_multiplier:.2f}× {mult_arrow}"
    )

    bot.send_message(chat_id, message)
