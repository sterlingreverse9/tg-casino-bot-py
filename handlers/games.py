import random
import time
from bot_instance import bot
from wallet import get_balance, adjust_balance, record_bet, update_wager
from helpers import announce_win
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton

# Game Rules & Limits
MIN_BET = 5.0
MAX_BET = 50.0

MULTIPLIER_CHOICE = 1.8  # For high/low/odd/even
MULTIPLIER_EXACT = 5.0   # For exact number 1-6


def parse_choice(choice_str: str):
    """Normalize user input choice."""
    s = str(choice_str).strip().lower()
    if s in ["high", "h", "7", "high (4-6)"]:
        return "high"
    if s in ["low", "l", "low (1-3)"]:
        return "low"
    if s in ["odd", "o"]:
        return "odd"
    if s in ["even", "e"]:
        return "even"
    if s in ["1", "2", "3", "4", "5", "6"]:
        return int(s)
    return None


def get_dice_keyboard(bet_amount: float):
    """Generate inline keyboard layout for /dr <amt> panel."""
    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(
        InlineKeyboardButton("High (4-6) [1.8x]", callback_data=f"dr_play:{bet_amount}:high"),
        InlineKeyboardButton("Low (1-3) [1.8x]", callback_data=f"dr_play:{bet_amount}:low"),
        InlineKeyboardButton("Odd [1.8x]", callback_data=f"dr_play:{bet_amount}:odd"),
        InlineKeyboardButton("Even [1.8x]", callback_data=f"dr_play:{bet_amount}:even"),
    )
    num_btns = [
        InlineKeyboardButton(f"🎲 {n} [5x]", callback_data=f"dr_play:{bet_amount}:{n}")
        for n in range(1, 7)
    ]
    markup.add(*num_btns[:3])
    markup.add(*num_btns[3:])
    return markup


def evaluate_win(value: int, choice) -> bool:
    """Check if the rolled dice value satisfies user choice."""
    if choice == "high":
        return value >= 4
    if choice == "low":
        return value <= 3
    if choice == "odd":
        return value % 2 != 0
    if choice == "even":
        return value % 2 == 0
    if isinstance(choice, int):
        return value == choice
    return False


def play_dice_roll(bot, chat_id, telegram_id: int, bet_amount: float, choice: str = None, display_name: str = None):
    # 1. Bet Limits Validation
    if bet_amount < MIN_BET:
        bot.send_message(chat_id, f"⚠️ Minimum bet is ₹{MIN_BET:.2f}", parse_mode="HTML")
        return
    if bet_amount > MAX_BET:
        bot.send_message(chat_id, f"⚠️ Maximum bet is ₹{MAX_BET:.2f}", parse_mode="HTML")
        return

    # 2. Open Panel Mode (if choice is not given)
    if choice is None:
        balance = get_balance(telegram_id)
        if balance < bet_amount:
            bot.send_message(chat_id, f"❌ Insufficient balance! Your balance: ₹{balance:.2f}")
            return

        text = (
            f"🎲 <b>Dice Roll Game</b>\n\n"
            f"💰 <b>Selected Bet:</b> ₹{bet_amount:.2f}\n"
            f"Select your prediction below:"
        )
        bot.send_message(chat_id, text, reply_markup=get_dice_keyboard(bet_amount), parse_mode="HTML")
        return

    # 3. Parse and validate choice
    parsed_choice = parse_choice(choice)
    if parsed_choice is None:
        bot.send_message(
            chat_id,
            "❌ Invalid choice! Choose: <code>high</code>, <code>low</code>, <code>odd</code>, <code>even</code>, or a number (<code>1-6</code>).",
            parse_mode="HTML"
        )
        return

    # 4. Check Balance
    balance = get_balance(telegram_id)
    if bet_amount > balance:
        bot.send_message(chat_id, f"❌ Insufficient balance! Your balance: ₹{balance:.2f}")
        return

    # 5. Deduct balance & update wager requirement
    adjust_balance(telegram_id, -bet_amount)
    try:
        update_wager(telegram_id, bet_amount)
    except Exception as e:
        print(f"[DICE WAGER ERROR] {e}")

    # 6. Send Telegram Animated Dice
    dice_msg = bot.send_dice(chat_id, emoji="🎲")
    time.sleep(3)
    value = int(dice_msg.dice.value)

    # 7. Calculate Result
    won = evaluate_win(value, parsed_choice)
    multiplier = MULTIPLIER_EXACT if isinstance(parsed_choice, int) else MULTIPLIER_CHOICE
    payout = round(bet_amount * multiplier, 2) if won else 0.0

    if won:
        adjust_balance(telegram_id, payout)

    # 8. Record Bet Transaction
    record_bet(
        telegram_id=telegram_id,
        game="dice",
        bet_amount=bet_amount,
        payout=payout,
        result="win" if won else "loss",
        meta={"choice": str(parsed_choice), "rolled": value, "multiplier": multiplier if won else 0},
    )

    # 9. Announce Win to channel
    user_label = display_name or f"User {telegram_id}"
    if won:
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
            print(f"[DICE WIN ANNOUNCE ERROR] {e}")

    # 10. Send Final Result Message Safely (Fix for Issue 2)
    outcome_text = f"🎉 <b>YOU WON ₹{payout:.2f}!</b> ({multiplier}x)" if won else "❌ <b>YOU LOST!</b>"
    result_message = (
        f"🎲 <b>Dice Roll Result</b>\n\n"
        f"👤 <b>Player:</b> {user_label}\n"
        f"🎯 <b>Choice:</b> <code>{str(parsed_choice).upper()}</code>\n"
        f"🎲 <b>Rolled:</b> <code>{value}</code>\n"
        f"💰 <b>Bet:</b> ₹{bet_amount:.2f}\n\n"
        f"{outcome_text}"
    )

    try:
        bot.send_message(chat_id, result_message, reply_to_message_id=dice_msg.message_id, parse_mode="HTML")
    except Exception:
        bot.send_message(chat_id, result_message, parse_mode="HTML")


# ==================== CALLBACK HANDLER FOR INLINE BUTTONS ====================

@bot.callback_query_handler(func=lambda call: call.data.startswith("dr_play:"))
def cb_dice_play(call):
    try:
        _, bet_str, choice = call.data.split(":")
        bet_amount = float(bet_str)
    except Exception:
        bot.answer_callback_query(call.id, "Invalid data!", show_alert=True)
        return

    bot.answer_callback_query(call.id)
    try:
        bot.delete_message(call.message.chat.id, call.message.message_id)
    except Exception:
        pass

    play_dice_roll(
        bot=bot,
        chat_id=call.message.chat.id,
        telegram_id=call.from_user.id,
        bet_amount=bet_amount,
        choice=choice,
        display_name=call.from_user.first_name,
    )
