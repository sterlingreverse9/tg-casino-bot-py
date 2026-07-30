from db import select, insert, update


def is_game_enabled(game: str) -> bool:
    row = select("game_status", filters={"game": game}, single=True)
    if row is None:
        return True  # not configured yet = enabled by default
    return bool(row.get("enabled", True))


def set_game_enabled(game: str, enabled: bool):
    row = select("game_status", filters={"game": game}, single=True)
    if row is None:
        insert("game_status", {"game": game, "enabled": enabled})
    else:
        update("game_status", {"game": game}, {"enabled": enabled})
