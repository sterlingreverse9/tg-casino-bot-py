import html
import time
import threading
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
from wallet import get_balance, adjust_balance
from settings import get_min_bet, get_max_bet, get_house_balance
from helpers import ensure_user, is_user_frozen

EMOJI_GAME_CONFIG = {
    "dice": {"emoji": "🎲", "label": "Dice", "aliases": ["dice", "dr"]},
    "dart": {"emoji": "🎯", "label": "Darts", "aliases": ["dart", "darts"]},
    "basket": {"emoji": "🏀", "label": "Basketball", "aliases": ["basket", "basketball"]},
    "slots": {"emoji": "🎰", "label": "Slots", "aliases": ["slots", "slot"]},
    "foot": {"emoji": "⚽", "label": "Football", "aliases": ["foot", "football"]},
    "bowl": {"emoji": "🎳", "label": "Bowling", "aliases": ["bowl", "bowling"]},
}

# State Tracking
PENDING_CHALLENGES = {}  # { challenge_id: {...} }
ACTIVE_BOT_GAMES = {}    # { user_id: {...} }
ACTIVE_PVP_GAMES = {}    # { game_id: {...} }
TIMERS = {}              # { game_id: Threading.Timer }


def get_mention(user):
    """Returns @username or HTML link fallback if username is missing."""
    if getattr(user, "username", None):
        return f"@{user.username}"
    first_name = html.escape(user.first_name or "User")
    return f'<a href="tg://user?id={user.id}">{first_name}</a>'


def setup_dice_handlers(bot):
    all_commands = []
    for cfg in EMOJI_GAME_CONFIG.values():
        all_commands.extend(cfg["aliases"])

    # ------------------------------------------------------------------
    # 1. COMMAND HANDLER
    # ------------------------------------------------------------------
    @bot.message_handler(commands=all_commands)
    def handle_game_command(message):
        try:
            ensure_user(message)
            user = message.from_user
            user_mention = get_mention(user)

            if is_user_frozen(user.id):
                bot.reply_to(message, f"❄️ {user_mention}, your account is currently frozen.", parse_mode="HTML")
                return

            raw_text = message.text.strip()
            bot_username = bot.get_me().username
            if bot_username and f"@{bot_username}" in raw_text:
                raw_text = raw_text.replace(f"@{bot_username}", "")

            args = raw_text.split()
            cmd_name = args[0].lstrip("/").lower()

            # Identify Game Type
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

            # Show Guide if no args
            if len(args) == 1:
                guide_text = (
                    f"<b>{emoji} {label} Game Guide</b>\n\n"
                    f"<b>🎮 Play vs Bot:</b>\n"
                    f"• <code>/{main_cmd} 10</code> — Play 1 Round\n"
                    f"• <code>/{main_cmd} 10 3</code> — Play Best of 3 Rounds\n\n"
                    f"<b>⚔️ Play vs Player (PvP):</b>\n"
                    f"• <code>/{main_cmd} 10 @username</code> — Challenge player (1 round)\n"
                    f"• <code>/{main_cmd} 10 3 @username</code> — Challenge player (3 rounds)"
                )
                bot.send_message(chat_id, guide_text, parse_mode="HTML")
                return

            # Parse command parameters: Bet, Rounds, Target User
            target_username = None
            bet_amount = None
            rounds = 1

            for arg in args[1:]:
                if arg.startswith("@"):
                    target_username = arg.lstrip("@").lower()
                elif bet_amount is None:
                    try:
                        bet_amount = float(arg)
                    except ValueError:
                        pass
                else:
                    try:
                        rounds = int(arg)
                    except ValueError:
                        pass

            if bet_amount is None or bet_amount <= 0:
                bot.send_message(chat_id, f"⚠️ {user_mention}, please specify a valid bet amount.", parse_mode="HTML")
                return

            if rounds < 1 or rounds > 10:
                bot.send_message(chat_id, f"⚠️ {user_mention}, rounds must be between 1 and 10.", parse_mode="HTML")
                return

            # Validate Wager Limits
            min_bet = get_min_bet()
            max_bet = get_max_bet(get_house_balance())

            if bet_amount < min_bet:
                bot.send_message(chat_id, f"⚠️ {user_mention}, minimum bet is ₹{min_bet}.", parse_mode="HTML")
                return
            if bet_amount > max_bet:
                bot.send_message(chat_id, f"⚠️ {user_mention}, maximum bet is ₹{round(max_bet, 2)}.", parse_mode="HTML")
                return

            user_bal = get_balance(user.id)
            if user_bal < bet_amount:
                bot.send_message(chat_id, f"❌ {user_mention}, you don't have enough balance! (Balance: ₹{user_bal:.2f})", parse_mode="HTML")
                return

            # --- MODE 1: PVP VS PLAYER ---
            if target_username:
                if target_username == (user.username or "").lower():
                    bot.send_message(chat_id, f"❌ {user_mention}, you cannot challenge yourself!", parse_mode="HTML")
                    return

                challenge_id = f"chal_{user.id}_{int(time.time())}"
                PENDING_CHALLENGES[challenge_id] = {
                    "challenger_id": user.id,
                    "challenger_mention": user_mention,
                    "target_username": target_username,
                    "bet_amount": bet_amount,
                    "rounds": rounds,
                    "emoji": emoji,
                    "chat_id": chat_id,
                }

                markup = InlineKeyboardMarkup()
                markup.add(
                    InlineKeyboardButton("Accept ⚔️", callback_data=f"pvp_accept_{challenge_id}"),
                    InlineKeyboardButton("Reject ❌", callback_data=f"pvp_reject_{challenge_id}")
                )

                bot.send_message(
                    chat_id,
                    f"⚔️ <b>PvP Challenge Issued!</b> {emoji}\n\n"
                    f"👤 <b>Challenger:</b> {user_mention}\n"
                    f"🎯 <b>Challenged:</b> @{target_username}\n"
                    f"💵 <b>Stake:</b> ₹{bet_amount:.2f} each\n"
                    f"🔄 <b>Rounds:</b> {rounds}\n\n"
                    f"@{target_username}, accept or reject below:",
                    parse_mode="HTML",
                    reply_markup=markup
                )
                return

            # --- MODE 2: VS BOT ---
            if user.id in ACTIVE_BOT_GAMES:
                bot.send_message(chat_id, f"⚠️ {user_mention}, finish your current game first!", parse_mode="HTML")
                return

            adjust_balance(user.id, -bet_amount)

            ACTIVE_BOT_GAMES[user.id] = {
                "user_mention": user_mention,
                "bet_amount": bet_amount,
                "rounds": rounds,
                "current_round": 1,
                "user_wins": 0,
                "bot_wins": 0,
                "emoji": emoji,
                "chat_id": chat_id
            }

            bot.send_message(
                chat_id,
                f"🎮 {user_mention}, game started! (Round 1 of {rounds})\n"
                f"Send <b>{emoji}</b> now to make your roll!",
                parse_mode="HTML"
            )

        except Exception as e:
            print(f"[Game Command Error]: {e}")

    # ------------------------------------------------------------------
    # 2. PVP INLINE CALLBACKS
    # ------------------------------------------------------------------
    @bot.callback_query_handler(func=lambda call: call.data.startswith("pvp_"))
    def handle_pvp_callback(call):
        try:
            action, _, c_id = call.data.partition("_")[2].partition("_")
            c_id = f"{action}_{c_id}"

            if c_id not in PENDING_CHALLENGES:
                bot.answer_callback_query(call.id, "This challenge expired or is invalid.", show_alert=True)
                return

            chal = PENDING_CHALLENGES[c_id]
            clicker = call.from_user
            clicker_mention = get_mention(clicker)

            if (clicker.username or "").lower() != chal["target_username"]:
                bot.answer_callback_query(call.id, "This challenge is not for you!", show_alert=True)
                return

            if action == "reject":
                del PENDING_CHALLENGES[c_id]
                bot.answer_callback_query(call.id, "Challenge rejected.")
                bot.edit_message_text(f"❌ {clicker_mention} rejected the challenge from {chal['challenger_mention']}.", chal['chat_id'], call.message.message_id, parse_mode="HTML")
                return

            # Check target balance
            clicker_bal = get_balance(clicker.id)
            bet = chal["bet_amount"]
            if clicker_bal < bet:
                bot.answer_callback_query(call.id, f"You need ₹{bet:.2f} balance to accept!", show_alert=True)
                return

            # Deduct balance from both
            adjust_balance(chal["challenger_id"], -bet)
            adjust_balance(clicker.id, -bet)

            game_id = f"pvpgame_{c_id}"
            ACTIVE_PVP_GAMES[game_id] = {
                "game_id": game_id,
                "p1_id": chal["challenger_id"],
                "p1_mention": chal["challenger_mention"],
                "p2_id": clicker.id,
                "p2_mention": clicker_mention,
                "p1_wins": 0,
                "p2_wins": 0,
                "p1_roll": None,
                "p2_roll": None,
                "current_turn": chal["challenger_id"],
                "bet_amount": bet,
                "rounds": chal["rounds"],
                "current_round": 1,
                "emoji": chal["emoji"],
                "chat_id": chal["chat_id"]
            }

            del PENDING_CHALLENGES[c_id]
            bot.answer_callback_query(call.id, "Game Accepted!")

            bot.edit_message_text(
                f"⚔️ <b>PvP Game Started!</b> {chal['emoji']}\n\n"
                f"👥 <b>Players:</b> {chal['challenger_mention']} vs {clicker_mention}\n"
                f"💰 <b>Total Pot:</b> ₹{bet * 2:.2f}\n"
                f"🔄 <b>Round 1 of {chal['rounds']}</b>\n\n"
                f"👉 {chal['challenger_mention']}, send <b>{chal['emoji']}</b> now! (120s limit)",
                chal['chat_id'],
                call.message.message_id,
                parse_mode="HTML"
            )

            # Start AFK Timer for Turn 1
            start_afk_timer(bot, game_id)

        except Exception as e:
            print(f"[PvP Callback Error]: {e}")

    # ------------------------------------------------------------------
    # 3. DICE/EMOJI ROLL LISTENER
    # ------------------------------------------------------------------
    @bot.message_handler(content_types=["dice"])
    def handle_dice_roll(message):
        uid = message.from_user.id

        # --- PROCESS VS BOT GAME ---
        if uid in ACTIVE_BOT_GAMES:
            game = ACTIVE_BOT_GAMES[uid]
            if message.dice.emoji != game["emoji"]:
                return

            u_val = message.dice.value
            bot_msg = bot.send_dice(message.chat.id, emoji=game["emoji"])
            b_val = bot_msg.dice.value

            time.sleep(2)  # Wait for animation

            if u_val > b_val:
                game["user_wins"] += 1
                res = "You won this round! 🎉"
            elif b_val > u_val:
                game["bot_wins"] += 1
                res = "Bot won this round! 🤖"
            else:
                res = "It's a tie round! 🤝"

            # Check if game finishes
            req_wins = (game["rounds"] // 2) + 1
            if game["rounds"] == 1 or game["user_wins"] == req_wins or game["bot_wins"] == req_wins:
                finish_bot_game(bot, uid, game, u_val, b_val)
            else:
                game["current_round"] += 1
                bot.send_message(
                    message.chat.id,
                    f"📊 {game['user_mention']}, Round Result:\n"
                    f"You: <b>{u_val}</b> | Bot: <b>{b_val}</b> — {res}\n\n"
                    f"<b>Score:</b> You {game['user_wins']} - {game['bot_wins']} Bot\n"
                    f"👉 Send <b>{game['emoji']}</b> for Round {game['current_round']}!",
                    parse_mode="HTML"
                )
            return

        # --- PROCESS PVP GAME ---
        pvp_game = None
        for g in ACTIVE_PVP_GAMES.values():
            if uid in (g["p1_id"], g["p2_id"]):
                pvp_game = g
                break

        if not pvp_game or message.dice.emoji != pvp_game["emoji"]:
            return

        if uid != pvp_game["current_turn"]:
            bot.reply_to(message, f"⚠️ {get_mention(message.from_user)}, it's not your turn!", parse_mode="HTML")
            return

        # Reset AFK Timer on valid roll
        cancel_afk_timer(pvp_game["game_id"])

        if uid == pvp_game["p1_id"]:
            pvp_game["p1_roll"] = message.dice.value
            pvp_game["current_turn"] = pvp_game["p2_id"]
            bot.send_message(
                message.chat.id,
                f"{pvp_game['p1_mention']} rolled: <b>{message.dice.value}</b>\n\n"
                f"👉 {pvp_game['p2_mention']}, send <b>{pvp_game['emoji']}</b> now! (120s limit)",
                parse_mode="HTML"
            )
            start_afk_timer(bot, pvp_game["game_id"])
        else:
            pvp_game["p2_roll"] = message.dice.value
            process_pvp_round(bot, pvp_game)


# ----------------------------------------------------------------------
# HELPER FUNCTIONS & GAME LOGIC
# ----------------------------------------------------------------------
def finish_bot_game(bot, uid, game, u_val, b_val):
    pot = game["bet_amount"] * 2
    um = game["user_mention"]

    if game["user_wins"] > game["bot_wins"]:
        adjust_balance(uid, pot)
        msg = f"🏆 <b>YOU WIN!</b> {um}\nFinal Score: You <b>{u_val}</b> vs Bot <b>{b_val}</b>\n💰 Won: ₹{pot:.2f}"
    elif game["bot_wins"] > game["user_wins"]:
        msg = f"💀 <b>YOU LOST!</b> {um}\nFinal Score: You <b>{u_val}</b> vs Bot <b>{b_val}</b>\n💸 Lost: ₹{game['bet_amount']:.2f}"
    else:
        # Tie-breaker logic (Tie in 1 round = refund)
        adjust_balance(uid, game["bet_amount"])
        msg = f"🤝 <b>IT'S A DRAW!</b> {um}\nScore: <b>{u_val}</b> vs <b>{b_val}</b>\nStakes refunded."

    bot.send_message(game["chat_id"], msg, parse_mode="HTML")
    del ACTIVE_BOT_GAMES[uid]


def process_pvp_round(bot, game):
    p1_r = game["p1_roll"]
    p2_r = game["p2_roll"]

    if p1_r > p2_r:
        game["p1_wins"] += 1
        r_res = f"{game['p1_mention']} wins this round!"
    elif p2_r > p1_r:
        game["p2_wins"] += 1
        r_res = f"{game['p2_mention']} wins this round!"
    else:
        r_res = "Round Draw!"

    # Reset round rolls
    game["p1_roll"] = None
    game["p2_roll"] = None

    req_wins = (game["rounds"] // 2) + 1
    is_last = (game["current_round"] >= game["rounds"])

    if game["p1_wins"] == req_wins or game["p2_wins"] == req_wins or (is_last and game["p1_wins"] != game["p2_wins"]):
        finish_pvp_game(bot, game)
    elif is_last and game["p1_wins"] == game["p2_wins"]:
        # Tie Breaker Round!
        game["current_turn"] = game["p1_id"]
        bot.send_message(
            game["chat_id"],
            f"⚖️ <b>TIE! Playing 1 Extra Tie-Breaker Round!</b>\n\n"
            f"👉 {game['p1_mention']}, send <b>{game['emoji']}</b>!",
            parse_mode="HTML"
        )
        start_afk_timer(bot, game["game_id"])
    else:
        game["current_round"] += 1
        game["current_turn"] = game["p1_id"]
        bot.send_message(
            game["chat_id"],
            f"📊 <b>Round {game['current_round'] - 1} Complete!</b>\n"
            f"{game['p1_mention']}: {p1_r} | {game['p2_mention']}: {p2_r} ({r_res})\n\n"
            f"👉 {game['p1_mention']}, send <b>{game['emoji']}</b> for Round {game['current_round']}!",
            parse_mode="HTML"
        )
        start_afk_timer(bot, game["game_id"])


def finish_pvp_game(bot, game):
    tot_pot = game["bet_amount"] * 2

    if game["p1_wins"] > game["p2_wins"]:
        adjust_balance(game["p1_id"], tot_pot)
        winner_text = f"🏆 {game['p1_mention']} WINS ₹{tot_pot:.2f}!"
    elif game["p2_wins"] > game["p1_wins"]:
        adjust_balance(game["p2_id"], tot_pot)
        winner_text = f"🏆 {game['p2_mention']} WINS ₹{tot_pot:.2f}!"
    else:
        adjust_balance(game["p1_id"], game["bet_amount"])
        adjust_balance(game["p2_id"], game["bet_amount"])
        winner_text = "🤝 It's a DRAW! Both stakes refunded."

    res_msg = (
        f"🏁 <b>GAME OVER!</b> {game['emoji']}\n\n"
        f"👤 {game['p1_mention']} Wins: <b>{game['p1_wins']}</b>\n"
        f"👤 {game['p2_mention']} Wins: <b>{game['p2_wins']}</b>\n\n"
        f"{winner_text}"
    )
    bot.send_message(game["chat_id"], res_msg, parse_mode="HTML")
    del ACTIVE_PVP_GAMES[game["game_id"]]


# ----------------------------------------------------------------------
# 4. AFK TIMEOUT HANDLER (120 SECONDS)
# ----------------------------------------------------------------------
def start_afk_timer(bot, game_id):
    cancel_afk_timer(game_id)
    t = threading.Timer(120.0, handle_afk_timeout, args=[bot, game_id])
    TIMERS[game_id] = t
    t.start()


def cancel_afk_timer(game_id):
    if game_id in TIMERS:
        TIMERS[game_id].cancel()
        del TIMERS[game_id]


def handle_afk_timeout(bot, game_id):
    if game_id not in ACTIVE_PVP_GAMES:
        return

    game = ACTIVE_PVP_GAMES[game_id]
    afk_id = game["current_turn"]

    if afk_id == game["p1_id"]:
        afk_mention = game["p1_mention"]
        winner_id = game["p2_id"]
        winner_mention = game["p2_mention"]
    else:
        afk_mention = game["p2_mention"]
        winner_id = game["p1_id"]
        winner_mention = game["p1_mention"]

    total_pot = game["bet_amount"] * 2
    winner_share = total_pot * 0.50  # 50% to winner, 50% retained by house

    adjust_balance(winner_id, winner_share)

    bot.send_message(
        game["chat_id"],
        f"⏰ <b>TIMEOUT AFK FORFEIT!</b>\n\n"
        f"❌ {afk_mention} took longer than 120s to roll and forfeits!\n"
        f"🏆 {winner_mention} wins <b>₹{winner_share:.2f}</b> (50% share).\n"
        f"🏛️ <b>₹{winner_share:.2f}</b> goes to House penalty fee.",
        parse_mode="HTML"
    )

    del ACTIVE_PVP_GAMES[game_id]
    cancel_afk_timer(game_id)
