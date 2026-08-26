"""Media safety gateway.
If NSFW_CLASSIFIER_URL is configured, media is downloaded from Telegram and sent to the
configured classifier. The endpoint should return JSON containing one of:
nsfw_score / score / unsafe_score (0..1 or 0..100), or label = safe|suspicious|nsfw.
Without a provider, the bot never pretends to visually classify nudity; it uses review.
"""
import os, aiohttp
from config import NSFW_CLASSIFIER_URL, NSFW_CLASSIFIER_API_KEY

async def classify_media(message):
    if not NSFW_CLASSIFIER_URL:
        return {"available": False, "label": "unknown", "score": None}
    try:
        media = message.photo[-1] if message.photo else (message.video or message.animation)
        if not media:
            return {"available": False, "label": "unknown", "score": None}
        tg_file = await message.get_bot().get_file(media.file_id)
        data = await tg_file.download_as_bytearray()
        headers = {"Authorization": f"Bearer {NSFW_CLASSIFIER_API_KEY}"} if NSFW_CLASSIFIER_API_KEY else {}
        form = aiohttp.FormData(); form.add_field("file", bytes(data), filename="telegram_media")
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=20)) as session:
            async with session.post(NSFW_CLASSIFIER_URL, data=form, headers=headers) as r:
                if r.status >= 400: return {"available": False, "label": "unknown", "score": None}
                payload = await r.json()
        raw = payload.get("nsfw_score", payload.get("unsafe_score", payload.get("score")))
        score = float(raw) if raw is not None else None
        if score is not None and score > 1: score /= 100.0
        label = str(payload.get("label", "")).lower()
        if score is not None:
            label = "nsfw" if score >= .85 else "suspicious" if score >= .55 else "safe"
        if label not in ("safe", "suspicious", "nsfw"): label="unknown"
        return {"available": True, "label": label, "score": score}
    except Exception:
        return {"available": False, "label": "unknown", "score": None}

def media_requires_review(message, settings, user):
    new = int((user or {}).get("message_count", 0)) < int(settings.get("new_member_message_limit", 10))
    return bool(new and (message.photo or message.video or message.animation))
