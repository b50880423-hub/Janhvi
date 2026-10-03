import logging
import re
from datetime import datetime, timezone
from telegram import Update
from telegram.ext import ContextTypes
from database import mongo
from config import HISTORY_SOURCE_BOT
from history_client import fetch_history, resolve_target_id, client as history_client

logger = logging.getLogger(__name__)


def _name(user):
    return (getattr(user, "full_name", "") or "").strip()

async def record_profile(user, source="message", chat_id=None):
    """Store a profile snapshot only when its observed name/username changes."""
    if not user or getattr(user, "is_bot", False) or mongo.profile_history is None:
        return
    now = datetime.now(timezone.utc)
    uid = int(user.id)
    username = getattr(user, "username", None)
    full_name = _name(user)
    latest = await mongo.profile_history.find_one({"user_id": uid}, sort=[("observed_at", -1)])
    if latest and latest.get("username") == username and latest.get("full_name") == full_name:
        # Update last-seen metadata without creating duplicate history entries.
        await mongo.profile_history.update_one({"_id": latest["_id"]}, {"$set": {"last_observed_at": now, "last_source": source}})
        return
    await mongo.profile_history.insert_one({
        "user_id": uid, "username": username, "username_lower": (username or "").lower(),
        "full_name": full_name, "full_name_lower": full_name.lower(),
        "observed_at": now, "last_observed_at": now, "source": source,
        "chat_id": int(chat_id) if chat_id is not None else None,
    })

async def profile_tracker_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    user = update.effective_user
    if msg and user:
        try: await record_profile(user, "message", update.effective_chat.id if update.effective_chat else None)
        except Exception: logger.exception("Could not record observed Telegram profile")

async def profile_tracker_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cm = update.chat_member
    if not cm: return
    user = getattr(cm.new_chat_member, "user", None)
    if user:
        try: await record_profile(user, "chat_member_update", cm.chat.id)
        except Exception: logger.exception("Could not record member profile")

async def profile_tracker_join(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    if not msg: return
    for user in (msg.new_chat_members or []):
        try: await record_profile(user, "new_chat_members", msg.chat.id)
        except Exception: logger.exception("Could not record joined member profile")

def _format_date(value):
    if not value: return "unknown time"
    if getattr(value, "tzinfo", None) is None: value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

def _chunks(text, limit=3900):
    text = text.strip()
    while len(text) > limit:
        cut = text.rfind("\n", 0, limit)
        if cut < limit // 2: cut = limit
        yield text[:cut]
        text = text[cut:].lstrip()
    if text: yield text

async def history_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.effective_message
    if not message: return
    if not context.args:
        await message.reply_text("Usage: /history USER_ID or /history @username\nExample: /history 6446674912\n\nDisplay-name searches only search records already observed by this bot: /history Rahul Sharma")
        return
    query = " ".join(context.args).strip()
    target_id = None
    if query.isdigit() or (query.startswith("@") and len(context.args) == 1):
        try: target_id = await resolve_target_id(query)
        except (ValueError, RuntimeError) as exc:
            await message.reply_text(str(exc)); return
    elif len(context.args) == 1 and context.args[0].startswith("@"):
        await message.reply_text("Could not resolve that username. Try the numeric Telegram user ID."); return

    local_records = []
    if target_id is not None:
        cur = mongo.profile_history.find({"user_id": target_id}).sort("observed_at", 1).limit(100)
        local_records = await cur.to_list(length=100)
    else:
        # Display names are not unique; return a small set of matching observed profiles.
        cur = mongo.profile_history.find({"full_name_lower": query.lower()}).sort("observed_at", -1).limit(10)
        matches = await cur.to_list(length=10)
        if not matches:
            await message.reply_text("No matching display name has been observed by this bot yet. Display names are not globally searchable through Telegram.")
            return
        ids = list(dict.fromkeys(int(r["user_id"]) for r in matches))
        await message.reply_text("Matching observed accounts:\n" + "\n".join(f"• {r.get('full_name') or '(no name)'} — ID `{r['user_id']}`" for r in matches[:10]), parse_mode="Markdown")
        return

    sections = [f"📚 Profile history for {target_id}"]
    if local_records:
        sections.append("\n🗃️ Your bot's observed history:")
        for rec in local_records:
            uname = "@" + rec["username"] if rec.get("username") else "(no username)"
            sections.append(f"• {rec.get('full_name') or '(no display name)'} | {uname}\n  First observed: {_format_date(rec.get('observed_at'))}")
    else:
        sections.append("\n🗃️ Your bot has not observed this profile yet.")

    # Reuse a successful past-source report first to preserve quota and make imported history durable.
    cached = await mongo.external_history_reports.find_one({"user_id": target_id}) if mongo.external_history_reports is not None else None
    if cached and cached.get("raw_report"):
        sections.append(f"\n🌐 Cached past history source (@{HISTORY_SOURCE_BOT.lstrip('@')}, fetched {_format_date(cached.get('fetched_at'))}):\n{cached['raw_report']}")
    else:
        try:
            source_messages = await fetch_history(target_id)
            raw_report = "\n\n".join(source_messages).strip()
            if raw_report:
                lower_report = raw_report.lower()
                quota_or_error = any(term in lower_report for term in (
                    "daily quota reached", "daily limit reached", "quota exceeded", "try again tomorrow",
                    "too many requests", "rate limit", "flood wait"
                ))
                if quota_or_error:
                    # Never cache quota/error replies as if they were a user's history.
                    sections.append(f"\n🌐 The history source is temporarily limiting requests:\n{raw_report}")
                else:
                    await mongo.external_history_reports.update_one(
                        {"user_id": target_id},
                        {"$set": {"user_id": target_id, "source": HISTORY_SOURCE_BOT, "raw_report": raw_report,
                                   "fetched_at": datetime.now(timezone.utc)}}, upsert=True)
                    sections.append(f"\n🌐 Past history source (@{HISTORY_SOURCE_BOT.lstrip('@')}):\n{raw_report}")
            else:
                sections.append("\n🌐 The external history source returned no text records.")
        except Exception as exc:
            logger.info("External history fetch unavailable for %s: %s", target_id, type(exc).__name__)
            sections.append(f"\n🌐 Past history source unavailable right now ({type(exc).__name__}). Local tracking will continue.")

    combined = "\n".join(sections)
    for part in _chunks(combined):
        await message.reply_text(part, disable_web_page_preview=True)
