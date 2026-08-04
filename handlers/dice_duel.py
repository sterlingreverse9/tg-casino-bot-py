import html
from wallet import get_balance, get_house_balance
from settings import get_min_bet, get_max_bet

EMOJI_GAME_CONFIG = {
    "dice": {"emoji": "🎲", "label": "Dice", "aliases": ["dice", "dr"]},
    "dart": {"emoji": "🎯", "label": "Darts", "aliases": ["dart", "darts"]},
    "basket": {"emoji": "🏀", "label": "Basketball", "aliases": ["basket", "basketball"]},
    "slots": {"emoji": "🎰", "label": "Slots", "aliases": ["slots", "slot"]},
    "foot": {"emoji": "⚽", "label": "Football", "aliases": ["foot", "football"]},
    "bowl": {"emoji": "🎳", "label": "Bowling", "aliases": ["bowl", "bowling"]},
}

# Stores active pending rolls: { user_id: { "emoji": "⚽", "bet_amount": 10.0, "rounds": 1 } }
PENDING_ROLLS = {}

def setup_dice_handlers(bot):
    all_commands = []
    for cfg in EMOJI_GAME_CONFIG.values():
        all_commands.extend(cfg["aliases"])

    @bot.message_handler(commands=all_commands)
    def handle_emoji_game_command(message):
        try:
            raw_text = message.text.strip()
            bot_username = bot.get_me().username
            if bot_username and f"@{bot_username}" in raw_text:
                raw_text = raw_text.replace(f"@{bot_username}", "")

            args = raw_text.split()
            cmd_name = args[0].lstrip("/").lower()

            game_cfg = None
            for cfg in EMOJI_GAME_CONFIG.values():
                if cmd_name in cfg["aliases"]:
                    game_cfg = cfg
                    break

            if not game_cfg:
                game_cfg = EMOJI_GAME_CONFIG["dice"]

            emoji = game_cfg["emoji"]
            label = game_cfg["label"]
            main_cmd = game_cfg["aliases"][0]

            chat_id = message.chat.id
            telegram_id = message.from_user.id
            username = message.from_user.username
            first_name = message.from_user.first_name or "User"

            safe_name = html.escape(first_name)
            # Tag user via @username or clickable HTML link
            user_mention = f"@{username}" if username else f'<a href="tg://user?id={telegram_id}">{safe_name}</a>'

            if len(args) == 1:
                help_text = (
                    f"<b>{emoji} {label}</b>\n\n"
                    f"<b>vs Bot:</b>\n"
                    f"<code>/{main_cmd} 50</code> — 1 round\n"
                    f"<code>/{main_cmd} 50 3</code> — 3 rounds\n\n"
                    f"<b>vs Player:</b>\n"
                    f"<code>/{main_cmd} @user 50</code> — challenge a player"
                )
                bot.send_message(chat_id, help_text, parse_mode="HTML")
                return

            if args[1].startswith("@"):
                bot.send_message(chat_id, "PvP challenges coming soon!")
                return

            try:
                bet_amount = float(args[1])
            except ValueError:
                bot.send_message(chat_id, f"⚠️ {user_mention}, invalid bet amount.", parse_mode="HTML")
                return

            rounds = 1
            if len(args) >= 3:
                try:
                    rounds = int(args[2])
                    if rounds < 1 or rounds > 5:
                        bot.send_message(chat_id, f"⚠️ {user_mention}, rounds must be between 1 and 5.", parse_mode="HTML")
                        return
                except ValueError:
                    bot.send_message(chat_id, f"⚠️ {user_mention}, invalid number of rounds.", parse_mode="HTML")
                    return

            balance = get_balance(telegram_id)
            min_bet = get_min_bet()
            max_bet = get_max_bet(get_house_balance())

            if balance < bet_amount:
                formatted_bal = int(balance) if balance.is_integer() else balance
                bot.send_message(
                    chat_id,
                    f"❌ {user_mention} Not quite enough in the tank 💸 — you've got ₹{formatted_bal}",
                    parse_mode="HTML",
                )
                return

            if bet_amount < min_bet:
                bot.send_message(chat_id, f"⚠️ {user_mention}, minimum bet is ₹{min_bet}.", parse_mode="HTML")
                return

            if bet_amount > max_bet:
                bot.send_message(chat_id, f"⚠️ {user_mention}, maximum bet is ₹{round(max_bet, 2)}.", parse_mode="HTML")
                return

            # Register pending roll for this user
            PENDING_ROLLS[telegram_id] = {
                "emoji": emoji,
                "bet_amount": bet_amount,
                "rounds": rounds,
                "username": username,
                "first_name": first_name,
            }

            bot.send_message(
                chat_id,
                f"🎯 {user_mention}, send <b>{emoji}</b> now to make your roll!",
                parse_mode="HTML"
            )

        except Exception as e:
            print(f"Error in emoji game command handler: {e}")

    # Listener for user's manually sent dice/emoji rolls
    @bot.message_handler(content_types=['dice'])
    def handle_user_dice_roll(message):
        telegram_id = message.from_user.id
        
        # Check if user has an active bet registered
        if telegram_id not in PENDING_ROLLS:
            return

        game_data = PENDING_ROLLS[telegram_id]

        # Verify if sent dice matches expected game emoji
        if message.dice.emoji != game_data["emoji"]:
            return

        # Clear pending state once handled
        del PENDING_ROLLS[telegram_id]

        from games.dice_duel import process_user_roll

        process_user_roll(
            bot=bot,
            chat_id=message.chat.id,
            telegram_id=telegram_id,
            bet_amount=game_data["bet_amount"],
            rounds=game_data["rounds"],
            username=game_data["username"],
            first_name=game_data["first_name"],
            emoji=game_data["emoji"],
            user_dice_val=message.dice.value
        )
