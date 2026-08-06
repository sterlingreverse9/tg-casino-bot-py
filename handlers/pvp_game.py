import time
import asyncio
import random
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton, Message
from bot_instance import bot
from wallet import get_balance, adjust_balance, resolve_amount
from helpers import ensure_user
from pvp_state import create_challenge, get_challenge, remove_challenge
from games.coinflip import should_rig_user, RIG_CONFIG

WINS_CHANNEL = "@thecassinowins"
HOUSE_EDGE = 0.20
PVP_TIMEOUT = 120
MAX_BET = 5000  # Enforce Maxbet Cap

GAME_EMOJIS = {
    "dice": "🎲",
    "bowl": "🎳",
    "dart": "🎯",
    "basket": "🏀",
    "football": "⚽",
    "slots": "🎰"
}

ACTIVE_PVP_SESSIONS = {}


def get_rigged_roll(emoji: str, win: bool, user_roll: int = None) -> int:
    """Natural, smart roll generator (prevents spamming 6s)."""
    if emoji in ["🎲", "🎯", "🎳"]:
        if win:
            if user_roll:
                possible = [r for r in range(user_roll + 1, 7)]
                return random.choice(possible) if possible else 6
            return random.choice([4, 5, 6])
        else:
            if user_roll:
                possible = [r for r in range(1, user_roll)]
                return random.choice(possible) if possible else 1
            return random.choice([1, 2, 3])
    elif emoji == "🏀":
        return random.choice([4, 5]) if win else random.choice([1, 2, 3])
    elif emoji == "⚽":
        return random.choice([3, 4, 5]) if win else random.choice([1, 2])
    elif emoji == "🎰":
        return 64 if win else random.choice([1, 10, 22, 43])
    return random.randint(1, 6)


# --- 1. DR (DICE ROLL) GAME ---
@bot.message_handler(commands=["dr"])
def handle_dr_command(message: Message):
    ensure_user(message)
    user_id = message.from_user.id
    username = message.from_user.username or ""
    args = message.text.split()

    if len(args) < 2:
        bot.reply_to(message, "⚠️ Usage: <code>/dr &lt;amount&gt; [choice]</code>", parse_mode="HTML")
        return

    amount = resolve_amount(user_id, args[1])
    if amount is None or amount <= 0:
        bot.reply_to(message, "❌ Invalid bet amount.")
        return

    if amount > MAX_BET:
        bot.reply_to(message, f"❌ Max bet limit is ₹{MAX_BET}.")
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

        bot.reply_to(message, f"🎲 <b>Dice Roll (DR) • ₹{amount:.2f}</b>\nSelect prediction:", parse_mode="HTML", reply_markup=markup)
        return

    choice = args[2].lower()
    process_dr_game(message.chat.id, user_id, username, message.from_user.first_name, amount, choice)


@bot.callback_query_handler(func=lambda call: call.data.startswith("dr_play:"))
def handle_dr_callback(call):
    _, amount_str, choice = call.data.split(":")
    user_id = call.from_user.id
    username = call.from_user.username or ""
    amount = float(amount_str)

    if amount > MAX_BET:
        bot.answer_callback_query(call.id, f"❌ Max bet limit is ₹{MAX_BET}", show_alert=True)
        return

    bot.delete_message(call.message.chat.id, call.message.message_id)
    process_dr_game(call.message.chat.id, user_id, username, call.from_user.first_name, amount, choice)


def process_dr_game(chat_id, user_id, username, name, amount, choice):
    adjust_balance(user_id, -amount)

    dice_msg = bot.send_dice(chat_id, emoji="🎲")
    outcome = dice_msg.dice.value

    rigged = should_rig_user(username)
    win_rate = RIG_CONFIG["win_rate"] if rigged else 0.50
    will_win = random.random() < win_rate

    won = False
    multiplier = 1.8

    if choice in ["1", "2", "3", "4", "5", "6"]:
        multiplier = 5.0
        won = (outcome == int(choice)) if not rigged else will_win
    elif choice == "high":
        won = (outcome >= 4) if not rigged else will_win
    elif choice == "low":
        won = (outcome <= 3) if not rigged else will_win
    elif choice == "odd":
        won = (outcome % 2 != 0) if not rigged else will_win
    elif choice == "even":
        won = (outcome % 2 == 0) if not rigged else will_win

    if won:
        payout = amount * multiplier
        adjust_balance(user_id, payout)
        res_text = f"⚡ <b>Dice Roll (DR) • ₹{amount:.2f}</b>\n\n👤 <b>Player:</b> {name}\n🎯 <b>Choice:</b> {choice.upper()}\n🎲 <b>Outcome:</b> {outcome}\n\n🎉 <b>You Won ₹{payout:.2f}!</b>"
    else:
        res_text = f"⚡ <b>Dice Roll (DR) • ₹{amount:.2f}</b>\n\n👤 <b>Player:</b> {name}\n🎯 <b>Choice:</b> {choice.upper()}\n🎲 <b>Outcome:</b> {outcome}\n\n❌ <b>You Lost ₹{amount:.2f}</b>"

    bot.send_message(chat_id, res_text, parse_mode="HTML")


# --- 2. SECURITY HANDLER FOR FORWARDED DICE EXPLOITS ---
@bot.message_handler(content_types=["dice"])
def handle_player_dice_roll(message: Message):
    # Reject forwarded dice completely
    if message.forward_date or message.forward_from or message.forward_from_chat:
        bot.reply_to(message, "⚠️ <b>Forwarded dice are invalid!</b>", parse_mode="HTML")
        return

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
        rigged = should_rig_user(session.get("username", ""))
        bot_win = not rigged if rigged else random.choice([True, False])

        bot.send_message(chat_id, f"Bot rolling {session['emoji']}...")
        
        # Send fresh native roll
        b_roll_msg = bot.send_dice(chat_id, emoji=session["emoji"])
        b_roll = b_roll_msg.dice.value
        time.sleep(1)

        if roll_val > b_roll:
            session["user_wins"] += 1
        elif b_roll > roll_val:
            session["bot_wins"] += 1

        if session["current_round"] < session["rounds"]:
            session["current_round"] += 1
            bot.send_message(chat_id, f"<b>--- ROUND {session['current_round']}/{session['rounds']} ---</b>\n{session['username']} roll your {session['emoji']} now!", parse_mode="HTML")
        else:
            if session["user_wins"] > session["bot_wins"]:
                prize = (session["bet"] * 2) * (1 - HOUSE_EDGE)
                adjust_balance(user_id, prize)
                bot.send_message(chat_id, f"🏆 <b>GAME OVER!</b>\n\n{session['username']} won ₹{prize:.2f}! 🎉", parse_mode="HTML")
            else:
                bot.send_message(chat_id, "💀 <b>GAME OVER!</b>\n\nBot won the match!", parse_mode="HTML")
            del ACTIVE_PVP_SESSIONS[chat_id]
        return

    # --- Mode B: PLAYER VS PLAYER ---
    if session.get("mode") == "pvp":
        if user_id != session["turn"]:
            return

        if user_id == session["p1_id"]:
            session["p1_roll"] = roll_val
            session["turn"] = session["p2_id"]
            bot.send_message(chat_id, f"🎯 {session['p2_user']} roll your {session['emoji']} now!", parse_mode="HTML")

        elif user_id == session["p2_id"]:
            session["p2_roll"] = roll_val
            r1, r2 = session["p1_roll"], session["p2_roll"]
            r_num = session["current_round"]

            if r1 > r2:
                session["p1_wins"] += 1
                session["summary"].append(f"Round {r_num}: {session['p1_user']} ({r1}) vs {session['p2_user']} ({r2}) ➔ <b>{session['p1_user']} won</b>")
            elif r2 > r1:
                session["p2_wins"] += 1
                session["summary"].append(f"Round {r_num}: {session['p1_user']} ({r1}) vs {session['p2_user']} ({r2}) ➔ <b>{session['p2_user']} won</b>")
            else:
                session["summary"].append(f"Round {r_num}: {session['p1_user']} ({r1}) vs {session['p2_user']} ({r2}) ➔ <b>Tie</b>")

            if session["current_round"] < session["rounds"]:
                session["current_round"] += 1
                session["p1_roll"] = None
                session["p2_roll"] = None
                session["turn"] = session["p1_id"]
                bot.send_message(chat_id, f"<b>--- ROUND {session['current_round']}/{session['rounds']} ---</b>\n{session['p1_user']} roll your {session['emoji']} now!", parse_mode="HTML")
            else:
                finish_pvp_match(chat_id, session)


def finish_pvp_match(chat_id, session):
    p1_wins, p2_wins = session["p1_wins"], session["p2_wins"]

    if p1_wins == p2_wins:
        p1_wins += 1  # Break tie

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
        + f"\n\n👑 <b>Winner:</b> {winner}\n💀 <b>Loser:</b> {loser}\n💵 <b>Prize Payout:</b> ₹{prize:.2f}"
    )
    bot.send_message(chat_id, summary_msg, parse_mode="HTML")
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
