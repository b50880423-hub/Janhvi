import logging

from telegram import Update
from telegram.ext import ContextTypes

from database.mongo import get_settings, get_filters, is_whitelisted
from services.detection import detect
from services.moderation import punish, delete_message, mute_user
from services.media_safety import explicit_text, explicit_link, classify_media

logger = logging.getLogger("security-bot")


async def moderate_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.effective_message
    chat = update.effective_chat

    if not message or not message.from_user or not chat:
        return
    if chat.type not in ("group", "supergroup"):
        return

    settings = get_settings(chat.id)
    if not settings.get("enabled", True):
        return

    user_id = message.from_user.id
    if await is_exempt(update, user_id):
        return

    # Never moderate group admins/owners.
    try:
        member = await chat.get_member(user_id)
        if member.status in ("administrator", "creator"):
            return
    except Exception as e:
        logger.exception("Could not check group member status: %s", e)
        # Continue moderation; failing to inspect membership should not disable
        # the entire protection system.

    # Explicit-content protection has priority.
    caption = message.caption or message.text or ""
    explicit_reason = explicit_text(caption) or explicit_link(caption)

    if not explicit_reason:
        try:
            explicit_reason = await classify_media(message, context)
        except Exception as e:
            logger.exception("Media safety classification failed: %s", e)

    if explicit_reason:
        from database.mongo import add_violation, add_event
        from datetime import datetime, timezone
        from config import EXPLICIT_MUTE_MINUTES

        count = add_violation(
            chat.id,
            user_id,
            explicit_reason,
            message.from_user.username,
        )

        deleted = await delete_message(message)
        muted, mute_error = await mute_user(message, EXPLICIT_MUTE_MINUTES)

        add_event({
            "created_at": datetime.now(timezone.utc),
            "chat_id": chat.id,
            "user_id": user_id,
            "username": message.from_user.username,
            "reason": explicit_reason,
            "violations": count,
            "deleted": deleted,
            "muted": muted,
            "mute_minutes": EXPLICIT_MUTE_MINUTES,
            "mute_error": mute_error,
            "action": (
                "explicit delete + 24h mute"
                if muted else
                "explicit delete + mute failed"
            ),
        })

        try:
            status = (
                "🔇 24 hour mute"
                if muted
                else f"⚠️ mute failed: {mute_error or 'unknown Telegram error'}"
            )
            await chat.send_message(
                f"🚨 <b>Explicit content removed</b>\n"
                f"User: {message.from_user.mention_html()}\n"
                f"Reason: <b>{explicit_reason}</b>\n"
                f"Action: 🗑️ deleted + {status}",
                parse_mode="HTML",
                disable_notification=True,
            )
        except Exception as e:
            logger.exception("Failed to send explicit-content action message: %s", e)
        return

    reasons = detect(message, settings, get_filters(chat.id))
    if not reasons:
        return

    reason = reasons[0]
    count, minutes, deleted, muted, mute_error = await punish(
        message, reason, settings
    )

    if count <= 3:
        try:
            warning = await chat.send_message(
                f"⚠️ <b>Warning {count}/3</b>\n"
                f"User: {message.from_user.mention_html()}\n"
                f"Reason: <b>{reason}</b>\n"
                f"Next violations may result in a mute.",
                parse_mode="HTML",
                disable_notification=True,
            )

            # Delete the warning later only when JobQueue is available.
            if context.job_queue:
                context.job_queue.run_once(
                    delete_later,
                    settings.get("warning_message_seconds", 15),
                    data=warning,
                )
        except Exception as e:
            logger.exception(
                "Failed to send Warning %s/3 in chat %s: %s",
                count,
                chat.id,
                e,
            )
    else:
        try:
            status = (
                f"🔇 muted for {minutes} minutes"
                if muted
                else f"⚠️ mute failed: {mute_error or 'unknown Telegram error'}"
            )
            await chat.send_message(
                f"🛡️ <b>Automatic moderation</b>\n"
                f"User: {message.from_user.mention_html()}\n"
                f"Reason: <b>{reason}</b>\n"
                f"Violation: <b>{count}</b>\n"
                f"Action: 🗑️ deleted + {status}",
                parse_mode="HTML",
                disable_notification=True,
            )
        except Exception as e:
            logger.exception("Failed to send automatic moderation message: %s", e)


async def delete_later(context: ContextTypes.DEFAULT_TYPE):
    try:
        await context.job.data.delete()
    except Exception as e:
        logger.exception("Failed to delete old warning message: %s", e)


async def is_exempt(update: Update, user_id: int):
    return is_whitelisted(update.effective_chat.id, user_id)
