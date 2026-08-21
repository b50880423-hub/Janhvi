from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ChatType

async def start(update, context):
    buttons = [[InlineKeyboardButton("➕ Add me to a group", url=f"https://t.me/{context.bot.username}?startgroup=true")],
               [InlineKeyboardButton("🤫 Whisper Help", callback_data="as:refresh")]]
    text = (
        "🛡️ <b>Advanced AntiSpam + Group Whisper Bot</b>\n\n"
        "I protect Telegram groups and provide protected group-to-user whispers.\n\n"
        "🤫 <b>Whisper:</b> use <code>/whisper @username message</code> or reply to a user's message with <code>/whisper message</code>.\n\n"
        "Add me to your group and make me an administrator."
    )
    await update.message.reply_text(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(buttons))
