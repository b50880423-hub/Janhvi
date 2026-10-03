"""Generate a Telethon StringSession locally. Keep the output secret."""
import asyncio, os
from telethon import TelegramClient
from telethon.sessions import StringSession
async def main():
    api_id=os.getenv("TELEGRAM_API_ID", "").strip(); api_hash=os.getenv("TELEGRAM_API_HASH", "").strip()
    if not api_id or not api_hash:
        print("Set TELEGRAM_API_ID and TELEGRAM_API_HASH first; obtain them from https://my.telegram.org/apps")
        return
    async with TelegramClient(StringSession(), int(api_id), api_hash) as client:
        print("\nTELEGRAM_USER_SESSION (secret; do not share or commit):\n")
        print(client.session.save())
if __name__ == "__main__": asyncio.run(main())
