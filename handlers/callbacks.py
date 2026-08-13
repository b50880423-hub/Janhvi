from database.mongo import get_group, update_group
from config import DEFAULT_SETTINGS
from utils.keyboards import settings_keyboard
from utils.permissions import is_admin

async def settings_callback(update, context):
    q = update.callback_query
    await q.answer()
    if not q.message or not q.message.chat:
        return
    if not await is_admin(context.bot, q.message.chat.id, q.from_user.id):
        await q.answer("Admins only.", show_alert=True)
        return

    s = await get_group(q.message.chat.id, DEFAULT_SETTINGS)
    data = q.data.split(":")
    if len(data) >= 3 and data[1] == "toggle":
        key = data[2]
        s[key] = not bool(s.get(key, False))
        await update_group(q.message.chat.id, {key: s[key]})
    elif len(data) >= 2 and data[1] == "presets":
        await update_group(q.message.chat.id, DEFAULT_SETTINGS)
        s = await get_group(q.message.chat.id, DEFAULT_SETTINGS)

    s = await get_group(q.message.chat.id, DEFAULT_SETTINGS)
    try:
        await q.edit_message_reply_markup(reply_markup=settings_keyboard(s))
    except Exception:
        pass
