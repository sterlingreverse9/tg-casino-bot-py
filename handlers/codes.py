import html
from telebot.types import Message
from bot_instance import bot
from db import select, insert, update
from wallet import adjust_balance, record_bet

REQUIRED_TAG = "@thecassinobot"


@bot.message_handler(commands=["redeem", "claim", "code"])
def redeem_code_cmd(message: Message):
    """Redeems a promotional code for balance rewards with strict username tag check and max_claims enforcement."""
    telegram_id = message.from_user.id
    user_obj = message.from_user

    # 1. Require @thecassinobot in user's Name or Username
    first_name = user_obj.first_name or ""
    last_name = user_obj.last_name or ""
    username = user_obj.username or ""

    full_user_text = f"{first_name} {last_name} {username}".lower()

    if REQUIRED_TAG.lower() not in full_user_text:
        bot.reply_to(
            message,
            f"⚠️ <b>Access Denied!</b>\n\n"
            f"To claim promo codes, you must add <code>{REQUIRED_TAG}</code> to your Telegram name (or username).\n\n"
            f"Example: <i>{first_name} {REQUIRED_TAG}</i>",
            parse_mode="HTML"
        )
        return

    args = message.text.split()[1:]
    if not args:
        bot.reply_to(message, "⚠️ Usage: <code>/claim &lt;code&gt;</code>", parse_mode="HTML")
        return

    promo_code = args[0].strip().upper()

    # 2. Fetch promo code details from database
    code_data = select("codes", filters={"code": promo_code}, single=True)
    if not code_data:
        bot.reply_to(message, "❌ Invalid or expired promo code.")
        return

    # Check active status
    if not code_data.get("is_active", True):
        bot.reply_to(message, "❌ This promo code is no longer active.")
        return

    max_claims = code_data.get("max_claims", 1)
    current_claims = code_data.get("claimed_count", 0)
    reward_amount = float(code_data.get("reward_amount", 0.0))

    # 3. Enforce Strict Max Claims Check
    if current_claims >= max_claims:
        bot.reply_to(message, "❌ This promo code has reached its maximum claim limit!")
        return

    # 4. Check if user already claimed this specific code
    already_claimed = select("code_claims", filters={"code": promo_code, "user_id": telegram_id}, single=True)
    if already_claimed:
        bot.reply_to(message, "⚠️ You have already claimed this promo code!")
        return

    # 5. Atomic Execution: Record claim row FIRST to prevent race conditions
    try:
        claim_entry = insert("code_claims", {
            "code": promo_code,
            "user_id": telegram_id,
            "reward": reward_amount
        })

        if not claim_entry:
            bot.reply_to(message, "❌ Claim failed due to a concurrency conflict. Please try again.")
            return

        # Atomically increment claim count
        new_claim_count = current_claims + 1
        update_data = {"claimed_count": new_claim_count}

        # Deactivate if max claims limit reached
        if new_claim_count >= max_claims:
            update_data["is_active"] = False

        update("codes", filters={"code": promo_code}, values=update_data)

        # Credit user wallet
        adjust_balance(telegram_id, reward_amount)

        # Record transaction log
        record_bet(telegram_id, "promo_code", 0.0, reward_amount, "win")

        user_name_escaped = html.escape(first_name or "User")
        bot.reply_to(
            message,
            f"🎉 <b>Code Claimed Successfully!</b>\n\n"
            f"👤 <b>User:</b> {user_name_escaped}\n"
            f"🎁 <b>Reward:</b> ₹{reward_amount:.2f}\n"
            f"📊 <b>Claims:</b> {new_claim_count}/{max_claims}",
            parse_mode="HTML"
        )

    except Exception as e:
        print(f"[Promo Code Claim Error]: {e}")
        bot.reply_to(message, "⚠️ An error occurred while processing your reward.")


@bot.message_handler(commands=["makecode", "createcode"])
def create_code_cmd(message: Message):
    """Admin command to create new promo codes: /makecode CODE AMOUNT MAX_CLAIMS"""
    telegram_id = message.from_user.id

    # Check Admin permission
    user = select("users", filters={"telegram_id": telegram_id}, single=True)
    if not user or not user.get("is_admin"):
        bot.reply_to(message, "❌ Only administrators can create promo codes.")
        return

    args = message.text.split()[1:]
    if len(args) < 3:
        bot.reply_to(
            message, 
            "⚠️ Usage: <code>/makecode &lt;CODE&gt; &lt;AMOUNT&gt; &lt;MAX_CLAIMS&gt;</code>\n"
            "Example: <code>/makecode BONUS100 50 5</code>", 
            parse_mode="HTML"
        )
        return

    promo_code = args[0].strip().upper()

    try:
        reward_amount = float(args[1])
        max_claims = int(args[2])
    except ValueError:
        bot.reply_to(message, "❌ Amount and Max Claims must be valid numbers.")
        return

    if reward_amount <= 0 or max_claims <= 0:
        bot.reply_to(message, "⚠️ Amount and Max Claims must be greater than 0.")
        return

    # Check existing code
    existing = select("codes", filters={"code": promo_code}, single=True)
    if existing:
        bot.reply_to(message, "⚠️ A promo code with this name already exists!")
        return

    # Create code in DB
    res = insert("codes", {
        "code": promo_code,
        "reward_amount": reward_amount,
        "max_claims": max_claims,
        "claimed_count": 0,
        "is_active": True,
        "created_by": telegram_id
    })

    if res:
        bot.reply_to(
            message,
            f"✅ <b>Promo Code Created!</b>\n\n"
            f"🎟️ <b>Code:</b> <code>{promo_code}</code>\n"
            f"💰 <b>Reward:</b> ₹{reward_amount:.2f}\n"
            f"👥 <b>Max Claims:</b> {max_claims}",
            parse_mode="HTML"
        )
    else:
        bot.reply_to(message, "❌ Failed to create promo code in database.")
