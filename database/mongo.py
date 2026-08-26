from motor.motor_asyncio import AsyncIOMotorClient
from config import MONGO_URI, MONGO_DB

client = None
db = None
groups = None
users = None
violations = None
events = None
whispers = None
whisper_sessions = None

async def connect_db():
    global client, db, groups, users, violations, events, whispers, whisper_sessions, mute_records, appeals
    if not MONGO_URI:
        raise RuntimeError("MONGO_URI is missing")
    client = AsyncIOMotorClient(MONGO_URI, serverSelectionTimeoutMS=10000)
    await client.admin.command("ping")
    db = client[MONGO_DB]
    groups = db.groups
    users = db.users
    violations = db.violations
    events = db.events
    whispers = db.whispers
    whisper_sessions = db.whisper_sessions
    mute_records = db.mute_records
    appeals = db.appeals

    await groups.create_index("chat_id", unique=True)
    await users.create_index([("chat_id", 1), ("user_id", 1)], unique=True)
    await users.create_index([("chat_id", 1), ("username", 1)])
    await violations.create_index([("chat_id", 1), ("user_id", 1)])
    await events.create_index("created_at")
    await whispers.create_index("whisper_id", unique=True)
    await whispers.create_index([("chat_id", 1), ("created_at", -1)])
    await whispers.create_index([("chat_id", 1), ("sender_id", 1)])
    await whispers.create_index([("chat_id", 1), ("recipient_id", 1)])
    await whispers.create_index([("chat_id", 1), ("conversation_id", 1)])
    await whispers.create_index("expires_at", expireAfterSeconds=0)
    await whisper_sessions.create_index([("chat_id", 1), ("user_id", 1)], unique=True)
    await whisper_sessions.create_index("expires_at", expireAfterSeconds=0)
    await mute_records.create_index([("chat_id", 1), ("user_id", 1)])
    await appeals.create_index([("chat_id", 1), ("user_id", 1), ("status", 1)])

async def get_group(chat_id, defaults):
    doc = await groups.find_one({"chat_id": chat_id})
    if not doc:
        doc = {"chat_id": chat_id, **defaults}
        await groups.insert_one(doc)
    else:
        missing = {k: v for k, v in defaults.items() if k not in doc}
        if missing:
            await groups.update_one({"chat_id": chat_id}, {"$set": missing})
            doc.update(missing)
    return doc

async def update_group(chat_id, data):
    await groups.update_one({"chat_id": chat_id}, {"$set": data}, upsert=True)

async def get_user(chat_id, user_id):
    return await users.find_one({"chat_id": chat_id, "user_id": user_id})

async def upsert_user(chat_id, user_id, data):
    await users.update_one({"chat_id": chat_id, "user_id": user_id}, {"$set": data}, upsert=True)

async def get_user_by_username(chat_id, username):
    username = (username or "").lstrip("@").strip().lower()
    if not username:
        return None
    return await users.find_one({
        "chat_id": chat_id,
        "username": {"$regex": "^" + __import__("re").escape(username) + "$", "$options": "i"},
    })

async def add_violation(chat_id, user_id, reason, decay_hours=24):
    """Add a violation, but reset stale history after a clean period."""
    from datetime import datetime, timezone, timedelta
    now = datetime.now(timezone.utc)
    doc = await violations.find_one({"chat_id": chat_id, "user_id": user_id})
    count = int(doc.get("count", 0)) if doc else 0
    last = doc.get("last_at") if doc else None
    if last and decay_hours and last < now - timedelta(hours=max(1, int(decay_hours))):
        count = 0
    count += 1
    await violations.update_one(
        {"chat_id": chat_id, "user_id": user_id},
        {"$set": {"count": count, "last_reason": reason, "last_at": now, "updated_at": now}},
        upsert=True
    )
    return count

async def reset_violations(chat_id, user_id):
    await violations.update_one({"chat_id": chat_id, "user_id": user_id}, {"$set": {"count": 0}})

async def get_violation_count(chat_id, user_id):
    doc = await violations.find_one({"chat_id": chat_id, "user_id": user_id})
    return int(doc.get("count", 0)) if doc else 0

async def get_recent_events(chat_id, limit=10):
    cur = events.find({"chat_id": chat_id}).sort("created_at", -1).limit(limit)
    return await cur.to_list(length=limit)

async def log_event(data):
    if events is not None:
        await events.insert_one(data)

# Premium mute appeal system
mute_records = None
appeals = None

async def _appeal_collections():
    global mute_records, appeals
    if db is None:
        raise RuntimeError('Database is not connected')
    if mute_records is None:
        mute_records = db.mute_records
        appeals = db.appeals
        await mute_records.create_index([('chat_id',1),('user_id',1)])
        await appeals.create_index([('chat_id',1),('user_id',1),('status',1)])
    return mute_records, appeals

async def save_mute_record(chat_id, user_id, minutes, reason='Manual mute'):
    mr, _ = await _appeal_collections()
    from datetime import datetime, timezone, timedelta
    now=datetime.now(timezone.utc); until=now+timedelta(minutes=minutes)
    await mr.update_one({'chat_id':chat_id,'user_id':user_id},{'$set':{'chat_id':chat_id,'user_id':user_id,'minutes':minutes,'reason':reason,'muted_at':now,'until':until}},upsert=True)
    return until

async def get_mute_record(chat_id, user_id):
    mr,_=await _appeal_collections(); return await mr.find_one({'chat_id':chat_id,'user_id':user_id})

async def create_appeal(chat_id,user_id,text):
    _,ap=await _appeal_collections()
    from datetime import datetime, timezone
    now=datetime.now(timezone.utc)
    doc={'chat_id':chat_id,'user_id':user_id,'text':text,'status':'pending','created_at':now}
    r=await ap.insert_one(doc); doc['_id']=r.inserted_id; return doc

async def resolve_appeal(appeal_id, action, admin_id):
    from bson import ObjectId
    _,ap=await _appeal_collections()
    try: oid=ObjectId(appeal_id)
    except Exception: return None
    doc=await ap.find_one({'_id':oid,'status':'pending'})
    if not doc: return None
    await ap.update_one({'_id':oid},{'$set':{'status':action,'resolved_by':admin_id}})
    return doc
