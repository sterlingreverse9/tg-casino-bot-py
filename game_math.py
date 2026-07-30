from config import HOUSE_EDGE


def multiplier_for(win_chance: float) -> float:
    """
    Payout multiplier for a given true win probability.
    Matches spec: 50% win chance, 0.10 edge -> multiplier 1.9
    (bet 10 -> win 19)
    multiplier = (1 / win_chance) - house_edge
    """
    return (1 / win_chance) - HOUSE_EDGE


def payout_for(bet_amount: float, win_chance: float) -> float:
    return round(bet_amount * multiplier_for(win_chance), 2)
