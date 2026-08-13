from datetime import datetime, timezone, timedelta
from telegram import ChatPermissions
from telegram.error import TelegramError
from database.mongo import add_violation, add_event

def mute_minutes(count):
    if count < 4:
        return 0
    if count == 4:
        return 20
    if count == 5:
        return 60
    if count == 6:
        return 120
    if count == 7:
        return 360
    return 1440

async def delete_message(message):
    try:
        await message.delete()
        return True
    except TelegramError:
        return False

async def mute_user(message, minutes):
    try:
        until = datetime.now(timezone.utc) + timedelta(minutes=minutes)
        await message.chat.restrict_member(
            user_id=message.from_user.id,
            permissions=ChatPermissions(can_send_messages=False),
            until_date=until,
        )
        return True, ""
    except TelegramError as e:
        return False, str(e)

async def punish(message, reason, settings):
    count = add_violation(message.chat.id, message.from_user.id, reason,
                          message.from_user.username)
    deleted = await delete_message(message)
    minutes = mute_minutes(count)
    muted, mute_error = (False, "")
    if minutes:
        muted, mute_error = await mute_user(message, minutes)

    action = "delete + warning" if minutes == 0 else (
        f"delete + mute {minutes}m" if muted else f"delete + mute failed ({minutes}m)"
    )
    add_event({
        "created_at": datetime.now(timezone.utc),
        "chat_id": message.chat.id,
        "user_id": message.from_user.id,
        "username": message.from_user.username,
        "reason": reason,
        "violations": count,
        "deleted": deleted,
        "muted": muted,
        "mute_minutes": minutes,
        "mute_error": mute_error,
        "action": action,
    })
    return count, minutes, deleted, muted, mute_error
