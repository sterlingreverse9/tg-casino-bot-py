import html
from bot_instance import bot
from games.dice import play_dice_roll, cb_dice_play

# Try importing game engines if they exist in games/
try:
    from games.coinflip import play_coinflip
except ImportError:
    play_coinflip = None

try:
    from games.limbo import play_limbo
except ImportError:
    play_limbo = None


def get_args(message):
    parts = message.text.split()
    return parts[1:] if len(parts) > 1 else []


# ==================== DICE ROLL HANDLER ====================
@bot.message_handler(commands=["dr", "dice"])
def cmd_dice(message):
    args = get_args(message)
    if not args:
        bot.reply_to(
            message,
            "⚠️ <b>Usage:</b> <code>/dr &lt;amount&gt; [choice]</code>\n"
            "<i>Choices: high, low, odd, even, 1-6</i>",
            parse_mode="HTML"
        )
        return

    try:
        bet_amount = float(args[0])
    except ValueError:
        bot.reply_to(message, "❌ Invalid bet amount!")
        return

    choice = args[1] if len(args) > 1 else None
    play_dice_roll(
        bot=bot,
        chat_id=message.chat.id,
        telegram_id=message.from_user.id,
        bet_amount=bet_amount,
        choice=choice,
        display_name=message.from_user.first_name or "Player"
    )


# ==================== COINFLIP HANDLER ====================
@bot.message_handler(commands=["cf", "coinflip"])
def cmd_coinflip(message):
    args = get_args(message)
    if not args:
        bot.reply_to(
            message,
            "⚠️ <b>Usage:</b> <code>/cf &lt;amount&gt; &lt;heads|tails&gt;</code>",
            parse_mode="HTML"
        )
        return

    if not play_coinflip:
        bot.reply_to(message, "⚠️ Coinflip engine module is missing!")
        return

    try:
        bet_amount = float(args[0])
        choice = args[1] if len(args) > 1 else "heads"
    except (ValueError, IndexError):
        bot.reply_to(message, "❌ Usage: <code>/cf &lt;amount&gt; &lt;heads|tails&gt;</code>", parse_mode="HTML")
        return

    play_coinflip(
        bot=bot,
        chat_id=message.chat.id,
        telegram_id=message.from_user.id,
        bet_amount=bet_amount,
        choice=choice,
        display_name=message.from_user.first_name or "Player"
    )


# ==================== LIMBO HANDLER ====================
@bot.message_handler(commands=["limbo", "lb"])
def cmd_limbo(message):
    args = get_args(message)
    if not args:
        bot.reply_to(
            message,
            "⚠️ <b>Usage:</b> <code>/limbo &lt;amount&gt; &lt;target_multiplier&gt;</code>",
            parse_mode="HTML"
        )
        return

    if not play_limbo:
        bot.reply_to(message, "⚠️ Limbo engine module is missing!")
        return

    try:
        bet_amount = float(args[0])
        target = float(args[1]) if len(args) > 1 else 2.0
    except (ValueError, IndexError):
        bot.reply_to(message, "❌ Usage: <code>/limbo &lt;amount&gt; &lt;target_multiplier&gt;</code>", parse_mode="HTML")
        return

    play_limbo(
        bot=bot,
        chat_id=message.chat.id,
        telegram_id=message.from_user.id,
        bet_amount=bet_amount,
        target_multiplier=target,
        display_name=message.from_user.first_name or "Player"
    )
