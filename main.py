from config import CASINO_NAME
from bot_instance import bot
from wallet import get_balance

# Importing handlers
# Add this import near the top of main.py
import handlers.codes
import handlers.basic
import handlers.admin
import handlers.rain
import handlers.deposit
import handlers.withdraw
import handlers.rakeback
import handlers.games
import handlers.tower
import handlers.referral
import handlers.tracking
import handlers.broadcast

# Register secret wallet handlers explicitly (/gimmemoney)
from wallet import setup_secret_wallet_handlers
setup_secret_wallet_handlers(bot)

# Register dice duel handlers explicitly
from handlers.dice_duel import setup_dice_handlers
setup_dice_handlers(bot)


# --- Restrict /checkbal command strictly to @mrpuppyx ---
AUTHORIZED_USERNAME = "mrpuppyx"

@bot.message_handler(commands=["checkbal"])
def check_balance_cmd(message):
    sender_username = (message.from_user.username or "").lower()

    # 1. Access restriction
    if sender_username != AUTHORIZED_USERNAME.lower():
        bot.reply_to(message, "❌ You are not authorized to use this command.")
        return

    target_user_id = None
    target_display_name = None

    # 2. Handle reply-to mode
    if message.reply_to_message:
        reply_user = message.reply_to_message.from_user
        target_user_id = reply_user.id
        target_display_name = f"@{reply_user.username}" if reply_user.username else reply_user.first_name

    # 3. Handle parameter mode (/checkbal @username or /checkbal 12345678)
    else:
        args = message.text.split()[1:]
        if not args:
            bot.reply_to(
                message,
                "⚠️ Usage:\n"
                "• Reply to a message: `/checkbal`\n"
                "• Specify user: `/checkbal @username`\n"
                "• Specify Telegram ID: `/checkbal <telegram_id>`",
                parse_mode="Markdown"
            )
            return

        raw_target = args[0].replace("@", "")

        if raw_target.isdigit():
            target_user_id = int(raw_target)
            target_display_name = f"ID: `{target_user_id}`"
        else:
            if message.entities:
                for entity in message.entities:
                    if entity.type == "text_mention" and entity.user:
                        target_user_id = entity.user.id
                        target_display_name = f"@{entity.user.username}" if entity.user.username else entity.user.first_name
                        break

            if not target_user_id:
                bot.reply_to(
                    message,
                    f"⚠️ Direct username resolution is restricted by Telegram. "
                    f"Please reply directly to @{raw_target}'s message or use their numeric Telegram ID."
                )
                return

    # 4. Fetch and send balance
    try:
        balance = get_balance(target_user_id)
        bot.reply_to(
            message,
            f"<b>🔍 Balance Check</b>\n\n"
            f"<b>User:</b> {target_display_name}\n"
            f"<b>Balance:</b> ₹{balance}",
            parse_mode="HTML"
        )
    except Exception as e:
        bot.reply_to(message, f"❌ Error retrieving balance: {str(e)}")


print(f"{CASINO_NAME} bot running...")
if __name__ == "__main__":
    print(f"{CASINO_NAME} bot running...")
    try:
        # skip_pending=True ignores old messages sent while bot was offline
        bot.infinity_polling(timeout=10, long_polling_timeout=5, skip_pending=True)
    except Exception as e:
        print(f"Bot crashed with error: {e}")

