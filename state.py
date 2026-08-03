"""Shared in-memory state and constants used across handler modules."""

deposit_states = {}   # telegram_id -> {"step": "amount"|"screenshot"|"utr", "deposit_id": int}
withdraw_states = {}  # telegram_id -> {"step": "amount"|"upi"|"confirm", "amount": float, "upi": str, "fee": float, "net": float}
admin_wd_states = {}  # admin_id -> {"wd_id": str}

active_rains = {}     # message_id -> {"amount", "chat_id", "participants": set()}
dice_setups = {}      # setup_id -> in-progress dice duel wizard state
active_matches = {}   # match_id -> live dice duel match state
dice_waiters = {}     # (chat_id, telegram_id) -> match_id
tower_setups = {}     # setup_id -> pending tower game awaiting difficulty
active_towers = {}    # (chat_id, telegram_id) -> live tower game state

HOUSE_EDGE_RAKE = 0.10
PROMO_TAG = "@thecassinobot"
CASINO_LABEL = "The Casino"
MIN_WAGERED_FOR_RAIN = 1000
