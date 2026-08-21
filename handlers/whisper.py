import html, secrets
from datetime import datetime, timezone, timedelta
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ChatType
from database.mongo import get_user, upsert_user
import database.mongo as mongo
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
    await mongo.whispers.insert_one(doc)
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
    await mongo.whispers.update_one({"whisper_id": wid}, {"$set": {"public_message_id": card.message_id}})
    await msg.reply_text("✅ Whisper created. The message content is not posted publicly.", quote=True)



async def whisper_inline_query(update, context):
    """Create an inline whisper draft. The draft becomes a real group whisper
    when the inline result's Open Whisper button is pressed. This keeps the
    message in the group and never sends the user to the bot DM.
    """
    iq = update.inline_query
    if not iq or not iq.from_user:
        return

    query = (iq.query or "").strip()
    if not query:
        await iq.answer([], cache_time=0, is_personal=True,
                        switch_pm_text="Type @username message",
                        switch_pm_parameter="whisper_help")
        return

    parts = query.split(maxsplit=1)
    if len(parts) < 2:
        await iq.answer([], cache_time=0, is_personal=True)
        return

    raw_target = parts[0].strip()
    text = parts[1].strip()
    if not raw_target.startswith("@") or not text:
        await iq.answer([], cache_time=0, is_personal=True)
        return

    target_username = raw_target[1:].strip().lower()
    if not target_username or len(target_username) > 32:
        await iq.answer([], cache_time=0, is_personal=True)
        return
    if len(text) > 4000:
        text = text[:4000]

    # InlineQuery has no destination group/chat id. Store a short-lived draft;
    # the callback that runs in the destination group supplies the chat id.
    token = _cid()
    pending = {
        "whisper_id": token,
        "status": "pending_inline",
        "sender_id": iq.from_user.id,
        "sender_username": iq.from_user.username,
        "sender_name": iq.from_user.full_name,
        "recipient_username": target_username,
        "text": encrypt_text(text),
        "created_at": _now(),
        "expires_at": _now() + timedelta(minutes=10),
    }
    await mongo.whispers.update_one(
        {"whisper_id": token}, {"$set": pending}, upsert=True
    )

    from telegram import InlineQueryResultArticle, InputTextMessageContent

    card = (
        f"🔐 <b>A whisper message to @{html.escape(target_username)}</b>\n"
        "Only they can open this whisper."
    )
    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("🔓 Open Whisper", callback_data=f"ws:inline:{token}")
    ]])
    result = InlineQueryResultArticle(
        id=token,
        title=f"🔐 Whisper to @{target_username}",
        description="Only the selected user can open this whisper.",
        input_message_content=InputTextMessageContent(
            card, parse_mode="HTML"
        ),
        reply_markup=keyboard,
    )
    await iq.answer([result], cache_time=0, is_personal=True)

async def whisper_callback(update, context):
    q = update.callback_query
    if not q.message or not q.message.chat:
        return
    parts = q.data.split(":")
    if len(parts) < 3: return
    wid = parts[2]
    uid = q.from_user.id

    # Inline whispers are finalized only after they are inserted into a group.
    if parts[1] == "inline":
        pending = await mongo.whispers.find_one({"whisper_id": wid, "status": "pending_inline"})
        if not pending:
            await q.answer("Invalid or expired whisper! Please create another one.", show_alert=True)
            return
        if pending.get("expires_at") and pending["expires_at"] < _now():
            await mongo.whispers.delete_one({"whisper_id": wid})
            await q.answer("Whisper expired! Please create another one.", show_alert=True)
            return
        if uid != pending["sender_id"]:
            from database.mongo import users
            username = pending.get("recipient_username")
            target_doc = await users.find_one({
                "username": {"$regex": f"^{__import__('re').escape(username)}$", "$options": "i"}
            })
            if not target_doc or int(target_doc.get("user_id", 0)) != uid:
                await q.answer("🔒 This whisper is not for you.", show_alert=True)
                return
        else:
            target_doc = None

        from database.mongo import users
        if target_doc is None:
            username = pending.get("recipient_username")
            target_doc = await users.find_one({
                "username": {"$regex": f"^{__import__('re').escape(username)}$", "$options": "i"}
            })
        if not target_doc:
            await q.answer("I haven't seen that username yet. Ask the user to interact with the bot first.", show_alert=True)
            return

        recipient_id = int(target_doc["user_id"])
        if uid not in (pending["sender_id"], recipient_id):
            await q.answer("🔒 This whisper is not for you.", show_alert=True)
            return

        final_doc = {
            "whisper_id": wid, "conversation_id": _cid(),
            "chat_id": q.message.chat.id,
            "sender_id": pending["sender_id"], "recipient_id": recipient_id,
            "sender_username": pending.get("sender_username"),
            "recipient_username": pending.get("recipient_username"),
            "sender_name": pending.get("sender_name"),
            "recipient_name": target_doc.get("first_name") or pending.get("recipient_username"),
            "anonymous": False,
            "messages": [{"message_id": 1, "sender_id": pending["sender_id"],
                          "text": pending["text"], "created_at": _now(), "edited": False}],
            "created_at": pending["created_at"], "updated_at": _now(),
            "status": "active", "public_message_id": q.message.message_id,
        }
        await mongo.whispers.replace_one({"whisper_id": wid}, final_doc, upsert=True)
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔓 Open Whisper", callback_data=f"ws:open:{wid}")],
                                    [InlineKeyboardButton("💬 Reply", callback_data=f"ws:reply:{wid}"),
                                     InlineKeyboardButton("🚫 Block", callback_data=f"ws:block:{wid}")]])
        try:
            await q.edit_message_text(
                f"🔐 <b>A whisper message to @{html.escape(pending.get('recipient_username') or 'user')}</b>\n"
                "Only they can open this whisper.",
                parse_mode="HTML", reply_markup=kb
            )
        except Exception:
            pass
        messages = [decrypt_text(m["text"]) for m in final_doc.get("messages", [])]
        secret_text = "\n\n──────────\n\n".join(messages).strip() or "This whisper is empty."
        if len(secret_text) > 195:
            secret_text = secret_text[:192] + "…"
        await q.answer(secret_text, show_alert=True)
        return

    doc = await mongo.whispers.find_one({"whisper_id": wid})
    if not doc:
        await q.answer("Whisper no longer exists.", show_alert=True); return
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
        # Show ONLY the decrypted whisper text in Telegram's native alert.
        # Do NOT open the bot DM and do NOT send a second message.
        messages = [decrypt_text(m["text"]) for m in doc.get("messages", [])]
        secret_text = "\n\n──────────\n\n".join(messages).strip()
        if not secret_text:
            secret_text = "This whisper is empty."
        # Telegram limits callback-answer text to 200 characters.
        if len(secret_text) > 195:
            secret_text = secret_text[:192] + "…"
        await q.answer(secret_text, show_alert=True)
        return
    if parts[1] == "reply":
        await mongo.whisper_sessions.update_one(
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
    session = await mongo.whisper_sessions.find_one({"chat_id": msg.chat.id, "user_id": msg.from_user.id})
    if not session: return
    await mongo.whisper_sessions.delete_one({"chat_id": msg.chat.id, "user_id": msg.from_user.id})
    text = msg.text or msg.caption
    if not text:
        await msg.reply_text("❌ Reply mode currently accepts text. Use /whisper for a new conversation.")
        return
    doc = await mongo.whispers.find_one({"whisper_id": session["whisper_id"]})
    if not doc or msg.from_user.id not in (doc["sender_id"], doc["recipient_id"]):
        return
    new_id = len(doc.get("messages", [])) + 1
    await mongo.whispers.update_one({"whisper_id": doc["whisper_id"]}, {"$push": {"messages": {
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
    count = await mongo.whispers.count_documents({"chat_id": msg.chat.id})
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
        docs=await mongo.whispers.find({"chat_id":q.message.chat.id}).sort("created_at",-1).skip(page*8).limit(8).to_list(length=8)
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
        d=await mongo.whispers.find_one({"whisper_id":value})
        # page is nonnumeric whisper id for view
        if not d:
            await q.answer("Whisper not found.",show_alert=True); return
        lines=[f"👤 {html.escape(d.get('sender_name','User'))} → {html.escape(d.get('recipient_name','User'))}",f"🆔 <code>{d['whisper_id']}</code>",""]
        for m in d.get("messages",[]):
            who=d.get("sender_name") if m["sender_id"]==d["sender_id"] else d.get("recipient_name")
            lines.append(f"<b>{html.escape(who or 'User')}</b>  •  {m['created_at'].strftime('%Y-%m-%d %H:%M UTC') if hasattr(m['created_at'],'strftime') else ''}\n{html.escape(decrypt_text(m['text']))}")
        await q.edit_message_text("👑 <b>Owner Read-Only View</b>\n\n"+"\n\n──────────\n\n".join(lines)+"\n\n🔒 No read status, expiry, or conversation state was changed.",parse_mode="HTML",reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back",callback_data="wa:list:0")]]))
    elif action=="panel":
        count=await mongo.whispers.count_documents({"chat_id":q.message.chat.id})
        await q.edit_message_text(f"👑 <b>Whisper Owner Vault</b>\n\n📨 Total whispers: <b>{count}</b>",parse_mode="HTML",reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("📨 All Whispers",callback_data="wa:list:0")]]))
