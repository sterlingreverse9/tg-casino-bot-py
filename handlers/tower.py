import uuid
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
from bot_instance import bot
from wallet import get_balance, adjust_balance, get_house_balance, resolve_amount, record_bet
from game_status import is_game_enabled
from settings import get_min_bet, get_max_bet
from games.tower import DIFFICULTY_CONFIG, TOTAL_FLOORS, generate_floor, floor_multiplier
from helpers import ensure_user
from state import tower_setups, active_towers


def tower_difficulty_keyboard(setup_id: str):
    markup = InlineKeyboardMarkup()
    markup.row(
        InlineKeyboardButton("🟢 Easy", callback_data=f"twrdiff:{setup_id}:easy"),
        InlineKeyboardButton("🟡 Medium", callback_data=f"twrdiff:{setup_id}:medium"),
        InlineKeyboardButton("🔴 Hard", callback_data=f"twrdiff:{setup_id}:hard"),
    )
    markup.row(InlineKeyboardButton("❌ Cancel", callback_data=f"twrcancel:{setup_id}"))
    return markup


def tower_floor_keyboard(telegram_id: int, chat_id: int, num_tiles: int, show_cashout: bool):
    markup = InlineKeyboardMarkup()
    markup.row(*[
        InlineKeyboardButton(f"🎁 {i + 1}", callback_data=f"twr:{telegram_id}:{chat_id}:{i}")
        for i in range(num_tiles)
    ])
    if show_cashout:
        markup.row(InlineKeyboardButton("💰 Cashout", callback_data=f"twrcash:{telegram_id}:{chat_id}"))
    return markup


@bot.message_handler(commands=["tower"])
def cmd_tower(message):
    ensure_user(message)
    if not is_game_enabled("tower"):
        bot.reply_to(message, "Tower is currently disabled.")
        return
    parts = message.text.split()
    if len(parts) < 2:
        bot.reply_to(message, "Usage: /tower <amount|all|half> [easy|medium|hard]")
        return

    bet_amount = resolve_amount(message.from_user.id, parts[1])
    if bet_amount is None:
        bot.reply_to(message, "Amount must be a number, 'all', or 'half'.")
        return

    min_bet = get_min_bet()
    max_bet = get_max_bet(get_house_balance())
    if bet_amount < min_bet:
        bot.reply_to(message, f"Minimum bet is {min_bet} coins.")
        return
    if bet_amount > max_bet:
        bot.reply_to(message, f"Maximum bet is {round(max_bet, 2)} coins.")
        return
    if bet_amount > get_balance(message.from_user.id):
        bot.reply_to(message, f"Not enough balance. Your balance: {get_balance(message.from_user.id)}")
        return

    setup_id = uuid.uuid4().hex[:10]
    tower_setups[setup_id] = {
        "telegram_id": message.from_user.id,
        "chat_id": message.chat.id,
        "bet_amount": bet_amount,
    }

    if len(parts) >= 3 and parts[2].lower() in DIFFICULTY_CONFIG:
        start_tower(setup_id, parts[2].lower())
    else:
        bot.reply_to(message, "🏗️ Choose difficulty:", reply_markup=tower_difficulty_keyboard(setup_id))


def start_tower(setup_id: str, difficulty: str):
    setup = tower_setups.pop(setup_id, None)
    if setup is None:
        return
    telegram_id, chat_id, bet_amount = setup["telegram_id"], setup["chat_id"], setup["bet_amount"]

    if bet_amount > get_balance(telegram_id):
        bot.send_message(chat_id, "Not enough balance anymore.")
        return

    adjust_balance(telegram_id, -bet_amount)
    key = (chat_id, telegram_id)
    active_towers[key] = {
        "bet_amount": bet_amount,
        "difficulty": difficulty,
        "current_floor": 0,
        "tiles": generate_floor(difficulty),
    }

    tiles_count = DIFFICULTY_CONFIG[difficulty]["tiles"]
    bot.send_message(
        chat_id,
        f"🏗️ Tower ({difficulty}) started! Bet: {bet_amount} coins\nFloor 1/{TOTAL_FLOORS} — pick a tile:",
        reply_markup=tower_floor_keyboard(telegram_id, chat_id, tiles_count, show_cashout=False),
    )


@bot.callback_query_handler(func=lambda call: call.data.startswith("twrdiff:"))
def handle_tower_difficulty(call):
    _, setup_id, difficulty = call.data.split(":")
    setup = tower_setups.get(setup_id)
    if setup is None or call.from_user.id != setup["telegram_id"]:
        bot.answer_callback_query(call.id, "Not your game.")
        return
    bot.answer_callback_query(call.id)
    start_tower(setup_id, difficulty)


@bot.callback_query_handler(func=lambda call: call.data.startswith("twrcancel:"))
def handle_tower_cancel(call):
    setup_id = call.data.split(":")[1]
    setup = tower_setups.get(setup_id)
    if setup is None or call.from_user.id != setup["telegram_id"]:
        bot.answer_callback_query(call.id, "Not your game.")
        return
    tower_setups.pop(setup_id, None)
    bot.answer_callback_query(call.id, "Cancelled.")
    bot.send_message(setup["chat_id"], "❌ Tower game cancelled. No coins were deducted.")


@bot.callback_query_handler(func=lambda call: call.data.startswith("twr:"))
def handle_tower_tile(call):
    _, tid_str, cid_str, idx_str = call.data.split(":")
    telegram_id, chat_id, idx = int(tid_str), int(cid_str), int(idx_str)

    if call.from_user.id != telegram_id:
        bot.answer_callback_query(call.id, "Not your game.")
        return

    key = (chat_id, telegram_id)
    tower = active_towers.get(key)
    if tower is None:
        bot.answer_callback_query(call.id, "No active tower game.")
        return

    bot.answer_callback_query(call.id)
    tile_result = tower["tiles"][idx]

    if tile_result == "bomb":
        active_towers.pop(key, None)
        record_bet(
            telegram_id=telegram_id, game="tower", bet_amount=tower["bet_amount"], payout=0, result="loss",
            meta={"difficulty": tower["difficulty"], "floor_reached": tower["current_floor"]},
        )
        bot.send_message(
            chat_id,
            f"💥 Boom! You hit a bomb on floor {tower['current_floor'] + 1}.\n"
            f"Lost {tower['bet_amount']} coins.\nBalance: {get_balance(telegram_id)}",
        )
        return

    tower["current_floor"] += 1
    mult = floor_multiplier(tower["difficulty"], tower["current_floor"])

    if tower["current_floor"] >= TOTAL_FLOORS:
        payout = round(tower["bet_amount"] * mult, 2)
        adjust_balance(telegram_id, payout)
        record_bet(
            telegram_id=telegram_id, game="tower", bet_amount=tower["bet_amount"], payout=payout, result="win",
            meta={"difficulty": tower["difficulty"], "floor_reached": tower["current_floor"]},
        )
        active_towers.pop(key, None)
        bot.send_message(
            chat_id,
            f"🏆 You reached the top! Floor {TOTAL_FLOORS}/{TOTAL_FLOORS} • {mult}x\n"
            f"✅ Won {payout} coins!\nBalance: {get_balance(telegram_id)}",
        )
        return

    tower["tiles"] = generate_floor(tower["difficulty"])
    tiles_count = DIFFICULTY_CONFIG[tower["difficulty"]]["tiles"]
    bot.send_message(
        chat_id,
        f"✅ Safe! Floor {tower['current_floor']}/{TOTAL_FLOORS} cleared • {mult}x\n"
        f"Floor {tower['current_floor'] + 1}/{TOTAL_FLOORS} — pick a tile:",
        reply_markup=tower_floor_keyboard(telegram_id, chat_id, tiles_count, show_cashout=True),
    )


@bot.callback_query_handler(func=lambda call: call.data.startswith("twrcash:"))
def handle_tower_cashout(call):
    _, tid_str, cid_str = call.data.split(":")
    telegram_id, chat_id = int(tid_str), int(cid_str)

    if call.from_user.id != telegram_id:
        bot.answer_callback_query(call.id, "Not your game.")
        return

    key = (chat_id, telegram_id)
    tower = active_towers.pop(key, None)
    if tower is None:
        bot.answer_callback_query(call.id, "No active tower game.")
        return

    bot.answer_callback_query(call.id)
    mult = floor_multiplier(tower["difficulty"], tower["current_floor"])
    payout = round(tower["bet_amount"] * mult, 2)
    adjust_balance(telegram_id, payout)
    record_bet(
        telegram_id=telegram_id, game="tower", bet_amount=tower["bet_amount"], payout=payout, result="win",
        meta={"difficulty": tower["difficulty"], "floor_reached": tower["current_floor"]},
    )
    bot.send_message(
        chat_id,
        f"💰 Cashed out at floor {tower['current_floor']}/{TOTAL_FLOORS} • {mult}x\n"
        f"✅ Won {payout} coins!\nBalance: {get_balance(telegram_id)}",
    )

