import random
from settings import get_house_edge

TOTAL_FLOORS = 8

DIFFICULTY_CONFIG = {
    "easy": {"tiles": 4, "bombs": 2},    # 50% survive per floor (was 75%)
    "medium": {"tiles": 4, "bombs": 3},  # 25% survive per floor (was 50%)
    "hard": {"tiles": 5, "bombs": 4},    # 20% survive per floor (was 25%)
}


def survive_chance(difficulty: str) -> float:
    cfg = DIFFICULTY_CONFIG[difficulty]
    return (cfg["tiles"] - cfg["bombs"]) / cfg["tiles"]


def floor_multiplier(difficulty: str, floors_cleared: int) -> float:
    p = survive_chance(difficulty)
    edge = get_house_edge()
    return round((1 / p) ** floors_cleared * (1 - edge), 4)


def generate_floor(difficulty: str):
    cfg = DIFFICULTY_CONFIG[difficulty]
    tiles = ["bomb"] * cfg["bombs"] + ["gold"] * (cfg["tiles"] - cfg["bombs"])
    random.shuffle(tiles)
    return tiles

