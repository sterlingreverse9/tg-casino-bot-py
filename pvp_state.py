import time

# Challenge format: { challenge_id: { "challenger_id": int, "amount": float, "game_type": str, "created_at": float } }
PENDING_CHALLENGES = {}

# Active duel sessions format: { user_id: { "game_data": dict, "last_active": float } }
ACTIVE_DUELS = {}

CHALLENGE_TIMEOUT_SECONDS = 60
SESSION_TIMEOUT_SECONDS = 60


def create_challenge(challenger_id, amount, game_type="dice"):
    cleanup_expired()
    challenge_id = f"{challenger_id}_{int(time.time())}"
    PENDING_CHALLENGES[challenge_id] = {
        "challenger_id": challenger_id,
        "amount": amount,
        "game_type": game_type,
        "created_at": time.time(),
    }
    print(
        f"[PVP LOG] Challenge created: {challenge_id} | Amount: ₹{amount}",
        flush=True,
    )
    return challenge_id


def get_challenge(challenge_id):
    cleanup_expired()
    return PENDING_CHALLENGES.get(challenge_id)


def remove_challenge(challenge_id):
    if challenge_id in PENDING_CHALLENGES:
        del PENDING_CHALLENGES[challenge_id]
        print(f"[PVP LOG] Challenge removed: {challenge_id}", flush=True)


def set_active_duel(user_id, game_data):
    """Locks user into an active game session with timestamp."""
    ACTIVE_DUELS[user_id] = {"game_data": game_data, "last_active": time.time()}


def get_active_duel(user_id):
    """Retrieves active game session if not expired."""
    cleanup_expired()
    session = ACTIVE_DUELS.get(user_id)
    if session:
        return session["game_data"]
    return None


def clear_active_duel(user_id):
    """Clears game session upon completion or forfeit."""
    if user_id in ACTIVE_DUELS:
        del ACTIVE_DUELS[user_id]
        print(f"[PVP LOG] Cleared active duel for user {user_id}", flush=True)


def update_duel_activity(user_id):
    """Resets inactivity timer on player action."""
    if user_id in ACTIVE_DUELS:
        ACTIVE_DUELS[user_id]["last_active"] = time.time()


def cleanup_expired():
    """Purges expired pending challenges and abandoned active games."""
    now = time.time()

    # Clear pending challenges > 60s
    expired_challenges = [
        cid
        for cid, data in PENDING_CHALLENGES.items()
        if now - data["created_at"] > CHALLENGE_TIMEOUT_SECONDS
    ]
    for cid in expired_challenges:
        del PENDING_CHALLENGES[cid]
        print(f"[PVP LOG] Expired challenge purged: {cid}", flush=True)

    # Clear abandoned active duels > 60s
    abandoned_users = [
        uid
        for uid, session in ACTIVE_DUELS.items()
        if now - session["last_active"] > SESSION_TIMEOUT_SECONDS
    ]
    for uid in abandoned_users:
        del ACTIVE_DUELS[uid]
        print(
            f"[PVP LOG] Abandoned duel purged for inactive user: {uid}",
            flush=True,
        )
