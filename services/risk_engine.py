from dataclasses import dataclass

WEIGHTS={
 'message flood':16,'duplicate message spam':20,'similarity spam':22,'mention spam':12,
 'link spam':18,'forward spam':8,'prohibited content':18,'sticker spam':12,
 'repeated sticker spam':24,'blocked/NSFW sticker':42,'photo spam':8,'video spam':8,
 'GIF spam':8,'document spam':8,'blacklisted user':100,'lockdown violation':28,
 'new-member risky media':22,'raid pattern':35,
}

def level(score):
    if score < 30: return 'SAFE'
    if score < 51: return 'SUSPICIOUS'
    if score < 71: return 'HIGH_RISK'
    if score < 86: return 'SEVERE'
    return 'CRITICAL'

def calculate(reason, violations, reputation=0, trusted=False, extra=0):
    score=WEIGHTS.get(reason,12)+max(0,violations-1)*8+int(extra)
    if trusted and reason not in ('blacklisted user','blocked/NSFW sticker'): score-=12
    score-=min(20,max(0,int(reputation))//5)
    return max(0,min(100,score))

def action_for(score):
    if score < 51: return ('warn',0)
    if score < 71: return ('review',0)
    if score < 86: return ('mute',15)
    if score < 96: return ('mute',60)
    return ('mute',180)
