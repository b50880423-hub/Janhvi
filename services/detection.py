import re
from collections import defaultdict, deque
from datetime import datetime, timezone

FLOOD = defaultdict(deque)
DUPES = defaultdict(deque)
STICKERS = defaultdict(deque)

URL_RE = re.compile(r"(https?://|www\.|t\.me/|telegram\.me/|tg://)", re.I)
MENTION_RE = re.compile(r"@\w+")

def _now():
    return datetime.now(timezone.utc).timestamp()

def detect(message, settings, filters):
    reasons = []
    text = message.text or message.caption or ""
    now = _now()
    key = (message.chat.id, message.from_user.id)

    # Sticker rate limit: allow up to 10 stickers in 10 seconds.
    # The 11th+ sticker is treated as sticker spam.
    if message.sticker and settings.get("stickers"):
        sq = STICKERS[key]
        sq.append(now)
        while sq and now - sq[0] > 10:
            sq.popleft()
        if len(sq) > 10:
            reasons.append("sticker spam (11+ in 10s)")

    # Flood
    if settings.get("flood"):
        q = FLOOD[key]
        q.append(now)
        while q and now - q[0] > settings.get("flood_window", 8):
            q.popleft()
        if len(q) >= settings.get("flood_limit", 6):
            reasons.append("message flood")

    # Duplicate
    if settings.get("duplicate") and text:
        q = DUPES[key]
        q.append((now, text.strip().lower()))
        while q and now - q[0][0] > 30:
            q.popleft()
        same = sum(1 for _, t in q if t == text.strip().lower())
        if same >= settings.get("duplicate_limit", 3):
            reasons.append("duplicate message")

    if settings.get("links") and URL_RE.search(text):
        reasons.append("link spam")
    if settings.get("mentions") and len(MENTION_RE.findall(text)) >= 6:
        reasons.append("mention spam")
    if settings.get("photos") and message.photo:
        reasons.append("photo")
    if settings.get("videos") and (message.video or message.video_note):
        reasons.append("video")
    if settings.get("gifs") and message.animation:
        reasons.append("GIF")
    if settings.get("documents") and message.document:
        reasons.append("document")
    if settings.get("forwards") and (message.forward_origin is not None):
        reasons.append("forward")

    low = text.lower()
    if settings.get("badwords"):
        for term in filters:
            if term and term in low:
                reasons.append(f"filtered term: {term}")
                break

    # Unique reasons only.
    return list(dict.fromkeys(reasons))
