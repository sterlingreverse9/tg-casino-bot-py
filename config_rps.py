# Game configuration settings for RPS
RPS_MIN_BET = 10.0
RPS_MAX_BET = 10000.0
RPS_DEFAULT_MULTIPLIER = 1.80  # 1.80x payout (20% house edge)

# Winning logic lookup map
# rock (✊) beats scissors (✌️)
# paper (✋) beats rock (✊)
# scissors (✌️) beats paper (✋)
RPS_CHOICES = ["rock", "scissors", "paper"]
EMOJI_MAP = {
    "rock": "✊",
    "scissors": "✌️",
    "paper": "✋"
}

COUNTER_WIN = {
    "rock": "paper",
    "scissors": "rock",
    "paper": "scissors"
}

COUNTER_LOSE = {
    "rock": "scissors",
    "scissors": "paper",
    "paper": "rock"
}
