import random
import time
from bot_instance import bot
from wallet import get_balance, adjust_balance, record_bet, update_wager
from settings import get_min_bet, get_max_bet
from helpers import announce_win
from games.predict import play_predict_number
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton

# --- DR CONSTANTS & MULTIPLIERS ---
DICE_MIN_BET = 5.0
DICE_MAX_BET = 50.0
MULTIPLIER_CHOICE = 1.8  # high / low / odd / even
MULTIPLIER_EXACT = 5.0   # exact numbers 1-6

# --- CONSTANTS & BUCKETS FOR LIMBO ---
MIN_MULTIPLIER = 1.01
MAX_MULTIPLIER = 1000

BUCKETS = [
    (1.00, 1.00, 0.15),      # 15% (strictly 1.00x)
    (1.01, 1.50, 0.18),      # 18%
    (1.50, 2.00, 0.36),      # 36%
    (2.00, 3.00, 0.15),      # 15%
    (3.00, 5.00, 0.08),      # 8%
    (5.00, 10.00, 0.04),     # 4%
    (10.00, 50.00, 0.03),    # 3%
    (50.00, MAX_MULTIPLIER, 0.01),  # 1%
]


def parse_multiplier(text: str):
    """'2x', '2X', or '2' -> 2.0. Returns None if invalid."""
    s = text.lower().rstrip("x").strip()
    try:
        value = float(s)
    except ValueError:
        return None
    if value < MIN_MULTIPLIER or value > MAX_MULTIPLIER:
        return None
    return value


def roll_result() -> float:
    r = random.random()
    cumulative = 0.0
    for low, high, prob in BUCKETS:
        cumulative += prob
        if r <= cumulative:
            if low == high:
                return float(low)
            return round(random.uniform(low, high), 2)
    low, high, _ = BUCKETS[-1]
    return round(random.uniform(low, high), 2)


# --- DICE ROLL LOGIC ---
def parse_choice(choice_str: str):
    s = str(choice_str).strip().lower()
    if s in ["high", "h", "high (4-6)"]:
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


def evaluate_dice_win(roll: int, choice) -> bool:
    if choice == "high":
        return roll >= 4
    if choice == "low":
        return roll <= 3
    if choice == "odd":
        return roll % 2 != 0
    if choice == "even":
        return roll % 2 == 0
    if isinstance(choice, int):
        return roll == choice
    return False


def play_dice_roll(bot, chat_id, telegram_id: int, bet_amount: float, choice: str = None, display_name: str = None):
    # 1. Bet Limits
    if bet_amount < DICE_MIN_BET:
        bot.send_message(chat_id, f"⚠️ Minimum bet is ₹{DICE_MIN_BET:.2f}", parse_mode="HTML")
        return
    if bet_amount > DICE_MAX_BET:
        bot.send_message(chat_id, f"⚠️ Maximum bet is ₹{DICE_MAX_BET:.2f}", parse_mode="HTML")
        return

    balance = get_balance(telegram_id)
    if bet_amount > balance:
        bot.send_message(chat_id, f"❌ Insufficient balance! Your balance: ₹{balance:.2f}")
        return

    # 2. Open Panel if Choice Not Passed
    if choice is None:
        text = (
            f"🎲 <b>Dice Roll Game</b>\n\n"
            f"💰 <b>Selected Bet:</b> ₹{bet_amount:.2f}\n"
            f"Select your prediction below:"
        )
        bot.send_message(chat_id, text, reply_markup=get_dice_keyboard(bet_amount), parse_mode="HTML")
        return

    parsed_choice = parse_choice(choice)
    if parsed_choice is None:
        bot.send_message(
            chat_id,
            "⚠️ Invalid choice. Use <code>high</code>, <code>low</code>, <code>even</code>, <code>odd</code>, or <code>1-6</code>.",
            parse_mode="HTML"
        )
        return

    # 3. Deduct Balance & Update Wager
    adjust_balance(telegram_id, -bet_amount)
    try:
        update_wager(telegram_id, bet_amount)
    except Exception as e:
        print(f"[DICE WAGER ERROR] {e}")

    # 4. Roll Dice
    dice_msg = bot.send_dice(chat_id, emoji="🎲")
    time.sleep(3)
    roll = int(dice_msg.dice.value)

    # 5. Evaluate Win & Multipliers
    won = evaluate_dice_win(roll, parsed_choice)
    multiplier = MULTIPLIER_EXACT if isinstance(parsed_choice, int) else MULTIPLIER_CHOICE
    payout = round(bet_amount * multiplier, 2) if won else 0.0

    if won:
        adjust_balance(telegram_id, payout)

    record_bet(
        telegram_id=telegram_id,
        game="dice_roll",
        bet_amount=bet_amount,
        payout=payout,
        result="win" if won else "loss",
        meta={"choice": str(parsed_choice), "roll": roll},
    )

    new_balance = get_balance(telegram_id)
    user_label = display_name or f"ID: {telegram_id}"

    if won:
        msg = (
            f"⚡ <b>Dice Roll (DR) • ₹{bet_amount:.2f}</b>\n\n"
            f"👤 <b>Player:</b> {user_label} 🎲\n"
            f"🎯 <b>Choice:</b> {str(parsed_choice).upper()}\n"
            f"🎲 <b>Outcome:</b> {roll}\n\n"
            f"🎉 <b>You Won ₹{payout:.2f}!</b> ({multiplier}x)\n"
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
            print(f"[DR WIN ERROR] {e}", flush=True)
    else:
        msg = (
            f"⚡ <b>Dice Roll (DR) • ₹{bet_amount:.2f}</b>\n\n"
            f"👤 <b>Player:</b> {user_label} 🎲\n"
            f"🎯 <b>Choice:</b> {str(parsed_choice).upper()}\n"
            f"🎲 <b>Outcome:</b> {roll}\n\n"
            f"❌ <b>You Lost ₹{bet_amount:.2f}</b>\n"
            f"💰 <b>Balance:</b> ₹{new_balance:.2f}"
        )

    bot.send_message(chat_id, msg, parse_mode="HTML")


# --- LIMBO LOGIC ---
def play_limbo(bot, chat_id, telegram_id: int, bet_amount: float, target_multiplier: float, user_name: str = None):
    balance = get_balance(telegram_id)
    min_bet = get_min_bet()
    max_bet = get_max_bet()

    if bet_amount < min_bet:
        bot.send_message(chat_id, f"⚠️ Minimum bet is ₹{min_bet:.2f}")
        return
    if bet_amount > max_bet:
        bot.send_message(chat_id, f"⚠️ Maximum bet is ₹{max_bet:.2f}")
        return
    if bet_amount > balance:
        bot.send_message(chat_id, f"❌ Insufficient balance! Your balance: ₹{balance:.2f}")
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

    display_result = result
    if won and random.random() < 0.20:
        fake_high = round(random.uniform(10.00, 50.00), 2)
        display_result = max(fake_high, target_multiplier)

    header_arrow = "⬆️" if won else "⬇️"
    mult_arrow = "⬆️" if won else "⬇️"

    message = (
        f"{header_arrow} <b>Limbo</b>\n\n"
        f"₹{bet_amount:.2f} → ₹{payout:.2f} ({display_result:.2f}×)\n\n"
        f"Multiplier: {target_multiplier:.2f}× {mult_arrow}"
    )

    bot.send_message(chat_id, message, parse_mode="HTML")


# ==================== TELEGRAM COMMAND DISPATCHERS ====================

@bot.message_handler(commands=["dr", "diceroll", "dice"])
def cmd_dice_roll(message):
    args = message.text.split()[1:]

    if len(args) < 1:
        bot.reply_to(
            message,
            "⚠️ <b>Usage:</b>\n"
            "• <code>/dr &lt;amt&gt;</code> — Open inline prediction panel\n"
            "• <code>/dr &lt;amt&gt; &lt;choice&gt;</code> — Bet directly\n\n"
            "<b>Example:</b> <code>/dr 10 high</code> or <code>/dr 10 5</code>",
            parse_mode="HTML"
        )
        return

    try:
        bet_amount = float(args[0])
    except ValueError:
        bot.reply_to(message, "❌ Invalid bet amount!", parse_mode="HTML")
        return

    choice = args[1] if len(args) >= 2 else None

    play_dice_roll(
        bot=bot,
        chat_id=message.chat.id,
        telegram_id=message.from_user.id,
        bet_amount=bet_amount,
        choice=choice,
        display_name=message.from_user.first_name
    )


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


@bot.message_handler(commands=["pn", "predictnumber", "pnumber", "predict"])
def cmd_predict_number(message):
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
        chat_id=message.chat.id,
        telegram_id=message.from_user.id,
        bet_amount=bet_amount,
        guess=guess,
        display_name=message.from_user.first_name,
        username=message.from_user.username
    )


@bot.message_handler(commands=["limbo", "lb"])
def cmd_limbo(message):
    args = message.text.split()[1:]

    if len(args) < 2:
        bot.reply_to(
            message,
            "⚠️ <b>Usage:</b> <code>/limbo &lt;bet&gt; &lt;target_multiplier&gt;</code>\n"
            "<b>Example:</b> <code>/limbo 10 2x</code>",
            parse_mode="HTML"
        )
        return

    try:
        bet_amount = float(args[0])
    except ValueError:
        bot.reply_to(message, "❌ Invalid bet amount!", parse_mode="HTML")
        return

    target_multiplier = parse_multiplier(args[1])
    if target_multiplier is None:
        bot.reply_to(
            message,
            f"❌ Invalid multiplier! Target must be between {MIN_MULTIPLIER}x and {MAX_MULTIPLIER}x.",
            parse_mode="HTML"
        )
        return

    play_limbo(
        bot=bot,
        chat_id=message.chat.id,
        telegram_id=message.from_user.id,
        bet_amount=bet_amount,
        target_multiplier=target_multiplier,
        user_name=message.from_user.first_name
    )
