import logging
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, ChatMemberHandler, filters
from config import BOT_TOKEN
from database.mongo import connect_db
from handlers.start import start
from handlers.admin import (
    settings, help_cmd, warn, mute, unmute, ban, unban, whitelist, unwhitelist,
    userinfo, warnings, resetwarnings
)
from handlers.callbacks import settings_callback
from handlers.moderation import moderate_message
from web.health_server import start_health_server
from handlers.admin import my_chat_member

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

async def post_init(app):
    await connect_db()

def main():
    start_health_server()
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN is missing")
    app = Application.builder().token(BOT_TOKEN).post_init(post_init).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("settings", settings))
    app.add_handler(CommandHandler("warn", warn))
    app.add_handler(CommandHandler("mute", mute))
    app.add_handler(CommandHandler("unmute", unmute))
    app.add_handler(CommandHandler("ban", ban))
    app.add_handler(CommandHandler("unban", unban))
    app.add_handler(CommandHandler("whitelist", whitelist))
    app.add_handler(CommandHandler("unwhitelist", unwhitelist))
    app.add_handler(CommandHandler("userinfo", userinfo))
    app.add_handler(CommandHandler("warnings", warnings))
    app.add_handler(CommandHandler("resetwarnings", resetwarnings))
    app.add_handler(CallbackQueryHandler(settings_callback, pattern=r"^as:"))
    app.add_handler(ChatMemberHandler(my_chat_member, ChatMemberHandler.MY_CHAT_MEMBER))
    app.add_handler(MessageHandler(filters.ALL, moderate_message), group=10)

    logger.info("AntiSpam bot started")
    app.run_polling(allowed_updates=["message", "edited_message", "callback_query", "my_chat_member"])

if __name__ == "__main__":
    main()
