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


# --- 1. DR (DICE ROLL) WITH INLINE BUTTONS & ALL MODES ---
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

    # If only amount is passed, show inline buttons
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

    # Direct command parsing: /dr <amount> <choice>
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

    # Check winning condition and set payout multiplier
    won = False
    multiplier = 0.0

    if choice in ["1", "2", "3", "4", "5", "6"] and outcome == int(choice):
        won = True
        multiplier = 5.0  # Exact number guess
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


# --- 2. GAME INITIALIZATION & PVP ---
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


# --- 3. CLEAN VS BOT MATCH ENGINE ---
def run_bot_match(message, emoji, bet, rounds):
    user_id = message.from_user.id
    chat_id = message.chat.id
    username = f"@{message.from_user.username}" if message.from_user.username else message.from_user.first_name

    adjust_balance(user_id, -bet)
    user_wins, bot_wins = 0, 0

    bot.send_message(chat_id, f"🎮 <b>Match vs Bot Started ({rounds} Rounds, ₹{bet:.2f} Bet)</b>", parse_mode="HTML")

    for r in range(1, rounds + 1):
        bot.send_message(chat_id, f"<b>--- ROUND {r}/{rounds} ---</b>\n{username} rolling {emoji}...", parse_mode="HTML")
        u_roll = bot.send_dice(chat_id, emoji=emoji).dice.value
        time.sleep(1.5)

        bot.send_message(chat_id, f"Bot rolling {emoji}...")
        b_roll = bot.send_dice(chat_id, emoji=emoji).dice.value
        time.sleep(1.5)

        if u_roll > b_roll:
            user_wins += 1
        elif b_roll > u_roll:
            bot_wins += 1

    if user_wins == bot_wins:
        bot.send_message(chat_id, f"⚖️ <b>TIE! Starting Tie-Breaker Round...</b>", parse_mode="HTML")
        u_tb = bot.send_dice(chat_id, emoji=emoji).dice.value
        time.sleep(1.5)
        b_tb = bot.send_dice(chat_id, emoji=emoji).dice.value
        time.sleep(1.5)
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


# --- 4. PVP CALLBACKS & GAME LOOPS ---
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

        bot.send_message(chat_id, f"{p1} rolling {emoji}...")
        r1 = bot.send_dice(chat_id, emoji=emoji).dice.value
        time.sleep(2)

        bot.send_message(chat_id, f"{p2} rolling {emoji}...")
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
        bot.send_message(chat_id, f"{p1} rolling {emoji}...")
        r1 = bot.send_dice(chat_id, emoji=emoji).dice.value
        time.sleep(2)

        bot.send_message(chat_id, f"{p2} rolling {emoji}...")
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
        f"💵 <b>Prize Payout:</b> ₹{prize:.2f} (20% House Edge deducted)"
    )
    bot.send_message(chat_id, summary_msg, parse_mode="HTML")

    try:
        wins_channel_msg = (
            f"⚡ <b>BIG PVP WIN!</b> {emoji}\n\n"
            f"👑 <b>Winner:</b> {winner}\n"
            f"💀 <b>Defeated:</b> {loser}\n"
            f"💰 <b>Total Prize:</b> ₹{prize:.2f}\n"
            f"🎮 <b>Game Mode:</b> {c['rounds']} Round(s) {emoji}"
        )
        bot.send_message(WINS_CHANNEL, wins_channel_msg, parse_mode="HTML")
    except Exception as err:
        print(f"⚠️ Failed to post to wins channel: {err}")

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
