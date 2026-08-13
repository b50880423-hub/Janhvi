from telegram import InlineKeyboardButton, InlineKeyboardMarkup

def settings_keyboard(s):
    rows = [
        [InlineKeyboardButton(f"🛡️ Protection: {'ON' if s['enabled'] else 'OFF'}", callback_data="as:toggle:enabled")],
        [InlineKeyboardButton(f"🔗 Links: {'ON' if s['antilink'] else 'OFF'}", callback_data="as:toggle:antilink"),
         InlineKeyboardButton(f"🎨 Stickers: {'ON' if s['antisticker'] else 'OFF'}", callback_data="as:toggle:antisticker")],
        [InlineKeyboardButton(f"🖼️ Photos: {'ON' if s['antiphoto'] else 'OFF'}", callback_data="as:toggle:antiphoto"),
         InlineKeyboardButton(f"🎥 Videos: {'ON' if s['antivideo'] else 'OFF'}", callback_data="as:toggle:antivideo")],
        [InlineKeyboardButton(f"📎 Documents: {'ON' if s['antidocument'] else 'OFF'}", callback_data="as:toggle:antidocument"),
         InlineKeyboardButton(f"↪️ Forwards: {'ON' if s['antiforward'] else 'OFF'}", callback_data="as:toggle:antiforward")],
        [InlineKeyboardButton(f"💬 Flood: {'ON' if s['antiflood'] else 'OFF'}", callback_data="as:toggle:antiflood"),
         InlineKeyboardButton(f"♻️ Duplicate: {'ON' if s['antiduplicate'] else 'OFF'}", callback_data="as:toggle:antiduplicate")],
        [InlineKeyboardButton(f"📣 Mentions: {'ON' if s['antimention'] else 'OFF'}", callback_data="as:toggle:antimention"),
         InlineKeyboardButton(f"🤬 Bad words: {'ON' if s['badwords'] else 'OFF'}", callback_data="as:toggle:badwords")],
        [InlineKeyboardButton("⚙️ Presets", callback_data="as:presets"),
         InlineKeyboardButton("🔄 Refresh", callback_data="as:refresh")]
    ]
    return InlineKeyboardMarkup(rows)
