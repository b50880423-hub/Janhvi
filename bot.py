import logging
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, ChatMemberHandler, InlineQueryHandler, filters
from config import BOT_TOKEN
from database.mongo import connect_db
from handlers.start import start
from handlers.admin import (
    settings, help_cmd, warn, mute, unmute, whitelist, unwhitelist, blacklist, unblacklist,
    userinfo, warnings, resetwarnings, lock, unlock, filter_cmd, antispam, logs, badwords_cmd, smartstatus, setlimit, my_chat_member, trust, untrust, silentmode, threatlevel, lockdown, unlockdown, nsfwstickers, member_profile, security, mode, domain_cmd, reviewqueue, appeal, promote, promote_callback
)
from handlers.callbacks import settings_callback, security_callback, review_callback, appeal_callback
from handlers.moderation import moderate_message, monitor_member
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
        "start": start, "help": help_cmd, "settings": settings, "appeal": appeal,
        "warn": warn, "mute": mute, "unmute": unmute,
        "whitelist": whitelist, "unwhitelist": unwhitelist,
        "blacklist": blacklist, "unblacklist": unblacklist,
        "userinfo": userinfo, "warnings": warnings, "resetwarnings": resetwarnings,
        "lock": lock, "unlock": unlock, "filter": filter_cmd, "badwords": badwords_cmd,
        "antispam": antispam, "logs": logs, "smartstatus": smartstatus, "setlimit": setlimit, "smartstatus": smartstatus, "setlimit": setlimit,
        "whisper": whisper_command, "whisperowner": owner_whisper_panel,
        "security": security, "mode": mode, "domain": domain_cmd, "reviewqueue": reviewqueue,
        "promote": promote,
        "trust": trust, "untrust": untrust, "silentmode": silentmode, "threatlevel": threatlevel, "lockdown": lockdown, "unlockdown": unlockdown, "nsfwstickers": nsfwstickers, "profile": member_profile,
    }
    for name, handler in commands.items(): app.add_handler(CommandHandler(name, handler))
    app.add_handler(CallbackQueryHandler(settings_callback, pattern=r"^as:"))
    app.add_handler(CallbackQueryHandler(security_callback, pattern=r"^sec:"))
    app.add_handler(CallbackQueryHandler(review_callback, pattern=r"^rv:"))
    app.add_handler(CallbackQueryHandler(appeal_callback, pattern=r"^ap:"))
    app.add_handler(CallbackQueryHandler(promote_callback, pattern=r"^pr:"))
    app.add_handler(InlineQueryHandler(whisper_inline_query))
    app.add_handler(CallbackQueryHandler(whisper_callback, pattern=r"^ws:"))
    app.add_handler(CallbackQueryHandler(owner_whisper_callback, pattern=r"^wa:"))
    app.add_handler(ChatMemberHandler(my_chat_member, ChatMemberHandler.MY_CHAT_MEMBER))
    app.add_handler(ChatMemberHandler(my_chat_member, ChatMemberHandler.CHAT_MEMBER))
    app.add_handler(ChatMemberHandler(monitor_member, ChatMemberHandler.CHAT_MEMBER), group=2)
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
