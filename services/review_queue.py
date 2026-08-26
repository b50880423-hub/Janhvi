from datetime import datetime, timezone
from bson import ObjectId
from database.mongo import db

async def add_review(item):
    if db is None:return None
    doc={**item,'status':'open','created_at':datetime.now(timezone.utc)}
    r=await db.review_queue.insert_one(doc); return str(r.inserted_id)

async def resolve_review(review_id, action, admin_id):
    if db is None:return None
    try: oid=ObjectId(review_id)
    except Exception:return None
    doc=await db.review_queue.find_one({'_id':oid,'status':'open'})
    if not doc:return None
    await db.review_queue.update_one({'_id':oid},{'$set':{'status':'resolved','resolution':action,'resolved_by':admin_id,'resolved_at':datetime.now(timezone.utc)}})
    return doc
