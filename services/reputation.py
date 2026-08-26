def member_level(messages, reputation, trusted=False):
    if trusted: return '🛡️ VERIFIED'
    if messages >= 1000 or reputation >= 85: return '👑 VETERAN'
    if messages >= 200 or reputation >= 60: return '⭐ TRUSTED'
    if messages >= 30: return '💬 REGULAR'
    return '🌱 NEW MEMBER'

def next_reputation(current, message_count, violation=False):
    current=int(current or 0)
    if violation: return max(0,current-5)
    if message_count and message_count % 25 == 0: return min(100,current+1)
    return current
