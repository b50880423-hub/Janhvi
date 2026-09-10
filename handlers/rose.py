"""Janhvi command suite: Rose-style group utilities plus original extensions.
All persistent data is stored per-group in MongoDB.
"""
import re
from datetime import datetime, timezone, timedelta
from html import escape
from telegram import ChatPermissions, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ChatMemberStatus
import database.mongo as mongo
from database.mongo import get_group, get_user_by_username, upsert_user, log_event
from config import DEFAULT_SETTINGS
from utils.permissions import is_admin


def _chat(update):
    return update.effective_chat

async def _admin(update):
    return bool(update.effective_chat and update.effective_user and await is_admin(update.get_bot(), update.effective_chat.id, update.effective_user.id))

async def _deny(update):
    await update.effective_message.reply_text("❌ This command is available to group administrators only.")

async def _target(update, context, args=None):
    msg = update.effective_message
    if msg and msg.reply_to_message and msg.reply_to_message.from_user:
        u = msg.reply_to_message.from_user
        return u.id, u.mention_html()
    args = list(args if args is not None else context.args)
    if not args:
        return None, None
    raw = args[0].strip()
    if raw.lstrip("-").isdigit():
        uid = int(raw)
        return uid, f"<code>{uid}</code>"
    if raw.startswith("@"):
        u = await get_user_by_username(update.effective_chat.id, raw)
        if u:
            uid = int(u["user_id"])
            return uid, f"@{escape(raw[1:])}"
    return None, None

async def _bot_can_restrict(update):
    try:
        me = await update.get_bot().get_me()
        m = await update.get_bot().get_chat_member(update.effective_chat.id, me.id)
        return m.status == ChatMemberStatus.OWNER or bool(getattr(m, "can_restrict_members", False))
    except Exception:
        return False

async def _record(chat_id, action, uid, admin_id, reason=""):
    await log_event({"chat_id": chat_id, "type": action, "user_id": uid, "admin_id": admin_id,
                     "reason": reason, "created_at": datetime.now(timezone.utc)})

# ---------------- Notes ----------------
async def save_note(update, context):
    if not await _admin(update): return await _deny(update)
    if not context.args or not update.effective_message.reply_to_message:
        return await update.effective_message.reply_text("Usage: reply to a message with <code>/save name</code>.", parse_mode="HTML")
    name = context.args[0].lower().strip()
    msg = update.effective_message.reply_to_message
    payload = {"name": name, "chat_id": update.effective_chat.id, "created_by": update.effective_user.id,
               "created_at": datetime.now(timezone.utc), "text": msg.text_html if msg.text else (msg.caption_html or "")}
    if msg.photo: payload.update(type="photo", file_id=msg.photo[-1].file_id)
    elif msg.video: payload.update(type="video", file_id=msg.video.file_id)
    elif msg.animation: payload.update(type="animation", file_id=msg.animation.file_id)
    elif msg.document: payload.update(type="document", file_id=msg.document.file_id)
    elif msg.audio: payload.update(type="audio", file_id=msg.audio.file_id)
    else: payload["type"] = "text"
    await mongo.notes.update_one({"chat_id": payload["chat_id"], "name": name}, {"$set": payload}, upsert=True)
    await update.effective_message.reply_text(f"✅ Note <code>{escape(name)}</code> saved.", parse_mode="HTML")

async def get_note(update, context):
    if not update.effective_chat or not context.args:
        return await update.effective_message.reply_text("Usage: /get name")
    name = context.args[0].lower().strip()
    doc = await mongo.notes.find_one({"chat_id": update.effective_chat.id, "name": name})
    if not doc: return await update.effective_message.reply_text("❌ That note does not exist.")
    typ, fid, text = doc.get("type", "text"), doc.get("file_id"), doc.get("text", "")
    if typ == "photo" and fid: await update.effective_message.reply_photo(fid, caption=text or None, parse_mode="HTML")
    elif typ == "video" and fid: await update.effective_message.reply_video(fid, caption=text or None, parse_mode="HTML")
    elif typ == "animation" and fid: await update.effective_message.reply_animation(fid, caption=text or None, parse_mode="HTML")
    elif typ == "document" and fid: await update.effective_message.reply_document(fid, caption=text or None, parse_mode="HTML")
    elif typ == "audio" and fid: await update.effective_message.reply_audio(fid, caption=text or None, parse_mode="HTML")
    else: await update.effective_message.reply_text(text or "(empty note)", parse_mode="HTML")

async def notes(update, context):
    if not update.effective_chat: return
    rows = await mongo.notes.find({"chat_id": update.effective_chat.id}).sort("name", 1).to_list(length=100)
    if not rows: return await update.effective_message.reply_text("📝 No notes have been saved in this group.")
    lines = ["📝 <b>Saved notes</b>"] + [f"• <code>{escape(r['name'])}</code>" for r in rows]
    await update.effective_message.reply_text("\n".join(lines), parse_mode="HTML")

async def clear_note(update, context):
    if not await _admin(update): return await _deny(update)
    if not context.args: return await update.effective_message.reply_text("Usage: /clear name")
    name = context.args[0].lower().strip()
    r = await mongo.notes.delete_one({"chat_id": update.effective_chat.id, "name": name})
    await update.effective_message.reply_text("🗑️ Note removed." if r.deleted_count else "❌ Note not found.")

# ---------------- Custom commands ----------------
async def save_command(update, context):
    if not await _admin(update): return await _deny(update)
    if not context.args or not update.effective_message.reply_to_message:
        return await update.effective_message.reply_text("Usage: reply to a message with <code>/command name</code>.", parse_mode="HTML")
    name = context.args[0].lower().lstrip("/")
    if not re.fullmatch(r"[a-z0-9_]{1,32}", name): return await update.effective_message.reply_text("❌ Use only letters, numbers and underscores.")
    msg = update.effective_message.reply_to_message
    text = msg.text_html if msg.text else (msg.caption_html or "")
    if not text and not (msg.photo or msg.video or msg.animation or msg.document):
        return await update.effective_message.reply_text("❌ This message type cannot be saved as a custom command yet.")
    doc = {"chat_id": update.effective_chat.id, "name": name, "text": text, "created_by": update.effective_user.id,
           "created_at": datetime.now(timezone.utc), "type": "text", "file_id": None}
    if msg.photo: doc.update(type="photo", file_id=msg.photo[-1].file_id)
    elif msg.video: doc.update(type="video", file_id=msg.video.file_id)
    elif msg.animation: doc.update(type="animation", file_id=msg.animation.file_id)
    elif msg.document: doc.update(type="document", file_id=msg.document.file_id)
    await mongo.custom_commands.update_one({"chat_id": doc["chat_id"], "name": name}, {"$set": doc}, upsert=True)
    await update.effective_message.reply_text(f"✅ Custom command <code>/{escape(name)}</code> saved.", parse_mode="HTML")

async def command_list(update, context):
    if not update.effective_chat: return
    rows = await mongo.custom_commands.find({"chat_id": update.effective_chat.id}).sort("name", 1).to_list(length=100)
    if not rows: return await update.effective_message.reply_text("⚙️ No custom commands configured.")
    await update.effective_message.reply_text("⚙️ <b>Custom commands</b>\n\n" + "\n".join(f"• <code>/{escape(r['name'])}</code>" for r in rows), parse_mode="HTML")

async def command_delete(update, context):
    if not await _admin(update): return await _deny(update)
    if not context.args: return await update.effective_message.reply_text("Usage: /delcommand name")
    name = context.args[0].lower().lstrip("/")
    r = await mongo.custom_commands.delete_one({"chat_id": update.effective_chat.id, "name": name})
    await update.effective_message.reply_text("🗑️ Custom command removed." if r.deleted_count else "❌ Custom command not found.")

async def custom_command_handler(update, context):
    msg = update.effective_message
    if not msg or not msg.text or not msg.text.startswith("/") or not update.effective_chat or update.effective_chat.type not in ("group", "supergroup"):
        return
    m = re.match(r"^/([A-Za-z0-9_]{1,32})(?:@\w+)?(?:\s+.*)?$", msg.text.strip(), re.S)
    if not m: return
    name = m.group(1).lower()
    if name in {"start","help","welcome","settings","rules","setrules","clearrules","panel","locks","filters","stop","stopall","rule","appeal","warn","mute","unmute","ban","unban","case","cases","userhistory","evidence","setlog","removelog","logstatus","whitelist","unwhitelist","blacklist","unblacklist","userinfo","id","warnings","resetwarnings","lock","unlock","filter","badwords","antispam","logs","smartstatus","setlimit","whisper","whisperowner","security","mode","domain","reviewqueue","promote","demote","trust","untrust","silentmode","threatlevel","lockdown","unlockdown","nsfwstickers","profile","save","get","notes","clear","command","commands","delcommand","purge","kick","tempban","tempmute","report","setgoodbye","goodbye","language","admins"}:
        return
    doc = await mongo.custom_commands.find_one({"chat_id": update.effective_chat.id, "name": name})
    if not doc: return
    text = doc.get("text", "").replace("{name}", escape(msg.from_user.first_name or "")).replace("{mention}", msg.from_user.mention_html())
    typ, fid = doc.get("type"), doc.get("file_id")
    if typ == "photo" and fid: await msg.reply_photo(fid, caption=text or None, parse_mode="HTML")
    elif typ == "video" and fid: await msg.reply_video(fid, caption=text or None, parse_mode="HTML")
    elif typ == "animation" and fid: await msg.reply_animation(fid, caption=text or None, parse_mode="HTML")
    elif typ == "document" and fid: await msg.reply_document(fid, caption=text or None, parse_mode="HTML")
    else: await msg.reply_text(text or "(empty command)", parse_mode="HTML")

# ---------------- Moderation extensions ----------------
async def purge(update, context):
    if not await _admin(update): return await _deny(update)
    if not update.effective_message.reply_to_message:
        return await update.effective_message.reply_text("Reply to the first message and use <code>/purge 20</code>.", parse_mode="HTML")
    try: count = max(1, min(100, int(context.args[0]))) if context.args else 10
    except ValueError: return await update.effective_message.reply_text("Usage: /purge <1-100>")
    start = update.effective_message.reply_to_message.message_id
    deleted = 0
    for mid in range(start, start + count):
        try:
            await context.bot.delete_message(update.effective_chat.id, mid); deleted += 1
        except Exception: pass
    try: await update.effective_message.delete()
    except Exception: pass
    await _record(update.effective_chat.id, "purge", update.effective_user.id, update.effective_user.id, f"deleted {deleted}")

async def kick(update, context):
    if not await _admin(update): return await _deny(update)
    uid, display = await _target(update, context)
    if not uid: return await update.effective_message.reply_text("Reply to a user or use /kick <user_id|@username>.")
    try: await context.bot.ban_chat_member(update.effective_chat.id, uid); await context.bot.unban_chat_member(update.effective_chat.id, uid, only_if_banned=True)
    except Exception as e: return await update.effective_message.reply_text(f"❌ Could not remove user: {e}")
    await _record(update.effective_chat.id, "kick", uid, update.effective_user.id, "Manual kick")
    await update.effective_message.reply_text(f"👢 Removed {display} from the group.", parse_mode="HTML")

async def temp_action(update, context, action):
    if not await _admin(update): return await _deny(update)
    uid, display = await _target(update, context)
    args = list(context.args)
    if not uid: return await update.effective_message.reply_text(f"Usage: /{action} <user_id|@username> <duration> [reason] — or reply to a user.")
    # Reply syntax: first arg is duration; target syntax: first is target, second is duration.
    duration_raw = args[0] if update.effective_message.reply_to_message and args else (args[1] if len(args) > 1 else "")
    m = re.fullmatch(r"(\d+)(m|h|d)", duration_raw.lower())
    if not m: return await update.effective_message.reply_text("Duration must look like 10m, 2h or 7d.")
    minutes = int(m.group(1)) * {"m":1,"h":60,"d":1440}[m.group(2)]
    minutes = max(1, min(minutes, 60*24*365))
    reason_parts = args[1:] if update.effective_message.reply_to_message else args[2:]
    reason = " ".join(reason_parts).strip() or "No reason provided"
    until = datetime.now(timezone.utc) + timedelta(minutes=minutes)
    previous_permissions = None
    if action == "tempmute":
        try:
            chat = await context.bot.get_chat(update.effective_chat.id)
            perms = getattr(chat, "permissions", None)
            if perms is not None:
                previous_permissions = perms.to_dict() if hasattr(perms, "to_dict") else dict(perms)
        except Exception:
            previous_permissions = None
    try:
        if action == "tempban":
            await context.bot.ban_chat_member(update.effective_chat.id, uid, until_date=until)
        else:
            await context.bot.restrict_chat_member(update.effective_chat.id, uid, permissions=ChatPermissions.no_permissions(), until_date=until)
    except Exception as e: return await update.effective_message.reply_text(f"❌ Could not apply action: {e}")
    await mongo.temp_actions.update_one({"chat_id": update.effective_chat.id, "user_id": uid, "action": action}, {"$set": {"chat_id":update.effective_chat.id,"user_id":uid,"action":action,"until":until,"created_by":update.effective_user.id,"reason":reason,"previous_permissions":previous_permissions}}, upsert=True)
    await _record(update.effective_chat.id, action, uid, update.effective_user.id, reason)
    await update.effective_message.reply_text(f"{'🚫' if action=='tempban' else '🔇'} <b>{'Temporary ban' if action=='tempban' else 'Temporary mute'}</b>\nUser: {display}\nDuration: {duration_raw}\nReason: {escape(reason)}", parse_mode="HTML")

async def tempban(update, context): return await temp_action(update, context, "tempban")
async def tempmute(update, context): return await temp_action(update, context, "tempmute")

async def expire_temp_actions(context):
    now = datetime.now(timezone.utc)
    rows = await mongo.temp_actions.find({"until": {"$lte": now}}).to_list(length=100)
    for row in rows:
        try:
            if row["action"] == "tempban": await context.bot.unban_chat_member(row["chat_id"], row["user_id"], only_if_banned=True)
            else:
                saved = row.get("previous_permissions") or {}
                permissions = ChatPermissions(**saved) if saved else ChatPermissions.all_permissions()
                await context.bot.restrict_chat_member(row["chat_id"], row["user_id"], permissions=permissions)
        except Exception: pass
        await mongo.temp_actions.delete_one({"_id": row["_id"]})

# ---------------- Reporting / language / goodbye ----------------
async def report(update, context):
    msg = update.effective_message
    if not msg or not msg.reply_to_message or not msg.reply_to_message.from_user:
        return await msg.reply_text("Reply to the message you want to report, then use /report [reason].")
    reason = " ".join(context.args).strip() or "No reason provided"
    group = await get_group(update.effective_chat.id, DEFAULT_SETTINGS)
    log_id = group.get("log_chat_id")
    target = int(log_id) if log_id else update.effective_chat.id
    u = msg.reply_to_message.from_user
    source_chat = update.effective_chat.id
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("⚠️ Warn", callback_data=f"report:warn:{source_chat}:{u.id}"), InlineKeyboardButton("🔇 Mute", callback_data=f"report:mute:{source_chat}:{u.id}"), InlineKeyboardButton("🚫 Ban", callback_data=f"report:ban:{source_chat}:{u.id}")]])
    text = f"🚨 <b>Member report</b>\nReporter: {msg.from_user.mention_html()}\nTarget: {u.mention_html()}\nReason: {escape(reason)}\nMessage ID: <code>{msg.reply_to_message.message_id}</code>"
    await context.bot.send_message(target, text, parse_mode="HTML", reply_markup=kb)
    await msg.reply_text("✅ Report sent to the moderators.")

async def language(update, context):
    if not await _admin(update): return await _deny(update)
    if not context.args:
        s = await get_group(update.effective_chat.id, DEFAULT_SETTINGS)
        return await update.effective_message.reply_text(f"🌐 Current language: <b>{escape(str(s.get('language','English')))}</b>\nUse /language English, Hindi, or Bengali.", parse_mode="HTML")
    value = " ".join(context.args).strip().title()
    allowed = {"English", "Hindi", "Bengali"}
    if value not in allowed: return await update.effective_message.reply_text("❌ Supported languages: English, Hindi, Bengali.")
    await mongo.groups.update_one({"chat_id": update.effective_chat.id}, {"$set":{"language":value}}, upsert=True)
    await update.effective_message.reply_text(f"🌐 Group language set to <b>{value}</b>.", parse_mode="HTML")

async def setgoodbye(update, context):
    if not await _admin(update): return await _deny(update)
    text = " ".join(context.args).strip()
    if not text: return await update.effective_message.reply_text("Usage: /setgoodbye {mention} has left {chat}.")
    await mongo.groups.update_one({"chat_id": update.effective_chat.id}, {"$set":{"goodbye_text":text,"goodbye_enabled":True}}, upsert=True)
    await update.effective_message.reply_text("✅ Goodbye message saved and enabled.")

async def goodbye(update, context):
    if not await _admin(update): return await _deny(update)
    if context.args and context.args[0].lower() in ("on","off"):
        enabled=context.args[0].lower()=="on"; await mongo.groups.update_one({"chat_id":update.effective_chat.id},{"$set":{"goodbye_enabled":enabled}},upsert=True)
        return await update.effective_message.reply_text(f"👋 Goodbye system {'enabled' if enabled else 'disabled'}.")
    s=await get_group(update.effective_chat.id,DEFAULT_SETTINGS)
    await update.effective_message.reply_text(f"👋 Goodbye: {'ON' if s.get('goodbye_enabled',False) else 'OFF'}\nUse /setgoodbye <message> or /goodbye on|off")

async def monitor_goodbye(update, context):
    cm=getattr(update,"chat_member",None)
    if not cm or not cm.old_chat_member or not cm.new_chat_member: return
    old,new=cm.old_chat_member.status,cm.new_chat_member.status
    if old not in (ChatMemberStatus.MEMBER,ChatMemberStatus.RESTRICTED,ChatMemberStatus.ADMINISTRATOR) or new not in (ChatMemberStatus.LEFT,ChatMemberStatus.BANNED): return
    u=cm.old_chat_member.user
    if not u or u.is_bot: return
    s=await get_group(cm.chat.id,DEFAULT_SETTINGS)
    if not s.get("goodbye_enabled",False): return
    text=s.get("goodbye_text") or "👋 {mention} has left {chat}."
    text=text.replace("{name}",escape(u.first_name or "")).replace("{full_name}",escape(u.full_name or "")).replace("{mention}",u.mention_html()).replace("{username}",escape('@'+u.username if u.username else u.full_name)).replace("{id}",str(u.id)).replace("{chat}",escape(cm.chat.title or "this group"))
    try: await context.bot.send_message(cm.chat.id,text,parse_mode="HTML")
    except Exception: pass

async def admins(update, context):
    if not update.effective_chat: return
    rows = await context.bot.get_chat_administrators(update.effective_chat.id)
    lines=["👮 <b>Group administrators</b>"]
    for m in rows:
        label=m.user.mention_html(); role="Owner" if m.status==ChatMemberStatus.OWNER else "Admin"
        lines.append(f"• {label} — {role}")
    await update.effective_message.reply_text("\n".join(lines),parse_mode="HTML")

async def report_callback(update, context):
    q=update.callback_query
    if not q: return
    await q.answer()
    if not await is_admin(context.bot, q.message.chat.id, q.from_user.id):
        return await q.answer("Admins only.", show_alert=True)
    parts = q.data.split(":")
    if len(parts) == 4:
        _, action, raw_chat, raw_uid = parts
        source_chat = int(raw_chat)
    else:
        _, action, raw_uid = parts
        source_chat = q.message.chat.id
    uid=int(raw_uid)
    if not await is_admin(context.bot, source_chat, q.from_user.id):
        return await q.answer("Admins only in the source group.", show_alert=True)
    try:
        if action=="ban": await context.bot.ban_chat_member(source_chat,uid)
        elif action=="mute": await context.bot.restrict_chat_member(source_chat,uid,permissions=ChatPermissions.no_permissions(),until_date=datetime.now(timezone.utc)+timedelta(hours=1))
        elif action=="warn":
            from database.mongo import add_violation
            await add_violation(source_chat,uid,"reported message")
        await q.edit_message_reply_markup(reply_markup=None)
        await q.message.reply_text(f"✅ Report action applied: <b>{escape(action)}</b> to <code>{uid}</code>.",parse_mode="HTML")
    except Exception as e:
        await q.message.reply_text(f"❌ Action failed in the source group: {escape(str(e))}",parse_mode="HTML")
