from datetime import datetime, timedelta, timezone
from telegram import ChatPermissions, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ChatMemberStatus
from database.mongo import (
    get_group, update_group, get_violation_count, reset_violations,
    upsert_user, get_user, get_user_by_username, get_recent_events, log_event
)
from database.mongo import save_mute_record, get_mute_record, create_appeal
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
        "/mute <user_id|@username> [minutes] — manually mute user\n"
        "/appeal <reason> — appeal a mute (use in bot DM)\n"
        "/unmute — unmute replied user\n"
        "/unmute <user_id|@username> — manually unmute user\n\n"
        "<b>Protection</b>\n"
        "/antispam — show/toggle protection\n"
        "/lock [type] — lock a content type\n"
        "/unlock [type] — unlock a content type\n"
        "/lockdown — stop all normal members from sending anything\n"
        "/unlockdown — restore normal member messaging\n"
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
        "/smartstatus — show smart moderation limits\n"
        "/setlimit — adjust moderation sensitivity\n"
        "/whisperowner — owner-only read-only Whisper Vault\n"
        "/userinfo [ID] — user info\n"
        "/settings — inline admin panel\n\n"
        "Automatic punishment is <b>delete + warning first</b>; repeated violations are muted gradually.",
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

async def resolve_moderation_target(update, context, args):
    """Resolve a target from a reply, numeric Telegram ID, or @username."""
    user = replied_user(update)
    if user:
        return user.id, user.mention_html()

    if not args:
        return None, None

    raw = args[0].strip()
    if raw.lstrip("-").isdigit():
        user_id = int(raw)
        return user_id, f"<code>{user_id}</code>"

    if raw.startswith("@"):
        # Resolve from users already seen in THIS group. Telegram does not let bots
        # look up every normal user by username, so we maintain this mapping.
        doc = await get_user_by_username(update.effective_chat.id, raw)
        if doc:
            uid = int(doc["user_id"])
            uname = doc.get("username") or raw.lstrip("@")
            return uid, f"@{uname}"
        return None, None

    return None, None

async def mute(update, context):
    if not await require_admin(update): return await deny(update)

    args = list(context.args)
    minutes = 30
    # /mute <user_id|@username> [minutes]
    # A reply still supports /mute [minutes].
    if replied_user(update):
        if args and args[0].isdigit():
            minutes = int(args[0])
    else:
        if len(args) >= 2 and args[1].isdigit():
            minutes = int(args[1])

    user_id, display = await resolve_moderation_target(update, context, args)
    if not user_id:
        return await update.effective_message.reply_text(
            "Usage:\n"
            "• Reply: /mute [minutes]\n"
            "• User ID: /mute <user_id> [minutes]\n"
            "• Username: /mute @username [minutes] (user must have sent a message in this group)"
        )

    minutes = max(1, min(minutes, 10080))
    try:
        until = datetime.now(timezone.utc) + timedelta(minutes=minutes)
        await update.effective_chat.restrict_member(
            user_id, permissions=ChatPermissions.no_permissions(), until_date=until
        )
        await save_mute_record(update.effective_chat.id, user_id, minutes, "Manual admin mute")
        await update.effective_message.reply_text(f"🔇 Muted {display} for {minutes} minutes.", parse_mode="HTML")
        try:
            await context.bot.send_message(user_id, f"🔇 <b>You were muted</b> in <b>{update.effective_chat.title}</b> for {minutes} minutes.\nReason: Manual admin mute\n\nIf you believe this was a mistake, send me /appeal followed by your explanation.", parse_mode="HTML")
        except Exception:
            pass
    except Exception as e:
        await update.effective_message.reply_text(f"❌ Could not mute: {e}")

async def unmute(update, context):
    if not await require_admin(update): return await deny(update)

    user_id, display = await resolve_moderation_target(update, context, list(context.args))
    if not user_id:
        return await update.effective_message.reply_text(
            "Usage:\n"
            "• Reply: /unmute\n"
            "• User ID: /unmute <user_id>\n"
            "• Username: /unmute @username (user must have sent a message in this group)"
        )

    try:
        await update.effective_chat.restrict_member(
            user_id, permissions=ChatPermissions.all_permissions()
        )
        await update.effective_message.reply_text(
            f"🔊 Unmuted {display}.", parse_mode="HTML"
        )
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

async def setlimit(update, context):
    if not await require_admin(update): return await deny(update)
    if len(context.args) != 2 or not context.args[1].isdigit():
        return await update.effective_message.reply_text("Usage: /setlimit flood|duplicate|mentions|muteafter|decay <number>")
    key = context.args[0].lower(); value = int(context.args[1])
    mapping = {"flood": ("max_messages", 2, 50), "duplicate": ("max_duplicate", 2, 20), "mentions": ("max_mentions", 1, 50), "muteafter": ("auto_mute_after", 1, 20), "decay": ("violation_decay_hours", 1, 720)}
    if key not in mapping: return await update.effective_message.reply_text("Unknown limit type.")
    field, low, high = mapping[key]; value = max(low, min(value, high))
    await update_group(update.effective_chat.id, {field: value})
    await update.effective_message.reply_text(f"✅ {key} limit set to {value}.")

async def smartstatus(update, context):
    if not await require_admin(update): return await deny(update)
    s = await get_group(update.effective_chat.id, DEFAULT_SETTINGS)
    await update.effective_message.reply_text(
        "🧠 <b>Smart Moderation Status</b>\n\n"
        f"Flood: {s.get('max_messages')} messages / {s.get('window_seconds')} sec\n"
        f"Duplicate: {s.get('max_duplicate')}\nMentions: {s.get('max_mentions')}\n"
        f"Mute after: {s.get('auto_mute_after')} warnings\n"
        f"Violation reset after: {s.get('violation_decay_hours')}h clean activity\n"
        f"Warning notices: {'ON' if s.get('notify_warnings', True) else 'OFF'}\n\nUse /setlimit to adjust thresholds.", parse_mode="HTML")

async def my_chat_member(update, context):
    # Track joins for future anti-raid extensions and preserve username resolution.
    cm = getattr(update, "chat_member", None)
    if not cm: return
    member = cm.new_chat_member
    user = member.user
    if user.is_bot: return
    await upsert_user(cm.chat.id, user.id, {"username": user.username, "full_name": user.full_name, "last_member_event": datetime.now(timezone.utc)})

async def trust(update, context):
    if not await require_admin(update): return await deny(update)
    uid, display = await resolve_moderation_target(update, context, list(context.args))
    if not uid: return await update.effective_message.reply_text("Reply to a user or use /trust <user_id|@username>")
    await upsert_user(update.effective_chat.id, uid, {"whitelisted": True})
    await update.effective_message.reply_text(f"⭐ {display} is now trusted/whitelisted.", parse_mode="HTML")

async def untrust(update, context):
    if not await require_admin(update): return await deny(update)
    uid, display = await resolve_moderation_target(update, context, list(context.args))
    if not uid: return await update.effective_message.reply_text("Reply to a user or use /untrust <user_id|@username>")
    await upsert_user(update.effective_chat.id, uid, {"whitelisted": False})
    await update.effective_message.reply_text(f"⭐ Trust removed for {display}.", parse_mode="HTML")

async def silentmode(update, context):
    if not await require_admin(update): return await deny(update)
    s = await get_group(update.effective_chat.id, DEFAULT_SETTINGS)
    value = (context.args[0].lower() if context.args else "")
    if value in ("on","off"):
        await update_group(update.effective_chat.id, {"silent_mode": value == "on"})
        return await update.effective_message.reply_text(f"🔕 Silent moderation {'ON' if value == 'on' else 'OFF'}.")
    await update.effective_message.reply_text(f"🔕 Silent moderation: {'ON' if s.get('silent_mode') else 'OFF'}\nUse /silentmode on|off")

async def threatlevel(update, context):
    if not await require_admin(update): return await deny(update)
    s = await get_group(update.effective_chat.id, DEFAULT_SETTINGS)
    rows = await get_recent_events(update.effective_chat.id, 20)
    risk = sum(int(x.get("risk_score",0)) for x in rows[-10:]) if rows else 0
    level = "SAFE" if risk < 40 else "ELEVATED" if risk < 100 else "HIGH ALERT" if risk < 180 else "ATTACK DETECTED"
    await update_group(update.effective_chat.id,{"threat_level":level})
    await update.effective_message.reply_text(f"🚨 <b>Threat Level: {level}</b>\nRecent moderation risk: <b>{risk}</b>\nLockdown: <b>{'ON' if s.get('lockdown') else 'OFF'}</b>",parse_mode="HTML")

def _permissions_to_dict(permissions):
    """Store Telegram chat default permissions so they can be restored."""
    if not permissions:
        return None
    fields = (
        "can_send_messages", "can_send_audios", "can_send_documents",
        "can_send_photos", "can_send_videos", "can_send_video_notes",
        "can_send_voice_notes", "can_send_polls", "can_send_other_messages",
        "can_add_web_page_previews", "can_change_info", "can_invite_users",
        "can_pin_messages", "can_manage_topics",
    )
    return {field: getattr(permissions, field, None) for field in fields
            if getattr(permissions, field, None) is not None}

async def lockdown(update, context):
    if not await require_admin(update):
        return await deny(update)

    chat = update.effective_chat
    settings = await get_group(chat.id, DEFAULT_SETTINGS)
    if settings.get("lockdown"):
        return await update.effective_message.reply_text("🔒 Group lockdown is already enabled.")

    previous = _permissions_to_dict(chat.permissions)
    try:
        await chat.set_permissions(ChatPermissions.no_permissions())
        await update_group(chat.id, {
            "lockdown": True,
            "threat_level": "LOCKDOWN",
            "lockdown_previous_permissions": previous,
        })
        await update.effective_message.reply_text(
            "🚨 <b>GROUP LOCKDOWN ENABLED</b>\n\n"
            "🔒 All normal members are now restricted from sending messages, stickers, media, links, polls, or other content.\n"
            "🛡️ Group administrators can continue using the group normally.\n\n"
            "Use /unlockdown to allow members to message again.",
            parse_mode="HTML",
        )
    except Exception as e:
        await update.effective_message.reply_text(
            f"❌ Could not enable lockdown: {e}\n\nMake sure the bot is an admin with the <b>Restrict Members</b> permission.",
            parse_mode="HTML",
        )

async def unlockdown(update, context):
    if not await require_admin(update):
        return await deny(update)

    chat = update.effective_chat
    settings = await get_group(chat.id, DEFAULT_SETTINGS)
    if not settings.get("lockdown"):
        return await update.effective_message.reply_text("🔓 Group lockdown is not currently enabled.")

    previous = settings.get("lockdown_previous_permissions")
    try:
        permissions = ChatPermissions(**previous) if previous else ChatPermissions.all_permissions()
        await chat.set_permissions(permissions)
        await update_group(chat.id, {
            "lockdown": False,
            "threat_level": "SAFE",
            "lockdown_previous_permissions": None,
        })
        await update.effective_message.reply_text(
            "🟢 <b>GROUP LOCKDOWN DISABLED</b>\n\n"
            "💬 Normal members can send messages and use the group again.\n"
            "🔓 The group's previous default permissions have been restored.",
            parse_mode="HTML",
        )
    except Exception as e:
        await update.effective_message.reply_text(
            f"❌ Could not disable lockdown: {e}\n\nMake sure the bot is an admin with the <b>Restrict Members</b> permission.",
            parse_mode="HTML",
        )

async def nsfwstickers(update, context):
    if not await require_admin(update): return await deny(update)
    s=await get_group(update.effective_chat.id,DEFAULT_SETTINGS)
    args=list(context.args)
    if not args:
        return await update.effective_message.reply_text("🛡️ NSFW Sticker Protection: {}\n\n/on or /off\n/add — reply to a known inappropriate sticker to block it\n/remove — reply to remove it\n/pack <name> — block a sticker set name\n/unpack <name> — unblock a sticker set\n/status".format('ON' if s.get('nsfw_sticker_protection',True) else 'OFF'))
    action=args[0].lower(); ids=list(s.get('nsfw_sticker_ids',[])); packs=list(s.get('blocked_sticker_sets',[]))
    if action in ('on','off'):
        await update_group(update.effective_chat.id,{"nsfw_sticker_protection":action=='on'})
        return await update.effective_message.reply_text(f"🛡️ NSFW sticker protection {action.upper()}.")
    sticker = update.effective_message.reply_to_message.sticker if update.effective_message.reply_to_message and update.effective_message.reply_to_message.sticker else None
    if action in ('add','block'):
        if not sticker: return await update.effective_message.reply_text("Reply to the sticker you want to block, then use /nsfwstickers add")
        key=getattr(sticker,'file_unique_id',None)
        if key and key not in ids: ids.append(key)
        await update_group(update.effective_chat.id,{"nsfw_sticker_ids":ids})
        return await update.effective_message.reply_text("🚫 Sticker blocked for this group.")
    if action in ('remove','unblock'):
        if not sticker: return await update.effective_message.reply_text("Reply to the sticker you want to unblock, then use /nsfwstickers remove")
        key=getattr(sticker,'file_unique_id',None); ids=[x for x in ids if x!=key]
        await update_group(update.effective_chat.id,{"nsfw_sticker_ids":ids})
        return await update.effective_message.reply_text("✅ Sticker removed from the block list.")
    if action=='pack' and len(args)>1:
        name=args[1]
        if name not in packs: packs.append(name)
        await update_group(update.effective_chat.id,{"blocked_sticker_sets":packs})
        return await update.effective_message.reply_text(f"🚫 Sticker set blocked: {name}")
    if action=='unpack' and len(args)>1:
        name=args[1]; packs=[x for x in packs if x!=name]
        await update_group(update.effective_chat.id,{"blocked_sticker_sets":packs})
        return await update.effective_message.reply_text(f"✅ Sticker set unblocked: {name}")
    if action=='status':
        return await update.effective_message.reply_text(f"🛡️ NSFW sticker protection: {'ON' if s.get('nsfw_sticker_protection',True) else 'OFF'}\nBlocked stickers: {len(ids)}\nBlocked sticker sets: {len(packs)}")
    await update.effective_message.reply_text("Unknown option. Use /nsfwstickers")

async def member_profile(update, context):
    uid, display = await resolve_moderation_target(update, context, list(context.args))
    if not uid: uid=update.effective_user.id; display=update.effective_user.mention_html()
    data=await get_user(update.effective_chat.id,uid) or {}; v=await get_violation_count(update.effective_chat.id,uid)
    rep=int(data.get('reputation',0)); level='🌱 New' if rep<10 else '💬 Active' if rep<30 else '⭐ Trusted' if rep<60 else '🏆 Veteran'
    await update.effective_message.reply_text(f"👤 <b>Member Intelligence Profile</b>\nUser: {display}\nID: <code>{uid}</code>\nLevel: {level}\nReputation: <b>{rep}/100</b>\nMessages: <b>{data.get('message_count',0)}</b>\nViolations: <b>{v}</b>\nTrusted: <b>{'Yes' if data.get('whitelisted') else 'No'}</b>",parse_mode='HTML')

async def security(update, context):
    if not await require_admin(update): return await deny(update)
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    s=await get_group(update.effective_chat.id,DEFAULT_SETTINGS)
    text=(f"🛡️ <b>PREMIUM V3 SECURITY CENTER</b>\n\nThreat: <b>{s.get('threat_level','SAFE')}</b>\nMode: <b>{s.get('mode','adaptive').upper()}</b>\n\n"
          f"Smart Risk: {'✅' if s.get('smart_risk_enabled') else '❌'}\nAnti-Raid: {'✅' if s.get('anti_raid') else '❌'}\nReview Queue: {'✅' if s.get('review_queue_enabled') else '❌'}\nNSFW Sticker Guard: {'✅' if s.get('nsfw_sticker_protection') else '❌'}")
    kb=InlineKeyboardMarkup([[InlineKeyboardButton('🧠 Smart Risk',callback_data='sec:smart_risk_enabled'),InlineKeyboardButton('🚨 Anti-Raid',callback_data='sec:anti_raid')],[InlineKeyboardButton('📋 Review Queue',callback_data='sec:review_queue_enabled'),InlineKeyboardButton('🔞 Sticker Guard',callback_data='sec:nsfw_sticker_protection')],[InlineKeyboardButton('🟢 Adaptive Mode',callback_data='sec:mode')]])
    await update.effective_message.reply_text(text,parse_mode='HTML',reply_markup=kb)

async def mode(update, context):
    if not await require_admin(update): return await deny(update)
    val=(context.args[0].lower() if context.args else '')
    if val not in ('adaptive','community','strict','gaming','announcement'):
        return await update.effective_message.reply_text('Usage: /mode adaptive|community|strict|gaming|announcement')
    await update_group(update.effective_chat.id,{'mode':val})
    await update.effective_message.reply_text(f'🛡️ Security mode set to {val.upper()}.')

async def domain_cmd(update, context):
    if not await require_admin(update): return await deny(update)
    if len(context.args)<2:return await update.effective_message.reply_text('Usage: /domain whitelist|blacklist|remove <domain>')
    action,domain=context.args[0].lower(),context.args[1].lower().replace('https://','').replace('http://','').split('/')[0]
    s=await get_group(update.effective_chat.id,DEFAULT_SETTINGS)
    wl=set(s.get('domain_whitelist',[])); bl=set(s.get('domain_blacklist',[]))
    if action=='whitelist':wl.add(domain);bl.discard(domain)
    elif action=='blacklist':bl.add(domain);wl.discard(domain)
    elif action=='remove':wl.discard(domain);bl.discard(domain)
    else:return await update.effective_message.reply_text('Usage: /domain whitelist|blacklist|remove <domain>')
    await update_group(update.effective_chat.id,{'domain_whitelist':sorted(wl),'domain_blacklist':sorted(bl)})
    await update.effective_message.reply_text(f'✅ Domain updated: {domain}')

async def reviewqueue(update, context):
    if not await require_admin(update): return await deny(update)
    from database.mongo import db
    if db is None:return await update.effective_message.reply_text('Database unavailable.')
    items=await db.review_queue.find({'chat_id':update.effective_chat.id,'status':'open'}).sort('created_at',-1).limit(10).to_list(10)
    if not items:return await update.effective_message.reply_text('📋 No open review items.')
    lines=['📋 <b>OPEN REVIEW QUEUE</b>']
    for x in items:lines.append(f"• <code>{x.get('user_id')}</code> — {x.get('reason')} — risk {x.get('risk_score')}/100")
    await update.effective_message.reply_text('\n'.join(lines),parse_mode='HTML')


async def appeal(update, context):
    # This command is designed for the bot's private chat.
    if update.effective_chat.type != "private":
        return await update.effective_message.reply_text("Please send your appeal to me in private chat. Open the bot and use /appeal <your explanation>.")
    if not context.args:
        return await update.effective_message.reply_text("Usage: /appeal <explain why you think the mute should be removed>")
    user_id=update.effective_user.id
    text=" ".join(context.args).strip()[:1500]
    from database.mongo import db
    rec=await db.mute_records.find_one({"user_id":user_id},sort=[("muted_at",-1)])
    if not rec:
        return await update.effective_message.reply_text("I couldn't find a recent mute record for you. Please contact a group admin.")
    chat_id=int(rec['chat_id'])
    appeal_doc=await create_appeal(chat_id,user_id,text)
    from bson import ObjectId
    aid=str(appeal_doc['_id'])
    buttons=InlineKeyboardMarkup([[InlineKeyboardButton("✅ Unmute",callback_data=f"ap:unmute:{aid}"),InlineKeyboardButton("⏳ Reduce",callback_data=f"ap:reduce:{aid}")],[InlineKeyboardButton("❌ Reject",callback_data=f"ap:reject:{aid}"),InlineKeyboardButton("⭐ Trust",callback_data=f"ap:trust:{aid}")]])
    username=(update.effective_user.username and '@'+update.effective_user.username) or update.effective_user.full_name
    try:
        await context.bot.send_message(chat_id, f"📩 <b>NEW MUTE APPEAL</b>\n\n👤 User: {username}\n🆔 ID: <code>{user_id}</code>\n🔇 Reason: {rec.get('reason','Unknown')}\n📝 Appeal: {text}", parse_mode='HTML', reply_markup=buttons)
    except Exception:
        return await update.effective_message.reply_text("Your appeal could not be delivered to the group admins. Please make sure the bot is still in the group.")
    await update.effective_message.reply_text("✅ Your appeal has been sent to the group admins. Please wait for their decision.")

# -------------------------
# Admin promotion system
# -------------------------
PROMOTE_LEVELS = {
    "normal": {
        "title": "Normal Admin",
        "can_delete_messages": True,
        "can_pin_messages": True,
        "can_manage_video_chats": True,
    },
    "powerful": {
        "title": "Powerful Admin",
        "can_delete_messages": True,
        "can_pin_messages": True,
        "can_manage_video_chats": True,
        "can_change_info": True,
    },
    "destructive": {
        "title": "Destructive Admin",
        "can_delete_messages": True,
        "can_pin_messages": True,
        "can_manage_video_chats": True,
        "can_change_info": True,
        "can_restrict_members": True,
        "can_invite_users": True,
        "can_promote_members": True,
        "can_manage_chat": True,
        "can_manage_topics": True,
    },
}

async def _promotion_allowed(update):
    """Only an admin with Add New Admins / Promote Members permission may promote."""
    if not update.effective_chat or not update.effective_user:
        return False
    try:
        member = await update.get_bot().get_chat_member(update.effective_chat.id, update.effective_user.id)
        return bool(getattr(member, "can_promote_members", False) or member.status == ChatMemberStatus.OWNER)
    except Exception:
        return False

async def _bot_can_promote(update):
    try:
        me = await update.get_bot().get_me()
        member = await update.get_bot().get_chat_member(update.effective_chat.id, me.id)
        return bool(getattr(member, "can_promote_members", False))
    except Exception:
        return False

async def resolve_promotion_target(update, context):
    u = replied_user(update)
    args = list(context.args)
    if u:
        # Reply usage: /promote Custom Admin Tag
        return u.id, u.mention_html(), " ".join(args).strip()
    if not args:
        return None, None, None
    raw = args[0].strip()
    custom_title = " ".join(args[1:]).strip()
    if raw.lstrip("-").isdigit():
        uid = int(raw)
        doc = await get_user(update.effective_chat.id, uid)
        if doc:
            name = doc.get("first_name") or doc.get("username") or str(uid)
            return uid, f"@{doc['username']}" if doc.get("username") else name, custom_title
        return uid, f"<code>{uid}</code>", custom_title
    if raw.startswith("@"):
        doc = await get_user_by_username(update.effective_chat.id, raw)
        if doc:
            return int(doc["user_id"]), f"@{doc.get('username', raw.lstrip('@'))}", custom_title
    return None, None, None

async def promote(update, context):
    if not await _promotion_allowed(update):
        return await update.effective_message.reply_text("❌ Only admins with the <b>Add New Admins</b> permission can use /promote.", parse_mode="HTML")
    if not await _bot_can_promote(update):
        return await update.effective_message.reply_text("❌ I need the <b>Add New Admins / Promote Members</b> permission first.", parse_mode="HTML")

    user_id, display, custom_title = await resolve_promotion_target(update, context)
    if not user_id:
        return await update.effective_message.reply_text(
            "Usage:\n• Reply: <code>/promote Custom Admin Tag</code>\n• Username: <code>/promote @username Custom Admin Tag</code>\n• User ID: <code>/promote user_id Custom Admin Tag</code>\n\nExample: <code>/promote @username Bishal</code>\nThe text after the member is used as their Telegram Admin Tag. Username promotion works for members the bot has already seen in this group.",
            parse_mode="HTML",
        )

    actor_id = update.effective_user.id
    # Keep callback data short; store the requested custom title in user_data.
    title_key = f"promote_title:{update.effective_chat.id}:{user_id}:{actor_id}"
    context.user_data[title_key] = custom_title or None
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🛡 Normal", callback_data=f"pr:normal:{user_id}:{actor_id}")],
        [InlineKeyboardButton("⚡ Powerful", callback_data=f"pr:powerful:{user_id}:{actor_id}")],
        [InlineKeyboardButton("💀 Destructive", callback_data=f"pr:destructive:{user_id}:{actor_id}")],
    ])
    await update.effective_message.reply_text(
        f"<b>Promote {display}</b>\n"
        f"🏷 Admin Tag: <b>{custom_title or 'No custom tag'}</b>\n\n"
        "🛡 <b>Normal</b> — Delete messages, Pin messages, Manage live streams\n"
        "⚡ <b>Powerful</b> — All Normal rights + Change group info\n"
        "💀 <b>Destructive</b> — Powerful rights + Ban/restrict users, Invite/add users, Add new admins and management rights\n\n"
        "Choose the admin level:",
        parse_mode="HTML", reply_markup=keyboard,
    )

async def promote_callback(update, context):
    q = update.callback_query
    try:
        _, level, raw_user_id, raw_actor_id = q.data.split(":", 3)
        user_id, actor_id = int(raw_user_id), int(raw_actor_id)
    except Exception:
        return await q.answer("Invalid promotion request.", show_alert=True)

    if q.from_user.id != actor_id:
        return await q.answer("Only the admin who opened this promotion menu can choose the level.", show_alert=True)
    if not await _promotion_allowed(update):
        return await q.answer("You no longer have permission to add admins.", show_alert=True)
    if not await _bot_can_promote(update):
        return await q.answer("The bot no longer has permission to add admins.", show_alert=True)

    rights = PROMOTE_LEVELS.get(level)
    if not rights:
        return await q.answer("Unknown admin level.", show_alert=True)

    title_key = f"promote_title:{update.effective_chat.id}:{user_id}:{actor_id}"
    custom_title = context.user_data.pop(title_key, None)

    try:
        await q.answer("Promoting member…")
        await update.effective_chat.promote_member(user_id=user_id, **{k: v for k, v in rights.items() if k != "title"})
        # Use the tag supplied in /promote, not the permission-level name.
        if custom_title:
            try:
                await update.effective_chat.set_administrator_custom_title(user_id=user_id, custom_title=custom_title[:16])
            except Exception:
                pass
        await q.edit_message_text(
            f"✅ <b>Promotion successful!</b>\n\n"
            f"User ID: <code>{user_id}</code>\n"
            f"Admin level: <b>{rights['title']}</b>\n"
            f"Admin Tag: <b>{custom_title or 'Not set'}</b>",
            parse_mode="HTML",
        )
    except Exception as e:
        await q.answer("Promotion failed.", show_alert=True)
        await q.edit_message_text(f"❌ <b>Could not promote this member.</b>\n<code>{e}</code>", parse_mode="HTML")
