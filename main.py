from config import CASINO_NAME
from bot_instance import bot

# Importing handlers
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

# Register dice duel handlers explicitly
from handlers.dice_duel import setup_dice_handlers
setup_dice_handlers(bot)

print(f"{CASINO_NAME} bot running...")
bot.infinity_polling()
