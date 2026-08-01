import threading
import uuid
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
from bot_instance import bot
from db import select, update
from wallet import get_or_create_user, get_balance, adjust_balance, record_bet, resolve_amount
from game_status import is_game_enabled
from games.dice_duel import parse_dice_code, decide_round_winner
from settings import get_min_bet
from game_math import payout_for
from helpers import ensure_user
from state import dice_setups, active_matches, dice_waiters, CASINO_LABEL, HOUSE_EDGE_RAKE


def display_name(user):
    if user.username:
        return f"@{user.username}"
    return user.first_name or "Player"


def parse_dice_command(text: str, reply_msg):
    """Returns (amount_str, code_or_None, opponent_username, opponent_id, opponent_name)."""
    tokens = text.split()[1:]
    amount_str, code, opponent_username = None, None, None
    for tok in tokens:
        if tok.startswith("@"):
            opponent_username = tok[1:]
        elif parse_dice_code(tok.lower()):
            code = tok.lower()
        elif amount_str is None:
            amount_str = tok

    opponent_id, opponent_name = None, None
    if reply_msg:
        opponent_id = reply_msg.from_user.id
        opponent_name = display_name(reply_msg.from_user)
        get_or_create_user(opponent_id, reply_msg.from_user.username)
    elif opponent_username:
        opponent = select("users", filters={"username": opponent_username}, single=True)
        if opponent:
            opponent_id = int(opponent["telegram_id"])
            opponent_name = f"@{opponent_username}"

    return amount_str, code, opponent_username, opponent_id, opponent_name


def rounds_keyboard(setup_id):
    markup = InlineKeyboardMarkup()
    markup.row(*[InlineKeyboardButton(str(n), callback_data=f"dround:{setup_id}:{n}") for n in (1, 2, 3)])
    return markup


def rolls_keyboard(setup_id):
    markup = InlineKeyboardMarkup()
    markup.row(*[InlineKeyboardButton(str(n), callback_data=f"droll:{setup_id}:{n}") for n in (1, 2, 3)])
    return markup


def mode_keyboard(setup_id):
    markup = InlineKeyboardMarkup()
    markup.row(
        InlineKeyboardButton("Normal (highest sum wins)", callback_data=f"dsmode:{setup_id}:normal"),
        InlineKeyboardButton("Crazy (lowest sum wins)", callback_data=f"dsmode:{setup_id}:crazy"),
    )
    return markup


def advance_setup(setup_id):
    setup = dice_setups.get(setup_id)
    if setup is None:
        return
    chat_id = setup["chat_id"]
    if setup["rounds"] is None:
        bot.send_message(chat_id, "🎲 How many rounds?", reply_markup=rounds_keyboard(setup_id))
    elif setup["dice_count"] is None:
        bot.send_message(chat_id, "🎲 How many dice per round?", reply_markup=rolls_keyboard(setup_id))
    elif setup["mode"] is None:
        bot.send_message(chat_id, "🎲 Choose your game mode:", reply_markup=mode_keyboard(setup_id))
    else:
        finalize_setup(setup_id)


def finalize_setup(setup_id):
    setup = dice_setups.pop(setup_id, None)
    if setup is None:
        return
    chat_id = setup["chat_id"]

    if setup["opponent_id"] is None:
        amount = resolve_amount(setup["initiator_id"], setup["amount_str"])
        if amount is None:
            bot.send_message(chat_id, "Amount must be a number, 'all', or 'half'.")
            return
        if amount < get_min_bet():
            bot.send_message(chat_id, f"Minimum bet is {get_min_bet()} coins.")
            return
        if amount > get_balance(setup["initiator_id"]):
            bot.send_message(chat_id, f"Not enough balance. Your balance: {get_balance(setup['initiator_id'])}")
            return
        adjust_balance(setup["initiator_id"], -amount)
        start_match(
            chat_id=chat_id,
            player_a=setup["initiator_id"], player_a_name=setup["initiator_name"], bet_a=amount,
            player_b=None, player_b_name=CASINO_LABEL, bet_b=0,
            dice_count=setup["dice_count"], rounds=setup["rounds"], mode=setup["mode"],
        )
        return

    markup = InlineKeyboardMarkup()
    markup.row(
        InlineKeyboardButton("✅ Accept", callback_data=f"daccept:{setup_id}"),
        InlineKeyboardButton("❌ Decline", callback_data=f"ddecline:{setup_id}"),
    )
    dice_setups[setup_id] = setup
    setup["status"] = "awaiting_accept"
    bot.send_message(
        chat_id,
        f"⚔️ {setup['initiator_name']} challenges {setup['opponent_name']} to a Dice Duel!\n"
        f"{setup['dice_count']} dice, {setup['rounds']} round(s), {setup['mode']} mode, bet: {setup['amount_str']} coins each.\n"
        f"{setup['opponent_name']} has 120 seconds to accept.",
        reply_markup=markup,
    )

    def expire_setup():
        d = dice_setups.get(setup_id)
        if d and d.get("status") == "awaiting_accept":
            dice_setups.pop(setup_id, None)
            bot.send_message(d["chat_id"], f"⌛ The challenge to {d['opponent_name']} expired.")

    threading.Timer(120, expire_setup).start()


@bot.message_handler(commands=["dice"])
def cmd_dice(message):
    ensure_user(message)
    if not is_game_enabled("dice"):
        bot.reply_to(message, "Dice Duel is currently disabled.")
        return

    amount_str, code, opponent_username, opponent_id, opponent_name = parse_dice_command(message.text, message.reply_to_message)
    if amount_str is None:
        bot.reply_to(message, "Usage: /dice <amount|all|half> [<dice>d<rounds>w] [@opponent]\nOr reply to someone's message with /dice <amount> [...]")
        return
    if opponent_username and opponent_id is None:
        bot.reply_to(message, f"That user needs to message this bot at least once (e.g. /me) before they can be challenged.")
        return
    if opponent_id == message.from_user.id:
        bot.reply_to(message, "You can't challenge yourself.")
        return

    dice_count, rounds = (None, None)
    if code:
        parsed = parse_dice_code(code)
        if parsed is None:
            bot.reply_to(message, "Invalid dice code. Format is <dice>d<rounds>w, e.g. 3d1w (max 3 dice, 3 rounds).")
            return
        dice_count, rounds = parsed

    setup_id = uuid.uuid4().hex[:10]
    dice_setups[setup_id] = {
        "initiator_id": message.from_user.id,
        "initiator_name": display_name(message.from_user),
        "amount_str": amount_str,
        "dice_count": dice_count,
        "rounds": rounds,
        "mode": None,
        "opponent_id": opponent_id,
        "opponent_name": opponent_name,
        "chat_id": message.chat.id,
        "status": "setup",
    }
    advance_setup(setup_id)


@bot.callback_query_handler(func=lambda call: call.data.startswith("dround:"))
def handle_dround(call):
    _, setup_id, n = call.data.split(":")
    setup = dice_setups.get(setup_id)
    if setup is None or call.from_user.id != setup["initiator_id"]:
        bot.answer_callback_query(call.id, "Not your setup.")
        return
    bot.answer_callback_query(call.id)
    setup["rounds"] = int(n)
    advance_setup(setup_id)


@bot.callback_query_handler(func=lambda call: call.data.startswith("droll:"))
def handle_droll(call):
    _, setup_id, n = call.data.split(":")
    setup = dice_setups.get(setup_id)
    if setup is None or call.from_user.id != setup["initiator_id"]:
        bot.answer_callback_query(call.id, "Not your setup.")
        return
    bot.answer_callback_query(call.id)
    setup["dice_count"] = int(n)
    advance_setup(setup_id)


@bot.callback_query_handler(func=lambda call: call.data.startswith("dsmode:"))
def handle_dsmode(call):
    _, setup_id, mode = call.data.split(":")
    setup = dice_setups.get(setup_id)
    if setup is None or call.from_user.id != setup["initiator_id"]:
        bot.answer_callback_query(call.id, "Not your setup.")
        return
    bot.answer_callback_query(call.id)
    setup["mode"] = mode
    advance_setup(setup_id)


@bot.callback_query_handler(func=lambda call: call.data.startswith("daccept:") or call.data.startswith("ddecline:"))
def handle_dice_response(call):
    action, setup_id = call.data.split(":")
    setup = dice_setups.get(setup_id)
    if setup is None or setup.get("status") != "awaiting_accept":
        bot.answer_callback_query(call.id, "This challenge is no longer active.")
        return
    if call.from_user.id != setup["opponent_id"]:
        bot.answer_callback_query(call.id, "This challenge isn't for you.")
        return

    if action == "ddecline":
        dice_setups.pop(setup_id, None)
        bot.answer_callback_query(call.id, "Challenge declined.")
        bot.send_message(setup["chat_id"], f"❌ {setup['opponent_name']} declined the challenge.")
        return

    bot.answer_callback_query(call.id)
    dice_setups.pop(setup_id, None)

    initiator_id, opponent_id = setup["initiator_id"], setup["opponent_id"]
    initiator_amount = resolve_amount(initiator_id, setup["amount_str"])
    opponent_amount = resolve_amount(opponent_id, setup["amount_str"])

    if initiator_amount is None or opponent_amount is None:
        bot.send_message(setup["chat_id"], "Amount must be a number, 'all', or 'half'.")
        return
    if initiator_amount < get_min_bet() or opponent_amount < get_min_bet():
        bot.send_message(setup["chat_id"], f"Minimum bet is {get_min_bet()} coins for both players.")
        return
    if initiator_amount > get_balance(initiator_id):
        bot.send_message(setup["chat_id"], f"{setup['initiator_name']} doesn't have enough balance anymore.")
        return
    if opponent_amount > get_balance(opponent_id):
        bot.send_message(setup["chat_id"], f"{setup['opponent_name']} doesn't have enough balance anymore.")
        return

    adjust_balance(initiator_id, -initiator_amount)
    adjust_balance(opponent_id, -opponent_amount)

    start_match(
        chat_id=setup["chat_id"],
        player_a=initiator_id, player_a_name=setup["initiator_name"], bet_a=initiator_amount,
        player_b=opponent_id, player_b_name=setup["opponent_name"], bet_b=opponent_amount,
        dice_count=setup["dice_count"], rounds=setup["rounds"], mode=setup["mode"],
    )


def start_match(chat_id, player_a, player_a_name, bet_a, player_b, player_b_name, bet_b, dice_count, rounds, mode):
    match_id = uuid.uuid4().hex[:10]
    active_matches[match_id] = {
        "chat_id": chat_id,
        "player_a": player_a, "player_a_name": player_a_name, "bet_a": bet_a,
        "player_b": player_b, "player_b_name": player_b_name, "bet_b": bet_b,
        "dice_count": dice_count, "rounds": rounds, "mode": mode,
        "current_round": 1, "a_wins": 0, "b_wins": 0,
        "a_current": [], "b_current": [], "round_log": [],
    }
    dice_waiters[(chat_id, player_a)] = match_id
    if player_b is not None:
        dice_waiters[(chat_id, player_b)] = match_id

    bot.send_message(
        chat_id,
        f"⚔️ Dice Duel started! {player_a_name} vs {player_b_name} • {dice_count} dice/round • {rounds} round(s) • {mode} mode\n"
        f"{player_a_name}, send your 🎲 dice now!",
    )
    if player_b is not None:
        schedule_afk_timers(match_id, 1, "a")
        schedule_afk_timers(match_id, 1, "b")


@bot.message_handler(content_types=["dice"])
def handle_incoming_dice(message):
    key = (message.chat.id, message.from_user.id)
    match_id = dice_waiters.get(key)
    if match_id is None:
        return
    match = active_matches.get(match_id)
    if match is None:
        return

    side = "a" if message.from_user.id == match["player_a"] else "b"
    match[f"{side}_current"].append(message.dice.value)

    remaining = match["dice_count"] - len(match[f"{side}_current"])
    if remaining > 0:
        bot.reply_to(message, f"Got it! Send {remaining} more dice.")
        return

    if match["player_b"] is None and side == "a":
        match["b_current"] = [
            bot.send_dice(match["chat_id"], emoji="🎲", reply_to_message_id=message.message_id).dice.value
            for _ in range(match["dice_count"])
        ]
    else:
        bot.reply_to(message, "Got your dice for this round!")

    if len(match["a_current"]) == match["dice_count"] and len(match["b_current"]) == match["dice_count"]:
        resolve_round(match_id)
    else:
        waiting_name = match["player_b_name"] if side == "a" else match["player_a_name"]
        bot.send_message(match["chat_id"], f"Waiting on {waiting_name} to send their dice...")


def resolve_round(match_id):
    match = active_matches.get(match_id)
    if match is None:
        return
    chat_id = match["chat_id"]
    a_sum, b_sum = sum(match["a_current"]), sum(match["b_current"])

    if a_sum == b_sum:
        bot.send_message(chat_id, f"Round tied ({a_sum} vs {b_sum})! Reroll this round — send your dice again.")
        match["a_current"], match["b_current"] = [], []
        prompt_reroll(match)
        if match["player_b"] is not None:
            schedule_afk_timers(match_id, match["current_round"], "a")
            schedule_afk_timers(match_id, match["current_round"], "b")
        return

    winner_side = decide_round_winner(a_sum, b_sum, match["mode"])
    match[f"{winner_side}_wins"] += 1
    winner_name = match["player_a_name"] if winner_side == "a" else match["player_b_name"]

    match["round_log"].append(
        f"Round {match['current_round']}: {match['player_a_name']} {match['a_current']} ({a_sum}) vs "
        f"{match['player_b_name']} {match['b_current']} ({b_sum}) — {winner_name} won"
    )
    bot.send_message(chat_id, match["round_log"][-1])

    needed = match["rounds"] // 2 + 1
    if match["a_wins"] >= needed or match["b_wins"] >= needed:
        finalize_match(match_id)
    else:
        match["current_round"] += 1
        match["a_current"], match["b_current"] = [], []
        prompt_reroll(match)
        if match["player_b"] is not None:
            schedule_afk_timers(match_id, match["current_round"], "a")
            schedule_afk_timers(match_id, match["current_round"], "b")


def prompt_reroll(match):
    chat_id = match["chat_id"]
    if match["player_b"] is None:
        bot.send_message(chat_id, f"{match['player_a_name']}, send your 🎲 dice for the next round!")
    else:
        bot.send_message(chat_id, f"{match['player_a_name']} and {match['player_b_name']}, send your 🎲 dice for the next round!")


def schedule_afk_timers(match_id, round_number, side):
    def warn():
        match = active_matches.get(match_id)
        if not match or match["current_round"] != round_number:
            return
        if len(match[f"{side}_current"]) >= match["dice_count"]:
            return
        name = match["player_a_name"] if side == "a" else match["player_b_name"]
        bot.send_message(match["chat_id"], f"⏰ {name}, you'll forfeit the match in 30 seconds if you don't roll!")

    def forfeit():
        match = active_matches.get(match_id)
        if not match or match["current_round"] != round_number:
            return
        if len(match[f"{side}_current"]) >= match["dice_count"]:
            return
        forfeit_player(match_id, side)

    threading.Timer(60, warn).start()
    threading.Timer(90, forfeit).start()


def forfeit_player(match_id, afk_side):
    match = active_matches.pop(match_id, None)
    if match is None:
        return
    chat_id = match["chat_id"]
    dice_waiters.pop((chat_id, match["player_a"]), None)
    if match["player_b"] is not None:
        dice_waiters.pop((chat_id, match["player_b"]), None)

    afk_name = match["player_a_name"] if afk_side == "a" else match["player_b_name"]
    afk_id = match["player_a"] if afk_side == "a" else match["player_b"]
    other_id = match["player_b"] if afk_side == "a" else match["player_a"]
    other_name = match["player_b_name"] if afk_side == "a" else match["player_a_name"]
    afk_bet = match["bet_a"] if afk_side == "a" else match["bet_b"]
    other_bet = match["bet_b"] if afk_side == "a" else match["bet_a"]

    half = round(afk_bet / 2, 2)
    to_house = round(afk_bet - half, 2)

    adjust_balance(other_id, other_bet + half)  # refund their own stake + half of the forfeiter's
    house = select("house", filters={"id": 1}, single=True)
    update("house", {"id": 1}, {"balance": float(house["balance"]) + to_house})

    record_bet(telegram_id=afk_id, game="dice_duel_pvp", bet_amount=afk_bet, payout=0, result="loss", meta={"forfeit": True})
    record_bet(telegram_id=other_id, game="dice_duel_pvp", bet_amount=other_bet, payout=other_bet + half, result="win", meta={"opponent_forfeited": True})

    bot.send_message(
        chat_id,
        f"⌛ {afk_name} didn't roll in time and forfeited.\n"
        f"{other_name} gets their {other_bet} coins back plus {half} coins.\n"
        f"{half} coins go to the house.",
    )


def finalize_match(match_id):
    match = active_matches.pop(match_id, None)
    if match is None:
        return
    dice_waiters.pop((match["chat_id"], match["player_a"]), None)
    if match["player_b"] is not None:
        dice_waiters.pop((match["chat_id"], match["player_b"]), None)

    winner_side = "a" if match["a_wins"] > match["b_wins"] else "b"
    summary = "\n".join(match["round_log"])

    if match["player_b"] is None:
        won = winner_side == "a"
        payout = payout_for_50_50(match["bet_a"]) if won else 0
        if won:
            adjust_balance(match["player_a"], payout)
        record_bet(
            telegram_id=match["player_a"], game="dice_duel_bot", bet_amount=match["bet_a"], payout=payout,
            result="win" if won else "loss", meta={"mode": match["mode"]},
        )
        outcome = (
            f"🏆 You won the duel! +{payout} coins.\nBalance: {get_balance(match['player_a'])}"
            if won else
            f"❌ You lost the duel. -{match['bet_a']} coins.\nBalance: {get_balance(match['player_a'])}"
        )
        bot.send_message(match["chat_id"], f"📋 Match Summary:\n{summary}\n\n{outcome}")
        return

    pot = match["bet_a"] + match["bet_b"]
    rake = round(pot * HOUSE_EDGE_RAKE, 2)
    winner_payout = round(pot - rake, 2)
    winner_id = match["player_a"] if winner_side == "a" else match["player_b"]
    winner_name = match["player_a_name"] if winner_side == "a" else match["player_b_name"]
    loser_name = match["player_b_name"] if winner_side == "a" else match["player_a_name"]
    loser_bet = match["bet_b"] if winner_side == "a" else match["bet_a"]

    adjust_balance(winner_id, winner_payout)
    record_bet(telegram_id=match["player_a"], game="dice_duel_pvp", bet_amount=match["bet_a"],
               payout=winner_payout if winner_side == "a" else 0, result="win" if winner_side == "a" else "loss",
               meta={"opponent": match["player_b_name"], "mode": match["mode"]})
    record_bet(telegram_id=match["player_b"], game="dice_duel_pvp", bet_amount=match["bet_b"],
               payout=winner_payout if winner_side == "b" else 0, result="win" if winner_side == "b" else "loss",
               meta={"opponent": match["player_a_name"], "mode": match["mode"]})

    house = select("house", filters={"id": 1}, single=True)
    update("house", {"id": 1}, {"balance": float(house["balance"]) + rake})

    bot.send_message(
        match["chat_id"],
        f"📋 Match Summary:\n{summary}\n\n"
        f"🏆 {winner_name} wins the duel!\n"
        f"{winner_name}: +{winner_payout} coins\n"
        f"{loser_name}: -{loser_bet} coins",
    )


def payout_for_50_50(bet_amount):
    from game_math import payout_for
    return payout_for(bet_amount, 0.5)

