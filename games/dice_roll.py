import time
from telebot.types import InlineKeyboardButton, InlineKeyboardMarkup
from wallet import adjust_balance, get_balance, get_house_balance, record_bet
from game_math import payout_for
from settings import get_max_bet, get_min_bet
from helpers import announce_win

EVEN_MONEY_CHOICES = {
    "high": {4, 5, 6},
    "low": {1, 2, 3},
    "even": {2, 4, 6},
    "odd": {1, 3, 5},
}
NUMBER_CHOICES = {"1", "2", "3", "4", "5", "6"}
ALL_CHOICES = set(EVEN_MONEY_CHOICES.keys()) | NUMBER_CHOICES

# Formatted display names as per target output
CHOICE_DISPLAY = {
    "low": "1 • 2 • 3 (Low)",
    "high": "4 • 5 • 6 (High)",
    "odd": "1 • 3 • 5 (Odd)",
    "even": "2 • 4 • 6 (Even)",
    "1": "1",
    "2": "2",
    "3": "3",
    "4": "4",
    "5": "5",
    "6": "6",
}


def send_selection_keyboard(bot, chat_id, telegram_id: int, bet_amount: float, username: str = None):
    """Sends the choice selection menu if no choice was passed in command."""
    user_ref = f"@{username}" if username else f"[{telegram_id}](tg://user?id={telegram_id})"
    
    markup = InlineKeyboardMarkup(row_width=3)
    markup.add(
        InlineKeyboardButton("Low", callback_data=f"dr_{bet_amount}_low"),
        InlineKeyboardButton("High", callback_data=f"dr_{bet_amount}_high"),
    )
    markup.add(
        InlineKeyboardButton("Odd", callback_data=f"dr_{bet_amount}_odd"),
        InlineKeyboardButton("Even", callback_data=f"dr_{bet_amount}_even"),
    )
    markup.add(
        *[InlineKeyboardButton(str(i), callback_data=f"dr_{bet_amount}_{i}") for i in range(1, 7)]
    )

    text = f"🎲 Dice Roll (DR) • ₹{int(bet_amount) if bet_amount.is_integer() else bet_amount}\n\n👤 {user_ref} — pick one:"
    bot.send_message(chat_id, text, reply_markup=markup, parse_mode="Markdown")


def play_dice_roll(bot, chat_id, telegram_id: int, bet_amount: float, choice: str = None, username: str = None):
    # If choice is missing, send inline selection buttons
    if not choice:
        send_selection_keyboard(bot, chat_id, telegram_id, bet_amount, username)
        return

    choice = choice.lower()
    if choice not in ALL_CHOICES:
        bot.send_message(chat_id, "Invalid choice. Use high, low, even, odd, or a number 1-6.")
        return

    balance = get_balance(telegram_id)
    min_bet = get_min_bet()
    max_bet = get_max_bet(get_house_balance())

    if bet_amount < min_bet:
        bot.send_message(chat_id, f"Minimum bet is ₹{min_bet}.")
        return
    if bet_amount > max_bet:
        bot.send_message(chat_id, f"Maximum bet is ₹{round(max_bet, 2)}.")
        return
    if bet_amount > balance:
        bot.send_message(chat_id, f"Not enough balance. Your balance: ₹{balance}")
        return

    adjust_balance(telegram_id, -bet_amount)

    # Send dice animation
    dice_message = bot.send_dice(chat_id, emoji="🎲")
    roll = dice_message.dice.value

    # Wait 3 seconds for dice animation to complete
    time.sleep(3)

    if choice in EVEN_MONEY_CHOICES:
        won = roll in EVEN_MONEY_CHOICES[choice]
        win_chance = 0.5
    else:
        won = roll == int(choice)
        win_chance = 1 / 6

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

    user_ref = f"@{username}" if username else f"[{telegram_id}](tg://user?id={telegram_id})"
    formatted_bet = int(bet_amount) if bet_amount.is_integer() else bet_amount
    formatted_choice = CHOICE_DISPLAY.get(choice, choice)

    if won:
        multiplier = round(payout / bet_amount, 2)
        formatted_payout = int(payout) if payout.is_integer() else payout
        
        result_text = (
            f"⚡ Dice Roll (DR) • ₹{formatted_bet}\n\n"
            f"👤 {user_ref}\n\n"
            f"🎯 You Chose:\n{formatted_choice}\n\n"
            f"🎲 Outcome:\n{roll}\n\n"
            f"💰 You Won ₹{formatted_payout} ({multiplier:.2f}x)"
        )
        bot.send_message(chat_id, result_text, parse_mode="Markdown")
        announce_win(username or str(telegram_id), payout, "Dice Roll")
    else:
        result_text = (
            f"⚡ Dice Roll (DR) • ₹{formatted_bet}\n\n"
            f"👤 {user_ref}\n\n"
            f"🎯 You Chose:\n{formatted_choice}\n\n"
            f"🎲 Outcome:\n{roll}\n\n"
            f"❌ You Lost ₹{formatted_bet}"
        )
        bot.send_message(chat_id, result_text, parse_mode="Markdown")


# Add Callback Handler for the Inline Keyboard buttons
def register_dice_callback_handler(bot):
    @bot.callback_query_handler(func=lambda call: call.data.startswith("dr_"))
    def handle_dice_callback(call):
        _, bet_str, choice = call.data.split("_")
        bet_amount = float(bet_str)
        
        # Answer callback to clear loading state on button
        bot.answer_callback_query(call.id)
        
        # Remove keyboard from previous message
        bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=None)
        
        play_dice_roll(
            bot=bot,
            chat_id=call.message.chat.id,
            telegram_id=call.from_user.id,
            bet_amount=bet_amount,
            choice=choice,
            username=call.from_user.username
        )
