import os

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
MONGO_URI = os.getenv("MONGO_URI", "")
MONGO_DB = os.getenv("MONGO_DB", "antispam_bot")
LOGGER_CHAT_ID = int(os.getenv("LOGGER_CHAT_ID", "0") or 0)

DEFAULT_SETTINGS = {
    "enabled": True,
    "antilink": True,
    "antisticker": True,
    "antiphoto": True,
    "antivideo": True,
    "antigif": True,
    "antidocument": True,
    "antiforward": True,
    "antimention": True,
    "antiflood": True,
    "antiduplicate": True,
    "badwords": True,
    "max_messages": 6,
    "window_seconds": 8,
    "max_duplicate": 3,
    "max_mentions": 6,
    "mute_minutes": 30,
}
