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
    global client, db, groups, users, violations, events, whispers, whisper_sessions
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

    await groups.create_index("chat_id", unique=True)
    await users.create_index([("chat_id", 1), ("user_id", 1)], unique=True)
    await users.create_index([("chat_id", 1), ("username", 1)])
    await users.create_index("username")
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

async def add_violation(chat_id, user_id, reason):
    await violations.update_one(
        {"chat_id": chat_id, "user_id": user_id},
        {"$inc": {"count": 1}, "$set": {"last_reason": reason}},
        upsert=True
    )
    doc = await violations.find_one({"chat_id": chat_id, "user_id": user_id})
    return int(doc.get("count", 0))

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
