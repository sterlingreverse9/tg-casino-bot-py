import html
from bot_instance import bot
from games.dice import play_dice_roll, cb_dice_play  # Imports your dice logic & callback handler

# Helper function to extract parameters safely
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
            "<i>Choices: high, low, odd, even, or numbers 1-6</i>\n"
            "<i>Example: /dr 10 high</i>",
            parse_mode="HTML"
        )
        return

    try:
        bet_amount = float(args[0])
    except ValueError:
        bot.reply_to(message, "❌ Invalid bet amount! Please enter a valid number.")
        return

    choice = args[1] if len(args) > 1 else None
    display_name = message.from_user.first_name or "Player"

    play_dice_roll(
        bot=bot,
        chat_id=message.chat.id,
        telegram_id=message.from_user.id,
        bet_amount=bet_amount,
        choice=choice,
        display_name=display_name
    )


# ==================== COINFLIP HANDLER ====================
@bot.message_handler(commands=["cf", "coinflip"])
def cmd_coinflip(message):
    args = get_args(message)
    if not args:
        bot.reply_to(
            message,
            "⚠️ <b>Usage:</b> <code>/cf &lt;amount&gt; &lt;heads|tails&gt;</code>\n"
            "<i>Example: /cf 10 heads</i>",
            parse_mode="HTML"
        )
        return

    # Add your existing coinflip execution logic here
    bot.reply_to(message, "🪙 Coinflip game processing...")


# ==================== LIMBO HANDLER ====================
@bot.message_handler(commands=["limbo", "lb"])
def cmd_limbo(message):
    args = get_args(message)
    if not args:
        bot.reply_to(
            message,
            "⚠️ <b>Usage:</b> <code>/limbo &lt;amount&gt; &lt;target_multiplier&gt;</code>\n"
            "<i>Example: /limbo 10 2.0</i>",
            parse_mode="HTML"
        )
        return

    # Add your existing limbo execution logic here
    bot.reply_to(message, "🚀 Limbo game processing...")


# ==================== SLOTS HANDLER ====================
@bot.message_handler(commands=["slots", "slot"])
def cmd_slots(message):
    args = get_args(message)
    if not args:
        bot.reply_to(
            message,
            "⚠️ <b>Usage:</b> <code>/slots &lt;amount&gt;</code>\n"
            "<i>Example: /slots 10</i>",
            parse_mode="HTML"
        )
        return

    # Add your existing slots execution logic here
    bot.reply_to(message, "🎰 Slots game processing...")
