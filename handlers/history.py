import logging
import re

from telegram import Update
from telegram.ext import ContextTypes

from config import TELEGRAM_API_ID, TELEGRAM_API_HASH, TELEGRAM_USER_SESSION, HISTORY_SOURCE_BOT, BOT_OWNER_IDS
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
    requester = update.effective_user
    if not requester or requester.id not in BOT_OWNER_IDS:
        await message.reply_text("❌ This command is restricted to the configured bot owner(s).")
        return

    if not context.args:
        await message.reply_text(
            "Usage: /history USER_ID\nExample: /history 6446674912\n\n"
            "This asks the configured history source directly. It does not collect profile changes."
        )
        return
    target = context.args[0].strip()
    if not re.fullmatch(r"\d{4,20}", target):
        await message.reply_text("Please provide a numeric Telegram user ID. Example: /history 6446674912")
        return
    if not (TELEGRAM_API_ID and TELEGRAM_API_HASH and TELEGRAM_USER_SESSION):
        await message.reply_text(
            "History lookup is not configured yet. The bot needs a separately authenticated Telegram user session.\n\n"
            "Set TELEGRAM_API_ID, TELEGRAM_API_HASH, and TELEGRAM_USER_SESSION in your deployment settings, then restart the bot."
        )
        return
    status = await message.reply_text(f"🔎 Looking up Telegram ID {target}…")
    try:
        results = await fetch_history(target)
        if not results:
            await status.edit_text("The history source returned no text results for this ID.")
            return
        await status.delete()
        combined = f"📜 Telegram history for {target}\nSource: @{HISTORY_SOURCE_BOT.lstrip('@')}\n\n" + "\n\n".join(results)
        for part in _chunks(combined):
            await message.reply_text(part, disable_web_page_preview=True)
    except TimeoutError as exc:
        await status.edit_text(f"⌛ {exc} Please try again later.")
    except RuntimeError as exc:
        await status.edit_text(str(exc))
    except Exception as exc:
        logger.exception("History lookup failed")
        await status.edit_text(f"History lookup failed ({type(exc).__name__}). Check the bot logs and history-source availability.")
