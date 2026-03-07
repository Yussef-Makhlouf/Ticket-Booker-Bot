import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.environ.get("BOT_TOKEN")
ADMIN_ID = os.environ.get("ADMIN_ID")

if ADMIN_ID:
    try:
        ADMIN_ID = int(ADMIN_ID)
    except ValueError:
        ADMIN_ID = None
