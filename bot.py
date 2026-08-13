import logging
from telegram import Update
from telegram.ext import (
    Application, CommandHandler, MessageHandler, ContextTypes, filters
)
from config import BOT_TOKEN, MONGO_URI
from database.mongo import init_db
from web.health_server import start_health_server
from handlers.moderation import moderate_message
from handlers.admin import (
    settings_cmd, antispam_cmd, lock_cmd, unlock_cmd, filter_cmd,
    warn_cmd, warnings_cmd, resetwarnings_cmd, mute_cmd, unmute_cmd,
    whitelist_cmd, unwhitelist_cmd, userinfo_cmd, stats_cmd, logs_cmd,
    status_cmd, help_cmd
)

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=logging.INFO,
)
log = logging.getLogger("security-bot")

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    log.error("Unhandled Telegram error: %s", context.error)

def main():
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN is missing")
    if not MONGO_URI:
        raise RuntimeError("MONGO_URI is missing")

    start_health_server()
    init_db()

    app = Application.builder().token(BOT_TOKEN).build()

    commands = {
        "settings": settings_cmd,
        "antispam": antispam_cmd,
        "lock": lock_cmd,
        "unlock": unlock_cmd,
        "filter": filter_cmd,
        "warn": warn_cmd,
        "warnings": warnings_cmd,
        "resetwarnings": resetwarnings_cmd,
        "mute": mute_cmd,
        "unmute": unmute_cmd,
        "whitelist": whitelist_cmd,
        "unwhitelist": unwhitelist_cmd,
        "userinfo": userinfo_cmd,
        "stats": stats_cmd,
        "logs": logs_cmd,
        "status": status_cmd,
        "help": help_cmd,
        "start": help_cmd,
    }
    for name, fn in commands.items():
        app.add_handler(CommandHandler(name, fn))

    app.add_handler(MessageHandler(
        filters.ALL & ~filters.COMMAND & filters.ChatType.GROUPS,
        moderate_message
    ))
    app.add_error_handler(error_handler)

    log.info("Ultra Telegram Security Bot started")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
