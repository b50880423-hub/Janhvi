from datetime import datetime, timezone
from database import mongo

async def _col():
    if mongo.db is None: raise RuntimeError('Database is not connected')
    c=mongo.db.moderation_cases
    await c.create_index([('chat_id',1),('case_id',-1)])
    await c.create_index([('chat_id',1),('user_id',1),('created_at',-1)])
    return c

async def create_case(chat_id, user_id, action, admin_id, reason='No reason provided', evidence=None):
    c=await _col()
    last=await c.find_one({'chat_id':chat_id}, sort=[('case_id',-1)])
    case_id=int(last.get('case_id',0))+1 if last else 1
    now=datetime.now(timezone.utc)
    doc={'chat_id':chat_id,'case_id':case_id,'user_id':user_id,'action':action,'admin_id':admin_id,'reason':reason,'evidence':evidence or {},'status':'active','created_at':now}
    await c.insert_one(doc); return doc

async def get_case(chat_id, case_id):
    c=await _col(); return await c.find_one({'chat_id':chat_id,'case_id':case_id})

async def get_cases(chat_id,user_id,limit=20):
    c=await _col(); return await c.find({'chat_id':chat_id,'user_id':user_id}).sort('created_at',-1).limit(limit).to_list(length=limit)

async def counts(chat_id,user_id):
    c=await _col();
    rows=await c.aggregate([{'$match':{'chat_id':chat_id,'user_id':user_id}},{'$group':{'_id':'$action','n':{'$sum':1}}}]).to_list(None)
    return {r['_id']:r['n'] for r in rows}
