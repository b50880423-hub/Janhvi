import re
import time
from collections import defaultdict, deque

URL_RE = re.compile(r"(https?://|www\.|t\.me/|telegram\.me/|discord\.gg/)", re.I)
BADWORDS = {"porn", "xxx", "fuck", "nude", "sex"}

class MemoryDetector:
    def __init__(self):
        self.messages = defaultdict(deque)
        self.duplicates = defaultdict(deque)

    def check_flood(self, chat_id, user_id, now, max_messages, window):
        key = (chat_id, user_id)
        q = self.messages[key]
        q.append(now)
        while q and now - q[0] > window:
            q.popleft()
        return len(q) > max_messages

    def check_duplicate(self, chat_id, user_id, text, now, max_duplicate):
        if not text:
            return False
        key = (chat_id, user_id)
        q = self.duplicates[key]
        normalized = " ".join(text.lower().split())
        q.append((now, normalized))
        while q and now - q[0][0] > 60:
            q.popleft()
        return sum(x[1] == normalized for x in q) >= max_duplicate

    def clear_user(self, chat_id, user_id):
        self.messages.pop((chat_id, user_id), None)
        self.duplicates.pop((chat_id, user_id), None)

detector = MemoryDetector()

def has_link(message):
    text = message.text or message.caption or ""
    return bool(URL_RE.search(text))

def has_badword(message):
    text = (message.text or message.caption or "").lower()
    return any(w in text for w in BADWORDS)

def mention_count(message):
    text = message.text or message.caption or ""
    return len(re.findall(r"@\w+", text)) + len(re.findall(r"https?://t\.me/", text, re.I))
