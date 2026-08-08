from bot_instance import bot
from wallet import get_balance, adjust_balance, record_bet, get_house_balance
from game_math import payout_for
from settings import get_min_bet, get_max_bet
from helpers import announce_win
from games.predict import play_predict_number


# --- DICE ROLL HANDLER ---
def play_dice_roll(bot, chat_id, telegram_id: int, bet_amount: float, choice: str, display_name: str = None):
    choice = str(choice).lower().strip()

    valid_choices = {"high", "low", "even", "odd", "1", "2", "3", "4", "5", "6"}
    if choice not in valid_choices:
        bot.send_message(chat_id, "⚠️ Invalid choice. Use high, low, even, odd, or 1-6.")
        return

    balance = get_balance(telegram_id)
    min_bet = get_min_bet()
    max_bet = get_max_bet(get_house_balance())

    if bet_amount < min_bet or bet_amount > max_bet or bet_amount > balance:
        bot.send_message(chat_id, "❌ Invalid bet amount or insufficient balance.")
        return

    # 1. Deduct balance
    adjust_balance(telegram_id, -bet_amount)

    # 2. Send dice & capture EXACT value synchronously
    dice_msg = bot.send_dice(chat_id, emoji="🎲")
    roll = int(dice_msg.dice.value)

    # 3. Explicit Win Condition Check
    won = False
    win_chance = 0.5
    label = choice.upper()

    if choice == "high":
        won = (roll in [4, 5, 6])
        label = "High (4-6)"
    elif choice == "low":
        won = (roll in [1, 2, 3])
        label = "Low (1-3)"
    elif choice == "even":
        won = (roll % 2 == 0)
        label = "Even"
    elif choice == "odd":
        won = (roll % 2 != 0)
        label = "Odd"
    elif choice in {"1", "2", "3", "4", "5", "6"}:
        won = (roll == int(choice))
        win_chance = 1 / 6
        label = f"Number {choice}"

    # 4. Payout Process
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

    # 5. Output Response
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


# --- PREDICT NUMBER COMMAND DISPATCHER ---
@bot.message_handler(commands=["pn", "predictnumber", "pnumber", "predict"])
def cmd_predict_number(message):
    chat_id = message.chat.id
    telegram_id = message.from_user.id
    display_name = message.from_user.first_name
    username = message.from_user.username

    args = message.text.split()[1:]

    if len(args) < 2:
        bot.reply_to(
            message,
            "⚠️ <b>Usage:</b> <code>/pn &lt;bet&gt; &lt;number (1-10)&gt;</code>\n"
            "<b>Example:</b> <code>/pn 10 7</code>",
            parse_mode="HTML"
        )
        return

    try:
        bet_amount = float(args[0])
        guess = int(args[1])
    except ValueError:
        bot.reply_to(
            message,
            "❌ Invalid parameters! Please pass valid numbers.\n"
            "<b>Example:</b> <code>/pn 10 7</code>",
            parse_mode="HTML"
        )
        return

    play_predict_number(
        bot=bot,
        chat_id=chat_id,
        telegram_id=telegram_id,
        bet_amount=bet_amount,
        guess=guess,
        display_name=display_name,
        username=username
    )
