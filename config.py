import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_KEY")

HOUSE_EDGE = float(os.getenv("HOUSE_EDGE", "0.10"))
STARTING_BALANCE = float(os.getenv("STARTING_BALANCE", "0"))

CASINO_NAME = "The Casino"
