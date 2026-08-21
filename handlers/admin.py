from datetime import datetime, timedelta, timezone
from telegram import ChatPermissions
from telegram.constants import ChatMemberStatus
from database.mongo import (
    get_group, update_group, get_violation_count, reset_violations,
    upsert_user, get_user, get_recent_events, log_event
)
from config import DEFAULT_SETTINGS, LOGGER_CHAT_ID
from utils.permissions import is_admin
from utils.keyboards import settings_keyboard

async def require_admin(update):
    return update.effective_chat and update.effective_user and await is_admin(
        update.get_bot(), update.effective_chat.id, update.effective_user.id
    )

async def deny(update):
    if update.effective_message:
        await update.effective_message.reply_text("❌ Admins only.")

async def settings(update, context):
    if not await require_admin(update): return await deny(update)
    s = await get_group(update.effective_chat.id, DEFAULT_SETTINGS)
    await update.effective_message.reply_text("🛡️ <b>AntiSpam Settings</b>", parse_mode="HTML", reply_markup=settings_keyboard(s))

async def help_cmd(update, context):
    await update.effective_message.reply_text(
        "<b>🛡️ Advanced AntiSpam Commands</b>\n\n"
        "<b>Moderation</b>\n"
        "/warn — warn replied user\n"
        "/warnings — show warnings\n"
        "/resetwarnings — reset warnings\n"
        "/mute [minutes] — mute replied user\n"
        "/unmute — unmute replied user\n\n"
        "<b>Protection</b>\n"
        "/antispam — show/toggle protection\n"
        "/lock [type] — lock a content type\n"
        "/unlock [type] — unlock a content type\n"
        "/filter add <word> — add custom filter\n"
        "/filter remove <word> — remove custom filter\n"
        "/filter list — list filters\n\n"
        "<b>Lists</b>\n"
        "/whitelist — whitelist replied user\n"
        "/unwhitelist — remove whitelist\n"
        "/blacklist — blacklist replied user (auto delete + mute)\n"
        "/unblacklist — remove blacklist\n\n"
        "<b>Info</b>\n"
        "/logs — recent moderation logs\n"
        "/whisperowner — owner-only read-only Whisper Vault\n"
        "/userinfo [ID] — user info\n"
        "/settings — inline admin panel\n\n"
        "Automatic punishment is <b>delete + temporary mute only</b>; 5th+ violations are 24h mutes.",
        parse_mode="HTML"
    )

def replied_user(update):
    msg = update.effective_message
    return msg.reply_to_message.from_user if msg and msg.reply_to_message else None

def target_user(update, context):
    u = replied_user(update)
    if u:
        return u
    if context.args and context.args[0].lstrip("-").isdigit():
        return int(context.args[0])
    return None

async def warn(update, context):
    if not await require_admin(update): return await deny(update)
    u = replied_user(update)
    if not u:
        return await update.effective_message.reply_text("Reply to a user's message.")
    from database.mongo import add_violation
    c = await add_violation(update.effective_chat.id, u.id, "manual warning")
    await update.effective_message.reply_text(f"⚠️ Warning added to {u.mention_html()}. Total: {c}", parse_mode="HTML")

async def mute(update, context):
    if not await require_admin(update): return await deny(update)
    u = replied_user(update)
    if not u:
        return await update.effective_message.reply_text("Reply to a user's message. Usage: /mute [minutes]")
    minutes = int(context.args[0]) if context.args and context.args[0].isdigit() else 30
    minutes = max(1, min(minutes, 10080))
    try:
        until = datetime.now(timezone.utc) + timedelta(minutes=minutes)
        await update.effective_chat.restrict_member(u.id, permissions=ChatPermissions.no_permissions(), until_date=until)
        await update.effective_message.reply_text(f"🔇 Muted {u.mention_html()} for {minutes} minutes.", parse_mode="HTML")
    except Exception as e:
        await update.effective_message.reply_text(f"❌ Could not mute: {e}")

async def unmute(update, context):
    if not await require_admin(update): return await deny(update)
    u = replied_user(update)
    if not u:
        return await update.effective_message.reply_text("Reply to a user's message.")
    try:
        await update.effective_chat.restrict_member(u.id, permissions=ChatPermissions.all_permissions())
        await update.effective_message.reply_text(f"🔊 Unmuted {u.mention_html()}.", parse_mode="HTML")
    except Exception as e:
        await update.effective_message.reply_text(f"❌ Could not unmute: {e}")

async def whitelist(update, context):
    if not await require_admin(update): return await deny(update)
    u = replied_user(update)
    if not u: return await update.effective_message.reply_text("Reply to a user's message.")
    await upsert_user(update.effective_chat.id, u.id, {"username": u.username, "whitelisted": True, "blacklisted": False})
    await update.effective_message.reply_text(f"✅ {u.mention_html()} is whitelisted.", parse_mode="HTML")

async def unwhitelist(update, context):
    if not await require_admin(update): return await deny(update)
    u = replied_user(update)
    if not u: return await update.effective_message.reply_text("Reply to a user's message.")
    await upsert_user(update.effective_chat.id, u.id, {"whitelisted": False})
    await update.effective_message.reply_text("✅ Whitelist removed.")

async def blacklist(update, context):
    if not await require_admin(update): return await deny(update)
    u = replied_user(update)
    if not u: return await update.effective_message.reply_text("Reply to a user's message.")
    await upsert_user(update.effective_chat.id, u.id, {"username": u.username, "blacklisted": True, "whitelisted": False})
    await update.effective_message.reply_text(f"🚨 {u.mention_html()} added to blacklist. Future messages will be deleted and muted.", parse_mode="HTML")

async def unblacklist(update, context):
    if not await require_admin(update): return await deny(update)
    u = replied_user(update)
    if not u: return await update.effective_message.reply_text("Reply to a user's message.")
    await upsert_user(update.effective_chat.id, u.id, {"blacklisted": False})
    await update.effective_message.reply_text("✅ Blacklist removed.")

async def userinfo(update, context):
    u = replied_user(update)
    uid = u.id if u else (int(context.args[0]) if context.args and context.args[0].lstrip("-").isdigit() else update.effective_user.id)
    c = await get_violation_count(update.effective_chat.id, uid)
    data = await get_user(update.effective_chat.id, uid) or {}
    await update.effective_message.reply_text(
        f"👤 <b>User info</b>\nID: <code>{uid}</code>\n⚠️ Violations: <b>{c}</b>\n"
        f"Whitelist: <b>{'Yes' if data.get('whitelisted') else 'No'}</b>\n"
        f"Blacklist: <b>{'Yes' if data.get('blacklisted') else 'No'}</b>", parse_mode="HTML"
    )

async def warnings(update, context):
    return await userinfo(update, context)

async def resetwarnings(update, context):
    if not await require_admin(update): return await deny(update)
    u = replied_user(update)
    if not u: return await update.effective_message.reply_text("Reply to a user's message.")
    await reset_violations(update.effective_chat.id, u.id)
    await update.effective_message.reply_text("✅ Warnings reset.")

LOCK_MAP = {
    "links": "antilink", "link": "antilink",
    "stickers": "antisticker", "sticker": "antisticker",
    "photos": "antiphoto", "photo": "antiphoto",
    "videos": "antivideo", "video": "antivideo",
    "gifs": "antigif", "gif": "antigif",
    "documents": "antidocument", "document": "antidocument",
    "forwards": "antiforward", "forward": "antiforward",
    "mentions": "antimention", "mention": "antimention",
    "flood": "antiflood", "duplicate": "antiduplicate", "badwords": "badwords",
}

async def lock(update, context):
    if not await require_admin(update): return await deny(update)
    if not context.args:
        return await update.effective_message.reply_text("Usage: /lock links|stickers|photos|videos|gifs|documents|forwards|mentions|flood|duplicate|badwords|all")
    item = context.args[0].lower()
    data = {v: True for k, v in LOCK_MAP.items()} if item == "all" else ({LOCK_MAP[item]: True} if item in LOCK_MAP else None)
    if data is None:
        return await update.effective_message.reply_text("❌ Unknown lock type.")
    await update_group(update.effective_chat.id, data)
    await update.effective_message.reply_text(f"🔒 Locked: {item}")

async def unlock(update, context):
    if not await require_admin(update): return await deny(update)
    if not context.args:
        return await update.effective_message.reply_text("Usage: /unlock links|stickers|photos|videos|gifs|documents|forwards|mentions|flood|duplicate|badwords|all")
    item = context.args[0].lower()
    data = {v: False for k, v in LOCK_MAP.items()} if item == "all" else ({LOCK_MAP[item]: False} if item in LOCK_MAP else None)
    if data is None:
        return await update.effective_message.reply_text("❌ Unknown unlock type.")
    await update_group(update.effective_chat.id, data)
    await update.effective_message.reply_text(f"🔓 Unlocked: {item}")

async def antispam(update, context):
    if not await require_admin(update): return await deny(update)
    s = await get_group(update.effective_chat.id, DEFAULT_SETTINGS)
    if context.args:
        action = context.args[0].lower()
        if action in ("on", "enable", "enabled"):
            await update_group(update.effective_chat.id, {"enabled": True})
            return await update.effective_message.reply_text("🛡️ AntiSpam is ON.")
        if action in ("off", "disable", "disabled"):
            await update_group(update.effective_chat.id, {"enabled": False})
            return await update.effective_message.reply_text("🛡️ AntiSpam is OFF.")
    await update.effective_message.reply_text(f"🛡️ AntiSpam: {'ON' if s.get('enabled', True) else 'OFF'}\nUse /antispam on or /antispam off")

async def filter_cmd(update, context):
    """Manage bad words for the CURRENT Telegram group only.

    Stored under groups.custom_filters using this group's chat_id, so adding a
    word in Group A never adds it to Group B.
    """
    if not await require_admin(update):
        return await deny(update)

    chat_id = update.effective_chat.id
    s = await get_group(chat_id, DEFAULT_SETTINGS)
    filters = list(s.get("custom_filters", []))

    if not context.args or context.args[0].lower() in ("list", "show"):
        if not filters:
            return await update.effective_message.reply_text(
                "🔤 <b>Group Bad-Word Filter</b>\n\nNo custom words have been added to this group.",
                parse_mode="HTML"
            )
        lines = ["🔤 <b>Group Bad-Word Filter</b>", "", "<b>Custom words:</b>"]
        for i, word in enumerate(filters, 1):
            lines.append(f"{i}. <code>{word}</code>")
        lines.append("\nUse <code>/filter remove &lt;word&gt;</code> to remove one.")
        return await update.effective_message.reply_text("\n".join(lines), parse_mode="HTML")

    action = context.args[0].lower()

    if action in ("add", "+"):
        word = " ".join(context.args[1:]).strip().lower()
        if not word:
            return await update.effective_message.reply_text(
                "Usage: <code>/filter add badword</code>\n"
                "You can also add a phrase: <code>/filter add bad phrase</code>",
                parse_mode="HTML"
            )
        if len(word) > 100:
            return await update.effective_message.reply_text("❌ Filter is too long (max 100 characters).")
        if word not in filters:
            filters.append(word)
        await update_group(chat_id, {"custom_filters": filters, "badwords": True})
        return await update.effective_message.reply_text(
            f"✅ Added <code>{word}</code> to this group's bad-word filter.\n"
            f"It will NOT affect other groups.", parse_mode="HTML"
        )

    if action in ("remove", "delete", "-"):
        word = " ".join(context.args[1:]).strip().lower()
        if not word:
            return await update.effective_message.reply_text(
                "Usage: <code>/filter remove badword</code>", parse_mode="HTML"
            )
        new_filters = [x for x in filters if x.lower() != word]
        if len(new_filters) == len(filters):
            return await update.effective_message.reply_text("❌ That word is not in this group's custom filter.")
        await update_group(chat_id, {"custom_filters": new_filters})
        return await update.effective_message.reply_text(
            f"✅ Removed <code>{word}</code> from this group's filter.", parse_mode="HTML"
        )

    if action in ("clear", "clearall", "reset"):
        await update_group(chat_id, {"custom_filters": []})
        return await update.effective_message.reply_text("🧹 All custom bad words for this group have been removed.")

    if action in ("on", "enable", "enabled"):
        await update_group(chat_id, {"badwords": True})
        return await update.effective_message.reply_text("🤬 Group bad-word protection is ON.")

    if action in ("off", "disable", "disabled"):
        await update_group(chat_id, {"badwords": False})
        return await update.effective_message.reply_text("🤬 Group bad-word protection is OFF.")

    return await update.effective_message.reply_text(
        "Usage:\n"
        "<code>/filter add word</code>\n"
        "<code>/filter remove word</code>\n"
        "<code>/filter list</code>\n"
        "<code>/filter clear</code>\n"
        "<code>/filter on</code> / <code>/filter off</code>",
        parse_mode="HTML"
    )

async def badwords_cmd(update, context):
    """Alias for /filter for admins who prefer /badwords."""
    return await filter_cmd(update, context)

async def logs(update, context):
    if not await require_admin(update): return await deny(update)
    rows = await get_recent_events(update.effective_chat.id, 10)
    if not rows:
        return await update.effective_message.reply_text("📝 No moderation logs yet.")
    lines = ["📝 <b>Recent moderation logs</b>"]
    for e in rows:
        ts = e.get("created_at")
        stamp = ts.strftime("%d %b %H:%M") if hasattr(ts, "strftime") else "?"
        lines.append(f"• {stamp} | <code>{e.get('user_id')}</code> | {e.get('reason','?')} | {e.get('action','?')}")
    await update.effective_message.reply_text("\n".join(lines), parse_mode="HTML")

async def my_chat_member(update, context):
    pass
