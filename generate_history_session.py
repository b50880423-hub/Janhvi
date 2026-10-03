"""Run locally to create TELEGRAM_USER_SESSION for the optional history lookup.
Never upload this file's output publicly or commit it to GitHub.
"""
import asyncio
import os
from telethon import TelegramClient
from telethon.sessions import StringSession

async def main():
    api_id = (os.getenv("TELEGRAM_API_ID") or os.getenv("API_ID", "")).strip()
    api_hash = (os.getenv("TELEGRAM_API_HASH") or os.getenv("API_HASH", "")).strip()
    if not api_id or not api_hash:
        print("Set TELEGRAM_API_ID and TELEGRAM_API_HASH first.")
        print("Get them from https://my.telegram.org/apps")
        return
    async with TelegramClient(StringSession(), int(api_id), api_hash) as client:
        print("\nTELEGRAM_USER_SESSION (keep this secret; anyone with it may access your Telegram account):\n")
        print(client.session.save())

if __name__ == "__main__":
    asyncio.run(main())
