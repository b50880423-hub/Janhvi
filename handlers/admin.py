from telegram import ChatPermissions
from telegram.constants import ChatMemberStatus
from database.mongo import get_group, update_group, get_violation_count, reset_violations, upsert_user
from config import DEFAULT_SETTINGS
from utils.permissions import is_admin
from utils.keyboards import settings_keyboard

async def require_admin(update):
    return update.effective_chat and update.effective_user and await is_admin(
        update.get_bot(), update.effective_chat.id, update.effective_user.id
    )

async def settings(update, context):
    if not await require_admin(update):
        await update.effective_message.reply_text("❌ Admins only.")
        return
    s = await get_group(update.effective_chat.id, DEFAULT_SETTINGS)
    await update.effective_message.reply_text("🛡️ <b>AntiSpam Settings</b>", parse_mode="HTML", reply_markup=settings_keyboard(s))

async def help_cmd(update, context):
    await update.effective_message.reply_text(
        "<b>Commands</b>\n\n"
        "/settings — admin control panel\n"
        "/warn — warn replied user\n"
        "/mute — mute replied user\n"
        "/unmute — unmute replied user\n"
        "/ban — ban replied user\n"
        "/unban — unban by user ID\n"
        "/whitelist — whitelist replied user\n"
        "/unwhitelist — remove whitelist\n"
        "/userinfo — show moderation info\n"
        "/warnings — show warning count\n"
        "/resetwarnings — reset warnings",
        parse_mode="HTML"
    )

def replied_user(update):
    return update.effective_message.reply_to_message.from_user if update.effective_message.reply_to_message else None

async def warn(update, context):
    if not await require_admin(update): return
    u = replied_user(update)
    if not u:
        await update.effective_message.reply_text("Reply to a user's message.")
        return
    from database.mongo import add_violation
    c = await add_violation(update.effective_chat.id, u.id, "manual warning")
    await update.effective_message.reply_text(f"⚠️ Warning added to {u.mention_html()}. Total: {c}", parse_mode="HTML")

async def mute(update, context):
    if not await require_admin(update): return
    u = replied_user(update)
    if not u:
        await update.effective_message.reply_text("Reply to a user's message.")
        return
    minutes = int(context.args[0]) if context.args and context.args[0].isdigit() else 30
    try:
        await update.effective_chat.restrict_member(u.id, permissions=ChatPermissions.no_permissions(), until_date=__import__("datetime").datetime.now(__import__("datetime").timezone.utc).timestamp()+minutes*60)
        await update.effective_message.reply_text(f"🔇 Muted {u.mention_html()} for {minutes} minutes.", parse_mode="HTML")
    except Exception as e:
        await update.effective_message.reply_text(f"❌ Could not mute: {e}")

async def unmute(update, context):
    if not await require_admin(update): return
    u = replied_user(update)
    if not u:
        await update.effective_message.reply_text("Reply to a user's message.")
        return
    try:
        await update.effective_chat.restrict_member(u.id, permissions=ChatPermissions.all_permissions())
        await update.effective_message.reply_text(f"🔊 Unmuted {u.mention_html()}.", parse_mode="HTML")
    except Exception as e:
        await update.effective_message.reply_text(f"❌ Could not unmute: {e}")

async def ban(update, context):
    if not await require_admin(update): return
    u = replied_user(update)
    if not u:
        await update.effective_message.reply_text("Reply to a user's message.")
        return
    try:
        await update.effective_chat.ban_member(u.id)
        await update.effective_message.reply_text(f"🚫 Banned {u.mention_html()}.", parse_mode="HTML")
    except Exception as e:
        await update.effective_message.reply_text(f"❌ Could not ban: {e}")

async def unban(update, context):
    if not await require_admin(update): return
    if not context.args or not context.args[0].isdigit():
        await update.effective_message.reply_text("Usage: /unban USER_ID")
        return
    try:
        await update.effective_chat.unban_member(int(context.args[0]), only_if_banned=True)
        await update.effective_message.reply_text("✅ User unbanned.")
    except Exception as e:
        await update.effective_message.reply_text(f"❌ Could not unban: {e}")

async def whitelist(update, context):
    if not await require_admin(update): return
    u = replied_user(update)
    if not u:
        await update.effective_message.reply_text("Reply to a user's message.")
        return
    await upsert_user(update.effective_chat.id, u.id, {"username": u.username, "whitelisted": True})
    await update.effective_message.reply_text(f"✅ {u.mention_html()} is whitelisted.", parse_mode="HTML")

async def unwhitelist(update, context):
    if not await require_admin(update): return
    u = replied_user(update)
    if not u:
        await update.effective_message.reply_text("Reply to a user's message.")
        return
    await upsert_user(update.effective_chat.id, u.id, {"whitelisted": False})
    await update.effective_message.reply_text("✅ Whitelist removed.")

async def userinfo(update, context):
    u = replied_user(update)
    if not u and context.args and context.args[0].isdigit():
        uid = int(context.args[0])
    elif u:
        uid = u.id
    else:
        uid = update.effective_user.id
    c = await get_violation_count(update.effective_chat.id, uid)
    await update.effective_message.reply_text(f"👤 User ID: <code>{uid}</code>\n⚠️ Violations: <b>{c}</b>", parse_mode="HTML")

async def warnings(update, context):
    await userinfo(update, context)

async def resetwarnings(update, context):
    if not await require_admin(update): return
    u = replied_user(update)
    if not u:
        await update.effective_message.reply_text("Reply to a user's message.")
        return
    await reset_violations(update.effective_chat.id, u.id)
    await update.effective_message.reply_text("✅ Warnings reset.")

async def my_chat_member(update, context):
    pass
