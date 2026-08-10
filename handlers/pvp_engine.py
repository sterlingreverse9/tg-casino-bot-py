import time
import threading
from bot_instance import bot
from wallet import get_balance, adjust_balance, record_bet, update_wager
from helpers import announce_win
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton

MIN_BET = 5.0
MAX_BET = 50.0
PAYOUT_MULT = 1.8

# Active PvP match state tracking
ACTIVE_MATCHES = {}  # key: match_id
USER_MATCHES = {}    # key: user_id -> match_id

GAME_EMOJIS = {
    "dice": "🎲",
    "foot": "⚽",
    "dart": "🎯",
    "slots": "🎰",
    "basket": "🏀",
    "bowl": "🎳"
}

class PvPGame:
    def __init__(self, game_type, challenger_id, challenger_name, target_id, target_name, bet, rounds, is_bot):
        self.match_id = f"{challenger_id}_{int(time.time())}"
        self.game_type = game_type
        self.emoji = GAME_EMOJIS.get(game_type, "🎲")
        self.p1_id = challenger_id
        self.p1_name = challenger_name
        self.p2_id = target_id
        self.p2_name = target_name
        self.bet = bet
        self.total_rounds = rounds
        self.is_bot = is_bot
        
        self.accepted = is_bot
        self.current_round = 1
        self.p1_score = 0
        self.p2_score = 0
        self.current_turn = challenger_id
        
        self.turn_timer = None
        self.accept_timer = None

    def start_accept_timer(self, chat_id, message_id):
        def expire_accept():
            if not self.accepted:
                adjust_balance(self.p1_id, self.bet)
                cleanup_match(self.match_id)
                try:
                    bot.edit_message_text(
                        f"⏰ <b>Challenge Expired!</b>\n{self.p2_name} did not accept in time. ₹{self.bet:.2f} refunded.",
                        chat_id=chat_id,
                        message_id=message_id,
                        parse_mode="HTML"
                    )
                except Exception:
                    pass
        self.accept_timer = threading.Timer(120.0, expire_accept)
        self.accept_timer.start()


def cleanup_match(match_id):
    if match_id in ACTIVE_MATCHES:
        game = ACTIVE_MATCHES[match_id]
        if game.accept_timer:
            game.accept_timer.cancel()
        if game.turn_timer:
            game.turn_timer.cancel()
        USER_MATCHES.pop(game.p1_id, None)
        if game.p2_id:
            USER_MATCHES.pop(game.p2_id, None)
        ACTIVE_MATCHES.pop(match_id, None)


def create_pvp_challenge(bot_inst, message, game_type, args):
    user = message.from_user
    chat_id = message.chat.id

    if user.id in USER_MATCHES:
        bot_inst.reply_to(message, "⚠️ You are already in an active game or pending challenge!")
        return

    # Parse Arguments
    bet = MIN_BET
    rounds = 1
    target_user = None
    
    parsed_numbers = []
    for arg in args:
        if arg.startswith("@"):
            target_user = arg
        elif arg.isdigit() or arg.replace('.', '', 1).isdigit():
            parsed_numbers.append(float(arg))

    if len(parsed_numbers) >= 1:
        bet = parsed_numbers[0]
    if len(parsed_numbers) >= 2:
        rounds = int(parsed_numbers[1])

    if bet < MIN_BET or bet > MAX_BET:
        bot_inst.reply_to(message, f"⚠️ Bet amount must be between ₹{MIN_BET:.2f} and ₹{MAX_BET:.2f}")
        return

    balance = get_balance(user.id)
    if balance < bet:
        bot_inst.reply_to(message, f"❌ Insufficient balance! Your balance: ₹{balance:.2f}")
        return

    # Deduct bet for challenger
    adjust_balance(user.id, -bet)
    update_wager(user.id, bet)

    # Mode A: Playing vs Bot
    if not target_user:
        game = PvPGame(game_type, user.id, user.first_name, 0, "The Casino Bot", bet, rounds, is_bot=True)
        ACTIVE_MATCHES[game.match_id] = game
        USER_MATCHES[user.id] = game.match_id
        
        bot_inst.reply_to(
            message,
            f"{game.emoji} <b>{game_type.upper()} VS BOT Started!</b>\n"
            f"💰 <b>Bet:</b> ₹{bet:.2f} | 🎯 <b>Rounds:</b> {rounds}\n\n"
            f" Send {game.emoji} to roll your turn!",
            parse_mode="HTML"
        )
        reset_turn_timer(game, chat_id)
        return

    # Mode B: Challenging another player
    markup = InlineKeyboardMarkup()
    markup.add(
        InlineKeyboardButton("✅ Accept Challenge", callback_data=f"pvp_acc:{user.id}:{bet}:{rounds}:{game_type}"),
        InlineKeyboardButton("❌ Decline", callback_data=f"pvp_dec:{user.id}")
    )

    msg = bot_inst.send_message(
        chat_id,
        f"⚔️ <b>{game_type.upper()} PVP CHALLENGE!</b>\n\n"
        f"👤 <b>Challenger:</b> {user.first_name}\n"
        f"🎯 <b>Target:</b> {target_user}\n"
        f"💰 <b>Bet:</b> ₹{bet:.2f}\n"
        f"🔄 <b>Rounds:</b> {rounds}\n\n"
        f"⏳ <i>{target_user}, you have 120 seconds to accept!</i>",
        reply_markup=markup,
        parse_mode="HTML"
    )

    game = PvPGame(game_type, user.id, user.first_name, None, target_user, bet, rounds, is_bot=False)
    ACTIVE_MATCHES[game.match_id] = game
    USER_MATCHES[user.id] = game.match_id
    game.start_accept_timer(chat_id, msg.message_id)


def reset_turn_timer(game, chat_id):
    if game.turn_timer:
        game.turn_timer.cancel()

    def turn_timeout():
        # Current turn user forfeit
        winner_id = game.p2_id if game.current_turn == game.p1_id else game.p1_id
        winner_name = game.p2_name if game.current_turn == game.p1_id else game.p1_name
        loser_name = game.p1_name if game.current_turn == game.p1_id else game.p2_name

        payout = round(game.bet * PAYOUT_MULT, 2)
        if winner_id != 0:
            adjust_balance(winner_id, payout)

        bot.send_message(
            chat_id,
            f"⏳ <b>Time's up!</b> {loser_name} failed to roll within 60s.\n"
            f"🏆 <b>{winner_name}</b> wins ₹{payout:.2f} by forfeit!",
            parse_mode="HTML"
        )
        cleanup_match(game.match_id)

    game.turn_timer = threading.Timer(60.0, turn_timeout)
    game.turn_timer.start()


@bot.callback_query_handler(func=lambda call: call.data.startswith("pvp_acc:"))
def cb_accept_pvp(call):
    _, challenger_id, bet_str, rounds_str, game_type = call.data.split(":")
    challenger_id = int(challenger_id)
    bet = float(bet_str)
    rounds = int(rounds_str)
    
    target = call.from_user
    match_id = USER_MATCHES.get(challenger_id)
    
    if not match_id or match_id not in ACTIVE_MATCHES:
        bot.answer_callback_query(call.id, "Challenge no longer active!", show_alert=True)
        return

    game = ACTIVE_MATCHES[match_id]
    
    if target.id == challenger_id:
        bot.answer_callback_query(call.id, "You cannot accept your own challenge!", show_alert=True)
        return

    balance = get_balance(target.id)
    if balance < bet:
        bot.answer_callback_query(call.id, "Insufficient balance to accept!", show_alert=True)
        return

    # Deduct target balance
    adjust_balance(target.id, -bet)
    update_wager(target.id, bet)

    game.accepted = True
    game.p2_id = target.id
    game.p2_name = target.first_name
    USER_MATCHES[target.id] = game.match_id
    if game.accept_timer:
        game.accept_timer.cancel()

    bot.edit_message_text(
        f"⚔️ <b>MATCH STARTED!</b>\n\n"
        f"👤 {game.p1_name} vs 👤 {game.p2_name}\n"
        f"💰 Bet: ₹{bet:.2f} | Rounds: {rounds}\n\n"
        f"👉 <b>{game.p1_name}</b>, send {game.emoji} to start Round 1!",
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
        parse_mode="HTML"
    )
    reset_turn_timer(game, call.message.chat.id)


@bot.message_handler(content_types=['dice'])
def handle_pvp_dice_roll(message):
    user_id = message.from_user.id
    match_id = USER_MATCHES.get(user_id)

    if not match_id or match_id not in ACTIVE_MATCHES:
        return

    game = ACTIVE_MATCHES[match_id]
    if not game.accepted or game.current_turn != user_id:
        return

    # Process Roll
    val = message.dice.value
    chat_id = message.chat.id

    if user_id == game.p1_id:
        game.p1_score += val
        if game.is_bot:
            bot_dice = bot.send_dice(chat_id, emoji=game.emoji)
            game.p2_score += bot_dice.dice.value
            process_round_end(game, chat_id)
        else:
            game.current_turn = game.p2_id
            bot.send_message(chat_id, f"👉 <b>{game.p2_name}</b>, send {game.emoji} for your turn!", parse_mode="HTML")
            reset_turn_timer(game, chat_id)
    else:
        game.p2_score += val
        process_round_end(game, chat_id)


def process_round_end(game, chat_id):
    if game.current_round < game.total_rounds:
        game.current_round += 1
        game.current_turn = game.p1_id
        bot.send_message(
            chat_id,
            f"📊 <b>Scoreboard (Round {game.current_round - 1}/{game.total_rounds}):</b>\n"
            f"👤 {game.p1_name}: {game.p1_score}\n"
            f"👤 {game.p2_name}: {game.p2_score}\n\n"
            f"👉 <b>{game.p1_name}</b>, send {game.emoji} for Round {game.current_round}!",
            parse_mode="HTML"
        )
        reset_turn_timer(game, chat_id)
        return

    # Check Winner
    payout = round(game.bet * PAYOUT_MULT, 2)
    if game.p1_score > game.p2_score:
        winner_id, winner_name = game.p1_id, game.p1_name
    elif game.p2_score > game.p1_score:
        winner_id, winner_name = game.p2_id, game.p2_name
    else:
        # Tie-breaker
        game.total_rounds += 1
        game.current_turn = game.p1_id
        bot.send_message(
            chat_id,
            f"🤝 <b>TIE GAME ({game.p1_score} - {game.p2_score})!</b>\nStarting Tie-Breaker Round! 👉 {game.p1_name}, roll {game.emoji}!",
            parse_mode="HTML"
        )
        reset_turn_timer(game, chat_id)
        return

    # Award Winner
    if winner_id != 0:
        adjust_balance(winner_id, payout)
        record_bet(winner_id, game.game_type, game.bet, payout, "win")
        try:
            announce_win(bot, winner_id, winner_name, f"{game.game_type.title()} PvP", game.bet, payout)
        except Exception:
            pass

    bot.send_message(
        chat_id,
        f"🏆 <b>GAME OVER!</b>\n\n"
        f"👤 {game.p1_name}: <code>{game.p1_score}</code>\n"
        f"👤 {game.p2_name}: <code>{game.p2_score}</code>\n\n"
        f"🎉 <b>Winner: {winner_name}</b> (+₹{payout:.2f})",
        parse_mode="HTML"
    )
    cleanup_match(game.match_id)
