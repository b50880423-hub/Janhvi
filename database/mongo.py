from datetime import datetime, timezone
from pymongo import MongoClient, ASCENDING, DESCENDING
from config import MONGO_URI, MONGO_DB, DEFAULT_SETTINGS

_client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=8000) if MONGO_URI else None
_db = _client[MONGO_DB] if _client else None

def _now():
    return datetime.now(timezone.utc)

def init_db():
    if _db is None:
        return
    _db.groups.create_index([("chat_id", ASCENDING)], unique=True)
    _db.filters.create_index([("chat_id", ASCENDING), ("term", ASCENDING)], unique=True)
    _db.violations.create_index([("chat_id", ASCENDING), ("user_id", ASCENDING)])
    _db.events.create_index([("chat_id", ASCENDING), ("created_at", DESCENDING)])
    _db.whitelist.create_index([("chat_id", ASCENDING), ("user_id", ASCENDING)], unique=True)

def mongo_ok():
    if not _client:
        return False
    try:
        _client.admin.command("ping")
        return True
    except Exception:
        return False

def get_settings(chat_id):
    if _db is None:
        return dict(DEFAULT_SETTINGS)
    doc = _db.groups.find_one({"chat_id": chat_id}) or {}
    settings = dict(DEFAULT_SETTINGS)
    settings.update(doc.get("settings", {}))
    _db.groups.update_one({"chat_id": chat_id},
                          {"$set": {"chat_id": chat_id, "settings": settings}},
                          upsert=True)
    return settings

def set_setting(chat_id, key, value):
    if _db is None:
        return
    _db.groups.update_one({"chat_id": chat_id},
                          {"$set": {f"settings.{key}": value, "updated_at": _now()}},
                          upsert=True)

def get_filters(chat_id):
    if _db is None:
        return []
    return [x["term"] for x in _db.filters.find({"chat_id": chat_id}, {"term": 1}).sort("term", ASCENDING)]

def add_filter(chat_id, term):
    if _db is None:
        return False
    term = term.strip().lower()
    if not term:
        return False
    try:
        _db.filters.insert_one({"chat_id": chat_id, "term": term, "created_at": _now()})
        return True
    except Exception:
        return False

def remove_filter(chat_id, term):
    if _db is None:
        return False
    return _db.filters.delete_one({"chat_id": chat_id, "term": term.strip().lower()}).deleted_count > 0

def clear_filters(chat_id):
    if _db is not None:
        _db.filters.delete_many({"chat_id": chat_id})

def is_whitelisted(chat_id, user_id):
    if _db is None:
        return False
    return _db.whitelist.find_one({"chat_id": chat_id, "user_id": user_id}) is not None

def set_whitelist(chat_id, user_id, enabled=True):
    if _db is None:
        return
    if enabled:
        _db.whitelist.update_one({"chat_id": chat_id, "user_id": user_id},
                                 {"$set": {"chat_id": chat_id, "user_id": user_id}},
                                 upsert=True)
    else:
        _db.whitelist.delete_one({"chat_id": chat_id, "user_id": user_id})

def get_violation_count(chat_id, user_id):
    if _db is None:
        return 0
    doc = _db.violations.find_one({"chat_id": chat_id, "user_id": user_id})
    return int(doc.get("count", 0)) if doc else 0

def add_violation(chat_id, user_id, reason, username=None):
    if _db is None:
        return 1
    doc = _db.violations.find_one_and_update(
        {"chat_id": chat_id, "user_id": user_id},
        {"$inc": {"count": 1, f"reasons.{reason}": 1},
         "$set": {"username": username, "last_reason": reason, "last_at": _now()}},
        upsert=True, return_document=True)
    return int(doc.get("count", 1))

def reset_violations(chat_id, user_id):
    if _db is not None:
        _db.violations.update_one({"chat_id": chat_id, "user_id": user_id},
                                  {"$set": {"count": 0, "reasons": {}, "last_at": _now()}})

def add_event(data):
    if _db is not None:
        _db.events.insert_one(data)

def recent_events(chat_id, limit=10):
    if _db is None:
        return []
    return list(_db.events.find({"chat_id": chat_id}).sort("created_at", DESCENDING).limit(limit))

def stats(chat_id):
    if _db is None:
        return {}
    events = _db.events.count_documents({"chat_id": chat_id})
    deleted = _db.events.count_documents({"chat_id": chat_id, "deleted": True})
    muted = _db.events.count_documents({"chat_id": chat_id, "muted": True})
    warnings = _db.events.count_documents({"chat_id": chat_id, "action": "delete + warning"})
    return {"events": events, "deleted": deleted, "muted": muted, "warnings": warnings}
