import re
import time
from datetime import datetime, timezone
from html import escape
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ChatMemberStatus, ChatType
from database.mongo import get_group, get_welcome_config, update_welcome_config, delete_welcome_config
from config import DEFAULT_SETTINGS

_WELCOME_DEDUP = {}
_WELCOME_DEDUP_TTL = 15

DEFAULT_WELCOME = (
    "🎉 <b>Welcome {mention}!</b>\n\n"
    "👤 <b>Name:</b> {full_name}\n"
    "🆔 <b>ID:</b> <code>{id}</code>\n"
    "👥 <b>Member:</b> #{count}\n\n"
    "✨ Please read the rules and enjoy <b>{chat}</b>!"
)

def _is_group(update):
    c = update.effective_chat
    return c and c.type in (ChatType.GROUP, ChatType.SUPERGROUP)

async def _is_owner(update):
    if not _is_group(update) or not update.effective_user:
        return False
    try:
        m = await update.effective_chat.get_member(update.effective_user.id)
        return m.status == ChatMemberStatus.OWNER
    except Exception:
        return False

def _help():
    return (
        "👋 <b>Advanced Welcome System</b>\n\n"
        "<b>Owner-only controls:</b>\n"
        "• <code>/welcome</code> — show current configuration\n"
        "• <code>/welcome on</code> / <code>off</code>\n"
        "• <code>/welcome set TEXT</code> — set a text welcome\n"
        "• Reply to media/message with <code>/welcome set</code> — use that message/media\n"
        "• <code>/welcome test</code> — preview without a new join\n"
        "• <code>/welcome reset</code> — restore the default welcome\n"
        "• <code>/welcome deleteafter 30</code> — auto-delete after 30 seconds (0=off)\n"
        "• <code>/welcome buttons</code> — show buttons\n"
        "• <code>/welcome button LABEL | URL</code> — add a button\n"
        "• <code>/welcome clearbuttons</code> — remove buttons\n"
        "• <code>/welcome mention on/off</code> — control user mention\n"
        "• <code>/welcome photo on/off</code> — use profile photo when available\n"
        "• <code>/welcome help</code> — this help\n\n"
        "<b>Variables:</b>\n"
        "<code>{name}</code> <code>{full_name}</code> <code>{mention}</code> "
        "<code>{username}</code> <code>{id}</code> <code>{chat}</code> "
        "<code>{chat_id}</code> <code>{count}</code> <code>{date}</code> <code>{time}</code>\n\n"
        "Tip: HTML formatting is supported: <code>&lt;b&gt;bold&lt;/b&gt;</code>."
    )

def _render(template, user, chat, count, mention=True):
    now = datetime.now()
    name = escape(user.first_name or "there")
    full = escape(user.full_name or user.first_name or "there")
    username = ("@" + user.username) if user.username else "N/A"
    mention_html = user.mention_html(name) if mention else name
    vals = {
        "name": name, "full_name": full, "mention": mention_html,
        "username": escape(username), "id": str(user.id),
        "chat": escape(chat.title or "this group"), "chat_id": str(chat.id),
        "count": str(count), "date": now.strftime("%d %b %Y"),
        "time": now.strftime("%H:%M"),
    }
    # Unknown placeholders remain visible rather than crashing.
    return re.sub(r"\{([a-z_]+)\}", lambda m: str(vals.get(m.group(1), m.group(0))), template)

def _buttons(cfg):
    rows = []
    for b in cfg.get("buttons", [])[:12]:
        rows.append([InlineKeyboardButton(b["label"][:64], url=b["url"])])
    return InlineKeyboardMarkup(rows) if rows else None

async def welcome_cmd(update, context):
    if not _is_group(update):
        return await update.effective_message.reply_text("Use this command inside a group.")
    if not await _is_owner(update):
        return await update.effective_message.reply_text("❌ Only the group owner can configure the welcome system.")
    cfg = await get_welcome_config(update.effective_chat.id) or {
        "enabled": False, "text": DEFAULT_WELCOME, "delete_after": 0,
        "buttons": [], "mention": True, "profile_photo": False
    }
    args = list(context.args)
    if not args:
        return await update.effective_message.reply_text(
            f"👋 <b>Welcome System</b>\n\n"
            f"Status: {'🟢 ON' if cfg.get('enabled') else '🔴 OFF'}\n"
            f"Auto-delete: {int(cfg.get('delete_after',0))}s\n"
            f"Mention: {'ON' if cfg.get('mention',True) else 'OFF'}\n"
            f"Profile photo: {'ON' if cfg.get('profile_photo',False) else 'OFF'}\n"
            f"Buttons: {len(cfg.get('buttons',[]))}\n\n"
            f"Use <code>/welcome help</code> for all controls.",
            parse_mode="HTML", reply_markup=_buttons(cfg)
        )
    action=args[0].lower()
    cid=update.effective_chat.id
    if action=="help":
        return await update.effective_message.reply_text(_help(),parse_mode="HTML")
    if action in ("on","enable"):
        await update_welcome_config(cid,{"enabled":True})
        return await update.effective_message.reply_text("✅ Welcome system enabled.")
    if action in ("off","disable"):
        await update_welcome_config(cid,{"enabled":False})
        return await update.effective_message.reply_text("⏸️ Welcome system disabled.")
    if action=="set":
        text=" ".join(args[1:]).strip()
        msg=update.effective_message.reply_to_message
        data={"enabled":True}
        if msg:
            if msg.text:
                data["text"]=msg.text_html if getattr(msg,"text_html",None) else msg.text
                data["media_type"]="text"
            elif msg.photo:
                data["text"]=msg.caption_html if getattr(msg,"caption_html",None) else (msg.caption or DEFAULT_WELCOME)
                data["media_type"]="photo"; data["file_id"]=msg.photo[-1].file_id
            elif msg.video:
                data["text"]=msg.caption_html if getattr(msg,"caption_html",None) else (msg.caption or DEFAULT_WELCOME)
                data["media_type"]="video"; data["file_id"]=msg.video.file_id
            elif msg.animation:
                data["text"]=msg.caption_html if getattr(msg,"caption_html",None) else (msg.caption or DEFAULT_WELCOME)
                data["media_type"]="animation"; data["file_id"]=msg.animation.file_id
            elif msg.document:
                data["text"]=msg.caption_html if getattr(msg,"caption_html",None) else (msg.caption or DEFAULT_WELCOME)
                data["media_type"]="document"; data["file_id"]=msg.document.file_id
            else:
                return await update.effective_message.reply_text("❌ Reply to text, photo, video, GIF, or document.")
        elif text:
            data["text"]=text; data["media_type"]="text"
        else:
            return await update.effective_message.reply_text("Usage: /welcome set Your message\\nOr reply to a message/media with /welcome set")
        await update_welcome_config(cid,data)
        return await update.effective_message.reply_text("✅ Welcome message saved and enabled.")
    if action=="test":
        return await send_welcome(update.effective_chat, context, update.effective_user, test=True)
    if action=="reset":
        await update_welcome_config(cid,{"enabled":False,"text":DEFAULT_WELCOME,"media_type":"text","file_id":None,"delete_after":0,"buttons":[],"mention":True,"profile_photo":False})
        return await update.effective_message.reply_text("♻️ Welcome settings reset to defaults and disabled.")
    if action=="deleteafter":
        try: seconds=max(0,min(86400,int(args[1])))
        except (IndexError,ValueError): return await update.effective_message.reply_text("Usage: /welcome deleteafter <seconds> (0-86400)")
        await update_welcome_config(cid,{"delete_after":seconds})
        return await update.effective_message.reply_text(f"🗑️ Auto-delete set to {seconds} seconds.")
    if action=="mention":
        if len(args)<2 or args[1].lower() not in ("on","off"):
            return await update.effective_message.reply_text("Usage: /welcome mention on/off")
        await update_welcome_config(cid,{"mention":args[1].lower()=="on"})
        return await update.effective_message.reply_text("✅ Mention setting updated.")
    if action=="photo":
        if len(args)<2 or args[1].lower() not in ("on","off"):
            return await update.effective_message.reply_text("Usage: /welcome photo on/off")
        await update_welcome_config(cid,{"profile_photo":args[1].lower()=="on"})
        return await update.effective_message.reply_text("✅ Profile-photo setting updated.")
    if action=="button":
        raw=" ".join(args[1:]); parts=[p.strip() for p in raw.split("|",1)]
        if len(parts)!=2 or not parts[0] or not re.match(r"^https?://",parts[1]):
            return await update.effective_message.reply_text("Usage: /welcome button Label | https://example.com")
        buttons=cfg.get("buttons",[])[:11]; buttons.append({"label":parts[0],"url":parts[1]})
        await update_welcome_config(cid,{"buttons":buttons})
        return await update.effective_message.reply_text("🔘 Button added.")
    if action=="clearbuttons":
        await update_welcome_config(cid,{"buttons":[]})
        return await update.effective_message.reply_text("🧹 Welcome buttons cleared.")
    if action=="buttons":
        bs=cfg.get("buttons",[])
        return await update.effective_message.reply_text(
            "🔘 <b>Buttons</b>\n" + ("\n".join(f"• {escape(b['label'])} → {escape(b['url'])}" for b in bs) or "No buttons configured."),
            parse_mode="HTML", reply_markup=_buttons(cfg)
        )
    return await update.effective_message.reply_text("Unknown option. Use <code>/welcome help</code>.",parse_mode="HTML")

def _welcome_already_sent(chat_id, user_id):
    now = time.monotonic()
    key = (chat_id, user_id)
    # Drop expired entries.
    for k, ts in list(_WELCOME_DEDUP.items()):
        if now - ts > _WELCOME_DEDUP_TTL:
            _WELCOME_DEDUP.pop(k, None)
    if key in _WELCOME_DEDUP:
        return True
    _WELCOME_DEDUP[key] = now
    return False

async def send_welcome(chat, context, user, test=False):
    if chat.type not in (ChatType.GROUP, ChatType.SUPERGROUP): return
    cfg=await get_welcome_config(chat.id)
    if not cfg or (not cfg.get("enabled") and not test): return
    if not test and _welcome_already_sent(chat.id, user.id): return
    count=0
    try:
        count=await context.bot.get_chat_member_count(chat.id)
    except Exception: pass
    text=_render(cfg.get("text") or DEFAULT_WELCOME,user,chat,count,bool(cfg.get("mention",True)))
    markup=_buttons(cfg)
    media=cfg.get("media_type","text"); fid=cfg.get("file_id")
    kwargs={"chat_id":chat.id,"parse_mode":"HTML","reply_markup":markup}
    try:
        if media=="photo" and fid: sent=await context.bot.send_photo(photo=fid,caption=text,**kwargs)
        elif media=="video" and fid: sent=await context.bot.send_video(video=fid,caption=text,**kwargs)
        elif media=="animation" and fid: sent=await context.bot.send_animation(animation=fid,caption=text,**kwargs)
        elif media=="document" and fid: sent=await context.bot.send_document(document=fid,caption=text,**kwargs)
        else: sent=await context.bot.send_message(text=text,**kwargs)
        if not test and int(cfg.get("delete_after",0))>0:
            context.job_queue.run_once(_delete_welcome,int(cfg["delete_after"]),data=(chat.id,sent.message_id),name=f"welcome:{chat.id}:{sent.message_id}")
    except Exception:
        # If HTML in a custom message is malformed, retry as plain text.
        try:
            sent=await context.bot.send_message(chat.id,text=re.sub(r"<[^>]+>","",text))
            if not test and int(cfg.get("delete_after",0))>0:
                context.job_queue.run_once(_delete_welcome,int(cfg["delete_after"]),data=(chat.id,sent.message_id))
        except Exception:
            pass

async def _delete_welcome(context):
    chat_id,message_id=context.job.data
    try: await context.bot.delete_message(chat_id,message_id)
    except Exception: pass

async def monitor_welcome(update, context):
    """Handle Telegram chat_member join events (works for public/private groups when delivered)."""
    cm=update.chat_member
    if not cm or not cm.new_chat_member: return
    old=cm.old_chat_member.status
    new=cm.new_chat_member.status
    if new not in (ChatMemberStatus.MEMBER, ChatMemberStatus.RESTRICTED): return
    if old in (ChatMemberStatus.MEMBER, ChatMemberStatus.RESTRICTED, ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER): return
    user=cm.new_chat_member.user
    if not user or user.is_bot: return
    await send_welcome(cm.chat,context,user)

async def monitor_welcome_service_message(update, context):
    """Fallback for normal new_chat_members service messages. This is important for
    groups where chat_member updates are not delivered to the bot. It covers both
    public and private groups/supergroups."""
    msg=update.effective_message
    chat=update.effective_chat
    if not msg or not chat or chat.type not in (ChatType.GROUP, ChatType.SUPERGROUP): return
    members=getattr(msg, "new_chat_members", None) or []
    for user in members:
        if user and not user.is_bot:
            await send_welcome(chat, context, user)
