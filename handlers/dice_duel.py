import html
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
from wallet import get_balance, adjust_balance, get_wager_remaining
from settings import get_min_bet, get_max_bet, get_house_balance
from helpers import ensure_user, is_user_frozen, format_display_name

EMOJI_GAME_CONFIG = {
    "dice": {"emoji": "🎲", "label": "Dice", "aliases": ["dice", "dr"]},
    "dart": {"emoji": "🎯", "label": "Darts", "aliases": ["dart", "darts"]},
    "basket": {"emoji": "🏀", "label": "Basketball", "aliases": ["basket", "basketball"]},
    "slots": {"emoji": "🎰", "label": "Slots", "aliases": ["slots", "slot"]},
    "foot": {"emoji": "⚽", "label": "Football", "aliases": ["foot", "football"]},
    "bowl": {"emoji": "🎳", "label": "Bowling", "aliases": ["bowl", "bowling"]},
}

# Pending PvP Challenges: { challenge_id: { "challenger_id": int, "target_username": str, "target_id": int, "amount": float, ... } }
PENDING_CHALLENGES = {}

# Active PvP Games: { game_id: { "player1_id": int, "player2_id": int, "current_turn": int, "p1_score": 0, "p2_score": 0, ... } }
ACTIVE_PVP_GAMES = {}


def setup_dice_handlers(bot):
    all_commands = []
    for cfg in EMOJI_GAME_CONFIG.values():
        all_commands.extend(cfg["aliases"])

    @bot.message_handler(commands=all_commands)
    def handle_emoji_game_command(message):
        try:
            ensure_user(message)
            telegram_id = message.from_user.id

            if is_user_frozen(telegram_id):
                bot.reply_to(message, "❄️ Your account is currently frozen.")
                return

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

            # Usage Help
            if len(args) < 3 or not args[1].startswith("@"):
                help_text = (
                    f"⚔️ <b>{emoji} {label} PvP Challenge</b>\n"
                    f"━━━━━━━━━━━━━━━━━━━━━\n"
                    f"<b>Usage:</b>\n"
                    f"<code>/{main_cmd} @username 50</code> — Challenge a player (1 round)\n"
                    f"<code>/{main_cmd} @username 50 3</code> — Challenge for 3 rounds\n\n"
                    f"📌 <i>Both players bet equal amounts. Winner takes all!</i>"
                )
                bot.send_message(chat_id, help_text, parse_mode="HTML")
                return

            target_username = args[1].lstrip("@").strip()
            if target_username.lower() == (message.from_user.username or "").lower():
                bot.reply_to(message, "❌ You cannot challenge yourself!")
                return

            try:
                bet_amount = float(args[2])
            except ValueError:
                bot.reply_to(message, "⚠️ Invalid bet amount.")
                return

            rounds = 1
            if len(args) >= 4:
                try:
                    rounds = int(args[3])
                    if rounds < 1 or rounds > 5:
                        bot.reply_to(message, "⚠️ Rounds must be between 1 and 5.")
                        return
                except ValueError:
                    bot.reply_to(message, "⚠️ Invalid round number.")
                    return

            min_bet = get_min_bet()
            max_bet = get_max_bet(get_house_balance())

            if bet_amount < min_bet or bet_amount > max_bet:
                bot.reply_to(message, f"⚠️ Bet amount must be between ₹{min_bet} and ₹{round(max_bet, 2)}.")
                return

            challenger_bal = get_balance(telegram_id)
            if challenger_bal < bet_amount:
                bot.reply_to(message, f"❌ Insufficient balance! You have ₹{challenger_bal:.2f}.")
                return

            challenge_id = f"{telegram_id}_{int(message.date)}"
            PENDING_CHALLENGES[challenge_id] = {
                "challenger_id": telegram_id,
                "challenger_name": message.from_user.first_name,
                "challenger_user": message.from_user.username or "",
                "target_username": target_username.lower(),
                "bet_amount": bet_amount,
                "rounds": rounds,
                "emoji": emoji,
                "label": label,
                "chat_id": chat_id,
            }

            markup = InlineKeyboardMarkup()
            markup.add(
                InlineKeyboardButton("Accept Challenge ⚔️", callback_data=f"pvp_accept_{challenge_id}"),
                InlineKeyboardButton("Decline ❌", callback_data=f"pvp_decline_{challenge_id}"),
            )

            challenger_tag = f"@{message.from_user.username}" if message.from_user.username else html.escape(message.from_user.first_name)
            msg = (
                f"⚔️ <b>PVP CHALLENGE ISSUED!</b> {emoji}\n"
                f"━━━━━━━━━━━━━━━━━━━━━\n"
                f"👤 <b>Challenger:</b> {challenger_tag}\n"
                f"🎯 <b>Target:</b> @{target_username}\n"
                f"💵 <b>Stake:</b> ₹{bet_amount:.2f} each\n"
                f"🏆 <b>Total Pot:</b> ₹{bet_amount * 2:.2f}\n"
                f"🔄 <b>Rounds:</b> {rounds}\n"
                f"━━━━━━━━━━━━━━━━━━━━━\n\n"
                f"👇 @{target_username}, click below to accept or decline:"
            )
            bot.send_message(chat_id, msg, parse_mode="HTML", reply_markup=markup)

        except Exception as e:
            print(f"[PvP Command Error]: {e}")

    @bot.callback_query_handler(func=lambda call: call.data.startswith("pvp_"))
    def handle_pvp_callbacks(call):
        try:
            action, _, challenge_id = call.data.partition("_")[2].partition("_")
            challenge_id = f"{action}_{challenge_id}" if not action.startswith("accept") and not action.startswith("decline") else challenge_id
            
            # Extract real action & challenge_id safely
            parts = call.data.split("_")
            action = parts[1]
            c_id = "_".join(parts[2:])

            if c_id not in PENDING_CHALLENGES:
                bot.answer_callback_query(call.id, "This challenge has expired.", show_alert=True)
                return

            ch = PENDING_CHALLENGES[c_id]
            user = call.from_user

            if (user.username or "").lower() != ch["target_username"]:
                bot.answer_callback_query(call.id, "This challenge is not for you!", show_alert=True)
                return

            if action == "decline":
                del PENDING_CHALLENGES[c_id]
                bot.answer_callback_query(call.id, "Challenge declined.")
                bot.edit_message_text("❌ Challenge was declined.", call.message.chat.id, call.message.message_id)
                return

            if is_user_frozen(user.id):
                bot.answer_callback_query(call.id, "❄️ Your account is frozen.", show_alert=True)
                return

            target_bal = get_balance(user.id)
            bet_amt = ch["bet_amount"]

            if target_bal < bet_amt:
                bot.answer_callback_query(call.id, f"Insufficient balance! You need ₹{bet_amt:.2f}.", show_alert=True)
                return

            # Deduct bets from both players
            adjust_balance(ch["challenger_id"], -bet_amt)
            adjust_balance(user.id, -bet_amt)

            # Start active PvP Game
            game_id = f"game_{c_id}"
            ACTIVE_PVP_GAMES[game_id] = {
                "p1_id": ch["challenger_id"],
                "p1_name": ch["challenger_name"],
                "p2_id": user.id,
                "p2_name": user.first_name,
                "p1_score": 0,
                "p2_score": 0,
                "current_turn": ch["challenger_id"],
                "emoji": ch["emoji"],
                "bet_amount": bet_amt,
                "rounds": ch["rounds"],
                "current_round": 1,
                "chat_id": ch["chat_id"],
            }

            del PENDING_CHALLENGES[c_id]
            bot.answer_callback_query(call.id, "Challenge accepted!")

            p1_tag = f"<a href='tg://user?id={ch['challenger_id']}'>{html.escape(ch['challenger_name'])}</a>"
            
            start_msg = (
                f"🚀 <b>PVP GAME STARTED!</b> {ch['emoji']}\n"
                f"━━━━━━━━━━━━━━━━━━━━━\n"
                f"🏆 <b>Prize Pool:</b> ₹{bet_amt * 2:.2f}\n"
                f"🔄 <b>Round 1 of {ch['rounds']}</b>\n"
                f"━━━━━━━━━━━━━━━━━━━━━\n\n"
                f"👉 {p1_tag}, send <b>{ch['emoji']}</b> now to take your turn!"
            )
            bot.edit_message_text(start_msg, call.message.chat.id, call.message.message_id, parse_mode="HTML")

        except Exception as e:
            print(f"[PvP Callback Error]: {e}")

    @bot.message_handler(content_types=["dice"])
    def handle_pvp_dice_roll(message):
        try:
            telegram_id = message.from_user.id

            # Find matching active PvP game
            game_id = None
            game = None
            for gid, gdata in ACTIVE_PVP_GAMES.items():
                if telegram_id in (gdata["p1_id"], gdata["p2_id"]):
                    game_id = gid
                    game = gdata
                    break

            if not game or message.dice.emoji != game["emoji"]:
                return

            if telegram_id != game["current_turn"]:
                bot.reply_to(message, "⚠️ It's not your turn!")
                return

            val = message.dice.value
            is_p1 = telegram_id == game["p1_id"]

            if is_p1:
                game["p1_score"] += val
                game["current_turn"] = game["p2_id"]
                p2_tag = f"<a href='tg://user?id={game['p2_id']}'>{html.escape(game['p2_name'])}</a>"
                bot.send_message(
                    message.chat.id,
                    f"🎲 <b>{html.escape(game['p1_name'])}</b> rolled: <b>{val}</b>\n\n👉 {p2_tag}, your turn! Send <b>{game['emoji']}</b>.",
                    parse_mode="HTML",
                )
            else:
                game["p2_score"] += val
                
                # Check if more rounds remain
                if game["current_round"] < game["rounds"]:
                    game["current_round"] += 1
                    game["current_turn"] = game["p1_id"]
                    p1_tag = f"<a href='tg://user?id={game['p1_id']}'>{html.escape(game['p1_name'])}</a>"
                    bot.send_message(
                        message.chat.id,
                        f"🎲 <b>{html.escape(game['p2_name'])}</b> rolled: <b>{val}</b>\n\n"
                        f"📊 <b>Scores after Round {game['current_round']-1}:</b>\n"
                        f"• {game['p1_name']}: {game['p1_score']}\n"
                        f"• {game['p2_name']}: {game['p2_score']}\n\n"
                        f"👉 Round {game['current_round']}! {p1_tag}, send <b>{game['emoji']}</b>.",
                        parse_mode="HTML",
                    )
                else:
                    # Game Finished - Calculate Winner
                    p1_score = game["p1_score"]
                    p2_score = game["p2_score"]
                    pot = game["bet_amount"] * 2

                    if p1_score > p2_score:
                        adjust_balance(game["p1_id"], pot)
                        winner_text = f"🏆 <b>{html.escape(game['p1_name'])} WINS ₹{pot:.2f}!</b> 🎉"
                    elif p2_score > p1_score:
                        adjust_balance(game["p2_id"], pot)
                        winner_text = f"🏆 <b>{html.escape(game['p2_name'])} WINS ₹{pot:.2f}!</b> 🎉"
                    else:
                        # Tie - Refund both
                        adjust_balance(game["p1_id"], game["bet_amount"])
                        adjust_balance(game["p2_id"], game["bet_amount"])
                        winner_text = "🤝 <b>IT'S A DRAW!</b> Stakes have been refunded to both players."

                    res_msg = (
                        f"🏁 <b>GAME OVER!</b> {game['emoji']}\n"
                        f"━━━━━━━━━━━━━━━━━━━━━\n"
                        f"👤 <b>{html.escape(game['p1_name'])} Score:</b> {p1_score}\n"
                        f"👤 <b>{html.escape(game['p2_name'])} Score:</b> {p2_score}\n"
                        f"━━━━━━━━━━━━━━━━━━━━━\n\n"
                        f"{winner_text}"
                    )
                    bot.send_message(message.chat.id, res_msg, parse_mode="HTML")
                    del ACTIVE_PVP_GAMES[game_id]

        except Exception as e:
            print(f"[PvP Dice Handler Error]: {e}")
