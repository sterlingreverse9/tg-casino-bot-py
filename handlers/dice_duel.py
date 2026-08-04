import html
import time
import threading
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton

from wallet import get_balance, adjust_balance, record_bet
import settings
from helpers import announce_win

# --- Helper Functions for Settings ---
def get_min_bet():
    return settings.get_min_bet() if hasattr(settings, "get_min_bet") else 10.0

def get_house_balance():
    return settings.get_house_balance() if hasattr(settings, "get_house_balance") else 10000.0

def get_max_bet():
    hb = get_house_balance()
    if hasattr(settings, "get_max_bet"):
        try:
            return settings.get_max_bet(hb)
        except Exception:
            return settings.get_max_bet()
    return 1000.0

def get_house_edge():
    if hasattr(settings, "get_house_edge"):
        val = settings.get_house_edge()
        return val() if callable(val) else val
    return 0.05


# --- Game Storage & Constants ---
# Game Commands Mapping
GAME_EMOJIS = {
    "/dice": "🎲",
    "/duel": "🎲",
    "/bowl": "🎳",
    "/basket": "🏀",
    "/slots": "🎰",
    "/foot": "⚽",
    "/dart": "🎯"
}

ALLOWED_COMMANDS = list(GAME_EMOJIS.keys())

# Active Games Structures
# active_bot_games[chat_id][telegram_id] = game_dict
active_bot_games = {}

# active_pvp_challenges[challenge_id] = challenge_dict
active_pvp_challenges = {}

pvp_lock = threading.Lock()


# --- Setup Handler Main Function ---
def setup_dice_handlers(bot):

    @bot.message_handler(commands=["dice", "duel", "bowl", "basket", "slots", "foot", "dart"])
    def initiate_game_cmd(message):
        chat_id = message.chat.id
        user = message.from_user
        telegram_id = user.id
        
        # Strict Command Extraction (Prevents /dr or /deposit triggers)
        cmd = message.text.split()[0].lower().split("@")[0]
        if cmd not in ALLOWED_COMMANDS:
            return

        emoji = GAME_EMOJIS[cmd]
        args = message.text.split()[1:]

        min_b = get_min_bet()
        max_b = get_max_bet()

        if not args:
            bot.reply_to(
                message,
                f"<b>{emoji} Game Usage:</b>\n"
                f"• Single Round: <code>{cmd} &lt;amount&gt;</code>\n"
                f"• Best of N Rounds: <code>{cmd} &lt;amount&gt; &lt;rounds&gt;</code>\n"
                f"📌 Min Bet: ₹{min_b} | Max Bet: ₹{max_b}",
                parse_mode="HTML"
            )
            return

        try:
            bet_amount = float(args[0])
        except ValueError:
            bot.reply_to(message, "❌ Invalid bet amount.")
            return

        rounds = 1
        if len(args) >= 2 and args[1].isdigit():
            rounds = int(args[1])
            if rounds < 1 or rounds > 10:
                bot.reply_to(message, "⚠️ Rounds must be between 1 and 10.")
                return

        if bet_amount < min_b or bet_amount > max_b:
            bot.reply_to(message, f"⚠️ Bet must be between ₹{min_b} and ₹{max_b}.")
            return

        user_bal = get_balance(telegram_id)
        if user_bal < bet_amount:
            bot.reply_to(message, "❌ Insufficient balance for this bet.")
            return

        # Check existing active game in this chat
        if chat_id in active_bot_games and telegram_id in active_bot_games[chat_id]:
            bot.reply_to(message, "⚠️ You already have an ongoing game in this chat! Complete it first.")
            return

        # Register Single Player vs Bot Game
        if chat_id not in active_bot_games:
            active_bot_games[chat_id] = {}

        active_bot_games[chat_id][telegram_id] = {
            "bet_amount": bet_amount,
            "rounds": rounds,
            "current_round": 1,
            "player_total": 0,
            "bot_total": 0,
            "emoji": emoji,
            "username": user.username,
            "first_name": user.first_name,
            "created_at": time.time()
        }

        safe_name = html.escape(user.first_name or "Player")
        user_mention = f"@{user.username}" if user.username else f'<a href="tg://user?id={telegram_id}">{safe_name}</a>'

        bot.send_message(
            chat_id,
            f"🎮 <b>Game Started!</b>\n\n"
            f"👤 <b>Player:</b> {user_mention}\n"
            f"💵 <b>Bet:</b> ₹{bet_amount:.2f}\n"
            f"🔄 <b>Rounds:</b> {rounds}\n\n"
            f"👉 Send {emoji} to roll for <b>Round 1</b>!",
            parse_mode="HTML"
        )


    # --- Listen for Dice Rolls ---
    @bot.message_handler(content_types=["dice"])
    def handle_dice_roll(message):
        chat_id = message.chat.id
        telegram_id = message.from_user.id
        rolled_emoji = message.dice.emoji
        dice_val = message.dice.value

        if chat_id not in active_bot_games or telegram_id not in active_bot_games[chat_id]:
            return

        game = active_bot_games[chat_id][telegram_id]

        # Ensure correct emoji match
        if game["emoji"] != rolled_emoji:
            return

        # Process Turn
        bet_amount = game["bet_amount"]
        curr_round = game["current_round"]
        rounds = game["rounds"]
        username = game["username"]
        first_name = game["first_name"]

        safe_name = html.escape(first_name or "Player")
        user_mention = f"@{username}" if username else f'<a href="tg://user?id={telegram_id}">{safe_name}</a>'

        # Deduct bet on Round 1
        if curr_round == 1 and game["player_total"] == 0 and game["bot_total"] == 0:
            if get_balance(telegram_id) < bet_amount:
                bot.reply_to(message, "❌ Insufficient balance.")
                del active_bot_games[chat_id][telegram_id]
                return
            adjust_balance(telegram_id, -bet_amount)

        game["player_total"] += dice_val

        # Bot rolls back
        time.sleep(1.0)
        msg_bot = bot.send_dice(chat_id, emoji=rolled_emoji)
        game["bot_total"] += msg_bot.dice.value
        time.sleep(1.5)

        # Multi-round progression
        if curr_round < rounds:
            game["current_round"] += 1
            next_r = game["current_round"]
            bot.send_message(
                chat_id,
                f"📊 <b>Score:</b> You {game['player_total']} - {game['bot_total']} Bot\n"
                f"🎯 {user_mention}, send <b>{rolled_emoji}</b> for <b>Round {next_r} of {rounds}</b>!",
                parse_mode="HTML"
            )
            return

        # Final Evaluation
        p_score = game["player_total"]
        b_score = game["bot_total"]
        edge = get_house_edge()

        if p_score > b_score:
            payout = round(bet_amount * (2.0 - edge), 2)
            adjust_balance(telegram_id, payout)
            record_bet(telegram_id, "dice_duel", bet_amount, payout, "win")
            net_profit = payout - bet_amount

            bot.send_message(
                chat_id,
                f"🎉 {user_mention} <b>YOU WON!</b>\n\n"
                f"👤 <b>Your Score:</b> {p_score}\n"
                f"🤖 <b>Bot Score:</b> {b_score}\n"
                f"💵 <b>Payout:</b> ₹{payout:.2f} (+₹{net_profit:.2f})",
                parse_mode="HTML"
            )
            announce_win(username or first_name or "Player", payout, f"{rolled_emoji} Game")

        elif p_score < b_score:
            record_bet(telegram_id, "dice_duel", bet_amount, 0.0, "loss")
            bot.send_message(
                chat_id,
                f"💥 {user_mention} <b>YOU LOST!</b>\n\n"
                f"👤 <b>Your Score:</b> {p_score}\n"
                f"🤖 <b>Bot Score:</b> {b_score}\n"
                f"💸 <b>Loss:</b> ₹{bet_amount:.2f}",
                parse_mode="HTML"
            )

        else:
            # Refund Push
            adjust_balance(telegram_id, bet_amount)
            record_bet(telegram_id, "dice_duel", bet_amount, bet_amount, "push")
            bot.send_message(
                chat_id,
                f"🤝 {user_mention} <b>IT'S A TIE!</b>\n\n"
                f"👤 <b>Your Score:</b> {p_score}\n"
                f"🤖 <b>Bot Score:</b> {b_score}\n"
                f"🔄 Your bet of ₹{bet_amount:.2f} was returned.",
                parse_mode="HTML"
            )

        # Clean active state
        del active_bot_games[chat_id][telegram_id]
