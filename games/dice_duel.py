import random
import re
from wallet import get_balance, adjust_balance, record_bet
from game_math import payout_for

MIN_BET = 10
CODE_PATTERN = re.compile(r"^(\d+)d(\d+)w$", re.IGNORECASE)


def parse_dice_code(code: str):
    """'3d1w' -> (3 dice per round, 1 round). Returns None if invalid."""
    match = CODE_PATTERN.match(code)
    if not match:
        return None
    dice_count, rounds = int(match.group(1)), int(match.group(2))
    if dice_count < 1 or dice_count > 5 or rounds < 1 or rounds > 9:
        return None
    return dice_count, rounds


def roll_dice_set(count: int):
    return [random.randint(1, 6) for _ in range(count)]


def decide_round_winner(a_dice, b_dice, mode: str):
    a_sum, b_sum = sum(a_dice), sum(b_dice)
    if a_sum == b_sum:
        return None  # tie -> reroll this round
    if mode == "crazy":
        return "a" if a_sum < b_sum else "b"
    return "a" if a_sum > b_sum else "b"


def play_match(dice_count: int, rounds: int, mode: str):
    """Simulate a full best-of-`rounds` match. Returns (winner 'a'/'b', round_log)."""
    a_wins = b_wins = 0
    needed = rounds // 2 + 1
    round_log = []
    while a_wins < needed and b_wins < needed:
        a_dice = roll_dice_set(dice_count)
        b_dice = roll_dice_set(dice_count)
        result = decide_round_winner(a_dice, b_dice, mode)
        if result is None:
            round_log.append({"a": a_dice, "b": b_dice, "result": "tie"})
            continue
        if result == "a":
            a_wins += 1
        else:
            b_wins += 1
        round_log.append({"a": a_dice, "b": b_dice, "result": result})
    return ("a" if a_wins > b_wins else "b"), round_log


def format_match_log(round_log, name_a: str, name_b: str):
    lines = []
    for i, r in enumerate(round_log, 1):
        a_sum, b_sum = sum(r["a"]), sum(r["b"])
        if r["result"] == "tie":
            lines.append(f"Round {i}: {name_a} {r['a']} ({a_sum}) vs {name_b} {r['b']} ({b_sum}) — tie, reroll")
        else:
            winner_name = name_a if r["result"] == "a" else name_b
            lines.append(f"Round {i}: {name_a} {r['a']} ({a_sum}) vs {name_b} {r['b']} ({b_sum}) — {winner_name} wins round")
    return "\n".join(lines)


def play_vs_bot(bot, chat_id, telegram_id: int, bet_amount: float, dice_count: int, rounds: int, mode: str):
    balance = get_balance(telegram_id)
    if bet_amount < MIN_BET:
        bot.send_message(chat_id, f"Minimum bet is {MIN_BET} coins.")
        return
    if bet_amount > balance:
        bot.send_message(chat_id, f"Not enough balance. Your balance: {balance}")
        return

    adjust_balance(telegram_id, -bet_amount)
    winner, round_log = play_match(dice_count, rounds, mode)
    won = winner == "a"
    payout = payout_for(bet_amount, 0.5) if won else 0
    if won:
        adjust_balance(telegram_id, payout)

    record_bet(
        telegram_id=telegram_id,
        game="dice_duel_bot",
        bet_amount=bet_amount,
        payout=payout,
        result="win" if won else "loss",
        meta={"mode": mode, "dice_count": dice_count, "rounds": rounds},
    )

    new_balance = get_balance(telegram_id)
    text = f"⚔️ Dice Duel vs {CASINO_LABEL} • {mode} mode\n" + format_match_log(round_log, "You", CASINO_LABEL) + "\n\n"
    if won:
        text += f"✅ You won {payout} coins!\nBalance: {new_balance}"
    else:
        text += f"❌ You lost {bet_amount} coins.\nBalance: {new_balance}"
    bot.send_message(chat_id, text)


CASINO_LABEL = "The Casino"
