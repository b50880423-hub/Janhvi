import logging
import re

from telegram import Update
from telegram.ext import ContextTypes

from config import TELEGRAM_API_ID, TELEGRAM_API_HASH, TELEGRAM_USER_SESSION, HISTORY_SOURCE_BOT
from history_client import fetch_history

logger = logging.getLogger(__name__)


def _chunks(text: str, limit: int = 3900):
    text = text.strip()
    while len(text) > limit:
        cut = text.rfind("\n", 0, limit)
        if cut < limit // 2:
            cut = limit
        yield text[:cut]
        text = text[cut:].lstrip()
    if text:
        yield text


async def history_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.effective_message
    if not message:
        return

    # Join args so display names with spaces can be passed as a best-effort query.
    target = " ".join(context.args).strip()
    if not target:
        await message.reply_text(
            "Usage:\n/history 6446674912\n/history @username\n/history Display Name\n\n"
            "Usernames are resolved to a Telegram ID when possible. Display-name searches depend on whether the external history source supports them; names are not unique."
        )
        return

    if len(target) > 128 or any(ch in target for ch in "\r\n"):
        await message.reply_text("Please provide a Telegram ID, @username, username, or a short display name.")
        return

    if not (TELEGRAM_API_ID and TELEGRAM_API_HASH and TELEGRAM_USER_SESSION):
        await message.reply_text(
            "History lookup is not configured yet. The bot needs a separately authenticated Telegram user session.\n\n"
            "Set TELEGRAM_API_ID, TELEGRAM_API_HASH, and TELEGRAM_USER_SESSION in your deployment settings, then restart the bot."
        )
        return

    status = await message.reply_text(f"🔎 Looking up: {target}…")
    try:
        results = await fetch_history(target)
        if not results:
            await status.edit_text(
                "The history source returned no text results. If you searched by display name, try a numeric ID or @username instead."
            )
            return
        await status.delete()
        combined = f"📜 Telegram history lookup: {target}\nSource: @{HISTORY_SOURCE_BOT.lstrip('@')}\n\n" + "\n\n".join(results)
        for part in _chunks(combined):
            await message.reply_text(part, disable_web_page_preview=True)
    except TimeoutError as exc:
        await status.edit_text(f"⌛ {exc} Please try again later.")
    except RuntimeError as exc:
        await status.edit_text(str(exc))
    except Exception as exc:
        logger.exception("History lookup failed")
        await status.edit_text(
            f"History lookup failed ({type(exc).__name__}). If you used a display name, the source may not support name searches. Try a numeric ID or @username."
        )
