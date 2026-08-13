from telegram import Update
from telegram.ext import ContextTypes
from database.mongo import get_settings, get_filters, is_whitelisted
from services.detection import detect
from services.moderation import punish
from services.media_safety import explicit_text, explicit_link, classify_media

import logging

logger = logging.getLogger("security-bot")

async def moderate_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.effective_message
    if not message or not message.from_user or not update.effective_chat:
        return
    if update.effective_chat.type not in ("group", "supergroup"):
        return

    settings = get_settings(update.effective_chat.id)
    if not settings.get("enabled"):
        return
    if await is_exempt(update, message.from_user.id):
        return

    # Never moderate group admins/owners.
    try:
        member = await update.effective_chat.get_member(message.from_user.id)
        if member.status in ("administrator", "creator"):
            return
    except Exception as e:
        logger.exception("Failed to send moderation warning: %s", e)

    # Explicit-content protection has priority.
    caption = message.caption or message.text or ""
    explicit_reason = explicit_text(caption) or explicit_link(caption)

    if not explicit_reason:
        explicit_reason = await classify_media(message, context)

    if explicit_reason:
        # Explicit content is an immediate first-occurrence action:
        # delete + 24h mute. Do not wait for the normal 4th violation.
        from database.mongo import add_violation, add_event
        from services.moderation import delete_message, mute_user
        from datetime import datetime, timezone

        count = add_violation(
            message.chat.id, message.from_user.id,
            explicit_reason, message.from_user.username
        )
        deleted = await delete_message(message)
        muted, mute_error = await mute_user(
            message, int(__import__("config").EXPLICIT_MUTE_MINUTES)
        )
        add_event({
            "created_at": datetime.now(timezone.utc),
            "chat_id": message.chat.id,
            "user_id": message.from_user.id,
            "username": message.from_user.username,
            "reason": explicit_reason,
            "violations": count,
            "deleted": deleted,
            "muted": muted,
            "mute_minutes": int(__import__("config").EXPLICIT_MUTE_MINUTES),
            "mute_error": mute_error,
            "action": "explicit delete + 24h mute" if muted else "explicit delete + mute failed",
        })
        try:
            status = "🔇 24 hour mute" if muted else "⚠️ mute failed"
            await message.chat.send_message(
                f"🚨 <b>Explicit content removed</b>\\n"
                f"User: {message.from_user.mention_html()}\\n"
                f"Reason: <b>{explicit_reason}</b>\\n"
                f"Action: 🗑️ deleted + {status}",
                parse_mode="HTML", disable_notification=True
            )
        except Exception as e:
            logger.exception("Failed to send moderation warning: %s", e)
        return

    reasons = detect(message, settings, get_filters(update.effective_chat.id))
    if not reasons:
        return

    reason = reasons[0]
    count, minutes, deleted, muted, mute_error = await punish(message, reason, settings)

    if count <= 3:
        try:
            warning = await message.chat.send_message(
                f"⚠️ <b>Warning {count}/3</b>\n"
                f"User: {message.from_user.mention_html()}\n"
                f"Reason: <b>{reason}</b>\n"
                f"Next violations may result in a mute.",
                parse_mode="HTML", disable_notification=True)
            context.job_queue.run_once(delete_later, 15, data=warning)
        except Exception as e:
            logger.exception("Failed to send moderation warning: %s", e)
    else:
        try:
            status = f"🔇 muted for {minutes} minutes" if muted else f"⚠️ mute failed: {mute_error}"
            await message.chat.send_message(
                f"🛡️ <b>Automatic moderation</b>\n"
                f"User: {message.from_user.mention_html()}\n"
                f"Reason: <b>{reason}</b>\n"
                f"Violation: <b>{count}</b>\n"
                f"Action: 🗑️ deleted + {status}",
                parse_mode="HTML", disable_notification=True)
        except Exception as e:
            logger.exception("Failed to send moderation warning: %s", e)

async def delete_later(context):
    try:
        await context.job.data.delete()
    except Exception as e:
        logger.exception("Failed to send moderation warning: %s", e)

async def is_exempt(update, user_id):
    return is_whitelisted(update.effective_chat.id, user_id)
