"""Optional authenticated Telegram user client for on-demand history lookups.

This does not collect profile changes. It sends a user ID to the configured
history-source bot only when a user invokes /history.
"""
import asyncio
import logging
import re

from telethon import TelegramClient
from telethon.sessions import StringSession

from config import TELEGRAM_API_ID, TELEGRAM_API_HASH, TELEGRAM_USER_SESSION, HISTORY_SOURCE_BOT

logger = logging.getLogger(__name__)
client = None
client_error = None


async def start_history_client():
    """Connect using a pre-generated StringSession; never prompt on Heroku."""
    global client, client_error
    if not (TELEGRAM_API_ID and TELEGRAM_API_HASH and TELEGRAM_USER_SESSION):
        client_error = "History client is not configured. Set TELEGRAM_API_ID, TELEGRAM_API_HASH, and TELEGRAM_USER_SESSION."
        logger.info("History lookup disabled: user-client session not configured")
        return
    try:
        client = TelegramClient(
            StringSession(TELEGRAM_USER_SESSION),
            int(TELEGRAM_API_ID),
            TELEGRAM_API_HASH,
            connection_retries=2,
            request_retries=2,
        )
        await client.connect()
        if not await client.is_user_authorized():
            await client.disconnect()
            client = None
            client_error = "The Telegram user session is not authorized. Generate a fresh StringSession and update TELEGRAM_USER_SESSION."
            logger.error(client_error)
            return
        client_error = None
        logger.info("History source client connected")
    except Exception as exc:
        logger.exception("Could not start history source client")
        client_error = f"History client connection failed: {type(exc).__name__}"
        if client:
            try:
                await client.disconnect()
            except Exception:
                pass
        client = None


async def stop_history_client():
    global client
    if client is not None:
        await client.disconnect()
        client = None


async def fetch_history(target: str) -> list[str]:
    """Ask the external history bot and return text messages it sends back.

    Numeric IDs are sent as-is. @usernames are resolved to a numeric ID using
    the authenticated Telegram account when possible. Plain display names are
    forwarded as a best-effort query because Telegram does not offer a reliable
    global lookup by display name, and names are not unique.
    """
    if client is None or not client.is_connected():
        raise RuntimeError(client_error or "History client is not connected.")

    lock = getattr(fetch_history, "_lock", None)
    if lock is None:
        lock = asyncio.Lock()
        setattr(fetch_history, "_lock", lock)

    async with lock:
        query = target.strip()
        if re.fullmatch(r"\d{4,20}", query):
            source_query = query
        elif re.fullmatch(r"@?[A-Za-z][A-Za-z0-9_]{4,31}", query):
            username = query.lstrip("@")
            try:
                entity = await client.get_entity(username)
                source_query = str(entity.id)
            except Exception:
                # The source may accept usernames directly; let it try.
                source_query = "@" + username
        else:
            # Best effort only: the external source must implement name search.
            source_query = query

        async with client.conversation(HISTORY_SOURCE_BOT, timeout=55, exclusive=True) as conv:
            await conv.send_message(source_query)
            try:
                first = await conv.get_response(timeout=45)
            except asyncio.TimeoutError as exc:
                raise TimeoutError("The history source did not respond in time.") from exc

            messages = []
            if first and first.raw_text:
                messages.append(first.raw_text)
            while len(messages) < 12:
                try:
                    reply = await conv.get_response(timeout=3)
                except asyncio.TimeoutError:
                    break
                if reply and reply.raw_text:
                    messages.append(reply.raw_text)
            return messages
