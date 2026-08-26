import re
from collections import defaultdict, deque

_windows = defaultdict(lambda: deque(maxlen=30))
_group_rates = defaultdict(lambda: deque(maxlen=200))

def normalize(text: str) -> str:
    text = (text or '').lower()
    text = re.sub(r'https?://\S+', '<link>', text)
    text = re.sub(r'[^\w\s<link>]', ' ', text)
    return ' '.join(text.split())

def similarity(a: str, b: str) -> float:
    a, b = normalize(a), normalize(b)
    if not a or not b: return 0.0
    sa, sb = set(a.split()), set(b.split())
    return len(sa & sb) / max(1, len(sa | sb))

def behavior_risk(chat_id, user_id, text, now):
    key=(chat_id,user_id); q=_windows[key]
    while q and now-q[0][0] > 60: q.popleft()
    extra=0
    n=normalize(text)
    if n:
        similar=sum(1 for _,old in q if similarity(n,old)>=0.82)
        if similar>=2: extra += min(20, 4*similar)
    q.append((now,n))
    return extra

def record_group_activity(chat_id, now):
    q=_group_rates[chat_id]
    q.append(now)
    while q and now-q[0] > 60: q.popleft()
    return len(q)
