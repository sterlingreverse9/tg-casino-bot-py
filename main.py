from config import CASINO_NAME
from bot_instance import bot

# Importing these registers every handler on the shared bot instance
import handlers.basic
import handlers.admin
import handlers.rain
import handlers.deposit
import handlers.withdraw
import handlers.rakeback
import handlers.games
import handlers.dice_duel
import handlers.tower
import handlers.referral
import handlers.tracking

print(f"{CASINO_NAME} bot running...")
bot.infinity_polling()
