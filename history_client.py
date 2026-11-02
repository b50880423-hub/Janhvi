"""On-demand history-source client. Uses only the account/session configured by the operator."""
import asyncio
import logging
from telethon import TelegramClient
from telethon.sessions import StringSession
from config import TELEGRAM_API_ID, TELEGRAM_API_HASH, TELEGRAM_USER_SESSION, HISTORY_SOURCE_BOT

logger = logging.getLogger(__name__)
client = None
client_error = None
_request_lock = asyncio.Lock()

async def start_history_client():
    global client, client_error
    if not (TELEGRAM_API_ID and TELEGRAM_API_HASH and TELEGRAM_USER_SESSION):
        client_error = "External history lookup is not configured. Local history tracking still works."
        logger.info(client_error)
        return
    try:
        client = TelegramClient(StringSession(TELEGRAM_USER_SESSION), int(TELEGRAM_API_ID), TELEGRAM_API_HASH,
                                connection_retries=2, request_retries=2)
        await client.connect()
        if not await client.is_user_authorized():
            await client.disconnect(); client = None
            client_error = "The configured Telegram user session is not authorized."
            logger.error(client_error); return
        client_error = None
        logger.info("External history source client connected")
    except Exception as exc:
        logger.exception("Failed to connect external history client")
        client_error = f"External history connection failed ({type(exc).__name__})."
        if client:
            try: await client.disconnect()
            except Exception: pass
        client = None

async def stop_history_client():
    global client
    if client is not None:
        await client.disconnect(); client = None

async def resolve_target_id(query: str):
    """Resolve a numeric ID or @username to a numeric Telegram ID."""
    if query.isdigit(): return int(query)
    if client is None or not client.is_connected():
        raise RuntimeError("Username lookup needs the configured Telegram user session. Try a numeric user ID instead.")
    name = query.strip()
    if name.startswith('@'): name = name[1:]
    if not name or any(ch.isspace() for ch in name):
        raise ValueError("Please provide a numeric ID or a single @username.")
    try:
        entity = await client.get_entity(name)
        return int(entity.id)
    except Exception as exc:
        raise ValueError("Could not resolve that username through Telegram. It may be invalid or inaccessible.") from exc

async def fetch_history(target_id: int):
    """Ask the configured history source on demand. Results depend on its access and quota."""
    if client is None or not client.is_connected():
        raise RuntimeError(client_error or "External history client is not connected.")
    async with _request_lock:
        async with client.conversation(HISTORY_SOURCE_BOT, timeout=55, exclusive=True) as conv:
            await conv.send_message(str(target_id))
            try:
                first = await conv.get_response(timeout=45)
            except asyncio.TimeoutError as exc:
                raise TimeoutError("The external history source did not respond in time.") from exc
            messages=[]
            if first and getattr(first, 'raw_text', None): messages.append(first.raw_text)
            while len(messages) < 12:
                try: reply = await conv.get_response(timeout=3)
                except asyncio.TimeoutError: break
                if reply and getattr(reply, 'raw_text', None): messages.append(reply.raw_text)
            return messages
