from collections import defaultdict, deque
from datetime import datetime, timezone

_events=defaultdict(deque)

def record(chat_id, reason, now=None):
    now=now or datetime.now(timezone.utc).timestamp(); q=_events[chat_id]
    q.append((now,reason))
    while q and now-q[0][0]>120: q.popleft()
    n=len(q)
    if n>=30:return 'LOCKDOWN',n
    if n>=15:return 'ATTACK DETECTED',n
    if n>=8:return 'HIGH ALERT',n
    if n>=4:return 'ELEVATED',n
    return 'SAFE',n
