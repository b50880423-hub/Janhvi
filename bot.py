import logging
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, ChatMemberHandler, InlineQueryHandler, filters
from config import BOT_TOKEN
from database.mongo import connect_db
from handlers.start import start
from handlers.admin import (
    settings, help_cmd, warn, mute, unmute, whitelist, unwhitelist, blacklist, unblacklist,
    userinfo, warnings, resetwarnings, lock, unlock, filter_cmd, antispam, logs, badwords_cmd, my_chat_member
)
from handlers.callbacks import settings_callback
from handlers.moderation import moderate_message
from handlers.whisper import (
    whisper_command, whisper_callback, whisper_inline_query, whisper_message_handler,
    owner_whisper_panel, owner_whisper_callback,
)
from web.health_server import start_health_server

logging.basicConfig(format="%(asctime)s | %(levelname)s | %(name)s | %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

async def post_init(app):
    await connect_db()

def main():
    start_health_server()
    if not BOT_TOKEN: raise RuntimeError("BOT_TOKEN is missing")
    app = Application.builder().token(BOT_TOKEN).post_init(post_init).build()
    commands = {
        "start": start, "help": help_cmd, "settings": settings,
        "warn": warn, "mute": mute, "unmute": unmute,
        "whitelist": whitelist, "unwhitelist": unwhitelist,
        "blacklist": blacklist, "unblacklist": unblacklist,
        "userinfo": userinfo, "warnings": warnings, "resetwarnings": resetwarnings,
        "lock": lock, "unlock": unlock, "filter": filter_cmd, "badwords": badwords_cmd,
        "antispam": antispam, "logs": logs,
        "whisper": whisper_command, "whisperowner": owner_whisper_panel,
    }
    for name, handler in commands.items(): app.add_handler(CommandHandler(name, handler))
    app.add_handler(CallbackQueryHandler(settings_callback, pattern=r"^as:"))
    app.add_handler(InlineQueryHandler(whisper_inline_query))
    app.add_handler(CallbackQueryHandler(whisper_callback, pattern=r"^ws:"))
    app.add_handler(CallbackQueryHandler(owner_whisper_callback, pattern=r"^wa:"))
    app.add_handler(ChatMemberHandler(my_chat_member, ChatMemberHandler.MY_CHAT_MEMBER))
    app.add_handler(
        MessageHandler(filters.ALL, whisper_message_handler),
        group=5,
    )
    app.add_handler(
        MessageHandler(filters.ALL, moderate_message),
        group=10,
    )
    logger.info("AntiSpam bot started")
    app.run_polling(allowed_updates=["message", "edited_message", "callback_query", "inline_query", "my_chat_member"])

if __name__ == "__main__": main()
