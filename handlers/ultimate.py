"""Janhvi Ultimate convenience and administration commands.
Keeps the core moderation handlers small while providing a cleaner, Rose-style UX.
"""
from html import escape
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from config import DEFAULT_SETTINGS
from database.mongo import get_group, update_group, log_event
from utils.permissions import is_admin
from handlers.admin import LOCK_MAP
from handlers.rose import clear_note, command_list

async def _admin(update):
    return bool(update.effective_chat and update.effective_user and await is_admin(update.get_bot(), update.effective_chat.id, update.effective_user.id))

async def _deny(update):
    await update.effective_message.reply_text("❌ This command is available to group administrators only.")

async def filters_list(update, context):
    if not update.effective_chat:
        return
    s = await get_group(update.effective_chat.id, DEFAULT_SETTINGS)
    words = list(s.get("custom_filters", []))
    if not words:
        return await update.effective_message.reply_text("🧹 <b>Filters</b>\n\nNo custom filters are configured.", parse_mode="HTML")
    text = "🧹 <b>Group Filters</b>\n\n" + "\n".join(f"{i}. <code>{escape(str(w))}</code>" for i, w in enumerate(words, 1))
    await update.effective_message.reply_text(text, parse_mode="HTML")

async def stop_filter(update, context):
    """Rose-style /stop keyword alias for /filter remove."""
    if not await _admin(update):
        return await _deny(update)
    if not context.args:
        return await update.effective_message.reply_text("Usage: /stop <word or phrase>")
    word = " ".join(context.args).strip().lower()
    s = await get_group(update.effective_chat.id, DEFAULT_SETTINGS)
    words = [str(x) for x in s.get("custom_filters", []) if str(x).lower() != word]
    if len(words) == len(s.get("custom_filters", [])):
        return await update.effective_message.reply_text("❌ That filter was not found.")
    await update_group(update.effective_chat.id, {"custom_filters": words})
    await update.effective_message.reply_text(f"🗑️ Filter removed: <code>{escape(word)}</code>", parse_mode="HTML")

async def stop_all_filters(update, context):
    if not await _admin(update):
        return await _deny(update)
    await update_group(update.effective_chat.id, {"custom_filters": [], "badwords": False})
    await update.effective_message.reply_text("🧹 All custom filters were removed and the filter engine is OFF.")

async def lock_status(update, context):
    if not update.effective_chat:
        return
    s = await get_group(update.effective_chat.id, DEFAULT_SETTINGS)
    labels = []
    seen = set()
    for label, key in LOCK_MAP.items():
        if label in seen or key in seen:
            continue
        seen.add(label); seen.add(key)
        labels.append(f"• {'🔒' if s.get(key, False) else '🔓'} {label.title()}")
    await update.effective_message.reply_text("🔐 <b>Content Locks</b>\n\n" + "\n".join(labels), parse_mode="HTML")

async def set_rules(update, context):
    if not await _admin(update):
        return await _deny(update)
    text = " ".join(context.args).strip()
    if not text and update.effective_message.reply_to_message:
        text = update.effective_message.reply_to_message.text_html or update.effective_message.reply_to_message.caption_html or ""
    if not text:
        return await update.effective_message.reply_text("Usage: reply to a rules message with /setrules, or use /setrules <text>.")
    await update_group(update.effective_chat.id, {"rules_text": text})
    await log_event({"chat_id": update.effective_chat.id, "type": "rules_update", "admin_id": update.effective_user.id})
    await update.effective_message.reply_text("✅ Group rules updated. Members can view them with /rules.")

async def unset_rules(update, context):
    if not await _admin(update):
        return await _deny(update)
    await update_group(update.effective_chat.id, {"rules_text": ""})
    await update.effective_message.reply_text("🗑️ Group rules cleared.")

async def janhvi_panel(update, context):
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("👮 Moderation", callback_data="rules:moderation"), InlineKeyboardButton("🔒 Locks", callback_data="rules:lockdown")],
        [InlineKeyboardButton("🧹 Filters", callback_data="rules:security"), InlineKeyboardButton("📝 Notes", callback_data="rules:other")],
        [InlineKeyboardButton("🚨 Security", callback_data="rules:security"), InlineKeyboardButton("⚙️ Admin", callback_data="rules:admin")],
    ])
    await update.effective_message.reply_text(
        "🌸 <b>JANHVI</b>\n\nYour advanced Telegram group management assistant.\n\nChoose a category below to explore commands.",
        parse_mode="HTML", reply_markup=kb
    )
