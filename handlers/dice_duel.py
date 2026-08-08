import html
import time
from wallet import get_balance, adjust_balance, record_bet
from pvp_state import set_active_duel, get_active_duel, clear_active_duel
from handlers.dice_duel_engine import process_user_roll


def setup_dice_handlers(bot):

    # Command Handler for /dice or /dr
    @bot.message_handler(commands=["dice", "dr"])
    def cmd_start_dice_duel(message):
        chat_id = message.chat.id
        user = message.from_user
        telegram_id = user.id
        username = user.username
        first_name = user.first_name

        # Parse bet amount
        args = message.text.split()[1:]
        try:
            bet_amount = float(args[0]) if args else 10.0
            if bet_amount <= 0:
                raise ValueError
        except ValueError:
            bot.reply_to(message, "⚠️ Please provide a valid positive bet amount (e.g. <code>/dice 10</code>).", parse_mode="HTML")
            return

        # Check balance before starting
        current_bal = float(get_balance(telegram_id))
        if current_bal < bet_amount:
            bot.reply_to(message, f"❌ Insufficient balance! Your current balance is ₹{current_bal:.2f}.")
            return

        # Initialize Game Session
        game_data = {
            "bet_amount": bet_amount,
            "rounds": 1,
            "current_round": 1,
            "player_total": 0,
            "bot_total": 0,
            "username": username,
            "first_name": first_name,
            "emoji": "🎲"
        }

        # Save session in pvp_state
        set_active_duel(telegram_id, game_data)

        safe_name = html.escape(first_name or "Player")
        user_mention = f"@{username}" if username else f'<a href="tg://user?id={telegram_id}">{safe_name}</a>'

        bot.send_message(
            chat_id,
            f"🎮 <b>Game Started!</b>\n\n"
            f"👤 <b>Player:</b> {user_mention}\n"
            f"💵 <b>Bet:</b> ₹{bet_amount:.2f}\n"
            f"🔄 <b>Target Rounds:</b> Best of 1\n\n"
            f"👉 Send 🎲 to roll for <b>Round 1</b>!",
            parse_mode="HTML"
        )
        print(f"[DICE HANDLER] Game registered for {telegram_id} | Bet: ₹{bet_amount:.2f}", flush=True)

    # Listen explicitly for Telegram Native Dice Animations
    @bot.message_handler(content_types=["dice"])
    def handle_dice_animation(message):
        user_id = message.from_user.id
        chat_id = message.chat.id

        # Check if user has an active session
        game_data = get_active_duel(user_id)
        if not game_data:
            return  # Ignore random dice rolls sent outside of active games

        # Match emoji type (ensures game only listens to 🎲 emoji)
        if message.dice.emoji != game_data.get("emoji", "🎲"):
            return

        user_dice_val = message.dice.value
        print(f"[DICE HANDLER] Captured roll {user_dice_val} from {user_id}", flush=True)

        # Process the roll inside engine
        process_user_roll(
            bot=bot,
            chat_id=chat_id,
            telegram_id=user_id,
            game_data=game_data,
            user_dice_val=user_dice_val
        )
