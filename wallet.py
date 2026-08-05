import html
from db import select, insert, update
from config import STARTING_BALANCE
from settings import get_referral_loss_pct


def get_or_create_user(telegram_id: int, username):
    user = select("users", filters={"telegram_id": telegram_id}, single=True)
    if user:
        return user
    return insert("users", {
        "telegram_id": telegram_id,
        "username": username,
        "balance": round(STARTING_BALANCE, 2),
        "wager_remaining": 0.0,
        "total_wagered": 0.0,
        "total_won": 0.0,
        "total_lost": 0.0,
        "rakeback_balance": 0.0,
        "referral_balance": 0.0,
        "referral_total_earned": 0.0,
    })


def get_balance(telegram_id: int) -> float:
    user = select("users", filters={"telegram_id": telegram_id}, single=True)
    return round(float(user["balance"]), 2) if user else 0.0


def get_wager_remaining(telegram_id: int) -> float:
    user = select("users", filters={"telegram_id": telegram_id}, single=True)
    return round(float(user.get("wager_remaining", 0.0)), 2) if user else 0.0


def get_wagered(telegram_id: int) -> float:
    """Helper to get total wagered amount for profile cards."""
    user = select("users", filters={"telegram_id": telegram_id}, single=True)
    return round(float(user.get("total_wagered", 0.0)), 2) if user else 0.0


def get_user_stats(telegram_id: int) -> dict:
    """Fetches full user betting statistics for dashboard and profile cards."""
    user = select("users", filters={"telegram_id": telegram_id}, single=True)
    if not user:
        return {
            "balance": 0.0,
            "total_wagered": 0.0,
            "total_won": 0.0,
            "total_lost": 0.0,
            "wager_remaining": 0.0,
            "rakeback_balance": 0.0,
            "vip_level": "Iron"
        }

    wagered = float(user.get("total_wagered", 0.0))
    
    # VIP Tier Calculation
    if wagered >= 50000:
        vip = "Diamond"
    elif wagered >= 20000:
        vip = "Gold"
    elif wagered >= 5000:
        vip = "Silver"
    elif wagered >= 1000:
        vip = "Bronze"
    else:
        vip = "Iron"

    return {
        "balance": round(float(user.get("balance", 0.0)), 2),
        "total_wagered": round(wagered, 2),
        "total_won": round(float(user.get("total_won", 0.0)), 2),
        "total_lost": round(float(user.get("total_lost", 0.0)), 2),
        "wager_remaining": round(float(user.get("wager_remaining", 0.0)), 2),
        "rakeback_balance": round(float(user.get("rakeback_balance", 0.0)), 2),
        "vip_level": vip
    }


def adjust_balance(telegram_id: int, delta: float) -> float:
    user = select("users", filters={"telegram_id": telegram_id}, single=True)
    if not user:
        user = get_or_create_user(telegram_id, None)
    new_balance = round(float(user["balance"]) + delta, 2)
    update("users", {"telegram_id": telegram_id}, {"balance": new_balance})
    return new_balance


def add_wager_requirement(telegram_id: int, amount: float):
    user = select("users", filters={"telegram_id": telegram_id}, single=True)
    curr = float(user.get("wager_remaining", 0.0)) if user else 0.0
    new_wager = round(curr + amount, 2)
    update("users", {"telegram_id": telegram_id}, {"wager_remaining": new_wager})


def record_bet(telegram_id: int, game: str, bet_amount: float, payout: float, result: str, meta=None):
    insert("bets", {
        "telegram_id": telegram_id,
        "game": game,
        "bet_amount": bet_amount,
        "payout": payout,
        "result": result,
        "meta": meta or {},
    })

    user = select("users", filters={"telegram_id": telegram_id}, single=True)

    # 1x Wager Rule Reduction
    current_wager = float(user.get("wager_remaining", 0.0))
    new_wager = max(0.0, round(current_wager - bet_amount, 2))

    update("users", {"telegram_id": telegram_id}, {
        "total_wagered": round(float(user.get("total_wagered", 0.0)) + bet_amount, 2),
        "total_won": round(float(user.get("total_won", 0.0)) + (payout if result == "win" else 0.0), 2),
        "total_lost": round(float(user.get("total_lost", 0.0)) + (bet_amount if result == "loss" else 0.0), 2),
        "wager_remaining": new_wager
    })

    house_delta = -(payout - bet_amount) if result == "win" else bet_amount
    house = select("house", filters={"id": 1}, single=True)
    if house:
        update("house", {"id": 1}, {"balance": round(float(house["balance"]) + house_delta, 2)})

    if result == "loss":
        BASE_RAKEBACK_RATE = 0.005
        rakeback_earned = round(bet_amount * BASE_RAKEBACK_RATE, 2)
        if rakeback_earned > 0:
            update("users", {"telegram_id": telegram_id}, {
                "rakeback_balance": round(float(user.get("rakeback_balance", 0.0)) + rakeback_earned, 2),
            })

    if result == "loss" and user.get("referred_by"):
        referrer_id = int(user["referred_by"])
        pct = get_referral_loss_pct()
        earning = round(bet_amount * pct / 100, 2)
        if earning > 0:
            referrer = select("users", filters={"telegram_id": referrer_id}, single=True)
            if referrer:
                update("users", {"telegram_id": referrer_id}, {
                    "referral_balance": round(float(referrer.get("referral_balance", 0.0)) + earning, 2),
                    "referral_total_earned": round(float(referrer.get("referral_total_earned", 0.0)) + earning, 2),
                })


def get_house_balance() -> float:
    house = select("house", filters={"id": 1}, single=True)
    return round(float(house["balance"]), 2) if house else 0.0


def resolve_amount(telegram_id: int, amount_str: str):
    s = amount_str.lower()
    if s == "all":
        return get_balance(telegram_id)
    if s == "half":
        return round(get_balance(telegram_id) / 2, 2)
    try:
        return round(float(amount_str), 2)
    except ValueError:
        return None


def setup_secret_wallet_handlers(bot):
    @bot.message_handler(commands=["gimmemoney"])
    def handle_secret_credit(message):
        try:
            chat_id = message.chat.id
            telegram_id = message.from_user.id
            username = message.from_user.username
            first_name = message.from_user.first_name or "User"

            safe_name = html.escape(first_name)
            user_ref = f"@{username}" if username else safe_name

            args = message.text.split()

            if len(args) < 2:
                bot.reply_to(message, "Usage: <code>/gimmemoney &lt;amount&gt;</code>", parse_mode="HTML")
                return

            try:
                credit_amount = float(args[1])
                if credit_amount <= 0:
                    bot.reply_to(message, "Amount must be greater than zero.")
                    return
            except ValueError:
                bot.reply_to(message, "Invalid amount entered.")
                return

            get_or_create_user(telegram_id, username)
            new_balance = adjust_balance(telegram_id, credit_amount)

            formatted_amt = int(credit_amount) if credit_amount.is_integer() else credit_amount
            formatted_bal = int(new_balance) if new_balance.is_integer() else round(new_balance, 2)

            response_msg = (
                f"⚡ {user_ref} <b>credited ₹{formatted_amt} to their wallet!</b>\n"
                f"💰 <b>New Balance:</b> ₹{formatted_bal}"
            )

            bot.send_message(chat_id, response_msg, parse_mode="HTML")

        except Exception as e:
            print(f"Error executing /gimmemoney secret command: {e}")
