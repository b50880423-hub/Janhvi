from datetime import datetime
from telegram.constants import ChatType
from database.mongo import get_group, get_user, upsert_user
from config import DEFAULT_SETTINGS
from services.spam_detector import detector, has_link, has_badword, mention_count
from services.moderation import punish
from utils.permissions import is_admin

async def moderate_message(update, context):
    message = update.effective_message
    if not message or not message.chat or message.chat.type not in (ChatType.GROUP, ChatType.SUPERGROUP): return
    if not message.from_user or message.from_user.is_bot: return
    if await is_admin(context.bot, message.chat.id, message.from_user.id): return

    user = await get_user(message.chat.id, message.from_user.id)
    if user and user.get("whitelisted"): return

    s = await get_group(message.chat.id, DEFAULT_SETTINGS)
    if not s.get("enabled", True): return

    if user and user.get("blacklisted"):
        await punish(message, "blacklisted user", s); return

    reason = None
    text = message.text or message.caption or ""
    now = datetime.utcnow().timestamp()
    custom = s.get("custom_filters", [])

    if s.get("antilink") and has_link(message): reason = "link spam"
    elif s.get("antisticker") and message.sticker: reason = "sticker spam"
    elif s.get("antiphoto") and message.photo: reason = "photo spam"
    elif s.get("antivideo") and message.video: reason = "video spam"
    elif s.get("antigif") and message.animation: reason = "GIF spam"
    elif s.get("antidocument") and message.document: reason = "document spam"
    elif s.get("antiforward") and (message.forward_origin or getattr(message, "is_automatic_forward", False)): reason = "forward spam"
    elif s.get("antimention") and mention_count(message) > int(s.get("max_mentions", 6)): reason = "mention spam"
    elif s.get("badwords") and has_badword(message, custom): reason = "prohibited content"
    elif s.get("antiflood") and detector.check_flood(message.chat.id, message.from_user.id, now, int(s.get("max_messages", 6)), int(s.get("window_seconds", 8))): reason = "message flood"
    elif s.get("antiduplicate") and detector.check_duplicate(message.chat.id, message.from_user.id, text, now, int(s.get("max_duplicate", 3))): reason = "duplicate message spam"

    if reason:
        await punish(message, reason, s)
