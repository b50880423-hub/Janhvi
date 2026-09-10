import logging
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, ChatMemberHandler, InlineQueryHandler, filters
from config import BOT_TOKEN
from database.mongo import connect_db
from handlers.start import start
from handlers.admin import (
    settings, help_cmd, warn, mute, unmute, whitelist, unwhitelist, blacklist, unblacklist,
    userinfo, warnings, resetwarnings, lock, unlock, filter_cmd, antispam, logs, badwords_cmd, smartstatus, setlimit, my_chat_member, trust, untrust, silentmode, threatlevel, lockdown, unlockdown, nsfwstickers, member_profile, security, mode, domain_cmd, reviewqueue, appeal, appeal_flow_callback, appeal_reason_message, promote, promote_callback, demote, ban, unban, case_cmd, userhistory, evidence, setlog, removelog, logstatus, rules, rules_callback
)
from handlers.callbacks import settings_callback, security_callback, review_callback, appeal_callback
from handlers.moderation import moderate_message, monitor_member
from handlers.welcome import welcome_cmd, monitor_welcome, monitor_welcome_service_message
from handlers.rose import save_note, get_note, notes, clear_note, save_command, command_list, command_delete, custom_command_handler, purge, kick, tempban, tempmute, expire_temp_actions, report, report_callback, language, setgoodbye, goodbye, monitor_goodbye, admins
from handlers.ultimate import filters_list, stop_filter, stop_all_filters, lock_status, set_rules, unset_rules, janhvi_panel
from handlers.whisper import (
    whisper_command, whisper_callback, whisper_inline_query, whisper_message_handler,
    owner_whisper_panel, owner_whisper_callback,
)
from web.health_server import start_health_server

logging.basicConfig(format="%(asctime)s | %(levelname)s | %(name)s | %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

async def post_init(app):
    await connect_db()
    if app.job_queue:
        app.job_queue.run_repeating(expire_temp_actions, interval=30, first=10, name="janhvi-temp-expiry")

def main():
    start_health_server()
    if not BOT_TOKEN: raise RuntimeError("BOT_TOKEN is missing")
    app = Application.builder().token(BOT_TOKEN).post_init(post_init).build()
    commands = {
        "start": start, "help": help_cmd, "janhvi": janhvi_panel, "welcome": welcome_cmd, "settings": settings, "rules": rules, "rule": rules, "setrules": set_rules, "clearrules": unset_rules, "appeal": appeal, "apeal": appeal,
        "warn": warn, "mute": mute, "unmute": unmute, "ban": ban, "unban": unban, "case": case_cmd, "cases": userhistory, "userhistory": userhistory, "evidence": evidence, "setlog": setlog, "removelog": removelog, "logstatus": logstatus,
        "whitelist": whitelist, "unwhitelist": unwhitelist,
        "blacklist": blacklist, "unblacklist": unblacklist,
        "userinfo": userinfo, "warnings": warnings, "resetwarnings": resetwarnings,
        "lock": lock, "unlock": unlock, "locks": lock_status, "filter": filter_cmd, "filters": filters_list, "stop": stop_filter, "stopall": stop_all_filters, "badwords": badwords_cmd,
        "antispam": antispam, "logs": logs, "smartstatus": smartstatus, "setlimit": setlimit, "smartstatus": smartstatus, "setlimit": setlimit,
        "whisper": whisper_command, "whisperowner": owner_whisper_panel,
        "security": security, "mode": mode, "domain": domain_cmd, "reviewqueue": reviewqueue,
        "promote": promote, "demote": demote,
        "save": save_note, "get": get_note, "notes": notes, "clear": clear_note, "command": save_command, "commands": command_list, "delcommand": command_delete,
        "purge": purge, "kick": kick, "tempban": tempban, "tempmute": tempmute, "report": report, "language": language, "setgoodbye": setgoodbye, "goodbye": goodbye, "admins": admins, "id": userinfo,
        "trust": trust, "untrust": untrust, "silentmode": silentmode, "threatlevel": threatlevel, "lockdown": lockdown, "unlockdown": unlockdown, "nsfwstickers": nsfwstickers, "profile": member_profile,
    }
    for name, handler in commands.items(): app.add_handler(CommandHandler(name, handler))
    app.add_handler(CallbackQueryHandler(rules_callback, pattern=r"^rules:"))
    app.add_handler(CallbackQueryHandler(report_callback, pattern=r"^report:"))
    app.add_handler(CallbackQueryHandler(settings_callback, pattern=r"^as:"))
    app.add_handler(CallbackQueryHandler(security_callback, pattern=r"^sec:"))
    app.add_handler(CallbackQueryHandler(review_callback, pattern=r"^rv:"))
    app.add_handler(CallbackQueryHandler(appeal_callback, pattern=r"^ap:"))
    app.add_handler(CallbackQueryHandler(appeal_flow_callback, pattern=r"^appealflow:"))
    app.add_handler(CallbackQueryHandler(promote_callback, pattern=r"^pr:"))
    app.add_handler(InlineQueryHandler(whisper_inline_query))
    app.add_handler(CallbackQueryHandler(whisper_callback, pattern=r"^ws:"))
    app.add_handler(CallbackQueryHandler(owner_whisper_callback, pattern=r"^wa:"))
    app.add_handler(ChatMemberHandler(my_chat_member, ChatMemberHandler.MY_CHAT_MEMBER))
    app.add_handler(ChatMemberHandler(my_chat_member, ChatMemberHandler.CHAT_MEMBER))
    app.add_handler(ChatMemberHandler(monitor_member, ChatMemberHandler.CHAT_MEMBER), group=2)
    app.add_handler(ChatMemberHandler(monitor_welcome, ChatMemberHandler.CHAT_MEMBER), group=3)
    app.add_handler(ChatMemberHandler(monitor_goodbye, ChatMemberHandler.CHAT_MEMBER), group=3)
    # Fallback join-event source: service messages work for both public and private groups.
    app.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, monitor_welcome_service_message), group=3)
    app.add_handler(MessageHandler(filters.TEXT & filters.ChatType.PRIVATE & ~filters.COMMAND, appeal_reason_message), group=4)
    app.add_handler(
        MessageHandler(filters.ALL, whisper_message_handler),
        group=5,
    )
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, custom_command_handler), group=9)
    app.add_handler(MessageHandler(filters.COMMAND, custom_command_handler), group=9)
    app.add_handler(
        MessageHandler(filters.ALL, moderate_message),
        group=10,
    )
    logger.info("AntiSpam bot started")
    app.run_polling(allowed_updates=["message", "edited_message", "callback_query", "inline_query", "my_chat_member", "chat_member"])

if __name__ == "__main__": main()
