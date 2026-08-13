from datetime import datetime, timezone
from telegram import ChatPermissions
from database.mongo import add_violation, log_event
from config import LOGGER_CHAT_ID


def mute_duration_for_violation(count: int) -> int:
    if count <= 1: return 30
    if count == 2: return 60
    if count == 3: return 120
    if count == 4: return 360
    return 1440

async def delete_message(message):
    try:
        await message.delete(); return True
    except Exception: return False

async def mute_user(message, minutes):
    try:
        until = datetime.now(timezone.utc).timestamp() + minutes * 60
        await message.chat.restrict_member(
            user_id=message.from_user.id,
            permissions=ChatPermissions.no_permissions(),
            until_date=int(until),
        )
        return True
    except Exception: return False

async def punish(message, reason, settings):
    count = await add_violation(message.chat.id, message.from_user.id, reason)
    deleted = await delete_message(message)
    minutes = mute_duration_for_violation(count)
    muted = await mute_user(message, minutes)
    action = f"delete + mute {minutes}m"
    event = {
        "created_at": datetime.now(timezone.utc), "chat_id": message.chat.id,
        "user_id": message.from_user.id, "username": message.from_user.username,
        "reason": reason, "violations": count, "deleted": deleted,
        "muted": muted, "mute_minutes": minutes, "action": action,
    }
    await log_event(event)
    # Optional logger group. The bot must be a member/admin there.
    if LOGGER_CHAT_ID:
        try:
            name = message.from_user.full_name.replace("<", "&lt;").replace(">", "&gt;")
            await message.get_bot().send_message(
                LOGGER_CHAT_ID,
                f"🛡️ <b>AntiSpam Log</b>\nGroup: <code>{message.chat.id}</code>\n"
                f"User: <b>{name}</b> (<code>{message.from_user.id}</code>)\n"
                f"Reason: <b>{reason}</b>\nViolations: <b>{count}</b>\n"
                f"Action: <b>{action}</b>\nDeleted: {deleted} | Muted: {muted}",
                parse_mode="HTML",
            )
        except Exception:
            pass
    return count, action, deleted, muted
