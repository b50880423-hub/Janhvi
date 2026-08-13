from datetime import datetime, timezone
from telegram import ChatPermissions
from database.mongo import add_violation, log_event

def mute_duration_for_violation(count: int) -> int:
    # minutes: 1st=30m, 2nd=1h, 3rd=2h, 4th=6h, 5th and every later violation=24h
    if count <= 1:
        return 30
    if count == 2:
        return 60
    if count == 3:
        return 120
    if count == 4:
        return 360
    return 1440  # 24 hours for 5th, 6th, 7th... forever

async def delete_message(message):
    try:
        await message.delete()
        return True
    except Exception:
        return False

async def mute_user(message, minutes):
    try:
        until = datetime.now(timezone.utc).timestamp() + minutes * 60
        await message.chat.restrict_member(
            user_id=message.from_user.id,
            permissions=ChatPermissions(
                can_send_messages=False,
                can_send_audios=False,
                can_send_documents=False,
                can_send_photos=False,
                can_send_videos=False,
                can_send_video_notes=False,
                can_send_voice_notes=False,
                can_send_polls=False,
                can_send_other_messages=False,
                can_add_web_page_previews=False,
                can_change_info=False,
                can_invite_users=False,
                can_pin_messages=False,
                can_manage_topics=False,
            ),
            until_date=int(until),
        )
        return True
    except Exception:
        return False

async def punish(message, reason, settings):
    # Automatic moderation is DELETE + MUTE only. Never automatically ban.
    count = await add_violation(message.chat.id, message.from_user.id, reason)
    deleted = await delete_message(message)
    minutes = mute_duration_for_violation(count)
    muted = await mute_user(message, minutes)

    action = f"delete + mute {minutes}m"
    await log_event({
        "created_at": datetime.now(timezone.utc),
        "chat_id": message.chat.id,
        "user_id": message.from_user.id,
        "username": message.from_user.username,
        "reason": reason,
        "violations": count,
        "deleted": deleted,
        "muted": muted,
        "mute_minutes": minutes,
        "action": action,
    })
    return count, action, deleted, muted
