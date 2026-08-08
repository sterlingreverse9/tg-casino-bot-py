import html
import uuid
import datetime
from telebot.types import Message
from bot_instance import bot
from db import select, insert, update
from wallet import get_balance, adjust_balance, record_bet

REQUIRED_TAG = "@thecassinobot"

# In-memory tracking for multi-step creation flow
# Structure: { telegram_id: {"step": "code_name"|"max_users"|"amount", "data": {...}} }
CODE_CREATION_FLOW = {}


@bot.message_handler(commands=["makecode", "createcode"])
def start_makecode_flow(message: Message):
    """Initiates interactive promo code creation flow."""
    telegram_id = message.from_user.id

    # Check Admin permission
    user = select("users", filters={"telegram_id": telegram_id}, single=True)
    if not user or not user.get("is_admin"):
        bot.reply_to(message, "❌ Only administrators can create promo codes.")
        return

    CODE_CREATION_FLOW[telegram_id] = {
        "step": "code_name",
        "data": {}
    }

    text = (
        "🎁 <b>CREATE A PROMO CODE</b>\n"
        "────────────────────────\n"
        "Please enter your desired <b>Code Name</b>.\n\n"
        "<i>Rules:</i>\n"
        "• At least 4 characters long\n"
        "• No spaces or special characters\n"
        "• Example: <code>Happy39</code>, <code>Everest32</code>"
    )
    bot.reply_to(message, text, parse_mode="HTML")


@bot.message_handler(func=lambda msg: msg.from_user.id in CODE_CREATION_FLOW and not msg.text.startswith("/"))
def handle_makecode_steps(message: Message):
    """Handles the multi-step inputs for creating a code."""
    telegram_id = message.from_user.id
    user_state = CODE_CREATION_FLOW.get(telegram_id)

    if not user_state:
        return

    step = user_state["step"]
    text_input = message.text.strip()

    # STEP 1: Code Name Input
    if step == "code_name":
        if len(text_input) < 4 or not text_input.isalnum():
            bot.reply_to(message, "⚠️ Invalid code name! Must be at least 4 alphanumeric characters without spaces.")
            return

        # Check existing code in Supabase
        existing = select("promo_codes", filters={"code_name": text_input}, single=True)
        if existing:
            bot.reply_to(message, "⚠️ A promo code with this name already exists! Enter a different name.")
            return

        user_state["data"]["code_name"] = text_input
        user_state["step"] = "max_users"

        reply_text = (
            f"✅ <b>Code Name set to:</b> {text_input}\n\n"
            f"👇 Enter <b>max users</b> who can claim this code (e.g., 4, 10):"
        )
        bot.reply_to(message, reply_text, parse_mode="HTML")

    # STEP 2: Max Users Input
    elif step == "max_users":
        try:
            max_users = int(text_input)
            if max_users <= 0:
                raise ValueError
        except ValueError:
            bot.reply_to(message, "⚠️ Max users must be a positive whole number.")
            return

        user_state["data"]["max_users"] = max_users
        user_state["step"] = "amount"

        reply_text = (
            f"👥 <b>Max Users:</b> {max_users}\n\n"
            f"👇 Enter <b>amount per user</b> (Min: ₹10):"
        )
        bot.reply_to(message, reply_text, parse_mode="HTML")

    # STEP 3: Amount Input & Completion
    elif step == "amount":
        try:
            amount_per_user = float(text_input)
            if amount_per_user < 10.0:
                bot.reply_to(message, "⚠️ Minimum amount per user is ₹10.00.")
                return
        except ValueError:
            bot.reply_to(message, "⚠️ Amount must be a valid number.")
            return

        code_name = user_state["data"]["code_name"]
        max_users = user_state["data"]["max_users"]

        # Calculate Total with 2.5% fee
        subtotal = amount_per_user * max_users
        total_deducted = subtotal * 1.025

        user_bal = get_balance(telegram_id)
        if user_bal < total_deducted:
            bot.reply_to(message, f"❌ Insufficient balance! Required: ₹{total_deducted:.2f}, Balance: ₹{user_bal:.2f}")
            del CODE_CREATION_FLOW[telegram_id]
            return

        # Deduct balance from creator
        adjust_balance(telegram_id, -total_deducted)

        creator_username = message.from_user.username or message.from_user.first_name

        # Valid schema insert matching Supabase promo_codes table
        record = {
            "code_id": uuid.uuid4().hex[:10],
            "creator_id": telegram_id,
            "creator_username": creator_username,
            "code_name": code_name,
            "max_users": max_users,
            "amount_per_user": amount_per_user,
            "total_cost": total_deducted,
            "claimed_by": [],
            "created_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }
        res = insert("promo_codes", record)

        if res:
            # Reply confirmation to Admin
            bot.reply_to(
                message,
                f"CODE MADE 🎉\n"
                f"CODE : {code_name}\n"
                f"AMOUNT PER USER : ₹{amount_per_user:.2f}\n"
                f"MAX CLAIMABLE USERS : {max_users}\n\n"
                f"use /claim {code_name} to claim"
            )

            # Announcement message
            announcement = (
                f"🚨 <b>NEW PROMO CODE CREATED</b>\n"
                f"👤 <b>Creator:</b> @{creator_username} ({telegram_id})\n"
                f"🏷️ <b>Code:</b> {code_name}\n"
                f"💵 <b>Amount/User:</b> ₹{amount_per_user:.2f}\n"
                f"👥 <b>Max Users:</b> {max_users}\n"
                f"💰 <b>Total Deducted:</b> ₹{total_deducted:.2f}"
            )
            bot.send_message(message.chat.id, announcement, parse_mode="HTML")
        else:
            # Refund on failure
            adjust_balance(telegram_id, total_deducted)
            bot.reply_to(message, "❌ Database insertion failed. Funds refunded.")

        del CODE_CREATION_FLOW[telegram_id]


@bot.message_handler(commands=["redeem", "claim", "code"])
def redeem_code_cmd(message: Message):
    """Redeems a promotional code for balance rewards."""
    telegram_id = message.from_user.id
    user_obj = message.from_user

    # Tag Verification Requirement
    first_name = user_obj.first_name or ""
    last_name = user_obj.last_name or ""
    username = user_obj.username or ""
    full_user_text = f"{first_name} {last_name} {username}".lower()

    if REQUIRED_TAG.lower() not in full_user_text:
        bot.reply_to(
            message,
            f"⚠️ <b>Access Denied!</b>\n\n"
            f"To claim promo codes, you must add <code>{REQUIRED_TAG}</code> to your Telegram name or username.",
            parse_mode="HTML"
        )
        return

    args = message.text.split()[1:]
    if not args:
        bot.reply_to(message, "⚠️ Usage: <code>/claim &lt;code&gt;</code>", parse_mode="HTML")
        return

    promo_code = args[0].strip()

    # Fetch from Supabase 'promo_codes'
    code_data = select("promo_codes", filters={"code_name": promo_code}, single=True)
    if not code_data:
        bot.reply_to(message, "❌ Invalid or expired promo code.")
        return

    max_claims = code_data.get("max_users", 1)
    reward_amount = float(code_data.get("amount_per_user", 0.0))

    # Calculate claim count dynamically from code_claims
    existing_claims = select("code_claims", filters={"code": promo_code}) or []
    current_claims = len(existing_claims)

    if current_claims >= max_claims:
        bot.reply_to(message, "❌ This promo code has reached its maximum claim limit!")
        return

    # Check if user already claimed this specific code
    already_claimed = select("code_claims", filters={"code": promo_code, "user_id": telegram_id}, single=True)
    if already_claimed:
        bot.reply_to(message, "⚠️ You have already claimed this promo code!")
        return

    try:
        claim_entry = insert("code_claims", {
            "code": promo_code,
            "user_id": telegram_id,
            "reward": reward_amount
        })

        if not claim_entry:
            bot.reply_to(message, "❌ Claim failed. Please try again.")
            return

        new_claim_count = current_claims + 1

        # Keep claimed_by list updated in promo_codes
        claimed_by = code_data.get("claimed_by", [])
        if telegram_id not in claimed_by:
            claimed_by.append(telegram_id)
            update("promo_codes", filters={"code_name": promo_code}, values={"claimed_by": claimed_by})

        # Credit user balance
        adjust_balance(telegram_id, reward_amount)
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
