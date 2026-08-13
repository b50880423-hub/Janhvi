# Advanced Telegram AntiSpam Bot

A MongoDB-backed Telegram group moderation bot for automatic spam protection.

## Features
- Anti-link
- Anti-sticker/photo/video/GIF/document spam
- Anti-forward
- Flood/rate-limit detection
- Duplicate-message detection
- Mention spam
- Automatic delete + escalating temporary mute
- No automatic permanent bans
- Whitelist
- Inline settings panel
- Logger group
- Per-group MongoDB settings

## Deploy on Render
Create a **Background Worker**:
- Build command: `pip install -r requirements.txt`
- Start command: `python bot.py`

Environment variables:
- `BOT_TOKEN`
- `MONGO_URI`
- `MONGO_DB` (optional)
- `LOGGER_CHAT_ID` (optional)

Add the bot to your Telegram group as an administrator with:
- Delete messages
- Restrict members
- Ban users (recommended)
- Read messages / normal group permissions

Then use `/settings` in the group.

## Important
The bot cannot reliably moderate content it is not allowed to receive. In groups where Telegram privacy mode is enabled, disable privacy mode for the bot via BotFather so it can inspect normal group messages.

Do not give the bot more permissions than needed.

## Automatic punishment
The anti-spam engine only performs:
1. Delete the offending message.
2. Temporarily mute the user.

Escalation:
- 1st violation: 30 minutes
- 2nd: 1 hour
- 3rd: 2 hours
- 4th: 6 hours
- 5th and every later violation: 24 hours

The bot never automatically permanently bans users.


## Render Web Service + Pinger
This version exposes a health endpoint for uptime monitors.

Render:
- Service type: Web Service
- Build command: `pip install -r requirements.txt`
- Start command: `python bot.py`
- Instances: 1

Health endpoints: `/`, `/health`, `/healthz`.
Use `https://YOUR-SERVICE.onrender.com/health` in your HTTP uptime monitor.

Only one process may poll the same Telegram bot token.
