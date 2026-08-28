from datetime import datetime, timedelta, timezone
from telegram import ChatPermissions, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ChatMemberStatus
from database.mongo import (
    get_group, update_group, get_violation_count, reset_violations,
    upsert_user, get_user, get_user_by_username, get_recent_events, log_event
)
from database.mongo import save_mute_record, get_mute_record, create_appeal
from services.cases import create_case, get_case, get_cases, counts as case_counts
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

async def _case_evidence(update):
    r = update.effective_message.reply_to_message if update.effective_message else None
    if not r: return {}
    text = r.text or r.caption or ''
    return {"message_id": r.message_id, "text": text[:4000], "date": r.date.isoformat() if r.date else None}

async def _send_admin_log(bot, source_chat_id, text):
    group = await get_group(source_chat_id, DEFAULT_SETTINGS)
    log_id = group.get("log_chat_id")
    if log_id:
        try: await bot.send_message(int(log_id), text, parse_mode="HTML")
        except Exception: pass

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
        "/unmute <user_id|@username> — manually unmute user\n/ban [reason] — permanently ban replied user\n/ban <user_id|@username> [reason] — permanently ban user\n/unban <user_id|@username> — manually remove a permanent ban\n\n"
        "<b>Protection</b>\n"
        "/antispam — show/toggle protection\n"
        "/lock [type] — lock a content type\n"
        "/unlock [type] — unlock a content type\n"
        "/lockdown — stop all normal members from sending anything\n"
        "/unlockdown — restore normal member messaging\n"
        "/demote — remove an admin\'s admin rights\n"
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


async def require_ban_permission(update):
    """Allow only the group owner or admins who have Telegram's ban/restrict-members power."""
    chat = update.effective_chat
    user = update.effective_user
    if not chat or not user:
        return False
    try:
        member = await update.get_bot().get_chat_member(chat.id, user.id)
    except Exception:
        return False
    if member.status == ChatMemberStatus.OWNER:
        return True
    return bool(
        member.status == ChatMemberStatus.ADMINISTRATOR
        and getattr(member, "can_restrict_members", False)
    )

async def deny_ban_permission(update):
    if update.effective_message:
        await update.effective_message.reply_text(
            "❌ You need the Telegram **Ban Users / Restrict Members** admin permission to use this command.",
            parse_mode="Markdown"
        )

async def ban(update, context):
    if not await require_ban_permission(update):
        return await deny_ban_permission(update)

    args = list(context.args)
    user_id, display = await resolve_moderation_target(update, context, args)
    if not user_id:
        return await update.effective_message.reply_text(
            "Usage:\n"
            "• Reply: /ban [reason]\n"
            "• User ID: /ban <user_id> [reason]\n"
            "• Username: /ban @username [reason] (user must have been seen in this group)"
        )

    # For reply, every argument is the reason. Otherwise the first argument is the target.
    reason_parts = args if replied_user(update) else args[1:]
    reason = " ".join(reason_parts).strip() or "No reason provided"

    try:
        # Refuse attempts to ban the chat owner.
        target_member = await context.bot.get_chat_member(update.effective_chat.id, user_id)
        if target_member.status == ChatMemberStatus.OWNER:
            return await update.effective_message.reply_text("❌ The group owner cannot be banned.")
    except Exception:
        # The target may already have left the group; Telegram can still ban by ID in many cases.
        pass

    try:
        await context.bot.ban_chat_member(update.effective_chat.id, user_id)
        await log_event({
            "chat_id": update.effective_chat.id,
            "type": "permanent_ban",
            "user_id": user_id,
            "admin_id": update.effective_user.id,
            "reason": reason,
            "created_at": datetime.now(timezone.utc),
        })
        case = await create_case(update.effective_chat.id, user_id, "permanent_ban", update.effective_user.id, reason, await _case_evidence(update))
        await _send_admin_log(context.bot, update.effective_chat.id, f"🚫 <b>CASE #{case['case_id']}</b>\nAction: Permanent Ban\nUser: <code>{user_id}</code>\nModerator: <code>{update.effective_user.id}</code>\nReason: {reason}")
        await update.effective_message.reply_text(
            f"🚫 Permanently banned {display}.\n📝 Reason: {reason}\n📁 Case: #{case['case_id']}", parse_mode="HTML"
        )
        try:
            await context.bot.send_message(
                user_id,
                f"🚫 <b>You were permanently banned</b> from <b>{update.effective_chat.title}</b>.\n"
                f"📝 Reason: {reason}",
                parse_mode="HTML",
            )
        except Exception:
            pass
    except Exception as e:
        await update.effective_message.reply_text(f"❌ Could not ban user: {e}")

async def unban(update, context):
    if not await require_ban_permission(update):
        return await deny_ban_permission(update)

    args = list(context.args)
    user_id, display = await resolve_moderation_target(update, context, args)
    if not user_id:
        return await update.effective_message.reply_text(
            "Usage:\n"
            "• User ID: /unban <user_id>\n"
            "• Username: /unban @username (user must have been seen in this group before being banned)"
        )

    try:
        await context.bot.unban_chat_member(
            update.effective_chat.id, user_id, only_if_banned=True
        )
        await log_event({
            "chat_id": update.effective_chat.id,
            "type": "unban",
            "user_id": user_id,
            "admin_id": update.effective_user.id,
            "reason": "Manual admin unban",
            "created_at": datetime.now(timezone.utc),
        })
        case = await create_case(update.effective_chat.id, user_id, "unban", update.effective_user.id, "Manual admin unban")
        await _send_admin_log(context.bot, update.effective_chat.id, f"🔓 <b>CASE #{case['case_id']}</b>\nAction: Unban\nUser: <code>{user_id}</code>\nModerator: <code>{update.effective_user.id}</code>")
        await update.effective_message.reply_text(f"🔓 Unbanned {display}. They can join the group again.\n📁 Case: #{case['case_id']}", parse_mode="HTML")
    except Exception as e:
        await update.effective_message.reply_text(f"❌ Could not unban user: {e}")

async def warn(update, context):
    if not await require_admin(update): return await deny(update)
    u = replied_user(update)
    if not u:
        return await update.effective_message.reply_text("Reply to a user's message.")
    from database.mongo import add_violation
    c = await add_violation(update.effective_chat.id, u.id, "manual warning")
    case = await create_case(update.effective_chat.id, u.id, "warning", update.effective_user.id, "Manual warning", await _case_evidence(update))
    await _send_admin_log(context.bot, update.effective_chat.id, f"⚠️ <b>CASE #{case['case_id']}</b>\nAction: Warning\nUser: <code>{u.id}</code>\nModerator: <code>{update.effective_user.id}</code>")
    await update.effective_message.reply_text(f"⚠️ Warning added to {u.mention_html()}. Total: {c}\n📁 Case: #{case['case_id']}", parse_mode="HTML")

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
        case = await create_case(update.effective_chat.id, user_id, "mute", update.effective_user.id, "Manual admin mute", await _case_evidence(update))
        await _send_admin_log(context.bot, update.effective_chat.id, f"🔇 <b>CASE #{case['case_id']}</b>\nAction: Mute ({minutes} minutes)\nUser: <code>{user_id}</code>\nModerator: <code>{update.effective_user.id}</code>")
        await update.effective_message.reply_text(f"🔇 Muted {display} for {minutes} minutes.\n📁 Case: #{case['case_id']}", parse_mode="HTML")
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
        case = await create_case(update.effective_chat.id, user_id, "unmute", update.effective_user.id, "Manual admin unmute")
        await _send_admin_log(context.bot, update.effective_chat.id, f"🔊 <b>CASE #{case['case_id']}</b>\nAction: Unmute\nUser: <code>{user_id}</code>\nModerator: <code>{update.effective_user.id}</code>")
        await update.effective_message.reply_text(f"🔊 Unmuted {display}.\n📁 Case: #{case['case_id']}", parse_mode="HTML")
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

async def _bot_can_restrict(update):
    try:
        me = await update.get_bot().get_me()
        member = await update.get_bot().get_chat_member(update.effective_chat.id, me.id)
        return bool(getattr(member, "can_restrict_members", False) or member.status == ChatMemberStatus.OWNER)
    except Exception:
        return False

LOCKDOWN_OPTIONS = {
    "text": ("can_send_messages", "💬 Send text messages"),
    "messages": ("can_send_messages", "💬 Send text messages"),
    "photo": ("can_send_photos", "🖼 Photos"),
    "photos": ("can_send_photos", "🖼 Photos"),
    "video": ("can_send_videos", "🎬 Videos"),
    "videos": ("can_send_videos", "🎬 Videos"),
    "sticker": ("can_send_other_messages", "🎭 Stickers"),
    "stickers": ("can_send_other_messages", "🎭 Stickers"),
    "gif": ("can_send_other_messages", "🎞 GIFs"),
    "gifs": ("can_send_other_messages", "🎞 GIFs"),
    "music": ("can_send_audios", "🎵 Music / audio"),
    "audio": ("can_send_audios", "🎵 Music / audio"),
    "file": ("can_send_documents", "📁 Files / documents"),
    "files": ("can_send_documents", "📁 Files / documents"),
    "document": ("can_send_documents", "📁 Files / documents"),
    "documents": ("can_send_documents", "📁 Files / documents"),
    "voice": ("can_send_voice_notes", "🎙 Voice messages"),
    "voicemessages": ("can_send_voice_notes", "🎙 Voice messages"),
    "video_message": ("can_send_video_notes", "📹 Video messages"),
    "videomessage": ("can_send_video_notes", "📹 Video messages"),
    "videomessages": ("can_send_video_notes", "📹 Video messages"),
    "link": ("can_add_web_page_previews", "🔗 Embed links / previews"),
    "links": ("can_add_web_page_previews", "🔗 Embed links / previews"),
    "embedlinks": ("can_add_web_page_previews", "🔗 Embed links / previews"),
    "poll": ("can_send_polls", "📊 Polls"),
    "polls": ("can_send_polls", "📊 Polls"),
    "addusers": ("can_invite_users", "👥 Add users"),
    "invite": ("can_invite_users", "👥 Add users"),
    "pin": ("can_pin_messages", "📌 Pin messages"),
    "pinmessages": ("can_pin_messages", "📌 Pin messages"),
    "chatinfo": ("can_change_info", "✏️ Change chat info"),
    "changeinfo": ("can_change_info", "✏️ Change chat info"),
}
LOCKDOWN_FIELDS = tuple({v[0] for v in LOCKDOWN_OPTIONS.values()})

async def _permission_state(chat, bot, fallback=None):
    """Return current default member permissions safely across PTB versions."""
    permissions = getattr(chat, "permissions", None)
    if permissions is None:
        try:
            full_chat = await bot.get_chat(chat.id)
            permissions = getattr(full_chat, "permissions", None)
        except Exception:
            permissions = None

    state = _permissions_to_dict(permissions) if permissions is not None else {}
    state = state or {}
    if fallback:
        for key, value in fallback.items():
            state.setdefault(key, value)
    return {field: bool(state.get(field, True)) for field in LOCKDOWN_FIELDS}

def _make_permissions(state):
    # Explicitly provide all supported default-member permissions.
    return ChatPermissions(**{field: bool(state.get(field, True)) for field in LOCKDOWN_FIELDS})

def _lockdown_usage():
    return (
        "<b>Usage</b>\n"
        "<code>/lockdown all</code> — disable everything\n"
        "<code>/lockdown text</code> — disable only text messages\n"
        "<code>/lockdown photos</code>, <code>videos</code>, <code>stickers</code>, <code>gifs</code>\n"
        "<code>/lockdown music</code>, <code>files</code>, <code>voice</code>, <code>videomessages</code>\n"
        "<code>/lockdown links</code>, <code>polls</code>, <code>addusers</code>, <code>pin</code>, <code>chatinfo</code>\n\n"
        "Use <code>/unlockdown all</code> or the same single option to enable it again.\n\n"
        "<i>Note: Telegram does not provide a default-member permission to separately disable reactions or 'edit own tags'. Those are controlled by Telegram/group settings and cannot be toggled through ChatPermissions.</i>"
    )

async def _bot_can_restrict(update):
    try:
        me = await update.get_bot().get_me()
        member = await update.get_bot().get_chat_member(update.effective_chat.id, me.id)
        return bool(getattr(member, "can_restrict_members", False) or member.status == ChatMemberStatus.OWNER)
    except Exception:
        return False

async def _apply_lockdown_state(update, context, state, active):
    chat = update.effective_chat
    await context.bot.set_chat_permissions(chat_id=chat.id, permissions=_make_permissions(state))
    await update_group(chat.id, {
        "lockdown": active,
        "threat_level": "LOCKDOWN" if active else "SAFE",
        "lockdown_current_permissions": state,
    })

async def lockdown(update, context):
    if not await require_admin(update): return await deny(update)
    chat = update.effective_chat
    if not chat or chat.type not in ("group", "supergroup"):
        return await update.effective_message.reply_text("❌ /lockdown can only be used in a group or supergroup.")
    if not await _bot_can_restrict(update):
        return await update.effective_message.reply_text("❌ I need the <b>Ban Users</b> admin right to restrict normal members and use lockdown.", parse_mode="HTML")

    option = (context.args[0].lower().replace("-", "").replace("_", "") if context.args else "all")
    if option in ("help", "list"):
        return await update.effective_message.reply_text(_lockdown_usage(), parse_mode="HTML")
    settings = await get_group(chat.id, DEFAULT_SETTINGS)
    previous = settings.get("lockdown_previous_permissions")
    if not previous:
        previous = await _permission_state(chat, context.bot)
        await update_group(chat.id, {"lockdown_previous_permissions": previous})
    current = dict(settings.get("lockdown_current_permissions") or await _permission_state(chat, context.bot, previous))

    if option == "all":
        for field in LOCKDOWN_FIELDS: current[field] = False
        label = "ALL MEMBER PERMISSIONS"
    elif option in LOCKDOWN_OPTIONS:
        field, label = LOCKDOWN_OPTIONS[option]
        current[field] = False
    else:
        return await update.effective_message.reply_text(_lockdown_usage(), parse_mode="HTML")
    try:
        await _apply_lockdown_state(update, context, current, True)
        await update.effective_message.reply_text(
            f"🔒 <b>LOCKDOWN UPDATED</b>\n\n🚫 Disabled: <b>{label}</b>\n🛡 Group admins are not affected.", parse_mode="HTML")
    except Exception as e:
        await update.effective_message.reply_text(f"❌ Lockdown failed: <code>{e}</code>", parse_mode="HTML")

async def unlockdown(update, context):
    if not await require_admin(update): return await deny(update)
    chat = update.effective_chat
    if not chat or chat.type not in ("group", "supergroup"):
        return await update.effective_message.reply_text("❌ /unlockdown can only be used in a group or supergroup.")
    if not await _bot_can_restrict(update):
        return await update.effective_message.reply_text("❌ I need the <b>Ban Users</b> admin right to change normal member permissions.", parse_mode="HTML")
    option = (context.args[0].lower().replace("-", "").replace("_", "") if context.args else "all")
    if option in ("help", "list"):
        return await update.effective_message.reply_text(_lockdown_usage(), parse_mode="HTML")
    settings = await get_group(chat.id, DEFAULT_SETTINGS)
    previous = settings.get("lockdown_previous_permissions") or await _permission_state(chat, context.bot)
    current = dict(settings.get("lockdown_current_permissions") or await _permission_state(chat, context.bot, previous))
    if option == "all":
        current = dict(previous)
        active = False
        label = "ALL SAVED MEMBER PERMISSIONS"
    elif option in LOCKDOWN_OPTIONS:
        field, label = LOCKDOWN_OPTIONS[option]
        current[field] = True
        active = any(not bool(current.get(f, True)) for f in LOCKDOWN_FIELDS)
    else:
        return await update.effective_message.reply_text(_lockdown_usage(), parse_mode="HTML")
    try:
        await _apply_lockdown_state(update, context, current, active)
        if option == "all":
            await update_group(chat.id, {"lockdown_previous_permissions": None})
        await update.effective_message.reply_text(
            f"🔓 <b>LOCKDOWN UPDATED</b>\n\n✅ Enabled: <b>{label}</b>\n🛡 Group admins are not affected.", parse_mode="HTML")
    except Exception as e:
        await update.effective_message.reply_text(f"❌ Unlock failed: <code>{e}</code>", parse_mode="HTML")

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
    """Interactive private-chat appeal flow."""
    if update.effective_chat.type != "private":
        return await update.effective_message.reply_text(
            "⚖️ Please open my private chat and use /appeal there."
        )
    user_id = update.effective_user.id
    from database.mongo import db
    rec = await db.mute_records.find_one({"user_id": user_id}, sort=[("muted_at", -1)])
    if not rec:
        return await update.effective_message.reply_text(
            "⚠️ I couldn't find a recent mute or restriction record for you. Please contact a group admin."
        )

    # Keep compatibility with the old one-line command: /appeal reason...
    if context.args:
        text = " ".join(context.args).strip()[:1500]
        return await _submit_appeal(update, context, rec, text)

    context.user_data["appeal_record"] = {
        "chat_id": int(rec["chat_id"]),
        "reason": rec.get("reason", "No reason recorded"),
    }
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("✍️ Write Appeal", callback_data="appealflow:write")],
        [InlineKeyboardButton("❌ Cancel", callback_data="appealflow:cancel")],
    ])
    await update.effective_message.reply_text(
        "⚖️ <b>APPEAL CENTER</b>\n"
        "━━━━━━━━━━━━━━━━\n\n"
        "🚫 A moderation restriction was found on your account.\n\n"
        "📝 If you believe the action was unfair, or you want another chance, you can submit an appeal for the group admins to review.\n\n"
        "Please be honest and respectful. 💙",
        parse_mode="HTML", reply_markup=keyboard,
    )

async def appeal_flow_callback(update, context):
    q = update.callback_query
    await q.answer()
    if not q.message or q.message.chat.type != "private":
        return await q.answer("Please use the bot's private chat.", show_alert=True)
    action = q.data.split(":", 1)[1] if ":" in q.data else ""
    if action == "cancel":
        context.user_data.pop("appeal_record", None)
        return await q.edit_message_text("❌ <b>Appeal cancelled.</b>\nYou can start again anytime with /appeal.", parse_mode="HTML")
    if action == "write":
        context.user_data["awaiting_appeal_reason"] = True
        return await q.edit_message_text(
            "✍️ <b>WHY SHOULD YOUR RESTRICTION BE REMOVED?</b>\n"
            "━━━━━━━━━━━━━━━━\n\n"
            "Please send your reason in <b>one message</b>.\n\n"
            "💡 Example: <i>I am sorry for what I did. It will not happen again. Please give me another chance.</i>",
            parse_mode="HTML",
        )

async def appeal_reason_message(update, context):
    if update.effective_chat.type != "private" or not context.user_data.get("awaiting_appeal_reason"):
        return
    if not update.effective_message or not update.effective_message.text or update.effective_message.text.startswith("/"):
        return await update.effective_message.reply_text("📝 Please send your appeal reason as normal text.")
    from database.mongo import db
    user_id = update.effective_user.id
    rec = await db.mute_records.find_one({"user_id": user_id}, sort=[("muted_at", -1)])
    if not rec:
        context.user_data.pop("awaiting_appeal_reason", None)
        return await update.effective_message.reply_text("⚠️ Your moderation record could no longer be found. Please contact a group admin.")
    context.user_data.pop("awaiting_appeal_reason", None)
    context.user_data.pop("appeal_record", None)
    text = update.effective_message.text.strip()[:1500]
    await _submit_appeal(update, context, rec, text)

async def _submit_appeal(update, context, rec, text):
    user_id = update.effective_user.id
    chat_id = int(rec["chat_id"])
    appeal_doc = await create_appeal(chat_id, user_id, text)
    aid = str(appeal_doc["_id"])
    buttons = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Accept & Unmute", callback_data=f"ap:unmute:{aid}")],
        [InlineKeyboardButton("❌ Reject", callback_data=f"ap:reject:{aid}")],
        [InlineKeyboardButton("⭐ Trust & Unmute", callback_data=f"ap:trust:{aid}")],
    ])
    username = (update.effective_user.username and "@" + update.effective_user.username) or update.effective_user.full_name
    message = (
        "⚖️ <b>NEW APPEAL RECEIVED</b>\n"
        "━━━━━━━━━━━━━━━━\n\n"
        f"👤 <b>User:</b> {username}\n"
        f"🆔 <b>User ID:</b> <code>{user_id}</code>\n"
        f"🚫 <b>Restriction Reason:</b> {rec.get('reason', 'Unknown')}\n\n"
        "📝 <b>USER'S APPEAL:</b>\n"
        f"<blockquote>{text}</blockquote>\n\n"
        "👇 <i>Choose an action below.</i>"
    )
    try:
        await context.bot.send_message(chat_id, message, parse_mode="HTML", reply_markup=buttons)
    except Exception:
        return await update.effective_message.reply_text("❌ Your appeal could not be delivered to the group admins. Please contact an admin.")
    await update.effective_message.reply_text(
        "📨 <b>APPEAL SUBMITTED SUCCESSFULLY!</b>\n"
        "━━━━━━━━━━━━━━━━\n\n"
        "Your request has been sent to the group administrators. Please wait patiently for their decision. 💙",
        parse_mode="HTML",
    )

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
        return member.status in (ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER) and bool(getattr(member, "can_promote_members", False))
    except Exception:
        return False

async def _safe_promote_rights(update, requested):
    """Telegram only lets a bot grant rights it already has. Clamp the preset to the bot's own rights."""
    me = await update.get_bot().get_me()
    bot_member = await update.get_bot().get_chat_member(update.effective_chat.id, me.id)
    result = {}
    for key, value in requested.items():
        if key == "title":
            continue
        if value:
            result[key] = bool(getattr(bot_member, key, False))
        else:
            result[key] = False
    return result

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
        # Numeric IDs do not need a database record. Telegram will verify membership
        # when promotion is attempted.
        doc = await get_user(update.effective_chat.id, uid)
        if doc:
            name = doc.get("full_name") or doc.get("first_name") or doc.get("username") or str(uid)
            return uid, f"@{doc['username']}" if doc.get("username") else name, custom_title
        return uid, f"<code>{uid}</code>", custom_title
    if raw.startswith("@"):
        doc = await get_user_by_username(update.effective_chat.id, raw)
        if doc:
            return int(doc["user_id"]), f"@{doc.get('username', raw.lstrip('@'))}", custom_title
        # Telegram bots cannot globally convert an arbitrary @username into a user ID.
        # Fall back to matching current administrators, which are available via Bot API.
        try:
            admins = await update.get_bot().get_chat_administrators(update.effective_chat.id)
            wanted = raw.lstrip("@").lower()
            for member in admins:
                user = member.user
                if (user.username or "").lower() == wanted:
                    return user.id, f"@{user.username}", custom_title
        except Exception:
            pass
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
        safe_rights = await _safe_promote_rights(update, rights)
        await update.effective_chat.promote_member(user_id=user_id, **safe_rights)
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


# -------------------------
# Admin demotion system
# -------------------------
async def demote(update, context):
    """Remove an administrator's listed admin rights and return them to normal-member status."""
    if not await _promotion_allowed(update):
        return await update.effective_message.reply_text(
            "❌ Only admins with the <b>Add New Admins</b> permission can use /demote.", parse_mode="HTML"
        )
    if not await _bot_can_promote(update):
        return await update.effective_message.reply_text(
            "❌ I need the <b>Add New Admins / Promote Members</b> permission first.", parse_mode="HTML"
        )

    user_id, display, _ = await resolve_promotion_target(update, context)
    if not user_id:
        return await update.effective_message.reply_text(
            "Usage:\n• Reply to an admin: <code>/demote</code>\n"
            "• <code>/demote @username</code>\n• <code>/demote user_id</code>", parse_mode="HTML"
        )
    try:
        target = await context.bot.get_chat_member(update.effective_chat.id, user_id)
        if target.status == ChatMemberStatus.OWNER:
            return await update.effective_message.reply_text("❌ The group owner cannot be demoted.")
        if target.status != ChatMemberStatus.ADMINISTRATOR:
            return await update.effective_message.reply_text("❌ That user is not currently an administrator.")

        # Explicitly remove every requested/admin-management right. Telegram also
        # clears the administrator custom title when the user is demoted.
        await update.effective_chat.promote_member(
            user_id=user_id,
            can_manage_chat=False,
            can_change_info=False,
            can_delete_messages=False,
            can_restrict_members=False,
            can_invite_users=False,
            can_pin_messages=False,
            can_promote_members=False,
            can_manage_video_chats=False,
            can_manage_topics=False,
            can_post_stories=False,
            can_edit_stories=False,
            can_delete_stories=False,
        )
        try:
            await update.effective_chat.set_administrator_custom_title(user_id=user_id, custom_title="")
        except Exception:
            pass
        await update.effective_message.reply_text(
            f"⬇️ <b>Demoted successfully.</b>\n\n{display or f'<code>{user_id}</code>'} is now a normal member.",
            parse_mode="HTML",
        )
    except Exception as e:
        await update.effective_message.reply_text(f"❌ Could not demote this admin: <code>{e}</code>", parse_mode="HTML")

async def case_cmd(update, context):
    if not await require_admin(update): return await deny(update)
    if not context.args or not context.args[0].isdigit(): return await update.effective_message.reply_text("Usage: /case <case_id>")
    doc=await get_case(update.effective_chat.id,int(context.args[0]))
    if not doc: return await update.effective_message.reply_text("❌ Case not found.")
    await update.effective_message.reply_text(f"📁 <b>CASE #{doc['case_id']}</b>\nAction: {doc['action']}\nUser ID: <code>{doc['user_id']}</code>\nModerator ID: <code>{doc['admin_id']}</code>\nReason: {doc['reason']}\nStatus: {doc['status']}\nTime: {doc['created_at'].strftime('%d %b %Y %H:%M UTC')}",parse_mode='HTML')

async def userhistory(update, context):
    if not await require_admin(update): return await deny(update)
    uid,_=await resolve_moderation_target(update,context,list(context.args))
    if not uid: return await update.effective_message.reply_text("Reply to a user or use /userhistory <user_id|@username>.")
    rows=await get_cases(update.effective_chat.id,uid,20); c=await case_counts(update.effective_chat.id,uid)
    lines=[f"📋 <b>USER MODERATION HISTORY</b>",f"User ID: <code>{uid}</code>",f"Warnings: {c.get('warning',0)} | Mutes: {c.get('mute',0)} | Bans: {c.get('permanent_ban',0)}","", "Recent cases:"]
    lines += [f"#{x['case_id']} — {x['action']} — {x['reason']}" for x in rows] or ["No cases found."]
    await update.effective_message.reply_text("\n".join(lines),parse_mode='HTML')

async def evidence(update, context):
    if not await require_admin(update): return await deny(update)
    if not context.args or not context.args[0].isdigit(): return await update.effective_message.reply_text("Usage: /evidence <case_id>")
    doc=await get_case(update.effective_chat.id,int(context.args[0])); ev=(doc or {}).get('evidence') or {}
    if not doc: return await update.effective_message.reply_text("❌ Case not found.")
    text=ev.get('text') or 'No message evidence was stored for this case.'
    await update.effective_message.reply_text(f"🧾 <b>EVIDENCE — CASE #{doc['case_id']}</b>\n{text}",parse_mode='HTML')

async def setlog(update, context):
    if not await require_admin(update): return await deny(update)
    if not context.args or not context.args[0].lstrip('-').isdigit(): return await update.effective_message.reply_text("Usage: /setlog <log_group_or_channel_id>")
    await update_group(update.effective_chat.id, {'log_chat_id':int(context.args[0])})
    await update.effective_message.reply_text("✅ Admin log destination saved.")

async def removelog(update, context):
    if not await require_admin(update): return await deny(update)
    await update_group(update.effective_chat.id, {'log_chat_id':None})
    await update.effective_message.reply_text("✅ Admin log destination removed.")

async def logstatus(update, context):
    if not await require_admin(update): return await deny(update)
    g=await get_group(update.effective_chat.id,DEFAULT_SETTINGS); lid=g.get('log_chat_id')
    await update.effective_message.reply_text(f"📜 Admin Log: {'Enabled ('+str(lid)+')' if lid else 'Not configured'}")

# ---------------- Detailed Rules & Command Guide ----------------
RULE_GUIDE = {
    "home": """🛡️ <b>GROUP MANAGEMENT BOT — COMPLETE GUIDE</b>\n━━━━━━━━━━━━━━━━━━\n\nThis guide explains the commands, moderation tools and permission rules available in this bot.\n\nSelect a section below.\n\n<b>Important:</b> Commands only work when both the acting admin and the bot have the required Telegram permissions. Telegram may also prevent an admin from managing an equal or higher administrator.""",
    "admin": """👑 <b>ADMIN MANAGEMENT</b>\n━━━━━━━━━━━━━━━━━━\n\n<b>/promote</b> — Promote a member. Use by replying to a member or, where the member is known to the bot, by username/User ID.\n\nPromotion levels:\n🛡️ <b>Normal:</b> Delete Messages, Pin Messages, Manage Live Streams.\n\n⚡ <b>Powerful:</b> Change Group Info, Pin Messages, Edit Member Tags/Manage Chat where Telegram supports it, Manage Stories, Ban/Restrict Users, Delete Messages, Manage Live Streams.\n\n💀 <b>Destructive:</b> All Powerful rights plus Invite Users via Link and Add New Admins.\n\n<b>Who can promote:</b> Group owner and admins with Telegram's Add New Admins permission, subject to the bot's permissions.\n\n<b>/demote</b> — Remove a member's administrator privileges. Use by reply or supported username/User ID targeting.""",
    "moderation": """🛡️ <b>MODERATION COMMANDS</b>\n━━━━━━━━━━━━━━━━━━\n\n<b>/warn</b> — Issue a warning. Example: <code>/warn @user reason</code> or reply with <code>/warn reason</code>.\n<b>/warnings</b> — View a member's warnings.\n<b>/resetwarnings</b> — Clear/reset a member's warning record.\n\n<b>/mute</b> — Restrict a member according to the bot's moderation system. Provide a clear reason when possible.\n<b>/unmute</b> — Remove a mute/restriction.\n\nWarnings and moderation actions may be recorded and used by the Case, History and Appeal systems. Admin commands require appropriate Telegram permissions.""",
    "ban": """🚫 <b>PERMANENT BAN SYSTEM</b>\n━━━━━━━━━━━━━━━━━━\n\n<b>/ban</b> — Permanently ban a member.\nExamples:\n<code>/ban @username reason</code>\nReply: <code>/ban reason</code>\n\nThe ban remains active until an authorized admin manually removes it.\n\n<b>/unban</b> — Manually remove a permanent ban.\nExamples:\n<code>/unban @username</code>\n<code>/unban 123456789</code>\n\n<b>Who can use these:</b> Group owner or an admin with Telegram's Ban/Restrict Members power. The bot must also have the necessary ban/restrict permission.""",
    "lockdown": """🔒 <b>LOCKDOWN & GROUP PERMISSIONS</b>\n━━━━━━━━━━━━━━━━━━\n\n<b>/lockdown all</b> — Restrict the supported member permissions.\n<b>/unlockdown all</b> — Restore supported permissions.\n\nIndividual controls include supported keywords such as:\n<code>text</code>, <code>photos</code>, <code>videos</code>, <code>stickers</code>, <code>gifs</code>, <code>music</code>, <code>files</code>, <code>voice</code>, <code>videomessages</code>, <code>links</code>, <code>polls</code>, <code>addusers</code>, <code>pin</code>, and <code>chatinfo</code>.\n\nExamples:\n<code>/lockdown text</code>\n<code>/unlockdown text</code>\n\nAdmins remain governed by Telegram's own administrator permissions.""",
    "cases": """📁 <b>MODERATION CASES, HISTORY & EVIDENCE</b>\n━━━━━━━━━━━━━━━━━━\n\n<b>/case &lt;case_id&gt;</b> — View one moderation case.\n<b>/cases &lt;user&gt;</b> — View a member's recent cases.\n<b>/userhistory &lt;user&gt;</b> — View a member's moderation history.\n<b>/evidence &lt;case_id&gt;</b> — View stored evidence for a case.\n\nCases can record actions such as warnings, mutes, un-mutes, permanent bans and unbans, together with moderator, target, reason, status, time and available evidence.""",
    "appeal": """⚖️ <b>APPEAL SYSTEM</b>\n━━━━━━━━━━━━━━━━━━\n\n<b>/appeal</b> (or <b>/apeal</b>) — Submit an appeal for an eligible recorded mute or restriction.\n\nThe member should explain clearly why the moderation action should be reviewed. The appeal is sent through the bot's review flow for administrators.\n\nIf the bot says no recent eligible record exists, the punishment may not have been recorded by the system or may not be eligible for appeal.""",
    "logs": """📜 <b>ADMIN LOG CHANNEL</b>\n━━━━━━━━━━━━━━━━━━\n\n<b>/setlog &lt;chat_id&gt;</b> — Set the destination for moderation/admin logs.\nExample: <code>/setlog -1001234567890</code>\n\n<b>/logstatus</b> — Check the configured log destination.\n<b>/removelog</b> — Remove the configured destination.\n\nThe bot must be able to send messages in the selected log chat. Important moderation and administration actions can be recorded there for audit purposes.""",
    "security": """🛡️ <b>SECURITY & AUTOMATIC MODERATION</b>\n━━━━━━━━━━━━━━━━━━\n\n<b>/antispam</b> — Anti-spam controls.\n<b>/security</b> — Security settings.\n<b>/silentmode</b> — Silent moderation behaviour.\n<b>/smartstatus</b> — Smart moderation status.\n<b>/threatlevel</b> — Threat/security level controls.\n<b>/reviewqueue</b> — Review pending moderation actions.\n<b>/setlimit</b> — Configure supported moderation limits.\n<b>/mode</b> — Configure moderation mode.\n<b>/domain</b> — Domain/link-related configuration.\n<b>/nsfwstickers</b> — NSFW sticker protection controls.\n\nUse these tools responsibly and review group-specific settings before enabling strict automation.""",
    "other": """📚 <b>OTHER AVAILABLE COMMANDS</b>\n━━━━━━━━━━━━━━━━━━\n\n<b>/start</b> — Start the bot.\n<b>/help</b> — Bot help/settings overview.\n<b>/settings</b> — Group settings.\n<b>/userinfo</b> — View user information.\n<b>/profile</b> — View member profile.\n<b>/lock</b> and <b>/unlock</b> — Existing lock controls.\n<b>/filter</b> and <b>/badwords</b> — Content filtering tools.\n<b>/whitelist</b>, <b>/unwhitelist</b> — Trusted/allowed entries.\n<b>/blacklist</b>, <b>/unblacklist</b> — Blocked entries.\n<b>/trust</b>, <b>/untrust</b> — Trusted member status.\n<b>/logs</b> — View supported moderation logs.\n<b>/whisper</b>, <b>/whisperowner</b> — Whisper features.\n\nAvailability and exact behaviour depend on the group's settings and the bot's installed modules.""",
    "rules": """⚠️ <b>BOT & ADMINISTRATION RULES</b>\n━━━━━━━━━━━━━━━━━━\n\n<b>For members</b>\n• Follow the group's own rules and admin instructions.\n• Do not spam or attempt to bypass moderation.\n• Use <b>/appeal</b> respectfully when eligible.\n\n<b>For administrators</b>\n• Use moderation powers responsibly.\n• Provide clear reasons for warnings, mutes and bans whenever possible.\n• Check <b>/userhistory</b> before serious repeat-offender actions.\n• Do not misuse promotion, ban or restriction powers.\n• Keep moderation decisions consistent with the group's policy.\n\n<b>Permission rule</b>\nA command can fail if the acting admin lacks the required Telegram right, the bot lacks the required right, or Telegram's administrator hierarchy prevents the action.\n\nPermanent bans remain until an authorized admin uses <b>/unban</b>."""
}

def _rules_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("👑 Admin Management", callback_data="rules:admin"), InlineKeyboardButton("🛡️ Moderation", callback_data="rules:moderation")],
        [InlineKeyboardButton("🚫 Ban System", callback_data="rules:ban"), InlineKeyboardButton("🔒 Lockdown", callback_data="rules:lockdown")],
        [InlineKeyboardButton("📁 Cases & Evidence", callback_data="rules:cases"), InlineKeyboardButton("⚖️ Appeals", callback_data="rules:appeal")],
        [InlineKeyboardButton("📜 Admin Logs", callback_data="rules:logs"), InlineKeyboardButton("🛡️ Security", callback_data="rules:security")],
        [InlineKeyboardButton("📚 Other Commands", callback_data="rules:other"), InlineKeyboardButton("⚠️ Bot Rules", callback_data="rules:rules")],
        [InlineKeyboardButton("🏠 Main Guide", callback_data="rules:home")],
    ])

async def rules(update, context):
    await update.effective_message.reply_text(RULE_GUIDE["home"], parse_mode="HTML", reply_markup=_rules_keyboard())

async def rules_callback(update, context):
    q = update.callback_query
    await q.answer()
    key = (q.data or "rules:home").split(":", 1)[1]
    text = RULE_GUIDE.get(key, RULE_GUIDE["home"])
    await q.edit_message_text(text, parse_mode="HTML", reply_markup=_rules_keyboard())
