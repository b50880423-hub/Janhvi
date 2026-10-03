"""Optional authenticated Telegram user client for on-demand history lookups.

This does not collect profile changes. It sends a user ID to the configured
history-source bot only when a user invokes /history.
"""
import asyncio
import logging

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


async def fetch_history(target_id: str) -> list[str]:
    """Ask the external history bot and return text messages it sends back."""
    if client is None or not client.is_connected():
        raise RuntimeError(client_error or "History client is not connected.")

    lock = getattr(fetch_history, "_lock", None)
    if lock is None:
        lock = asyncio.Lock()
        setattr(fetch_history, "_lock", lock)

    async with lock:
        async with client.conversation(HISTORY_SOURCE_BOT, timeout=55, exclusive=True) as conv:
            await conv.send_message(target_id)
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
