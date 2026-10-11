"""Admin-only bulk tagging commands for groups.

/atag mentions Telegram administrators. /utag mentions known group members
observed by the bot and stored in MongoDB (Telegram's Bot API cannot enumerate
all members of a group). Both commands may be used as replies to any message;
the replied message's text/caption becomes the heading.
"""
import asyncio
import html
import logging
from telegram.constants import ChatMemberStatus, ChatType
from telegram.error import TelegramError, RetryAfter
from database import mongo
from utils.permissions import is_admin

log = logging.getLogger(__name__)


def _mention(user_id, name):
    return f'<a href="tg://user?id={int(user_id)}">{html.escape(name or "Member")}</a>'


def _heading(message, context):
    if message.reply_to_message:
        replied = message.reply_to_message
        text = (replied.text or replied.caption or "").strip()
        if text:
            return text[:700]
    return " ".join(context.args).strip()[:700] or "📢 <b>Attention everyone!</b>"


async def _admin_only(update, context):
    chat, user, msg = update.effective_chat, update.effective_user, update.effective_message
    if not chat or chat.type not in (ChatType.GROUP, ChatType.SUPERGROUP):
        await msg.reply_text("⚠️ Use this command inside a group.")
        return False
    if not user or not await is_admin(context.bot, chat.id, user.id):
        await msg.reply_text("⛔ Only group admins can use this command.")
        return False
    return True


async def _send_tag_list(update, context, title, users):
    msg = update.effective_message
    chat_id = update.effective_chat.id
    heading = _heading(msg, context)
    # One mention per line, split safely under Telegram's message size limit.
    prefix = f"{heading}\n\n{title}\n"
    chunks, current = [], prefix
    count = 0
    for uid, name in users:
        line = f"• {_mention(uid, name)}\n"
        if len(current) + len(line) > 3500:
            chunks.append(current.rstrip())
            current = f"{title} (continued)\n"
        current += line
        count += 1
    if current.strip():
        chunks.append(current.rstrip())
    if not count:
        await msg.reply_text("ℹ️ No eligible members were found.")
        return
    status = await msg.reply_text(f"⏳ Preparing tags for {count} people…")
    for i, chunk in enumerate(chunks):
        try:
            await context.bot.send_message(
                chat_id=chat_id, text=chunk, parse_mode="HTML",
                disable_web_page_preview=True,
                reply_to_message_id=msg.reply_to_message.message_id if msg.reply_to_message else None,
                allow_sending_without_reply=True,
            )
        except RetryAfter as exc:
            await asyncio.sleep(float(exc.retry_after) + 0.5)
            try:
                await context.bot.send_message(chat_id=chat_id, text=chunk, parse_mode="HTML", disable_web_page_preview=True)
            except TelegramError:
                log.exception("Failed to send tag chunk in %s", chat_id)
        except TelegramError:
            log.exception("Failed to send tag chunk in %s", chat_id)
            await status.edit_text("⚠️ Telegram rejected a tag message. Try again later or use a smaller group.")
            return
        if i < len(chunks) - 1:
            await asyncio.sleep(1.1)
    try:
        await status.edit_text(f"✅ Tagged {count} {'admins' if title.startswith('👑') else 'known members'} in {len(chunks)} message(s).")
    except TelegramError:
        pass


async def atag(update, context):
    """Tag all current group administrators, one mention per line."""
    if not await _admin_only(update, context):
        return
    chat_id = update.effective_chat.id
    try:
        admins = await context.bot.get_chat_administrators(chat_id)
    except TelegramError:
        await update.effective_message.reply_text("❌ I couldn't fetch the admin list. Check my permissions and try again.")
        return
    users = [(m.user.id, m.user.full_name) for m in admins if not m.user.is_bot]
    await _send_tag_list(update, context, "👑 <b>GROUP ADMINS</b>", users)


async def utag(update, context):
    """Tag known group users; membership data is based on users the bot has seen."""
    if not await _admin_only(update, context):
        return
    collection = mongo.users
    if collection is None:
        await update.effective_message.reply_text("❌ Member database is not ready. Please try again shortly.")
        return
    chat_id = update.effective_chat.id
    records = await collection.find(
        {"chat_id": chat_id, "user_id": {"$exists": True}},
        {"user_id": 1, "full_name": 1, "username": 1, "is_bot": 1, "_id": 0},
    ).to_list(length=10000)
    result, seen = [], set()
    for record in records:
        uid = record.get("user_id")
        if not uid or uid in seen or record.get("is_bot"):
            continue
        seen.add(uid)
        try:
            member = await context.bot.get_chat_member(chat_id, uid)
            if member.status in (ChatMemberStatus.LEFT, ChatMemberStatus.BANNED):
                continue
            user = member.user
            if user.is_bot:
                continue
            result.append((user.id, user.full_name))
        except TelegramError:
            # Unknown/inaccessible records are skipped rather than guessed.
            continue
    result.sort(key=lambda item: item[1].casefold())
    await _send_tag_list(update, context, "👥 <b>GROUP MEMBERS</b>", result)
