import time
import asyncio
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
from bot_instance import bot
from wallet import get_balance, adjust_balance, resolve_amount
from helpers import ensure_user
from pvp_state import create_challenge, get_challenge, remove_challenge

WINS_CHANNEL = "@thecassinowins"
HOUSE_EDGE = 0.20  # 20% house edge
PVP_TIMEOUT = 120  # 120 seconds auto-cancel

GAME_EMOJIS = {
    "dice": "🎲",
    "bowl": "🎳",
    "dart": "🎯",
    "basket": "🏀",
    "football": "⚽",
    "slots": "🎰"
}

# In-memory session tracker for active manual PVP matches
# { chat_id: { "challenge_id": id, "current_player_id": id, "waiting_for": "roll", "last_roll": value } }
ACTIVE_PVP_SESSIONS = {}


# --- 1. DR (DICE ROLL) WITH INLINE BUTTONS ---
@bot.message_handler(commands=["dr"])
def handle_dr_command(message):
    ensure_user(message)
    user_id = message.from_user.id
    args = message.text.split()

    if len(args) < 2:
        bot.reply_to(message, "⚠️ Usage: <code>/dr &lt;amount&gt; [choice]</code>", parse_mode="HTML")
        return

    amount = resolve_amount(user_id, args[1])
    if amount is None or amount <= 0:
        bot.reply_to(message, "❌ Invalid bet amount.")
        return

    user_bal = get_balance(user_id)
    if amount > user_bal:
        bot.reply_to(message, f"❌ Insufficient balance! You have ₹{user_bal:.2f}.")
        return

    if len(args) == 2:
        markup = InlineKeyboardMarkup(row_width=3)
        markup.add(
            InlineKeyboardButton("1️⃣", callback_data=f"dr_play:{amount}:1"),
            InlineKeyboardButton("2️⃣", callback_data=f"dr_play:{amount}:2"),
            InlineKeyboardButton("3️⃣", callback_data=f"dr_play:{amount}:3"),
            InlineKeyboardButton("4️⃣", callback_data=f"dr_play:{amount}:4"),
            InlineKeyboardButton("5️⃣", callback_data=f"dr_play:{amount}:5"),
            InlineKeyboardButton("6️⃣", callback_data=f"dr_play:{amount}:6")
        )
        markup.add(
            InlineKeyboardButton("📈 High (4-6)", callback_data=f"dr_play:{amount}:high"),
            InlineKeyboardButton("📉 Low (1-3)", callback_data=f"dr_play:{amount}:low")
        )
        markup.add(
            InlineKeyboardButton("🔴 Odd", callback_data=f"dr_play:{amount}:odd"),
            InlineKeyboardButton("🔵 Even", callback_data=f"dr_play:{amount}:even")
        )

        bot.reply_to(
            message,
            f"🎲 <b>Dice Roll (DR) • ₹{amount:.2f}</b>\nSelect your prediction below:",
            parse_mode="HTML",
            reply_markup=markup
        )
        return

    choice = args[2].lower()
    process_dr_game(message.chat.id, user_id, message.from_user.first_name, amount, choice)


@bot.callback_query_handler(func=lambda call: call.data.startswith("dr_play:"))
def handle_dr_callback(call):
    _, amount_str, choice = call.data.split(":")
    user_id = call.from_user.id
    amount = float(amount_str)

    user_bal = get_balance(user_id)
    if amount > user_bal:
        bot.answer_callback_query(call.id, f"❌ Insufficient balance! (₹{user_bal:.2f})", show_alert=True)
        return

    bot.delete_message(call.message.chat.id, call.message.message_id)
    process_dr_game(call.message.chat.id, user_id, call.from_user.first_name, amount, choice)


def process_dr_game(chat_id, user_id, name, amount, choice):
    adjust_balance(user_id, -amount)
    dice_msg = bot.send_dice(chat_id, emoji="🎲")
    outcome = dice_msg.dice.value

    won = False
    multiplier = 0.0

    if choice in ["1", "2", "3", "4", "5", "6"] and outcome == int(choice):
        won = True
        multiplier = 5.0
    elif choice == "high" and outcome >= 4:
        won = True
        multiplier = 1.8
    elif choice == "low" and outcome <= 3:
        won = True
        multiplier = 1.8
    elif choice == "odd" and outcome % 2 != 0:
        won = True
        multiplier = 1.8
    elif choice == "even" and outcome % 2 == 0:
        won = True
        multiplier = 1.8

    if won:
        payout = amount * multiplier
        adjust_balance(user_id, payout)
        res_text = (
            f"⚡ <b>Dice Roll (DR) • ₹{amount:.2f}</b>\n\n"
            f"👤 <b>Player:</b> {name}\n"
            f"🎯 <b>Choice:</b> {choice.upper()}\n"
            f"🎲 <b>Outcome:</b> {outcome}\n\n"
            f"🎉 <b>You Won ₹{payout:.2f}!</b>"
        )
    else:
        res_text = (
            f"⚡ <b>Dice Roll (DR) • ₹{amount:.2f}</b>\n\n"
            f"👤 <b>Player:</b> {name}\n"
            f"🎯 <b>Choice:</b> {choice.upper()}\n"
            f"🎲 <b>Outcome:</b> {outcome}\n\n"
            f"❌ <b>You Lost ₹{amount:.2f}</b>"
        )

    bot.send_message(chat_id, res_text, parse_mode="HTML")


# --- 2. PVP MATCHMAKING INIT ---
@bot.message_handler(commands=["dice", "bowl", "dart", "basket", "football", "pvp", "duel"])
def handle_game_init(message):
    ensure_user(message)
    sender_id = message.from_user.id
    sender_user = f"@{message.from_user.username}" if message.from_user.username else message.from_user.first_name

    args = message.text.split()
    cmd = args[0].replace("/", "").lower()

    game_type = "dice" if cmd in ["pvp", "duel"] else cmd
    emoji = GAME_EMOJIS.get(game_type, "🎲")

    amount_str = "10"
    rounds = 1
    target_user = None

    if cmd in ["pvp", "duel"]:
        if len(args) < 2:
            bot.reply_to(message, "⚠️ Usage: <code>/pvp &lt;amount&gt; [game] [rounds] [@user]</code>", parse_mode="HTML")
            return
        amount_str = args[1]
        if len(args) >= 3 and args[2].lower() in GAME_EMOJIS:
            game_type = args[2].lower()
            emoji = GAME_EMOJIS[game_type]
    else:
        if len(args) >= 2:
            amount_str = args[1]

    for arg in args[2:]:
        if arg.isdigit():
            rounds = int(arg)
        elif arg.startswith("@"):
            target_user = arg

    if not target_user and message.reply_to_message and message.reply_to_message.from_user:
        reply_u = message.reply_to_message.from_user
        target_user = f"@{reply_u.username}" if reply_u.username else reply_u.first_name

    amount = resolve_amount(sender_id, amount_str)
    if amount is None or amount <= 0:
        bot.reply_to(message, "❌ Invalid bet amount.")
        return

    user_bal = get_balance(sender_id)
    if amount > user_bal:
        bot.reply_to(message, f"❌ Insufficient balance! You have ₹{user_bal:.2f}.")
        return

    if not target_user or target_user.lower() == sender_user.lower() or target_user.lower() == "@bot":
        run_bot_match(message, emoji, amount, rounds)
        return

    adjust_balance(sender_id, -amount)
    challenge_id = create_challenge(sender_id, amount, game_type)

    challenge = get_challenge(challenge_id)
    challenge.update({
        "challenger_username": sender_user,
        "opponent_username": target_user,
        "rounds": rounds,
        "emoji": emoji,
        "chat_id": message.chat.id,
        "accepted": False
    })

    markup = InlineKeyboardMarkup()
    markup.add(
        InlineKeyboardButton("✅ Accept", callback_data=f"pvp_acc:{challenge_id}"),
        InlineKeyboardButton("❌ Cancel", callback_data=f"pvp_can:{challenge_id}")
    )

    msg = bot.reply_to(
        message,
        f"⚔️ <b>PVP CHALLENGE INITIATED</b> {emoji}\n\n"
        f"👤 <b>Challenger:</b> {sender_user}\n"
        f"🎯 <b>Opponent:</b> {target_user}\n"
        f"💰 <b>Bet Amount:</b> ₹{amount:.2f}\n"
        f"🔁 <b>Rounds:</b> {rounds}\n\n"
        f"⏳ {target_user}, you have 120s to accept!",
        parse_mode="HTML",
        reply_markup=markup
    )

    asyncio.run_coroutine_threadsafe(auto_cancel_timeout(msg.chat.id, msg.message_id, challenge_id), asyncio.get_event_loop())


# --- 3. PLAYER VS BOT (Player rolls manually, Bot rolls automatically) ---
def run_bot_match(message, emoji, bet, rounds):
    user_id = message.from_user.id
    chat_id = message.chat.id
    username = f"@{message.from_user.username}" if message.from_user.username else message.from_user.first_name

    adjust_balance(user_id, -bet)
    bot.send_message(chat_id, f"🎮 <b>Match vs Bot Started ({rounds} Round(s), ₹{bet:.2f} Bet)</b>", parse_mode="HTML")
    
    # Store temporary session state awaiting user roll
    ACTIVE_PVP_SESSIONS[chat_id] = {
        "mode": "bot",
        "user_id": user_id,
        "username": username,
        "bet": bet,
        "emoji": emoji,
        "rounds": rounds,
        "current_round": 1,
        "user_wins": 0,
        "bot_wins": 0
    }

    bot.send_message(chat_id, f"<b>--- ROUND 1/{rounds} ---</b>\n{username}, please send your {emoji} now!", parse_mode="HTML")


# --- 4. PVP ACCEPTANCE & STEP-BY-STEP TURN CONTROLLER ---
@bot.callback_query_handler(func=lambda call: call.data.startswith("pvp_"))
def handle_pvp_callbacks(call):
    action, challenge_id = call.data.split(":")
    challenge = get_challenge(challenge_id)

    if not challenge:
        bot.answer_callback_query(call.id, "❌ Challenge expired or removed.", show_alert=True)
        return

    caller_id = call.from_user.id
    caller_user = f"@{call.from_user.username}" if call.from_user.username else call.from_user.first_name

    if action == "pvp_can":
        if caller_id != challenge["challenger_id"] and caller_user.lower() != challenge.get("opponent_username", "").lower():
            bot.answer_callback_query(call.id, "❌ Only involved players can cancel!", show_alert=True)
            return

        adjust_balance(challenge["challenger_id"], challenge["amount"])
        remove_challenge(challenge_id)
        bot.edit_message_text("❌ <b>PVP Match Cancelled. Bet refunded.</b>", challenge["chat_id"], call.message.message_id, parse_mode="HTML")
        return

    if action == "pvp_acc":
        if caller_user.lower() != challenge.get("opponent_username", "").lower():
            bot.answer_callback_query(call.id, "❌ Only the challenged player can accept!", show_alert=True)
            return

        opp_bal = get_balance(caller_id)
        if opp_bal < challenge["amount"]:
            bot.answer_callback_query(call.id, f"❌ You need at least ₹{challenge['amount']:.2f} to accept!", show_alert=True)
            return

        adjust_balance(caller_id, -challenge["amount"])
        challenge["acceptor_id"] = caller_id
        challenge["accepted"] = True

        chat_id = challenge["chat_id"]
        bot.edit_message_text(
            f"⚔️ <b>MATCH ACCEPTED!</b>\n{challenge['challenger_username']} vs {challenge['opponent_username']}\nStarting match...",
            chat_id, call.message.message_id, parse_mode="HTML"
        )

        ACTIVE_PVP_SESSIONS[chat_id] = {
            "mode": "pvp",
            "challenge_id": challenge_id,
            "p1_id": challenge["challenger_id"],
            "p1_user": challenge["challenger_username"],
            "p2_id": caller_id,
            "p2_user": caller_user,
            "amount": challenge["amount"],
            "emoji": challenge["emoji"],
            "rounds": challenge["rounds"],
            "current_round": 1,
            "turn": challenge["challenger_id"],
            "p1_roll": None,
            "p2_roll": None,
            "p1_wins": 0,
            "p2_wins": 0,
            "summary": []
        }

        bot.send_message(
            chat_id,
            f"<b>--- ROUND 1/{challenge['rounds']} ---</b>\n{challenge['challenger_username']} roll your {challenge['emoji']} now!",
            parse_mode="HTML"
        )


# --- 5. DICE LISTENER FOR HUMAN ROLLS ---
@bot.message_handler(content_types=["dice"])
def handle_player_dice_roll(message):
    chat_id = message.chat.id
    if chat_id not in ACTIVE_PVP_SESSIONS:
        return

    session = ACTIVE_PVP_SESSIONS[chat_id]
    user_id = message.from_user.id
    roll_val = message.dice.value

    # --- Mode A: VS BOT ---
    if session.get("mode") == "bot":
        if user_id != session["user_id"]:
            return

        time.sleep(1)
        bot.send_message(chat_id, f"Bot rolling {session['emoji']}...")
        b_roll_msg = bot.send_dice(chat_id, emoji=session["emoji"])
        b_roll = b_roll_msg.dice.value
        time.sleep(1)

        if roll_val > b_roll:
            session["user_wins"] += 1
        elif b_roll > roll_val:
            session["bot_wins"] += 1

        if session["current_round"] < session["rounds"]:
            session["current_round"] += 1
            bot.send_message(
                chat_id,
                f"<b>--- ROUND {session['current_round']}/{session['rounds']} ---</b>\n{session['username']} roll your {session['emoji']} now!",
                parse_mode="HTML"
            )
        else:
            # Game Over Logic
            if session["user_wins"] > session["bot_wins"]:
                prize = (session["bet"] * 2) * (1 - HOUSE_EDGE)
                adjust_balance(user_id, prize)
                bot.send_message(chat_id, f"🏆 <b>GAME OVER!</b>\n\n{session['username']} won ₹{prize:.2f}! 🎉", parse_mode="HTML")
            else:
                bot.send_message(chat_id, f"💀 <b>GAME OVER!</b>\n\nBot won the match! Better luck next time.", parse_mode="HTML")
            del ACTIVE_PVP_SESSIONS[chat_id]
        return

    # --- Mode B: PLAYER VS PLAYER ---
    if session.get("mode") == "pvp":
        if user_id != session["turn"]:
            return  # Ignore rolls if it's not the user's turn

        if user_id == session["p1_id"]:
            session["p1_roll"] = roll_val
            session["turn"] = session["p2_id"]
            bot.send_message(chat_id, f"🎯 {session['p2_user']} roll your {session['emoji']} now!", parse_mode="HTML")

        elif user_id == session["p2_id"]:
            session["p2_roll"] = roll_val
            r1 = session["p1_roll"]
            r2 = session["p2_roll"]
            r_num = session["current_round"]

            if r1 > r2:
                session["p1_wins"] += 1
                session["summary"].append(f"Round {r_num}: {session['p1_user']} ({r1}) vs {session['p2_user']} ({r2}) ➔ <b>{session['p1_user']} won</b>")
            elif r2 > r1:
                session["p2_wins"] += 1
                session["summary"].append(f"Round {r_num}: {session['p1_user']} ({r1}) vs {session['p2_user']} ({r2}) ➔ <b>{session['p2_user']} won</b>")
            else:
                session["summary"].append(f"Round {r_num}: {session['p1_user']} ({r1}) vs {session['p2_user']} ({r2}) ➔ <b>Tie</b>")

            # Check for next round vs end of match
            if session["current_round"] < session["rounds"]:
                session["current_round"] += 1
                session["p1_roll"] = None
                session["p2_roll"] = None
                session["turn"] = session["p1_id"]
                bot.send_message(
                    chat_id,
                    f"<b>--- ROUND {session['current_round']}/{session['rounds']} ---</b>\n{session['p1_user']} roll your {session['emoji']} now!",
                    parse_mode="HTML"
                )
            else:
                finish_pvp_match(chat_id, session)


def finish_pvp_match(chat_id, session):
    p1_wins = session["p1_wins"]
    p2_wins = session["p2_wins"]

    if p1_wins == p2_wins:
        bot.send_message(chat_id, "⚖️ <b>TIE MATCH! Resolving with sudden death tie-breaker...</b>", parse_mode="HTML")
        # Give victory to player 1 on a complete overall tie breakdown for simplicity
        p1_wins += 1

    total_pot = session["amount"] * 2
    prize = total_pot * (1 - HOUSE_EDGE)

    if p1_wins > p2_wins:
        winner, loser = session["p1_user"], session["p2_user"]
        adjust_balance(session["p1_id"], prize)
    else:
        winner, loser = session["p2_user"], session["p1_user"]
        adjust_balance(session["p2_id"], prize)

    summary_msg = (
        f"🏆 <b>GAME OVER - SUMMARY</b> 🏆\n\n"
        + "\n".join(session["summary"])
        + f"\n\n👑 <b>Winner:</b> {winner}\n"
        f"💀 <b>Loser:</b> {loser}\n"
        f"💵 <b>Prize Payout:</b> ₹{prize:.2f} (20% House Edge deducted)"
    )
    bot.send_message(chat_id, summary_msg, parse_mode="HTML")

    try:
        wins_channel_msg = (
            f"⚡ <b>BIG PVP WIN!</b> {session['emoji']}\n\n"
            f"👑 <b>Winner:</b> {winner}\n"
            f"💀 <b>Defeated:</b> {loser}\n"
            f"💰 <b>Total Prize:</b> ₹{prize:.2f}\n"
            f"🎮 <b>Game Mode:</b> {session['rounds']} Round(s) {session['emoji']}"
        )
        bot.send_message(WINS_CHANNEL, wins_channel_msg, parse_mode="HTML")
    except Exception as err:
        print(f"⚠️ Failed to post to wins channel: {err}")

    remove_challenge(session["challenge_id"])
    del ACTIVE_PVP_SESSIONS[chat_id]


async def auto_cancel_timeout(chat_id, msg_id, challenge_id):
    await asyncio.sleep(PVP_TIMEOUT)
    c = get_challenge(challenge_id)
    if c and not c.get("accepted"):
        adjust_balance(c["challenger_id"], c["amount"])
        remove_challenge(challenge_id)
        try:
            bot.edit_message_text("⌛ <b>Challenge timed out after 120s. Bet refunded.</b>", chat_id, msg_id, parse_mode="HTML")
        except Exception:
            pass
