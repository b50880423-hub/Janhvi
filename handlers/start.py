from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ChatType

async def start(update, context):
    buttons = [[InlineKeyboardButton("➕ Add me to a group", url=f"https://t.me/{context.bot.username}?startgroup=true")],
               [InlineKeyboardButton("⚙️ Admin Settings", callback_data="as:refresh")]]
    text = (
        "🛡️ <b>Advanced AntiSpam Bot</b>\n\n"
        "I protect Telegram groups from spam, links, floods, repeated messages, "
        "media spam and other unwanted content.\n\n"
        "Add me to your group and make me an administrator."
    )
    await update.message.reply_text(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(buttons))
