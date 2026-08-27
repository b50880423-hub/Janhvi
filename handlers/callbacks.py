from database.mongo import get_group, update_group, save_mute_record
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

async def security_callback(update, context):
    q=update.callback_query; await q.answer()
    if not q.message or not await is_admin(context.bot,q.message.chat.id,q.from_user.id):
        return await q.answer('Admins only.',show_alert=True)
    data=q.data.split(':',1)[1]; s=await get_group(q.message.chat.id,DEFAULT_SETTINGS)
    if data=='mode':
        modes=['adaptive','community','strict','gaming','announcement']; new=modes[(modes.index(s.get('mode','adaptive'))+1)%len(modes)]
        await update_group(q.message.chat.id,{'mode':new})
    else: await update_group(q.message.chat.id,{data:not bool(s.get(data,False))})
    await q.answer('Updated. Open /security to refresh.')

async def review_callback(update, context):
    from telegram import ChatPermissions
    from database.mongo import get_group, upsert_user
    from services.review_queue import resolve_review
    from datetime import datetime, timezone
    q=update.callback_query; await q.answer()
    parts=q.data.split(':')
    if len(parts)!=3: return
    action, rid=parts[1], parts[2]
    if not await is_admin(context.bot, q.from_user.id if False else q.message.chat.id, q.from_user.id):
        return await q.answer('Admins only.', show_alert=True)
    doc=await resolve_review(rid,action,q.from_user.id)
    if not doc:return await q.answer('Already resolved or expired.',show_alert=True)
    chat_id=int(doc['chat_id']); user_id=int(doc['user_id'])
    try:
        if action=='mute5':
            until=int(datetime.now(timezone.utc).timestamp()+300)
            await context.bot.restrict_chat_member(chat_id,user_id,ChatPermissions.no_permissions(),until_date=until)
            await save_mute_record(chat_id, user_id, 5, doc.get('reason') or 'Admin review mute')
        elif action=='mute60':
            until=int(datetime.now(timezone.utc).timestamp()+3600)
            await context.bot.restrict_chat_member(chat_id,user_id,ChatPermissions.no_permissions(),until_date=until)
            await save_mute_record(chat_id, user_id, 60, doc.get('reason') or 'Admin review mute')
        elif action=='trust':
            await upsert_user(chat_id,user_id,{'trusted':True})
        if action=='ban':
            await context.bot.ban_chat_member(chat_id,user_id)
        label={'delete':'Deleted','ignore':'Ignored','trust':'Trusted','mute5':'Muted 5m','mute60':'Muted 60m','ban':'Banned'}.get(action,action)
        await q.edit_message_text(f'✅ Review resolved: <b>{label}</b>\nUser ID: <code>{user_id}</code>\nReason: {doc.get("reason")}',parse_mode='HTML')
    except Exception as e:
        await q.answer(f'Action failed: {str(e)[:80]}',show_alert=True)

async def appeal_callback(update, context):
    from telegram import ChatPermissions
    from datetime import datetime, timezone, timedelta
    from database.mongo import resolve_appeal, upsert_user
    q=update.callback_query; await q.answer()
    parts=q.data.split(':')
    if len(parts)!=3: return
    action, aid=parts[1], parts[2]
    if not q.message or not await is_admin(context.bot, q.message.chat.id, q.from_user.id):
        return await q.answer('Admins only.',show_alert=True)
    doc=await resolve_appeal(aid,action,q.from_user.id)
    if not doc: return await q.answer('Already resolved.',show_alert=True)
    chat_id=int(doc['chat_id']); user_id=int(doc['user_id'])
    label={'unmute':'Unmuted','reduce':'Mute reduced','reject':'Appeal rejected','trust':'Trusted + unmuted'}.get(action,action)
    try:
        if action in ('unmute','trust'):
            await context.bot.restrict_chat_member(chat_id,user_id,ChatPermissions.all_permissions())
            if action=='trust': await upsert_user(chat_id,user_id,{'trusted':True})
        elif action=='reduce':
            until=datetime.now(timezone.utc)+timedelta(minutes=5)
            await context.bot.restrict_chat_member(chat_id,user_id,ChatPermissions.no_permissions(),until_date=until)
        await q.edit_message_reply_markup(reply_markup=None)
        await q.message.reply_text(f'📩 Appeal resolved: <b>{label}</b>\nUser ID: <code>{user_id}</code>',parse_mode='HTML')
        try:
            msg={'unmute':'✅ Your appeal was accepted. You have been unmuted.','reduce':'⏳ Your appeal was partly accepted. Your mute has been reduced.','reject':'❌ Your appeal was rejected by a group admin.','trust':'⭐ Your appeal was accepted. You have been trusted and unmuted.'}[action]
            await context.bot.send_message(user_id,msg)
        except Exception: pass
    except Exception as e:
        await q.answer(f'Action failed: {str(e)[:80]}',show_alert=True)
