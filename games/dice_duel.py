import re

MIN_BET = 10
CODE_PATTERN = re.compile(r"^(\d+)d(\d+)w$", re.IGNORECASE)


def parse_dice_code(code: str):
    """'3d1w' -> (rolls_per_round=3, rounds=1). Returns None if invalid."""
    match = CODE_PATTERN.match(code)
    if not match:
        return None
    dice_count, rounds = int(match.group(1)), int(match.group(2))
    if dice_count < 1 or dice_count > 3 or rounds < 1 or rounds > 3:
        return None
    return dice_count, rounds


def decide_round_winner(a_sum: int, b_sum: int, mode: str):
    if a_sum == b_sum:
        return None  # tie -> reroll
    if mode == "crazy":
        return "a" if a_sum < b_sum else "b"
    return "a" if a_sum > b_sum else "b"
