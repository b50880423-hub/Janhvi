from datetime import datetime, timezone
from telegram.constants import ChatType
from database.mongo import get_group, get_user, upsert_user
from config import DEFAULT_SETTINGS
from services.spam_detector import detector, has_link, has_badword, mention_count
from services.moderation import punish
from services.intelligence import behavior_risk, record_group_activity
from services.sticker_guard import check_sticker_flood
from services.link_intelligence import domain_risk
from services.nsfw_guard import media_requires_review, classify_media
from utils.permissions import is_admin

async def moderate_message(update, context):
    message = update.effective_message
    if not message or not message.chat or message.chat.type not in (ChatType.GROUP, ChatType.SUPERGROUP): return
    if not message.from_user or message.from_user.is_bot: return
    now = datetime.now(timezone.utc).timestamp()
    existing = await get_user(message.chat.id, message.from_user.id) or {}
    await upsert_user(message.chat.id, message.from_user.id, {
        "username": message.from_user.username, "full_name": message.from_user.full_name,
        "message_count": int(existing.get("message_count", 0))+1,
        "first_seen": existing.get("first_seen") or datetime.now(timezone.utc), "last_seen": datetime.now(timezone.utc),
        "reputation": min(100, int(existing.get("reputation", 0)) + (1 if int(existing.get("message_count",0)) % 20 == 19 else 0)),
    })
    if await is_admin(context.bot, message.chat.id, message.from_user.id): return
    user = await get_user(message.chat.id, message.from_user.id)
    if user and user.get("whitelisted"): return
    s = await get_group(message.chat.id, DEFAULT_SETTINGS)
    if not s.get("enabled", True): return
    group_rate = record_group_activity(message.chat.id, now)
    if user and user.get("blacklisted"):
        await punish(message,"blacklisted user",s); return
    text = message.text or message.caption or ""
    custom = s.get("custom_filters", [])
    reason=None; extra=0
    # Lockdown is deliberately targeted at risky new members/content rather than silencing everyone.
    if s.get("lockdown") and int(existing.get("message_count",0)) < 10 and (has_link(message) or message.sticker): reason="lockdown violation"
    elif s.get("antilink") and has_link(message):
        dr,_=domain_risk(text,s.get('domain_whitelist',[]),s.get('domain_blacklist',[])); extra+=dr; reason="link spam"
    elif message.sticker:
        flood, repeated, key = check_sticker_flood(message.chat.id,message.from_user.id,message.sticker,now,int(s.get("sticker_limit",6)),int(s.get("sticker_window_seconds",12)))
        set_name = getattr(message.sticker,"set_name",None)
        if s.get("nsfw_sticker_protection",True) and (key in set(s.get("nsfw_sticker_ids",[])) or (set_name and set_name in set(s.get("blocked_sticker_sets",[])))): reason="blocked/NSFW sticker"
        elif flood or repeated: reason="repeated sticker spam" if repeated else "sticker spam"
        elif s.get("antisticker"): reason="sticker spam"
    elif message.photo or message.video or message.animation:
        result=await classify_media(message)
        if result.get("label")=="nsfw": reason="high-confidence NSFW media"; extra=35
        elif result.get("label")=="suspicious": reason="suspicious media"; extra=15
        elif media_requires_review(message,s,user): reason="new-member risky media"
    elif s.get("antiphoto") and message.photo: reason="photo spam"
    elif s.get("antivideo") and message.video: reason="video spam"
    elif s.get("antigif") and message.animation: reason="GIF spam"
    elif s.get("antidocument") and message.document: reason="document spam"
    elif s.get("antiforward") and (message.forward_origin or getattr(message,"is_automatic_forward",False)): reason="forward spam"
    elif s.get("antimention") and mention_count(message)>int(s.get("max_mentions",8)): reason="mention spam"
    elif s.get("badwords") and has_badword(message,custom): reason="prohibited content"
    elif s.get("antiflood") and detector.check_flood(message.chat.id,message.from_user.id,now,int(s.get("max_messages",8)),int(s.get("window_seconds",10))): reason="message flood"
    elif s.get("antiduplicate") and detector.check_duplicate(message.chat.id,message.from_user.id,text,now,int(s.get("max_duplicate",4))): reason="duplicate message spam"
    else:
        extra = behavior_risk(message.chat.id,message.from_user.id,text,now) if s.get("similarity_enabled",True) else 0
        if extra >= 8: reason="similarity spam"
    if reason:
        # In very busy groups, reduce sensitivity slightly to avoid false positives.
        if s.get("adaptive_baseline",True) and group_rate > 100 and reason in ("message flood","duplicate message spam"): extra=max(0,extra-2)
        await punish(message,reason,s,extra_risk=extra)

async def monitor_member(update, context):
    cm=update.chat_member
    if not cm or not cm.new_chat_member: return
    old=str(cm.old_chat_member.status); new=str(cm.new_chat_member.status)
    if new not in ('member','restricted') or old in ('member','restricted','administrator','owner','creator'): return
    s=await get_group(cm.chat.id,DEFAULT_SETTINGS)
    if not s.get('anti_raid',True): return
    from services.anti_raid import join_risk
    now=datetime.now(timezone.utc).timestamp(); hit,count=join_risk(cm.chat.id,now,int(s.get('raid_join_threshold',8)),int(s.get('raid_window_seconds',60)))
    if hit:
        await update_group(cm.chat.id,{'threat_level':'HIGH ALERT','lockdown':bool(s.get('auto_raid_lockdown',True))})
        if count==int(s.get('raid_join_threshold',8)):
            try: await context.bot.send_message(cm.chat.id,'🚨 <b>Raid protection activated</b>\nRapid joins detected. Targeted new-member protection is now active.',parse_mode='HTML')
            except Exception:pass
