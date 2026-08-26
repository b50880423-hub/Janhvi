from datetime import datetime, timezone
from telegram import ChatPermissions
from database.mongo import add_violation, log_event, get_user, upsert_user
from config import LOGGER_CHAT_ID
from services.risk_engine import calculate, action_for
from services.threat_engine import record as record_threat
from services.review_queue import add_review
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

async def delete_message(message):
    try: await message.delete(); return True
    except Exception: return False

async def mute_user(message, minutes):
    try:
        until=datetime.now(timezone.utc).timestamp()+minutes*60
        await message.chat.restrict_member(message.from_user.id,ChatPermissions.no_permissions(),until_date=int(until)); return True
    except Exception:return False

async def punish(message, reason, settings, extra_risk=0):
    user=await get_user(message.chat.id,message.from_user.id) or {}
    trusted=bool(user.get('trusted') or user.get('whitelisted'))
    reputation=int(user.get('reputation',0))
    count=await add_violation(message.chat.id,message.from_user.id,reason,int(settings.get('violation_decay_hours',24)))
    score=calculate(reason,count,reputation,trusted,extra_risk)
    if reason=='blacklisted user':score=100
    action,minutes=action_for(score)
    if reason=='blocked/NSFW sticker':
        action,minutes=('mute',30 if count>=2 else 0)
        if count==1: action='warn'
    if not settings.get('smart_risk_enabled',True):
        action,minutes=('warn',0)
    deleted=await delete_message(message)
    queued=False
    if action=='review' and settings.get('review_queue_enabled',True):
        rid=await add_review({'chat_id':message.chat.id,'user_id':message.from_user.id,'username':message.from_user.username,'reason':reason,'risk_score':score})
        queued=True
        if rid:
            target=LOGGER_CHAT_ID or message.chat.id
            kb=InlineKeyboardMarkup([
                [InlineKeyboardButton('🗑 Delete',callback_data=f'rv:delete:{rid}'),InlineKeyboardButton('⚠️ Ignore',callback_data=f'rv:ignore:{rid}')],
                [InlineKeyboardButton('🔇 Mute 5m',callback_data=f'rv:mute5:{rid}'),InlineKeyboardButton('🔇 Mute 60m',callback_data=f'rv:mute60:{rid}')],
                [InlineKeyboardButton('⭐ Trust',callback_data=f'rv:trust:{rid}'),InlineKeyboardButton('🚫 Ban',callback_data=f'rv:ban:{rid}')],
            ])
            try:
                await message.get_bot().send_message(target,f'📋 <b>SMART MEDIA REVIEW</b>\nUser: {message.from_user.mention_html()}\nID: <code>{message.from_user.id}</code>\nReason: <b>{reason}</b>\nRisk: <b>{score}/100</b>',parse_mode='HTML',reply_markup=kb)
            except Exception: pass
        action='delete + admin review'
    muted=await mute_user(message,minutes) if action=='mute' and minutes else False
    if action=='mute': action=f'delete + mute {minutes}m'
    elif action=='warn': action='delete + warning'
    level,_=record_threat(message.chat.id,reason)
    await log_event({'created_at':datetime.now(timezone.utc),'chat_id':message.chat.id,'user_id':message.from_user.id,'username':message.from_user.username,'reason':reason,'violations':count,'risk_score':score,'deleted':deleted,'muted':muted,'mute_minutes':minutes,'action':action,'queued':queued,'threat_level':level,'extra_risk':extra_risk})
    await upsert_user(message.chat.id,message.from_user.id,{'reputation':max(0,reputation-5),'last_violation_at':datetime.now(timezone.utc)})
    if settings.get('notify_warnings',True) and not settings.get('silent_mode',False):
        try:
            if muted: text=f'🔇 {message.from_user.mention_html()} temporarily restricted for {minutes} minutes. Reason: {reason}.'
            elif queued: text=f'🛡️ {message.from_user.mention_html()}, your message was removed and sent for admin review.'
            else:text=f'⚠️ {message.from_user.mention_html()}, your message was removed. Please avoid repeating this behavior.'
            await message.chat.send_message(text,parse_mode='HTML')
        except Exception:pass
    if LOGGER_CHAT_ID:
        try: await message.get_bot().send_message(LOGGER_CHAT_ID,f'🛡️ <b>Premium V3</b>\nUser: <code>{message.from_user.id}</code>\nReason: <b>{reason}</b>\nRisk: <b>{score}/100</b>\nAction: <b>{action}</b>\nThreat: <b>{level}</b>',parse_mode='HTML')
        except Exception:pass
    return count,action,deleted,muted
