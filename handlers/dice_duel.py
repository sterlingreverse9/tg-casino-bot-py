import html
from games.dice_duel import run_dice_vs_bot, MIN_BET
from wallet import get_balance, get_house_balance
from settings import get_min_bet, get_max_bet


def setup_dice_handlers(bot):
    @bot.message_handler(commands=["dice"])
    def handle_dice_command(message):
        try:
            # Strip bot username if invoked via /dice@BotName
            raw_text = message.text
            bot_username = bot.get_me().username
            if bot_username and f"@{bot_username}" in raw_text:
                raw_text = raw_text.replace(f"@{bot_username}", "")

            args = raw_text.split()
            chat_id = message.chat.id
            telegram_id = message.from_user.id
            username = message.from_user.username
            
            # Format user reference safely with HTML escaping
            first_name = html.escape(message.from_user.first_name or "User")
            user_ref = f"@{username}" if username else first_name

            # Case 1: Send help menu if user types /dice alone
            if len(args) == 1:
                help_text = (
                    "<b>🎲 Dice</b>\n\n"
                    "<b>vs Bot:</b>\n"
                    "<code>/dice 50</code> — 1 round\n"
                    "<code>/dice 50 3</code> — 3 rounds\n\n"
                    "<b>vs Player:</b>\n"
                    "<code>/dice @user 50</code> — challenge a player\n"
                    "<code>/dice @user 50 3</code> — with amount only; rounds & mode selected via buttons"
                )
                bot.send_message(chat_id, help_text, parse_mode="HTML")
                return

            # Case 2: PvP Challenge
            if args[1].startswith("@"):
                bot.send_message(chat_id, "PvP challenges coming soon!")
                return

            # Parse Bet Amount
            try:
                bet_amount = float(args[1])
            except ValueError:
                bot.send_message(chat_id, "Invalid bet amount.")
                return

            # Parse Rounds (Default: 1)
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

            # Balance & Limit Checks
            balance = get_balance(telegram_id)
            min_bet = max(MIN_BET, get_min_bet())
            max_bet = get_max_bet(get_house_balance())

            if balance < bet_amount:
                formatted_bal = int(balance) if balance.is_integer() else balance
                bot.send_message(
                    chat_id,
                    f"❌ {user_ref} Not quite enough in the tank 💸 — you've got ₹{formatted_bal}",
                    parse_mode="HTML"
                )
                return

            if bet_amount < min_bet:
                bot.send_message(chat_id, f"Minimum bet is ₹{min_bet}.")
                return

            if bet_amount > max_bet:
                bot.send_message(chat_id, f"Maximum bet is ₹{round(max_bet, 2)}.")
                return

            # Run Game Logic
            run_dice_vs_bot(
                bot=bot,
                chat_id=chat_id,
                telegram_id=telegram_id,
                bet_amount=bet_amount,
                rounds=rounds,
                username=username
            )

        except Exception as e:
            print(f"Error in /dice command handler: {e}")
