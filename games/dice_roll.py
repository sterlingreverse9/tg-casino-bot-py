from telebot.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from bot_instance import bot
from wallet import (
    get_balance,
    adjust_balance,
    reduce_wager_requirement,
    record_bet
)
from settings import get_min_bet, get_max_bet


# --- FIXED EVALUATION LOGIC ---

def evaluate_dice_outcome(dice_value: int, bet_choice: str) -> tuple[bool, float]:
    choice = str(bet_choice).lower().strip()

    if choice == "high":
        is_win = dice_value in (4, 5, 6)
        return is_win, 1.80 if is_win else 0.0

    elif choice == "low":
        is_win = dice_value in (1, 2, 3)
        return is_win, 1.80 if is_win else 0.0

    elif choice == "even":
        is_win = (dice_value % 2 == 0)
        return is_win, 1.80 if is_win else 0.0

    elif choice == "odd":
        is_win = (dice_value % 2 != 0)
        return is_win, 1.80 if is_win else 0.0

    elif choice in ["1", "2", "3", "4", "5", "6"]:
        is_win = (dice_value == int(choice))
        return is_win, 5.50 if is_win else 0.0

    return False, 0.0


def validate_bet_amount(user_id: int, amount: float) -> tuple[bool, str]:
    min_b = get_min_bet()
    max_b = get_max_bet(user_id)
    user_bal = get_balance(user_id)

    if amount < min_b:
        return False, f"⚠️ Minimum bet is ₹{min_b:.2f}"
    if amount > max_b:
        return False, f"⚠️ Maximum bet is ₹{max_b:.2f}"
    if amount > user_bal:
        return False, f"❌ Insufficient balance! You have ₹{user_bal:.2f}"

    return True, ""


# --- INLINE KEYBOARD UI ---

def get_bet_selection_keyboard(amount: float) -> InlineKeyboardMarkup:
    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(
        InlineKeyboardButton("🔴 High (4-6) [1.8x]", callback_data=f"dr_{amount}_high"),
        InlineKeyboardButton("🔵 Low (1-3) [1.8x]", callback_data=f"dr_{amount}_low"),
        InlineKeyboardButton("🟣 Even [1.8x]", callback_data=f"dr_{amount}_even"),
        InlineKeyboardButton("🟡 Odd [1.8x]", callback_data=f"dr_{amount}_odd"),
    )
    num_buttons = [InlineKeyboardButton(f"🎲 {i} [5.5x]", callback_data=f"dr_{amount}_{i}") for i in range(1, 7)]
    markup.add(*num_buttons)
    return markup


def send_dr_guide(message: Message):
    guide_text = (
        "🎲 <b>Dice Roll (/dr) Guide</b>\n\n"
        "<b>Usage:</b>\n"
        "• <code>/dr &lt;amount&gt; &lt;choice&gt;</code> — Bet directly\n"
        "• <code>/dr &lt;amount&gt;</code> — Open inline bet selection\n"
        "• <code>/dr</code> — Show this guide\n\n"
        "<b>Choices & Payouts:</b>\n"
        "• <code>high</code> (4-6) → <b>1.80x</b>\n"
        "• <code>low</code> (1-3) → <b>1.80x</b>\n"
        "• <code>even</code> (2, 4, 6) → <b>1.80x</b>\n"
        "• <code>odd</code> (1, 3, 5) → <b>1.80x</b>\n"
        "• <code>1-6</code> → <b>5.50x</b>\n\n"
        "<b>Aliases:</b> /diceroll"
    )
    bot.reply_to(message, guide_text, parse_mode="HTML")


# --- GAME EXECUTION ---

def process_dice_bet(chat_id: int, user_id: int, amount: float, choice: str, reply_to_id: int = None, display_name: str = "Player"):
    valid, err_msg = validate_bet_amount(user_id, amount)
    if not valid:
        bot.send_message(chat_id, err_msg, reply_to_message_id=reply_to_id)
        return

    # 1. Deduct bet amount from user's balance
    adjust_balance(user_id, -amount)

    # 2. Telegram natural roll
    msg = bot.send_dice(chat_id, emoji="🎲")
    dice_val = msg.dice.value

    # 3. Evaluate outcome
    is_win, multiplier = evaluate_dice_outcome(dice_val, choice)

    if is_win:
        payout = amount * multiplier
        adjust_balance(user_id, payout)
        res_msg = (
            f"⚡ <b>Dice Roll (DR) • ₹{amount:.2f}</b>\n\n"
            f"👤 <b>Player:</b> {display_name} 🎲\n"
            f"🎯 <b>Choice:</b> {choice.upper()}\n"
            f"🎲 <b>Outcome:</b> {dice_val}\n\n"
            f"🎉 <b>You Won ₹{payout:.2f}!</b>"
        )
    else:
        payout = 0.0
        reduce_wager_requirement(user_id, amount)
        res_msg = (
            f"⚡ <b>Dice Roll (DR) • ₹{amount:.2f}</b>\n\n"
            f"👤 <b>Player:</b> {display_name} 🎲\n"
            f"🎯 <b>Choice:</b> {choice.upper()}\n"
            f"🎲 <b>Outcome:</b> {dice_val}\n\n"
            f"❌ <b>You Lost ₹{amount:.2f}</b>"
        )

    # 4. Record bet in DB
    record_bet(
        telegram_id=user_id,
        game="dice_roll",
        bet_amount=amount,
        payout=payout,
        result="WIN" if is_win else "LOSE",
        meta={"choice": choice, "rolled": dice_val}
    )

    bot.send_message(chat_id, res_msg, reply_to_message_id=reply_to_id, parse_mode="HTML")


# --- COMMAND HANDLERS ---

@bot.message_handler(commands=["dr", "diceroll"])
def handle_dr_command(message: Message):
    parts = message.text.split()

    if len(parts) == 1:
        send_dr_guide(message)
        return

    user_id = message.from_user.id
    display_name = message.from_user.first_name or "Player"

    try:
        from wallet import resolve_amount
        amount = resolve_amount(user_id, parts[1])
    except Exception:
        try:
            amount = float(parts[1])
        except ValueError:
            amount = None

    if amount is None or amount <= 0:
        bot.reply_to(message, "❌ Invalid bet amount.")
        return

    valid, err_msg = validate_bet_amount(user_id, amount)
    if not valid:
        bot.reply_to(message, err_msg)
        return

    if len(parts) == 2:
        kb = get_bet_selection_keyboard(amount)
        bot.reply_to(message, f"🎲 <b>Place your bet for ₹{amount:.2f}:</b>", reply_markup=kb, parse_mode="HTML")
        return

    choice = parts[2].lower().strip()
    if choice not in ["high", "low", "even", "odd", "1", "2", "3", "4", "5", "6"]:
        bot.reply_to(message, "❌ Invalid choice! Pick high, low, even, odd, or 1-6.", parse_mode="HTML")
        return

    process_dice_bet(message.chat.id, user_id, amount, choice, reply_to_id=message.message_id, display_name=display_name)


@bot.callback_query_handler(func=lambda call: call.data.startswith("dr_"))
def handle_dr_callback(call: CallbackQuery):
    user_id = call.from_user.id
    display_name = call.from_user.first_name or "Player"
    parts = call.data.split("_")

    if len(parts) < 3:
        bot.answer_callback_query(call.id, "Invalid action.")
        return

    try:
        amount = float(parts[1])
        choice = parts[2]
    except ValueError:
        bot.answer_callback_query(call.id, "Invalid data.")
        return

    try:
        bot.delete_message(call.message.chat.id, call.message.message_id)
    except Exception:
        pass

    process_dice_bet(call.message.chat.id, user_id, amount, choice, display_name=display_name)


# Aliases
play_dice_roll = process_dice_bet
handle_dice_roll = handle_dr_command
