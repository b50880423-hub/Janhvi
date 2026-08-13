from datetime import datetime, timezone
from telegram.constants import ChatMemberStatus, ParseMode
from telegram import ChatPermissions
from database.mongo import add_violation, log_event

async def delete_message(message):
    try:
        await message.delete()
        return True
    except Exception:
        return False

async def mute_user(message, minutes):
    until = datetime.now(timezone.utc).timestamp() + minutes * 60
    try:
        await message.chat.restrict_member(
            message.from_user.id,
            permissions=ChatPermissions.no_permissions(),
            until_date=int(until)
        )
        return True
    except Exception:
        return False

async def ban_user(message):
    try:
        await message.chat.ban_member(message.from_user.id)
        return True
    except Exception:
        return False

async def punish(message, reason, settings):
    count = await add_violation(message.chat.id, message.from_user.id, reason)
    await delete_message(message)

    warning_limit = int(settings.get("warning_limit", 3))
    ban_after = int(settings.get("ban_after_warnings", 6))
    mute_minutes = int(settings.get("mute_minutes", 30))

    action = "delete"
    if count >= ban_after:
        if await ban_user(message):
            action = "ban"
    elif count >= warning_limit:
        if await mute_user(message, mute_minutes):
            action = f"mute:{mute_minutes}m"

    await log_event({
        "created_at": datetime.now(timezone.utc),
        "chat_id": message.chat.id,
        "user_id": message.from_user.id,
        "username": message.from_user.username,
        "reason": reason,
        "violations": count,
        "action": action
    })
    return count, action
