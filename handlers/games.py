from games.dice_roll import play_dice_roll
from games.animated_dice import play_animated_game

# Handlers example block inside handlers/games.py:
def handle_dice_roll_cmd(bot, message):
    try:
        parts = message.text.split()
        if len(parts) < 3:
            bot.reply_to(message, "Usage: /dr <amount> <high|low|even|odd|1-6>")
            return

        bet_amount = float(parts[1])
        choice = parts[2].lower()
        user_name = message.from_user.first_name

        play_dice_roll(
            bot=bot,
            chat_id=message.chat.id,
            telegram_id=message.from_user.id,
            bet_amount=bet_amount,
            choice=choice,
            display_name=user_name
        )
    except ValueError:
        bot.reply_to(message, "Invalid amount. Enter a valid number.")
