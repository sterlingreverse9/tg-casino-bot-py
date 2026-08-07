from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
from bot_instance import bot
from wallet import resolve_amount
from game_status import is_game_enabled
from games.coinflip import play_coinflip
from games.dice_roll import play_dice_roll
from games.limbo import play_limbo, parse_multiplier
from games.predict import play_predict_number
from games.animated_dice import play_animated_game
from helpers import ensure_user, format_display_name, is_user_frozen


def name_of(user):
    return format_display_name(user.first_name, user.username)


# --- GAMES MENU HANDLER ---

@bot.message_handler(commands=["game", "games"])
def send_games_list(message):
    games_text = (
        "<b>🎰 Available Casino Games & Commands</b>\n"
        "────────────────────────\n\n"
        "<b>🪙 Coinflip</b>\n"
        "• Command: <code>/cf &lt;amount|all|half&gt; &lt;heads|tails&gt;</code>\n\n"
        "<b>🎲 Dice Roll</b>\n"
        "• Command: <code>/dr &lt;amount|all|half&gt; &lt;choice&gt;</code>\n\n"
        "<b>🚀 Limbo</b>\n"
        "• Command: <code>/limbo &lt;amount|all|half&gt; &lt;multiplier&gt;</code>\n\n"
        "<b>🎯 Predict Number</b>\n"
        "• Command: <code>/pn &lt;amount|all|half&gt; &lt;1-100&gt;</code>\n\n"
        "<b>🏀 Basketball</b>\n"
        "• Command: <code>/basket &lt;amount|all|half&gt;</code>\n\n"
        "<b>🎯 Darts</b>\n"
        "• Command: <code>/darts &lt;amount|all|half&gt;</code>\n\n"
        "<b>🎰 Slots</b>\n"
        "• Command: <code>/slots &lt;amount|all|half&gt;</code>\n\n"
        "<b>⚽ Football</b>\n"
        "• Command: <code>/football &lt;amount|all|half&gt;</code>\n\n"
        "<b>🎳 Bowling</b>\n"
        "• Command: <code>/bowl &lt;amount|all|half&gt;</code>\n\n"
        "────────────────────────\n"
        "<i>💡 Tip: Ensure you have sufficient balance before placing bets!</i>"
    )
    bot.reply_to(message, games_text, parse_mode="HTML")


# --- COINFLIP HANDLER ---

@bot.message_handler(commands=["cf"])
def cmd_cf(message):
    ensure_user(message)
    if is_user_frozen(message.from_user.id):
        bot.reply_to(message, "❄️ Your account is currently frozen.")
        return
    if not is_game_enabled("cf"):
        bot.reply_to(message, "Coinflip is currently disabled.")
        return
    parts = message.text.split()
    if len(parts) < 3 or parts[2].lower() not in ("heads", "tails"):
        bot.reply_to(message, "Usage: /cf <amount|all|half> <heads|tails>")
        return
    bet_amount = resolve_amount(message.from_user.id, parts[1])
    if bet_amount is None:
        bot.reply_to(message, "Amount must be a number, 'all', or 'half'.")
        return
    play_coinflip(bot, message, message.from_user.id, bet_amount, parts[2].lower())


# --- LIMBO HANDLER ---

@bot.message_handler(commands=["limbo"])
def cmd_limbo(message):
    ensure_user(message)
    if is_user_frozen(message.from_user.id):
        bot.reply_to(message, "❄️ Your account is currently frozen.")
        return
    if not is_game_enabled("limbo"):
        bot.reply_to(message, "Limbo is currently disabled.")
        return
    parts = message.text.split()
    if len(parts) < 3:
        bot.reply_to(message, "Usage: /limbo <amount|all|half> <multiplier>\nExample: /limbo 40 2x")
        return
    bet_amount = resolve_amount(message.from_user.id, parts[1])
    if bet_amount is None:
        bot.reply_to(message, "Amount must be a number, 'all', or 'half'.")
        return
    target_multiplier = parse_multiplier(parts[2])
    if target_multiplier is None:
        bot.reply_to(message, "Multiplier must be between 1.01x and 1000x, e.g. 2x or 6.")
        return
    play_limbo(bot, message.chat.id, message.from_user.id, bet_amount, target_multiplier, name_of(message.from_user))


# --- DICE ROLL HANDLERS ---

def build_dr_keyboard(telegram_id: int, amount_str: str):
    markup = InlineKeyboardMarkup()
    markup.row(
        InlineKeyboardButton("High (4-6)", callback_data=f"dr:{telegram_id}:{amount_str}:high"),
        InlineKeyboardButton("Low (1-3)", callback_data=f"dr:{telegram_id}:{amount_str}:low"),
    )
    markup.row(
        InlineKeyboardButton("Even", callback_data=f"dr:{telegram_id}:{amount_str}:even"),
        InlineKeyboardButton("Odd", callback_data=f"dr:{telegram_id}:{amount_str}:odd"),
    )
    markup.row(*[
        InlineKeyboardButton(str(n), callback_data=f"dr:{telegram_id}:{amount_str}:{n}")
        for n in range(1, 7)
    ])
    return markup


@bot.message_handler(commands=["dr", "diceroll", "dice"])
def cmd_dr(message):
    ensure_user(message)
    if is_user_frozen(message.from_user.id):
        bot.reply_to(message, "❄️ Your account is currently frozen.")
        return
    if not is_game_enabled("dr"):
        bot.reply_to(message, "Dice Roll is currently disabled.")
        return
    parts = message.text.split()
    telegram_id = message.from_user.id

    if len(parts) >= 3:
        amount_str, choice = parts[1], parts[2].lower()
        bet_amount = resolve_amount(telegram_id, amount_str)
        if bet_amount is None:
            bot.reply_to(message, "Amount must be a number, 'all', or 'half'.")
            return
        play_dice_roll(bot, message.chat.id, telegram_id, bet_amount, choice, name_of(message.from_user))
        return

    amount_str = parts[1] if len(parts) == 2 else "10"
    if amount_str.lower() not in ("all", "half"):
        try:
            float(amount_str)
        except ValueError:
            bot.reply_to(message, "Usage: /dr <amount> <choice> or /dr <amount>")
            return

    markup = build_dr_keyboard(telegram_id, amount_str)
    bot.send_message(message.chat.id, f"🎲 Dice Roll • Bet: {amount_str}\nPick your choice:", reply_markup=markup)


@bot.callback_query_handler(func=lambda call: call.data.startswith("dr:"))
def handle_dr_callback(call):
    if is_user_frozen(call.from_user.id):
        bot.answer_callback_query(call.id, "❄️ Your account is currently frozen.", show_alert=True)
        return
    if not is_game_enabled("dr"):
        bot.answer_callback_query(call.id, "Dice Roll is currently disabled.")
        return
    _, owner_id_str, amount_str, choice = call.data.split(":")
    owner_id = int(owner_id_str)
    if call.from_user.id != owner_id:
        bot.answer_callback_query(call.id, "This isn't your bet.")
        return
    bot.answer_callback_query(call.id)
    bet_amount = resolve_amount(owner_id, amount_str)
    if bet_amount is None:
        bot.send_message(call.message.chat.id, "Amount must be a number, 'all', or 'half'.")
        return
    play_dice_roll(bot, call.message.chat.id, owner_id, bet_amount, choice, name_of(call.from_user))


# --- PREDICT NUMBER HANDLER ---

@bot.message_handler(commands=["pn", "predictno", "predictnumber"])
def cmd_predict_number(message):
    ensure_user(message)
    if is_user_frozen(message.from_user.id):
        bot.reply_to(message, "❄️ Your account is currently frozen.")
        return
    if not is_game_enabled("pn"):
        bot.reply_to(message, "Predict Number is currently disabled.")
        return
    parts = message.text.split()
    if len(parts) != 3:
        bot.reply_to(message, "Usage: /pn <amount|all|half> <number 1-100>")
        return
    bet_amount = resolve_amount(message.from_user.id, parts[1])
    if bet_amount is None:
        bot.reply_to(message, "Amount must be a number, 'all', or 'half'.")
        return
    try:
        guess = int(parts[2])
    except ValueError:
        bot.reply_to(message, "Number must be a whole number between 1 and 100.")
        return
    play_predict_number(bot, message.chat.id, message.from_user.id, bet_amount, guess, name_of(message.from_user))


# --- ANIMATED TELEGRAM EMOJI GAMES (Basketball, Darts, Slots, Football, Bowling) ---

@bot.message_handler(commands=["basket", "basketball", "darts", "dart", "slots", "slot", "football", "bowl", "bowling"])
def cmd_animated_games(message):
    ensure_user(message)
    if is_user_frozen(message.from_user.id):
        bot.reply_to(message, "❄️ Your account is currently frozen.")
        return

    raw_cmd = message.text.split()[0].lower()
    cmd = raw_cmd.replace("/", "").split("@")[0]
    parts = message.text.split()

    if len(parts) < 2:
        bot.reply_to(message, f"Usage: /{cmd} <amount|all|half>\nExample: /{cmd} 10")
        return

    bet_amount = resolve_amount(message.from_user.id, parts[1])
    if bet_amount is None:
        bot.reply_to(message, "Amount must be a number, 'all', or 'half'.")
        return

    alias_map = {
        "dart": "darts",
        "slot": "slots",
        "bowl": "bowling",
        "basketball": "basket"
    }
    game_type = alias_map.get(cmd, cmd)

    play_animated_game(bot, message, message.from_user.id, bet_amount, game_type, name_of(message.from_user))
