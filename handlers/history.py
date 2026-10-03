from html import escape

from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ChatType


HISTORY_BOT_URL = "https://t.me/SangMataInfo_bot"


async def history_lookup(update, context):
    """Explain how to query an external Telegram name-history source.

    Telegram itself does not expose a historical-name API, and Telegram bots
    cannot directly query another bot's private database. This command provides
    a transparent handoff to a third-party history bot without collecting users'
    profile changes locally.
    """
    message = update.effective_message
    if not message:
        return

    target_id = None
    target_label = None

    if message.reply_to_message and message.reply_to_message.from_user:
        target = message.reply_to_message.from_user
        target_id = target.id
        target_label = target.full_name
    elif context.args:
        raw = context.args[0].strip()
        if raw.isdigit():
            target_id = int(raw)
            target_label = f"Telegram ID {target_id}"
        else:
            await message.reply_text(
                "Please use a numeric Telegram user ID, or reply to that user's message with /history.\n\n"
                "A username alone may not resolve to the correct account if it has changed."
            )
            return
    else:
        await message.reply_text(
            "🔎 <b>Telegram Name History</b>\n\n"
            "Telegram does not provide an official API for retrieving a user's complete past names or usernames. "
            "This bot does not collect profile changes locally.\n\n"
            "To check records an external history service may have observed, use /history USER_ID, "
            "or reply to a user's message with /history. Then open the history bot below and submit the numeric ID.\n\n"
            "⚠️ Results depend on what that service previously recorded; missing changes cannot be recovered automatically.",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Open history source", url=HISTORY_BOT_URL)]]),
        )
        return

    await message.reply_text(
        f"🔎 <b>History lookup prepared</b>\n\n"
        f"Target: <code>{target_id}</code>\n"
        f"Name: {escape(target_label or 'Unknown')}\n\n"
        "Open the external history source and send it this numeric ID. If records exist, it may show previously observed names and usernames. "
        "This bot cannot fetch that service's private results automatically because no public lookup API was identified.\n\n"
        "⚠️ History may be incomplete and is not an official Telegram record.",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("Open history source", url=HISTORY_BOT_URL)],
        ]),
    )
