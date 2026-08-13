import re
from collections import defaultdict, deque

URL_RE = re.compile(r"(https?://|www\.|t\.me/|telegram\.me/|discord\.gg/)", re.I)
# Built-in protection words. Group admins can add their own group-specific words in MongoDB.
BUILTIN_BADWORDS = {"porn", "xxx", "fuck", "nude", "sex"}
BADWORDS = BUILTIN_BADWORDS

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

def normalize_filter(value):
    return " ".join((value or "").strip().lower().split())

def has_badword(message, custom_filters=None):
    """Check built-in words plus filters belonging ONLY to this chat/group.

    Matching is case-insensitive. Single words use word boundaries; phrases are
    matched as normalized phrases. This avoids matching e.g. 'sex' inside 'sexton'.
    """
    text = normalize_filter(message.text or message.caption or "")
    if not text:
        return False

    for raw in (custom_filters or []):
        word = normalize_filter(raw)
        if not word:
            continue
        if " " in word:
            if word in text:
                return True
        else:
            if re.search(r"(?<!\w)" + re.escape(word) + r"(?!\w)", text, re.I):
                return True

    for word in BUILTIN_BADWORDS:
        if re.search(r"(?<!\w)" + re.escape(word) + r"(?!\w)", text, re.I):
            return True
    return False

def mention_count(message):
    text = message.text or message.caption or ""
    return len(re.findall(r"@\w+", text)) + len(re.findall(r"https?://t\.me/", text, re.I))
