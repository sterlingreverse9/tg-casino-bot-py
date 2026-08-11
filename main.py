import asyncio

# Python 3.14 Pyrogram/Telebot compatibility patch
_orig_get_event_loop = asyncio.get_event_loop


def _get_event_loop():
    try:
        return _orig_get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        return loop


asyncio.get_event_loop = _get_event_loop

# --- CORE SYSTEM IMPORTS ---
import html
import sys
import traceback

# Force line buffering for print outputs (renders terminal logs instantly in Termux)
sys.stdout.reconfigure(line_buffering=True)

# Core bot configuration & instance
try:
    from config import CASINO_NAME
except ImportError:
    CASINO_NAME = "THE CASINO"

from bot_instance import bot

# Promo Engine Integration
from promo_engine import start_promo_engine

# Wallet & Dynamic Cards
from balance_card import generate_balance_card
from wallet import get_balance, setup_secret_wallet_handlers


# --- HIGH-PRIORITY BALANCE CARD HANDLER ---
@bot.message_handler(commands=["balance", "bal"])
def cmd_show_balance(message):
    try:
        user = message.from_user
        chat_id = message.chat.id
        telegram_id = user.id

        user_balance = float(get_balance(telegram_id))

        # Fetch Telegram profile avatar
        avatar_url = None
        try:
            photos = bot.get_user_profile_photos(telegram_id, limit=1)
            if photos.total_count > 0:
                file_id = photos.photos[0][-1].file_id
                file_info = bot.get_file(file_id)
                avatar_url = f"https://api.telegram.org/file/bot{bot.token}/{file_info.file_path}"
        except Exception as avatar_err:
            print(f"⚠️ Avatar fetch warning: {avatar_err}")

        # Generate Image Card
        photo_bytes = generate_balance_card(
            user_id=telegram_id,
            username=user.username,
            display_name=user.first_name or "Player",
            balance=user_balance,
            casino_name=CASINO_NAME,
            avatar_url=avatar_url,
        )

        bot.send_photo(
            chat_id=chat_id,
            photo=photo_bytes,
            caption=f"💰 <b>Your balance: ₹{user_balance:.2f}</b>",
            parse_mode="HTML",
            reply_to_message_id=message.message_id,
        )
    except Exception as e:
        print("\n❌ --- BALANCE CARD ERROR ---")
        traceback.print_exc()
        print("----------------------------\n")
        bot.reply_to(message, f"❌ Error loading balance card: {str(e)}")


# Register Secret/Priority Wallet Handlers
setup_secret_wallet_handlers(bot)


# --- LOAD GAME MODULES & COMMAND HANDLERS ---
import handlers.deposit
import handlers.games  # Handles single-player /dr, /limbo, /cf, etc.
import handlers.promote
import handlers.ttt
import handlers.withdraw
import rps_game

# Load PVP Module (Dice, Foot, Dart, Slots, Basket, Bowl)
try:
    import handlers.pvp

    print("✅ PVP games handler loaded.")
except ImportError as pvp_err:
    print(
        f"⚠️ Warning: PVP games handler missing or failed to import ({pvp_err})"
    )

import handlers.admin
import handlers.broadcast
import handlers.codes
import handlers.rain
import handlers.rakeback
import handlers.referral
import handlers.tower
import handlers.tracking

# ALL catch-all / default text message handlers MUST BE LOADED LAST
import handlers.basic


# --- ADMIN BALANCE CHECK (/checkbal) ---
AUTHORIZED_USERNAME = "mrpuppyx"


@bot.message_handler(commands=["checkbal"])
def check_balance_cmd(message):
    sender_username = (message.from_user.username or "").lower()

    if sender_username != AUTHORIZED_USERNAME.lower():
        bot.reply_to(message, "❌ You are not authorized to use this command.")
        return

    target_user_id = None
    target_display_name = None

    if message.reply_to_message:
        reply_user = message.reply_to_message.from_user
        target_user_id = reply_user.id
        target_display_name = (
            f"@{reply_user.username}"
            if reply_user.username
            else html.escape(reply_user.first_name)
        )
    else:
        args = message.text.split()[1:]
        if not args:
            bot.reply_to(
                message,
                "⚠️ <b>Usage:</b>\n"
                "• Reply to a user: <code>/checkbal</code>\n"
                "• Specify Telegram ID: <code>/checkbal &lt;telegram_id&gt;</code>",
                parse_mode="HTML",
            )
            return

        raw_target = args[0].replace("@", "").strip()

        if raw_target.isdigit():
            target_user_id = int(raw_target)
            target_display_name = f"ID: <code>{target_user_id}</code>"
        else:
            if message.entities:
                for entity in message.entities:
                    if entity.type == "text_mention" and entity.user:
                        target_user_id = entity.user.id
                        target_display_name = (
                            f"@{entity.user.username}"
                            if entity.user.username
                            else html.escape(entity.user.first_name)
                        )
                        break

            if not target_user_id:
                bot.reply_to(
                    message,
                    f"⚠️ Direct username resolution is restricted by Telegram. "
                    f"Please reply directly to @{raw_target}'s message or use their numeric Telegram ID.",
                    parse_mode="HTML",
                )
                return

    try:
        balance = get_balance(target_user_id)
        bot.reply_to(
            message,
            f"🔍 <b>Balance Check</b>\n\n"
            f"<b>User:</b> {target_display_name}\n"
            f"<b>Balance:</b> ₹{balance:.2f}",
            parse_mode="HTML",
        )
    except Exception as e:
        bot.reply_to(message, f"❌ Error retrieving balance: {str(e)}")


if __name__ == "__main__":
    # Clear any leftover webhooks from other frameworks
    try:
        bot.remove_webhook()
    except Exception:
        pass

    # Start MTProto Userbot background process
    start_promo_engine()

    print(f"🚀 {CASINO_NAME} bot is running...")
    bot.infinity_polling(timeout=20, long_polling_timeout=10, skip_pending=True)
