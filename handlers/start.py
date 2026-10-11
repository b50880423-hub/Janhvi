import html
from urllib.parse import quote
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ChatType
import database.mongo as mongo

async def start(update, context):
    # Deep links allow a shared whisper to be reopened in the bot DM. Telegram
    # strips inline keyboards when a message is natively forwarded, so share a
    # bot start-link that recreates the Open Whisper button for the recipient.
    if context.args and context.args[0].startswith("whisper_"):
        wid = context.args[0][8:]
        doc = await mongo.whispers.find_one({"whisper_id": wid, "status": "active"})
        if not doc:
            await update.effective_message.reply_text("⌛ This whisper is unavailable or has expired.")
            return
        # Keep whisper access restricted to the sender and intended recipient.
        viewer_id = update.effective_user.id if update.effective_user else 0
        if viewer_id not in (int(doc.get("sender_id", 0)), int(doc.get("recipient_id", 0))):
            target = "@" + doc["recipient_username"] if doc.get("recipient_username") else (doc.get("recipient_name") or "the intended recipient")
            await update.effective_message.reply_text(
                f"🔒 This whisper is private and is only for {html.escape(target)}."
            )
            return
        sender_label = "@" + doc["sender_username"] if doc.get("sender_username") else (doc.get("sender_name") or "Someone")
        recipient_label = "@" + doc["recipient_username"] if doc.get("recipient_username") else (doc.get("recipient_name") or "User")
        me = await context.bot.get_me()
        deep_link = f"https://t.me/{me.username}?start=whisper_{wid}"
        share_url = ("https://t.me/share/url?url=" + quote(deep_link, safe="")
                     + "&text=" + quote("🤫 A private whisper is waiting for you. Open it in Janhvi.", safe=""))
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔓 Open Whisper", callback_data=f"ws:open:{wid}")],
            [InlineKeyboardButton("📤 Forward / Share Whisper", url=share_url)],
            [InlineKeyboardButton("↩️ Whisper back", callback_data=f"ws:reply:{wid}")],
        ])
        await update.effective_message.reply_text(
            "🤫 <b>PRIVATE WHISPER</b>\n\n"
            f"👤 From: {html.escape(sender_label)}\n"
            f"🎯 To: {html.escape(recipient_label)}\n\n"
            "🔐 The whisper content stays hidden until you press Open Whisper.\n"
            f"🆔 <code>{html.escape(wid)}</code>",
            parse_mode="HTML", reply_markup=kb)
        return

    buttons = [[InlineKeyboardButton("➕ Add me to a group", url=f"https://t.me/{context.bot.username}?startgroup=true")],
               [InlineKeyboardButton("🤫 Whisper Help", callback_data="as:refresh")]]
    text = (
        "🛡️ <b>Advanced AntiSpam + Group Whisper Bot</b>\n\n"
        "I protect Telegram groups and provide protected group-to-user whispers.\n\n"
        "🤫 <b>Whisper:</b> use <code>/whisper @username message</code> or reply to a user's message with <code>/whisper message</code>.\n\n"
        "Add me to your group and make me an administrator."
    )
    await update.message.reply_text(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(buttons))
