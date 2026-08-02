import time
from wallet import adjust_balance, record_bet
from settings import get_house_edge  # Dynamically fetches configured house edge %
from helpers import announce_win

MIN_BET = 10


def decide_round_winner(a_sum: int, b_sum: int, mode: str = "classic"):
    if a_sum == b_sum:
        return None  # tie -> reroll round
    if mode == "crazy":
        return "a" if a_sum < b_sum else "b"
    return "a" if a_sum > b_sum else "b"


def start_dice_game_step(bot, chat_id, telegram_id: int, bet_amount: float, rounds: int, username: str = None):
    """Deducts balance, prints initial message, and starts the turn flow."""
    adjust_balance(telegram_id, -bet_amount)

    user_ref = f"@{username}" if username else f'<a href="tg://user?id={telegram_id}">User</a>'
    formatted_bet = int(bet_amount) if bet_amount.is_integer() else bet_amount

    game_state = {
        "chat_id": chat_id,
        "telegram_id": telegram_id,
        "username": username,
        "bet_amount": bet_amount,
        "total_rounds": rounds,
        "current_round": 1,
        "player_wins": 0,
        "bot_wins": 0,
    }

    prompt_text = (
        f"<b>🎲 Dice vs Bot ₹{formatted_bet}</b>\n"
        f"<b>Round 1 of {rounds}</b>\n\n"
        f"👤 {user_ref} — send/copy this emoji now: 🎲"
    )
    bot.send_message(chat_id, prompt_text, parse_mode="HTML")

    bot.register_next_step_handler_by_chat_id(
        chat_id,
        lambda msg: handle_player_dice_turn(bot, msg, game_state)
    )


def handle_player_dice_turn(bot, message, state):
    if message.from_user.id != state["telegram_id"]:
        bot.register_next_step_handler_by_chat_id(
            state["chat_id"],
            lambda msg: handle_player_dice_turn(bot, msg, state)
        )
        return

    if not message.dice or message.dice.emoji != "🎲":
        bot.reply_to(message, "Please send a valid 🎲 emoji to take your turn!")
        bot.register_next_step_handler_by_chat_id(
            state["chat_id"],
            lambda msg: handle_player_dice_turn(bot, msg, state)
        )
        return

    player_roll = message.dice.value

    bot_dice_msg = bot.send_dice(state["chat_id"], emoji="🎲")
    bot_roll = bot_dice_msg.dice.value

    time.sleep(3)

    winner = decide_round_winner(player_roll, bot_roll, mode="classic")

    if winner is None:
        bot.send_message(
            state["chat_id"],
            f"🤝 <b>Tie ({player_roll} vs {bot_roll})! Roll again 🎲</b>",
            parse_mode="HTML"
        )
        bot.register_next_step_handler_by_chat_id(
            state["chat_id"],
            lambda msg: handle_player_dice_turn(bot, msg, state)
        )
        return

    if winner == "a":
        state["player_wins"] += 1
    else:
        state["bot_wins"] += 1

    # If scheduled rounds are complete but overall game is tied (e.g., 1-1 in 2 rounds)
    if state["current_round"] >= state["total_rounds"] and state["player_wins"] == state["bot_wins"]:
        user_ref = f"@{state['username']}" if state['username'] else "User"
        state["current_round"] += 1
        bot.send_message(
            state["chat_id"],
            f"⚔️ <b>Tie Game ({state['player_wins']}-{state['bot_wins']})! Tiebreaker Round {state['current_round']}</b>\n"
            f"👤 {user_ref} — Send 🎲 now!",
            parse_mode="HTML"
        )
        bot.register_next_step_handler_by_chat_id(
            state["chat_id"],
            lambda msg: handle_player_dice_turn(bot, msg, state)
        )
        return

    # Continue to next standard round
    if state["current_round"] < state["total_rounds"]:
        state["current_round"] += 1
        user_ref = f"@{state['username']}" if state['username'] else "User"

        bot.send_message(
            state["chat_id"],
            f"<b>Round {state['current_round']} of {state['total_rounds']}</b>\n"
            f"👤 {user_ref} — Send 1x 🎲 now!",
            parse_mode="HTML"
        )
        bot.register_next_step_handler_by_chat_id(
            state["chat_id"],
            lambda msg: handle_player_dice_turn(bot, msg, state)
        )
    else:
        finish_dice_game(bot, state)


def finish_dice_game(bot, state):
    won = state["player_wins"] > state["bot_wins"]
    bet_amount = state["bet_amount"]
    telegram_id = state["telegram_id"]
    username = state["username"]

    # Calculate multiplier using configured house edge % (e.g., 5% edge = 1.90x multiplier)
    house_edge_pct = get_house_edge()  # Expected format: float (e.g. 5.0 for 5%)
    multiplier = 2.0 * (1.0 - (house_edge_pct / 100.0))
    payout = round(bet_amount * multiplier, 2) if won else 0

    if won:
        adjust_balance(telegram_id, payout)
        announce_win(username or str(telegram_id), payout, "Dice vs Bot")

    record_bet(
        telegram_id=telegram_id,
        game="dice_vs_bot",
        bet_amount=bet_amount,
        payout=payout,
        result="win" if won else "loss",
        meta={"rounds": state["current_round"], "player_score": state["player_wins"], "bot_score": state["bot_wins"]},
    )

    formatted_bet = int(bet_amount) if bet_amount.is_integer() else bet_amount

    if won:
        formatted_payout = int(payout) if payout.is_integer() else payout
        bot.send_message(
            state["chat_id"],
            f"🎉 <b>You won! Score: {state['player_wins']}-{state['bot_wins']}</b>\n💰 <b>Payout: ₹{formatted_payout} ({multiplier:.2f}x)</b>",
            parse_mode="HTML"
        )
    else:
        bot.send_message(
            state["chat_id"],
            f"❌ <b>Bot won! Score: {state['bot_wins']}-{state['player_wins']}</b>\n💸 <b>You lost ₹{formatted_bet}</b>",
            parse_mode="HTML"
        )
