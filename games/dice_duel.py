import html
import time
from wallet import adjust_balance, record_bet
from settings import get_house_edge
from helpers import announce_win


def decide_round_winner(a_sum: int, b_sum: int, mode: str = "classic"):
    if a_sum == b_sum:
        return None  # tie -> reroll round
    if mode == "crazy":
        return "a" if a_sum < b_sum else "b"
    return "a" if a_sum > b_sum else "b"


def start_dice_game_step(bot, chat_id, telegram_id: int, bet_amount: float, rounds: int, username: str = None, first_name: str = "User"):
    """Deducts balance, prints initial message, and starts the turn flow."""
    adjust_balance(telegram_id, -bet_amount)

    safe_name = html.escape(first_name)
    user_ref = f"@{username}" if username else f'<a href="tg://user?id={telegram_id}">{safe_name}</a>'
    formatted_bet = int(bet_amount) if bet_amount.is_integer() else bet_amount

    game_state = {
        "chat_id": chat_id,
        "telegram_id": telegram_id,
        "username": username,
        "user_ref": user_ref,
        "bet_amount": bet_amount,
        "total_rounds": rounds,
        "current_round": 1,
        "player_wins": 0,
        "bot_wins": 0,
        "round_history": [],
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
        round_res = f"R{state['current_round']}: You 🎲{player_roll} vs Bot 🎲{bot_roll} (Won)"
    else:
        state["bot_wins"] += 1
        round_res = f"R{state['current_round']}: You 🎲{player_roll} vs Bot 🎲{bot_roll} (Lost)"

    state["round_history"].append(round_res)

    # Tiebreaker handling if overall score is equal after playing all rounds
    if state["current_round"] >= state["total_rounds"] and state["player_wins"] == state["bot_wins"]:
        state["current_round"] += 1
        bot.send_message(
            state["chat_id"],
            f"⚔️ <b>Tie Game ({state['player_wins']}-{state['bot_wins']})! Tiebreaker Round {state['current_round']}</b>\n"
            f"👤 {state['user_ref']} — Send 🎲 now!",
            parse_mode="HTML"
        )
        bot.register_next_step_handler_by_chat_id(
            state["chat_id"],
            lambda msg: handle_player_dice_turn(bot, msg, state)
        )
        return

    if state["current_round"] < state["total_rounds"]:
        state["current_round"] += 1
        bot.send_message(
            state["chat_id"],
            f"<b>Round {state['current_round']} of {state['total_rounds']}</b>\n"
            f"👤 {state['user_ref']} — Send 1x 🎲 now!",
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
    user_ref = state["user_ref"]

    # Dynamic house edge calculation
    raw_edge = float(get_house_edge())
    edge_decimal = raw_edge if raw_edge < 1.0 else (raw_edge / 100.0)
    
    # Correct formula: 2.0x minus the house edge
    multiplier = round(2.0 - edge_decimal, 2)

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
    formatted_payout = int(payout) if payout.is_integer() else payout

    history_text = "\n".join([f"• {h}" for h in state["round_history"]])

    if won:
        msg_text = (
            f"🎉 {user_ref} <b>You won! Score: {state['player_wins']}-{state['bot_wins']}</b>\n"
            f"💰 <b>Payout: ₹{formatted_payout} ({multiplier:.2f}x)</b>\n\n"
            f"<b>Round Summary:</b>\n{history_text}"
        )
    else:
        msg_text = (
            f"❌ {user_ref} <b>Bot won! Score: {state['bot_wins']}-{state['player_wins']}</b>\n"
            f"💸 <b>You lost ₹{formatted_bet}</b>\n\n"
            f"<b>Round Summary:</b>\n{history_text}"
        )

    bot.send_message(state["chat_id"], msg_text, parse_mode="HTML")
