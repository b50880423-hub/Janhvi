from telegram import Update
from telegram.ext import ContextTypes
from telegram.constants import ChatMemberStatus
from database.mongo import (
    get_settings, set_setting, get_filters, add_filter, remove_filter, clear_filters,
    set_whitelist, is_whitelisted, reset_violations, get_violation_count, stats,
    recent_events
)

async def is_admin(update, user_id=None):
    user_id = user_id or update.effective_user.id
    try:
        m = await update.effective_chat.get_member(user_id)
        return m.status in (ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER)
    except Exception:
        return False

def target_user(update):
    if update.message.reply_to_message:
        return update.message.reply_to_message.from_user
    return None

async def settings_cmd(update, context):
    if not await is_admin(update):
        return
    s = get_settings(update.effective_chat.id)
    enabled = "ON" if s["enabled"] else "OFF"
    await update.message.reply_text(
        f"🛡️ Security settings\n\n"
        f"AntiSpam: {enabled}\n"
        f"Links: {'ON' if s['links'] else 'OFF'}\n"
        f"Stickers: {'ON' if s['stickers'] else 'OFF'}\n"
        f"Photos: {'ON' if s['photos'] else 'OFF'}\n"
        f"Videos: {'ON' if s['videos'] else 'OFF'}\n"
        f"GIFs: {'ON' if s['gifs'] else 'OFF'}\n"
        f"Documents: {'ON' if s['documents'] else 'OFF'}\n"
        f"Flood: {'ON' if s['flood'] else 'OFF'}\n"
        f"Duplicate: {'ON' if s['duplicate'] else 'OFF'}\n"
        f"Bad words: {'ON' if s['badwords'] else 'OFF'}\n"
        f"Filters: {len(get_filters(update.effective_chat.id))}\n\n"
        f"Use /antispam on|off and /lock TYPE /unlock TYPE."
    )

async def antispam_cmd(update, context):
    if not await is_admin(update): return
    arg = context.args[0].lower() if context.args else None
    if arg in ("on","off"):
        set_setting(update.effective_chat.id, "enabled", arg == "on")
        await update.message.reply_text(f"🛡️ AntiSpam: {arg.upper()}")
    else:
        await settings_cmd(update, context)

LOCKS = {"links","stickers","photos","videos","gifs","documents","forwards","mentions","flood","duplicate","badwords"}

async def lock_cmd(update, context):
    if not await is_admin(update): return
    typ = context.args[0].lower() if context.args else ""
    if typ == "all":
        for x in LOCKS: set_setting(update.effective_chat.id, x, True)
        return await update.message.reply_text("🔒 All protections enabled.")
    if typ not in LOCKS:
        return await update.message.reply_text("Usage: /lock links|stickers|photos|videos|gifs|documents|forwards|mentions|flood|duplicate|badwords|all")
    set_setting(update.effective_chat.id, typ, True)
    await update.message.reply_text(f"🔒 {typ} protection enabled.")

async def unlock_cmd(update, context):
    if not await is_admin(update): return
    typ = context.args[0].lower() if context.args else ""
    if typ == "all":
        for x in LOCKS: set_setting(update.effective_chat.id, x, False)
        return await update.message.reply_text("🔓 All protections disabled.")
    if typ not in LOCKS:
        return await update.message.reply_text("Usage: /unlock TYPE")
    set_setting(update.effective_chat.id, typ, False)
    await update.message.reply_text(f"🔓 {typ} protection disabled.")

async def filter_cmd(update, context):
    if not await is_admin(update): return
    if not context.args:
        return await update.message.reply_text("Usage: /filter add WORD | remove WORD | list | clear | on | off")
    action = context.args[0].lower()
    cid = update.effective_chat.id
    if action == "add" and len(context.args) >= 2:
        term = " ".join(context.args[1:])
        ok = add_filter(cid, term)
        return await update.message.reply_text("✅ Filter added." if ok else "⚠️ Already exists or invalid.")
    if action == "remove" and len(context.args) >= 2:
        ok = remove_filter(cid, " ".join(context.args[1:]))
        return await update.message.reply_text("✅ Removed." if ok else "❌ Not found.")
    if action == "list":
        items = get_filters(cid)
        return await update.message.reply_text("🔤 Filters:\n" + ("\n".join(f"• {x}" for x in items) if items else "None"))
    if action == "clear":
        clear_filters(cid); return await update.message.reply_text("🧹 Group filter list cleared.")
    if action in ("on","off"):
        set_setting(cid, "badwords", action == "on")
        return await update.message.reply_text(f"🔤 Bad-word protection: {action.upper()}")
    await update.message.reply_text("Usage: /filter add WORD | remove WORD | list | clear | on | off")

async def warn_cmd(update, context):
    if not await is_admin(update): return
    u = target_user(update)
    if not u: return await update.message.reply_text("Reply to a user's message.")
    from database.mongo import add_violation
    count = add_violation(update.effective_chat.id, u.id, "manual warning", u.username)
    await update.message.reply_text(f"⚠️ Warning recorded for {u.mention_html()} — total: {count}", parse_mode="HTML")

async def warnings_cmd(update, context):
    if not await is_admin(update): return
    u = target_user(update)
    if not u: return await update.message.reply_text("Reply to a user's message.")
    c = get_violation_count(update.effective_chat.id, u.id)
    await update.message.reply_text(f"⚠️ {u.mention_html()} has {c} violation(s).", parse_mode="HTML")

async def resetwarnings_cmd(update, context):
    if not await is_admin(update): return
    u = target_user(update)
    if not u: return await update.message.reply_text("Reply to a user's message.")
    reset_violations(update.effective_chat.id, u.id)
    await update.message.reply_text("✅ Violations reset.")

async def mute_cmd(update, context):
    if not await is_admin(update): return
    u = target_user(update)
    if not u: return await update.message.reply_text("Reply to a user's message.")
    minutes = int(context.args[0]) if context.args and context.args[0].isdigit() else 20
    from telegram import ChatPermissions
    from datetime import datetime, timezone, timedelta
    try:
        await update.effective_chat.restrict_member(
            u.id, permissions=ChatPermissions(can_send_messages=False),
            until_date=datetime.now(timezone.utc)+timedelta(minutes=minutes))
        await update.message.reply_text(f"🔇 {u.mention_html()} muted for {minutes} minutes.", parse_mode="HTML")
    except Exception as e:
        await update.message.reply_text(f"❌ Could not mute: {e}")

async def unmute_cmd(update, context):
    if not await is_admin(update): return
    u = target_user(update)
    if not u: return await update.message.reply_text("Reply to a user's message.")
    from telegram import ChatPermissions
    try:
        await update.effective_chat.restrict_member(
            u.id, permissions=ChatPermissions(
                can_send_messages=True, can_send_audios=True, can_send_documents=True,
                can_send_photos=True, can_send_videos=True, can_send_video_notes=True,
                can_send_voice_notes=True, can_send_polls=True, can_send_other_messages=True,
                can_add_web_page_previews=True))
        await update.message.reply_text(f"🔊 {u.mention_html()} unmuted.", parse_mode="HTML")
    except Exception as e:
        await update.message.reply_text(f"❌ Could not unmute: {e}")

async def whitelist_cmd(update, context):
    if not await is_admin(update): return
    u = target_user(update)
    if not u: return await update.message.reply_text("Reply to a user's message.")
    set_whitelist(update.effective_chat.id, u.id, True)
    await update.message.reply_text(f"✅ {u.mention_html()} whitelisted.", parse_mode="HTML")

async def unwhitelist_cmd(update, context):
    if not await is_admin(update): return
    u = target_user(update)
    if not u: return await update.message.reply_text("Reply to a user's message.")
    set_whitelist(update.effective_chat.id, u.id, False)
    await update.message.reply_text(f"✅ {u.mention_html()} removed from whitelist.", parse_mode="HTML")

async def userinfo_cmd(update, context):
    if not await is_admin(update): return
    u = target_user(update)
    if not u: return await update.message.reply_text("Reply to a user's message.")
    c = get_violation_count(update.effective_chat.id, u.id)
    await update.message.reply_text(f"👤 {u.mention_html()}\n🆔 {u.id}\n⚠️ Violations: {c}", parse_mode="HTML")

async def stats_cmd(update, context):
    if not await is_admin(update): return
    s = stats(update.effective_chat.id)
    await update.message.reply_text(
        f"📊 Group security stats\n\n"
        f"Events: {s.get('events',0)}\nDeleted: {s.get('deleted',0)}\n"
        f"Warnings: {s.get('warnings',0)}\nMuted: {s.get('muted',0)}")

async def logs_cmd(update, context):
    if not await is_admin(update): return
    events = recent_events(update.effective_chat.id, 10)
    if not events:
        return await update.message.reply_text("📋 No moderation events yet.")
    lines = ["📋 Last moderation events:"]
    for e in events:
        lines.append(f"• {e.get('username') or e.get('user_id')} — {e.get('reason')} — {e.get('action')}")
    await update.message.reply_text("\n".join(lines))

async def status_cmd(update, context):
    if not await is_admin(update): return
    from database.mongo import mongo_ok
    from config import SIGHTENGINE_API_USER, SIGHTENGINE_API_SECRET
    visual = bool(SIGHTENGINE_API_USER and SIGHTENGINE_API_SECRET)
    await update.message.reply_text(
        f"🟢 Bot online\\n"
        f"MongoDB: {'🟢 connected' if mongo_ok() else '🔴 unavailable'}\\n"
        f"Visual NSFW moderation: {'🟢 enabled' if visual else '🟡 not configured'}"
    )

async def help_cmd(update, context):
    await update.message.reply_text(
        "🛡️ Ultra Security Bot\n\n"
        "Admin: /settings /antispam /lock /unlock /filter /warn /warnings /resetwarnings\n"
        "/mute /unmute /whitelist /unwhitelist /userinfo /stats /logs /status\n\n"
        "Reply to a user's message for user moderation commands."
    )
