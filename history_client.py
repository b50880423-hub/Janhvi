"""Reliable on-demand SangMata history client.

Uses the operator's own Telegram user session. The bot token cannot be used for
SangMata because Telegram bots cannot initiate private chats with other bots.
"""
import asyncio
import logging
from telethon import TelegramClient
from telethon.sessions import StringSession
from config import TELEGRAM_API_ID, TELEGRAM_API_HASH, TELEGRAM_USER_SESSION, HISTORY_SOURCE_BOT, HISTORY_COMMAND

logger = logging.getLogger(__name__)
client = None
client_error = None
_request_lock = asyncio.Lock()
_start_lock = asyncio.Lock()


def _source_name():
    name = (HISTORY_SOURCE_BOT or "sangmata_bot").strip()
    if name.startswith("https://t.me/"):
        name = name.rsplit("/", 1)[-1]
    return name.lstrip("@").strip() or "sangmata_bot"


def status():
    """Return a safe diagnostic string; never exposes the session."""
    if not TELEGRAM_API_ID:
        return "TELEGRAM_API_ID is missing."
    if not TELEGRAM_API_HASH:
        return "TELEGRAM_API_HASH is missing."
    if not TELEGRAM_USER_SESSION:
        return "TELEGRAM_USER_SESSION is missing."
    if client is None:
        return client_error or "History client is not started."
    if not client.is_connected():
        return client_error or "History client is disconnected."
    return f"Connected as the configured Telegram user; source=@{_source_name()}."


async def start_history_client():
    global client, client_error
    async with _start_lock:
        if client is not None and client.is_connected():
            return True
        if not (TELEGRAM_API_ID and TELEGRAM_API_HASH and TELEGRAM_USER_SESSION):
            client = None
            client_error = "Missing TELEGRAM_API_ID, TELEGRAM_API_HASH, or TELEGRAM_USER_SESSION."
            logger.error(client_error)
            return False
        try:
            # Always discard a stale/disconnected object before creating a new one.
            if client is not None:
                try:
                    await client.disconnect()
                except Exception:
                    pass
            client = TelegramClient(
                StringSession(TELEGRAM_USER_SESSION.strip()),
                int(str(TELEGRAM_API_ID).strip()),
                TELEGRAM_API_HASH.strip(),
                connection_retries=3,
                request_retries=2,
                auto_reconnect=True,
            )
            await client.connect()
            if not await client.is_user_authorized():
                await client.disconnect()
                client = None
                client_error = "TELEGRAM_USER_SESSION is not authorized. Generate a fresh Telethon StringSession and replace the ENV value."
                logger.error(client_error)
                return False

            # Validate the session and the SangMata destination during startup.
            me = await client.get_me()
            if not me:
                raise RuntimeError("Telegram user session returned no account information.")
            source = await client.get_entity(_source_name())
            logger.info(
                "SangMata client connected as %s (id=%s), source=@%s (id=%s)",
                getattr(me, "username", None) or getattr(me, "first_name", "user"),
                me.id,
                _source_name(),
                getattr(source, "id", "unknown"),
            )
            client_error = None
            return True
        except Exception as exc:
            logger.exception("Failed to connect/validate SangMata client")
            client_error = f"SangMata startup failed: {type(exc).__name__}: {exc}"
            if client is not None:
                try:
                    await client.disconnect()
                except Exception:
                    pass
            client = None
            return False


async def stop_history_client():
    global client
    if client is not None:
        try:
            await client.disconnect()
        finally:
            client = None


async def _ensure_client():
    if client is None or not client.is_connected():
        ok = await start_history_client()
        if not ok:
            raise RuntimeError(client_error or "SangMata client is not connected.")
    return client


async def resolve_target_id(query: str):
    """Resolve a numeric ID or @username to a numeric Telegram ID."""
    if query.isdigit():
        return int(query)
    tg = await _ensure_client()
    name = query.strip()
    if name.startswith('@'):
        name = name[1:]
    if not name or any(ch.isspace() for ch in name):
        raise ValueError("Please provide a numeric ID or a single @username.")
    try:
        entity = await tg.get_entity(name)
        return int(entity.id)
    except Exception as exc:
        raise ValueError("Could not resolve that username through Telegram. It may be invalid or inaccessible.") from exc


async def fetch_history(target_id: int):
    """Query SangMata's documented private-chat allhistory command by numeric ID."""
    tg = await _ensure_client()
    async with _request_lock:
        try:
            source = await tg.get_entity(_source_name())
            # Capture the last message first so we only read SangMata's reply to
            # this request and never accidentally return an old cached reply.
            latest = await tg.get_messages(source, limit=1)
            before_id = latest[0].id if latest else 0

            command = (HISTORY_COMMAND or "allhistory").strip().lstrip("/") or "allhistory"
            await tg.send_message(source, f"/{command} {int(target_id)}")

            messages = []
            deadline = asyncio.get_running_loop().time() + 55
            while asyncio.get_running_loop().time() < deadline and len(messages) < 12:
                remaining = max(1.0, deadline - asyncio.get_running_loop().time())
                try:
                    fresh = await tg.get_messages(source, limit=12, min_id=before_id)
                    fresh = list(reversed(fresh))
                    for msg in fresh:
                        if not msg or msg.out:
                            continue
                        text = getattr(msg, "raw_text", None)
                        if text and text not in messages:
                            messages.append(text)
                    if messages:
                        # SangMata may send several messages; wait briefly for
                        # the rest before returning.
                        await asyncio.sleep(min(2.0, remaining))
                        more = await tg.get_messages(source, limit=12, min_id=before_id)
                        for msg in reversed(list(more)):
                            if msg and not msg.out:
                                text = getattr(msg, "raw_text", None)
                                if text and text not in messages:
                                    messages.append(text)
                        break
                except Exception as exc:
                    raise RuntimeError(f"SangMata request failed: {type(exc).__name__}: {exc}") from exc
                await asyncio.sleep(min(1.0, remaining))

            if not messages:
                raise TimeoutError("SangMata did not return a response within 55 seconds.")
            return messages
        except TimeoutError:
            raise
        except Exception as exc:
            logger.exception("SangMata fetch failed for %s", target_id)
            raise RuntimeError(f"SangMata fetch failed: {type(exc).__name__}: {exc}") from exc
