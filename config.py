import os
from dotenv import load_dotenv
load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
MONGO_URI = os.getenv("MONGO_URI", "").strip()
MONGO_DB = os.getenv("MONGO_DB", "telegram_security").strip()
LOGGER_CHAT_ID = os.getenv("LOGGER_CHAT_ID", "").strip()

DEFAULT_SETTINGS = {
    "enabled": True,
    "links": True,
    "stickers": False,
    "photos": False,
    "videos": False,
    "gifs": True,
    "documents": False,
    "forwards": True,
    "mentions": True,
    "flood": True,
    "duplicate": True,
    "badwords": True,
    "raid": True,
    "warning_message_seconds": 15,
    "flood_limit": 6,
    "flood_window": 8,
    "duplicate_limit": 3,
}

SIGHTENGINE_API_USER = os.getenv("SIGHTENGINE_API_USER", "").strip()
SIGHTENGINE_API_SECRET = os.getenv("SIGHTENGINE_API_SECRET", "").strip()
SIGHTENGINE_MODEL = os.getenv("SIGHTENGINE_MODEL", "nudity-2.1").strip()
# First occurrence of positively identified explicit adult content => 24h mute.
EXPLICIT_MUTE_MINUTES = int(os.getenv("EXPLICIT_MUTE_MINUTES", "1440"))
