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

# active_bot_games[chat_id][telegram_id] = game_dict
active_bot_games = {}


def setup_dice_handlers(bot):

    @bot.message_handler(commands=["dice", "duel", "bowl", "basket", "slots", "foot", "dart"])
    def initiate_game_cmd(message):
        chat_id = message.chat.id
        user = message.from_user
        telegram_id = user.id
        
        # Strict Command Extraction
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

        if chat_id in active_bot_games and telegram_id in active_bot_games[chat_id]:
            bot.reply_to(message, "⚠️ You already have an ongoing game! Finish it first.")
            return

        if chat_id not in active_bot_games:
            active_bot_games[chat_id] = {}

        # Store Round Wins instead of raw total scores
        active_bot_games[chat_id][telegram_id] = {
            "bet_amount": bet_amount,
            "target_rounds": rounds,
            "current_round": 1,
            "player_wins": 0,
            "bot_wins": 0,
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
            f"🔄 <b>Target Rounds:</b> Best of {rounds}\n\n"
            f"👉 Send {emoji} to roll for <b>Round 1</b>!",
            parse_mode="HTML"
        )


    @bot.message_handler(content_types=["dice"])
    def handle_dice_roll(message):
        chat_id = message.chat.id
        telegram_id = message.from_user.id
        rolled_emoji = message.dice.emoji
        p_roll = message.dice.value

        if chat_id not in active_bot_games or telegram_id not in active_bot_games[chat_id]:
            return

        game = active_bot_games[chat_id][telegram_id]

        if game["emoji"] != rolled_emoji:
            return

        bet_amount = game["bet_amount"]
        curr_round = game["current_round"]
        target_rounds = game["target_rounds"]
        username = game["username"]
        first_name = game["first_name"]

        safe_name = html.escape(first_name or "Player")
        user_mention = f"@{username}" if username else f'<a href="tg://user?id={telegram_id}">{safe_name}</a>'

        # Deduct bet on first roll
        if curr_round == 1 and game["player_wins"] == 0 and game["bot_wins"] == 0:
            if get_balance(telegram_id) < bet_amount:
                bot.reply_to(message, "❌ Insufficient balance.")
                del active_bot_games[chat_id][telegram_id]
                return
            adjust_balance(telegram_id, -bet_amount)

        # Bot Roll
        time.sleep(1.0)
        msg_bot = bot.send_dice(chat_id, emoji=rolled_emoji)
        b_roll = msg_bot.dice.value
        time.sleep(1.2)

        # Compare individual round
        if p_roll > b_roll:
            game["player_wins"] += 1
            round_res = "You won this round! 🏆"
        elif b_roll > p_roll:
            game["bot_wins"] += 1
            round_res = "Bot won this round! 🤖"
        else:
            round_res = "Round Draw! 🤝 (No point awarded)"

        p_wins = game["player_wins"]
        b_wins = game["bot_wins"]

        # Check if game continues
        if curr_round < target_rounds:
            game["current_round"] += 1
            bot.send_message(
                chat_id,
                f"📊 <b>Round {curr_round} Result:</b> {round_res}\n"
                f"👤 You: {p_roll} | 🤖 Bot: {b_roll}\n\n"
                f"🏆 <b>Score:</b> You <b>{p_wins}</b> - <b>{b_wins}</b> Bot\n"
                f"🎯 {user_mention}, send <b>{rolled_emoji}</b> for <b>Round {game['current_round']} of {target_rounds}</b>!",
                parse_mode="HTML"
            )
            return

        # Handle Tie-Breaker if scores are equal at the end of scheduled rounds
        if p_wins == b_wins:
            game["current_round"] += 1
            bot.send_message(
                chat_id,
                f"📊 <b>Round {curr_round} Result:</b> {round_res}\n"
                f"🏆 <b>Score Tied:</b> {p_wins} - {b_wins}\n\n"
                f"⚔️ <b>TIE-BREAKER ROUND!</b> {user_mention}, send <b>{rolled_emoji}</b> to break the tie!",
                parse_mode="HTML"
            )
            return

        # Game Concluded - Final Winner Determination
        edge = get_house_edge()

        if p_wins > b_wins:
            payout = round(bet_amount * (2.0 - edge), 2)
            adjust_balance(telegram_id, payout)
            record_bet(telegram_id, "dice_duel", bet_amount, payout, "win")
            net_profit = payout - bet_amount

            bot.send_message(
                chat_id,
                f"🎉 {user_mention} <b>MATCH WON!</b>\n\n"
                f"👤 <b>Your Round Wins:</b> {p_wins}\n"
                f"🤖 <b>Bot Round Wins:</b> {b_wins}\n"
                f"💵 <b>Payout:</b> ₹{payout:.2f} (+₹{net_profit:.2f})",
                parse_mode="HTML"
            )
            announce_win(username or first_name or "Player", payout, f"{rolled_emoji} Game")

        else:
            record_bet(telegram_id, "dice_duel", bet_amount, 0.0, "loss")
            bot.send_message(
                chat_id,
                f"💥 {user_mention} <b>MATCH LOST!</b>\n\n"
                f"👤 <b>Your Round Wins:</b> {p_wins}\n"
                f"🤖 <b>Bot Round Wins:</b> {b_wins}\n"
                f"💸 <b>Loss:</b> ₹{bet_amount:.2f}",
                parse_mode="HTML"
            )

        del active_bot_games[chat_id][telegram_id]
