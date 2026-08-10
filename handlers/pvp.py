from bot_instance import bot
from games.pvp_engine import create_pvp_challenge

def parse_args(message):
    parts = message.text.split()
    return parts[1:] if len(parts) > 1 else []

@bot.message_handler(commands=["dice"])
def cmd_pvp_dice(message):
    create_pvp_challenge(bot, message, "dice", parse_args(message))

@bot.message_handler(commands=["foot", "football"])
def cmd_pvp_foot(message):
    create_pvp_challenge(bot, message, "foot", parse_args(message))

@bot.message_handler(commands=["dart", "darts"])
def cmd_pvp_dart(message):
    create_pvp_challenge(bot, message, "dart", parse_args(message))

@bot.message_handler(commands=["slots", "slot"])
def cmd_pvp_slots(message):
    create_pvp_challenge(bot, message, "slots", parse_args(message))

@bot.message_handler(commands=["basket", "basketball"])
def cmd_pvp_basket(message):
    create_pvp_challenge(bot, message, "basket", parse_args(message))

@bot.message_handler(commands=["bowl", "bowling"])
def cmd_pvp_bowl(message):
    create_pvp_challenge(bot, message, "bowl", parse_args(message))
