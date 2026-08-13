"""
Real optional visual moderation.

When SIGHTENGINE_API_USER and SIGHTENGINE_API_SECRET are configured, Telegram
media is downloaded temporarily and uploaded directly to Sightengine's image
moderation API. Sightengine's current nudity-2.1 model returns classes such as
sexual_activity, sexual_display and erotica.

If credentials are absent, the bot falls back to caption/URL keyword checks
and does not pretend it can visually classify the media.
"""

import asyncio
import os
import re
import tempfile
from pathlib import Path

import requests

from config import SIGHTENGINE_API_USER, SIGHTENGINE_API_SECRET, SIGHTENGINE_MODEL

EXPLICIT_TERMS = {
    "porn", "porno", "pornhub", "xxx", "nsfw", "nude", "nudes",
    "nudity", "sex", "sexual", "sexvideo", "adult", "hentai",
}
EXPLICIT_CLASSES = {
    "sexual_activity",
    "sexual_display",
    "erotica",
    "very_suggestive",
    "suggestive",
}
URL_RE = re.compile(r"(https?://|www\.|t\.me/|telegram\.me/)", re.I)

def explicit_text(text: str, terms=None):
    if not text:
        return None
    low = text.lower()
    for term in terms or EXPLICIT_TERMS:
        if term in low:
            return f"explicit keyword: {term}"
    return None

def explicit_link(text: str):
    if not text:
        return None
    # Fast first-line protection for clearly adult domains/URL text.
    low = text.lower()
    adult_domains = (
        "pornhub", "xvideos", "xnxx", "xhamster", "redtube",
        "youporn", "spankbang", "brazzers", "onlyfans",
    )
    if URL_RE.search(low):
        for domain in adult_domains:
            if domain in low:
                return f"explicit adult link: {domain}"
    return None

def media_object(message):
    if message.photo:
        return message.photo[-1]
    if message.sticker:
        return message.sticker
    if message.animation:
        return message.animation
    if message.video:
        return message.video
    # Telegram video notes can be moderated as video files.
    if message.video_note:
        return message.video_note
    return None

def _score_result(data):
    nudity = data.get("nudity", {}) if isinstance(data, dict) else {}
    # nudity-2.1 can return class keys. Treat high-confidence explicit classes
    # as blocking. A conservative threshold reduces false positives.
    for cls in EXPLICIT_CLASSES:
        try:
            score = float(nudity.get(cls, 0) or 0)
        except (TypeError, ValueError):
            score = 0
        if score >= 0.80:
            return f"visual explicit content ({cls}, {score:.2f})"
    # Some API responses expose sexual_activity directly.
    try:
        if float(nudity.get("sexual_activity", 0) or 0) >= 0.65:
            return "visual explicit content (sexual_activity)"
    except (TypeError, ValueError):
        pass
    return None

def _request_file(path):
    with open(path, "rb") as fh:
        resp = requests.post(
            "https://api.sightengine.com/1.0/check.json",
            data={
                "models": SIGHTENGINE_MODEL,
                "api_user": SIGHTENGINE_API_USER,
                "api_secret": SIGHTENGINE_API_SECRET,
            },
            files={"media": fh},
            timeout=20,
        )
    resp.raise_for_status()
    return resp.json()

async def classify_media(message, context=None):
    """
    Returns a reason string or None.
    Requires Sightengine credentials for visual classification.
    """
    if not SIGHTENGINE_API_USER or not SIGHTENGINE_API_SECRET:
        return None

    obj = media_object(message)
    if not obj:
        return None

    tmp = None
    try:
        # telegram.ext.ExtBot can download any Telegram File object.
        tg_file = await message.get_bot().get_file(obj.file_id)
        with tempfile.NamedTemporaryFile(delete=False, suffix=".bin") as f:
            tmp = f.name
        await tg_file.download_to_drive(tmp)
        data = await asyncio.to_thread(_request_file, tmp)
        return _score_result(data)
    except Exception:
        # A moderation provider outage must not crash the bot.
        return None
    finally:
        if tmp:
            try:
                Path(tmp).unlink(missing_ok=True)
            except Exception:
                pass
