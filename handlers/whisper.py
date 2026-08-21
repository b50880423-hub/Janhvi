import html, secrets
from datetime import datetime, timezone, timedelta
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ChatType
from database.mongo import get_user, upsert_user, whispers, whisper_sessions
from utils.permissions import is_group_owner
from utils.whisper_crypto import encrypt_text, decrypt_text

def _now():
    return datetime.now(timezone.utc)

def _wid():
    return secrets.token_hex(4).upper()

def _cid():
    return secrets.token_hex(8)

async def remember_user(message):
    if message and message.from_user and not message.from_user.is_bot and message.chat:
        u = message.from_user
        await upsert_user(message.chat.id, u.id, {
            "username": u.username,
            "first_name": u.first_name,
            "last_name": u.last_name,
            "last_seen_at": _now()
        })

async def resolve_target(update):
    msg = update.effective_message
    if msg.reply_to_message and msg.reply_to_message.from_user:
        return msg.reply_to_message.from_user
    args = update.effective_message.text.split(maxsplit=2) if update.effective_message and update.effective_message.text else []
    if len(args) < 3:
        return None, None
    raw = args[1].strip()
    if raw.startswith("@"):
        doc = await get_user(update.effective_chat.id, {"username": raw[1:].lower()}) if False else None
        # username lookup is case-insensitive in our stored normalized field
        doc = await __import__("database.mongo", fromlist=["users"]).users.find_one({
            "chat_id": update.effective_chat.id,
            "username": {"$regex": f"^{raw[1:]}$", "$options": "i"}
        })
        if doc:
            return doc.get("user_id"), None
        return None, f"I don't know {html.escape(raw)} yet. Reply to that user's message and use /whisper <message>."
    if raw.lstrip("-").isdigit():
        return int(raw), None
    return None, "Use /whisper @username message or reply to a user's message with /whisper message."

async def whisper_command(update, context):
    msg = update.effective_message
    if not msg or msg.chat.type not in (ChatType.GROUP, ChatType.SUPERGROUP) or not msg.from_user:
        return
    await remember_user(msg)
    target = None
    text = ""
    if msg.reply_to_message and msg.reply_to_message.from_user:
        target = msg.reply_to_message.from_user
        parts = (msg.text or "").split(maxsplit=1)
        text = parts[1].strip() if len(parts) > 1 else ""
    else:
        parts = (msg.text or "").split(maxsplit=2)
        if len(parts) < 3:
            await msg.reply_text("🤫 Usage: <code>/whisper @username message</code>\nOr reply to a user's message with <code>/whisper message</code>.", parse_mode="HTML")
            return
        raw = parts[1]
        if raw.startswith("@"):
            from database.mongo import users
            doc = await users.find_one({"chat_id": msg.chat.id, "username": {"$regex": f"^{raw[1:]}$", "$options": "i"}})
            if not doc:
                await msg.reply_text("❌ I haven't seen that username in this group yet. Reply to their message and use <code>/whisper message</code>.", parse_mode="HTML")
                return
            target = doc["user_id"]
        elif raw.lstrip("-").isdigit():
            target = int(raw)
        else:
            await msg.reply_text("❌ Invalid target. Use @username or reply to their message.")
            return
        text = parts[2].strip()
    if not text:
        await msg.reply_text("✍️ Add a message after /whisper.")
        return
    if isinstance(target, type(msg.from_user)):
        recipient_id, recipient_name = target.id, target.full_name
    else:
        recipient_id = int(target)
        recipient_name = None
    if recipient_id == msg.from_user.id:
        await msg.reply_text("❌ You can't whisper to yourself.")
        return
    try:
        member = await context.bot.get_chat_member(msg.chat.id, recipient_id)
        if member.user.is_bot:
            await msg.reply_text("❌ You can't whisper to a bot.")
            return
        recipient_name = member.user.full_name
        await upsert_user(msg.chat.id, recipient_id, {
            "username": member.user.username,
            "first_name": member.user.first_name,
            "last_name": member.user.last_name,
            "last_seen_at": _now()
        })
    except Exception:
        await msg.reply_text("❌ That user isn't currently accessible in this group.")
        return

    wid = _wid()
    cid = _cid()
    doc = {
        "whisper_id": wid, "conversation_id": cid, "chat_id": msg.chat.id,
        "sender_id": msg.from_user.id, "recipient_id": recipient_id,
        "sender_username": msg.from_user.username, "recipient_username": getattr(member.user, "username", None),
        "sender_name": msg.from_user.full_name, "recipient_name": recipient_name,
        "anonymous": False, "messages": [{
            "message_id": 1, "sender_id": msg.from_user.id,
            "text": encrypt_text(text), "created_at": _now(), "edited": False
        }],
        "created_at": _now(), "updated_at": _now(), "status": "active",
        "public_message_id": None
    }
    await whispers.insert_one(doc)
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔓 Open Whisper", callback_data=f"ws:open:{wid}")],
                               [InlineKeyboardButton("💬 Reply", callback_data=f"ws:reply:{wid}"),
                                InlineKeyboardButton("🚫 Block", callback_data=f"ws:block:{wid}")]])
    card = await msg.reply_text(
        f"🤫 <b>PRIVATE WHISPER</b>\n\n"
        f"👤 To: {html.escape(recipient_name)}\n"
        f"🔐 Only the recipient and sender can open this whisper.\n"
        f"🆔 <code>{wid}</code>",
        parse_mode="HTML", reply_markup=kb
    )
    await whispers.update_one({"whisper_id": wid}, {"$set": {"public_message_id": card.message_id}})
    await msg.reply_text("✅ Whisper created. The message content is not posted publicly.", quote=True)

async def whisper_callback(update, context):
    q = update.callback_query
    if not q.message or not q.message.chat:
        return
    parts = q.data.split(":")
    if len(parts) < 3: return
    wid = parts[2]
    doc = await whispers.find_one({"whisper_id": wid})
    if not doc:
        await q.answer("Whisper no longer exists.", show_alert=True); return
    uid = q.from_user.id
    if parts[1] == "block":
        if uid not in (doc["sender_id"], doc["recipient_id"]):
            await q.answer("Only conversation participants can block.", show_alert=True); return
        from database.mongo import users
        other = doc["sender_id"] if uid == doc["recipient_id"] else doc["recipient_id"]
        await users.update_one({"chat_id": doc["chat_id"], "user_id": uid}, {"$addToSet": {"blocked_users": other}}, upsert=True)
        await q.answer("User blocked.", show_alert=True); return
    if uid not in (doc["sender_id"], doc["recipient_id"]):
        await q.answer("🚫 Access denied.", show_alert=True); return
    if parts[1] == "open":
        lines = []
        for m in doc.get("messages", []):
            who = "You" if m["sender_id"] == uid else (doc.get("sender_name") if uid == doc["recipient_id"] else doc.get("recipient_name"))
            lines.append(f"👤 <b>{html.escape(who or 'User')}</b>\n{html.escape(decrypt_text(m['text']))}")
        await q.answer("🔓 Opened privately.", show_alert=True)
        await context.bot.send_message(chat_id=uid, text="🤫 <b>Whisper</b>\n\n" + "\n\n──────────\n\n".join(lines), parse_mode="HTML")
        return
    if parts[1] == "reply":
        await whisper_sessions.update_one(
            {"chat_id": doc["chat_id"], "user_id": uid},
            {"$set": {"whisper_id": wid, "expires_at": _now()+timedelta(minutes=5)}},
            upsert=True
        )
        await q.answer("Reply mode enabled for 5 minutes.", show_alert=True)
        await context.bot.send_message(uid, f"💬 Send your reply to whisper <code>{wid}</code> now.\nIt will be posted as a protected whisper card in the group.", parse_mode="HTML")

async def whisper_message_handler(update, context):
    msg = update.effective_message
    if not msg or not msg.from_user or msg.from_user.is_bot or msg.chat.type not in (ChatType.GROUP, ChatType.SUPERGROUP):
        return
    await remember_user(msg)
    session = await whisper_sessions.find_one({"chat_id": msg.chat.id, "user_id": msg.from_user.id})
    if not session: return
    await whisper_sessions.delete_one({"chat_id": msg.chat.id, "user_id": msg.from_user.id})
    text = msg.text or msg.caption
    if not text:
        await msg.reply_text("❌ Reply mode currently accepts text. Use /whisper for a new conversation.")
        return
    doc = await whispers.find_one({"whisper_id": session["whisper_id"]})
    if not doc or msg.from_user.id not in (doc["sender_id"], doc["recipient_id"]):
        return
    new_id = len(doc.get("messages", [])) + 1
    await whispers.update_one({"whisper_id": doc["whisper_id"]}, {"$push": {"messages": {
        "message_id": new_id, "sender_id": msg.from_user.id, "text": encrypt_text(text),
        "created_at": _now(), "edited": False
    }}, "$set": {"updated_at": _now()}})
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔓 Open Conversation", callback_data=f"ws:open:{doc['whisper_id']}")],
                               [InlineKeyboardButton("💬 Reply", callback_data=f"ws:reply:{doc['whisper_id']}"),
                                InlineKeyboardButton("🚫 Block", callback_data=f"ws:block:{doc['whisper_id']}")]])
    await msg.reply_text("💬 <b>PRIVATE WHISPER REPLY</b>\n\n🔐 Only the conversation participants can open this conversation.\n🆔 <code>"+doc["whisper_id"]+"</code>", parse_mode="HTML", reply_markup=kb)

async def owner_whisper_panel(update, context):
    msg=update.effective_message
    if not msg or msg.chat.type not in (ChatType.GROUP, ChatType.SUPERGROUP): return
    if not await is_group_owner(context.bot, msg.chat.id, msg.from_user.id):
        await msg.reply_text("❌ Group owner only."); return
    count = await whispers.count_documents({"chat_id": msg.chat.id})
    kb=InlineKeyboardMarkup([[InlineKeyboardButton("📨 All Whispers", callback_data="wa:list:0"),
                              InlineKeyboardButton("🔎 Search", callback_data="wa:search")]])
    await msg.reply_text(f"👑 <b>Whisper Owner Vault</b>\n\n📨 Total whispers: <b>{count}</b>\n\nRead-only audit access: viewing never marks user messages read or changes the conversation.", parse_mode="HTML", reply_markup=kb)

async def owner_whisper_callback(update, context):
    q=update.callback_query
    if not q.message: return
    if not await is_group_owner(context.bot, q.message.chat.id, q.from_user.id):
        await q.answer("Owner only.", show_alert=True); return
    parts=q.data.split(":")
    if len(parts)<3: return
    action, value=parts[1], parts[2]
    page=int(value) if value.isdigit() else 0
    from database.mongo import whispers
    if action=="list":
        docs=await whispers.find({"chat_id":q.message.chat.id}).sort("created_at",-1).skip(page*8).limit(8).to_list(length=8)
        if not docs:
            await q.answer("No whispers found.", show_alert=True); return
        rows=[]
        for d in docs:
            label=f"#{d['whisper_id']} • {d.get('sender_name','User')} → {d.get('recipient_name','User')}"
            rows.append([InlineKeyboardButton(label[:60], callback_data=f"wa:view:{d['whisper_id']}")])
        nav=[]
        if page>0: nav.append(InlineKeyboardButton("⬅️",callback_data=f"wa:list:{page-1}"))
        if len(docs)==8: nav.append(InlineKeyboardButton("➡️",callback_data=f"wa:list:{page+1}"))
        if nav: rows.append(nav)
        rows.append([InlineKeyboardButton("🔙 Vault",callback_data="wa:panel:0")])
        await q.edit_message_text("📨 <b>All Whispers — Read Only</b>\n\nSelect a conversation:",parse_mode="HTML",reply_markup=InlineKeyboardMarkup(rows))
    elif action=="view":
        d=await whispers.find_one({"whisper_id":value})
        # page is nonnumeric whisper id for view
        if not d:
            await q.answer("Whisper not found.",show_alert=True); return
        lines=[f"👤 {html.escape(d.get('sender_name','User'))} → {html.escape(d.get('recipient_name','User'))}",f"🆔 <code>{d['whisper_id']}</code>",""]
        for m in d.get("messages",[]):
            who=d.get("sender_name") if m["sender_id"]==d["sender_id"] else d.get("recipient_name")
            lines.append(f"<b>{html.escape(who or 'User')}</b>  •  {m['created_at'].strftime('%Y-%m-%d %H:%M UTC') if hasattr(m['created_at'],'strftime') else ''}\n{html.escape(decrypt_text(m['text']))}")
        await q.edit_message_text("👑 <b>Owner Read-Only View</b>\n\n"+"\n\n──────────\n\n".join(lines)+"\n\n🔒 No read status, expiry, or conversation state was changed.",parse_mode="HTML",reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back",callback_data="wa:list:0")]]))
    elif action=="panel":
        count=await whispers.count_documents({"chat_id":q.message.chat.id})
        await q.edit_message_text(f"👑 <b>Whisper Owner Vault</b>\n\n📨 Total whispers: <b>{count}</b>",parse_mode="HTML",reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("📨 All Whispers",callback_data="wa:list:0")]]))
