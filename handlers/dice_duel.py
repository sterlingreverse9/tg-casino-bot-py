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


def setup_dice_handlers(bot):
    all_commands = []
    for cfg in EMOJI_GAME_CONFIG.values():
        all_commands.extend(cfg["aliases"])

    @bot.message_handler(commands=all_commands)
    def handle_emoji_game_command(message):
        try:
            from games.dice_duel import start_dice_game_step

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
            user_ref = f"@{username}" if username else safe_name

            if len(args) == 1:
                help_text = (
                    f"<b>{emoji} {label}</b>\n\n"
                    f"<b>vs Bot:</b>\n"
                    f"<code>/{main_cmd} 50</code> — 1 round\n"
                    f"<code>/{main_cmd} 50 3</code> — 3 rounds\n\n"
                    f"<b>vs Player:</b>\n"
                    f"<code>/{main_cmd} @user 50</code> — challenge a player\n"
                    f"<code>/{main_cmd} @user 50 3</code> — with amount only; rounds & mode selected via buttons"
                )
                bot.send_message(chat_id, help_text, parse_mode="HTML")
                return

            if args[1].startswith("@"):
                bot.send_message(chat_id, "PvP challenges coming soon!")
                return

            try:
                bet_amount = float(args[1])
            except ValueError:
                bot.send_message(chat_id, "Invalid bet amount.")
                return

            rounds = 1
            if len(args) >= 3:
                try:
                    rounds = int(args[2])
                    if rounds < 1 or rounds > 5:
                        bot.send_message(chat_id, "Rounds must be between 1 and 5.")
                        return
                except ValueError:
                    bot.send_message(chat_id, "Invalid number of rounds.")
                    return

            balance = get_balance(telegram_id)
            min_bet = get_min_bet()
            max_bet = get_max_bet(get_house_balance())

            if balance < bet_amount:
                formatted_bal = int(balance) if balance.is_integer() else balance
                bot.send_message(
                    chat_id,
                    f"❌ {user_ref} Not quite enough in the tank 💸 — you've got ₹{formatted_bal}",
                    parse_mode="HTML",
                )
                return

            if bet_amount < min_bet:
                bot.send_message(chat_id, f"Minimum bet is ₹{min_bet}.")
                return

            if bet_amount > max_bet:
                bot.send_message(chat_id, f"Maximum bet is ₹{round(max_bet, 2)}.")
                return

            start_dice_game_step(
                bot=bot,
                chat_id=chat_id,
                telegram_id=telegram_id,
                bet_amount=bet_amount,
                rounds=rounds,
                username=username,
                first_name=first_name,
                emoji=emoji,
            )

        except Exception as e:
            print(f"Error in emoji game command handler: {e}")
