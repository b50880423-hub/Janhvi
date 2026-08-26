from collections import defaultdict, deque
_join_windows=defaultdict(deque)

def record_join(chat_id, now, window=60):
    q=_join_windows[chat_id]
    q.append(now)
    while q and now-q[0] > window: q.popleft()
    return len(q)
