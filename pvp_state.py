# pvp_state.py
import time

# Dictionary to hold active challenges
# Format: { challenge_id: { "challenger_id": int, "amount": float, "game_type": str, "created_at": float } }
PENDING_CHALLENGES = {}

def create_challenge(challenger_id, amount, game_type="dice"):
    challenge_id = f"{challenger_id}_{int(time.time())}"
    PENDING_CHALLENGES[challenge_id] = {
        "challenger_id": challenger_id,
        "amount": amount,
        "game_type": game_type,
        "created_at": time.time()
    }
    return challenge_id

def get_challenge(challenge_id):
    return PENDING_CHALLENGES.get(challenge_id)

def remove_challenge(challenge_id):
    if challenge_id in PENDING_CHALLENGES:
        del PENDING_CHALLENGES[challenge_id]
