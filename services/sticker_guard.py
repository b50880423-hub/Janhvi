from collections import defaultdict, deque
_recent=defaultdict(deque)

def sticker_key(sticker):
    return getattr(sticker,'file_unique_id',None) or getattr(sticker,'file_id',None)

def check_sticker_flood(chat_id,user_id,sticker,now,limit=5,window=12):
    q=_recent[(chat_id,user_id)]
    while q and now-q[0][0]>window: q.popleft()
    key=sticker_key(sticker)
    same=sum(1 for _,k in q if k==key)
    q.append((now,key))
    return (len(q)>=limit, same>=max(2,limit//2), key)
