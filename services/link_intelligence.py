import re
from urllib.parse import urlparse
URL=re.compile(r'https?://[^\s]+|t\.me/[^\s]+',re.I)

def domains(text):
    out=[]
    for raw in URL.findall(text or ''):
        u=raw if '://' in raw else 'https://'+raw
        d=urlparse(u).netloc.lower().split(':')[0]
        if d: out.append(d)
    return out

def domain_risk(text, whitelist=(), blacklist=()):
    ds=domains(text); extra=0
    for d in ds:
        if d in blacklist: return 50,d
        if d not in whitelist: extra+=4
    return min(20,extra), (ds[0] if ds else None)
