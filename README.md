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

## Advanced command system

- `/help` — full command list
- `/settings` — inline admin settings
- `/warn` — add a warning to a replied user
- `/warnings` — view warnings
- `/resetwarnings` — reset warnings
- `/mute [minutes]` — manually mute a replied user
- `/unmute` — manually unmute a replied user
- `/whitelist` / `/unwhitelist` — bypass or restore anti-spam checks
- `/blacklist` / `/unblacklist` — future messages are automatically deleted + muted
- `/userinfo [USER_ID]` — moderation information
- `/lock TYPE` / `/unlock TYPE` — enable/disable protection types
- `/filter add WORD` / `/filter remove WORD` / `/filter list` — custom filters
- `/antispam on|off` — master protection switch
- `/logs` — recent MongoDB moderation logs

Lock types: `links`, `stickers`, `photos`, `videos`, `gifs`, `documents`, `forwards`, `mentions`, `flood`, `duplicate`, `badwords`, `all`.

Automatic moderation remains **delete + temporary mute only**: 30m, 1h, 2h, 6h, then 24h for the 5th and every later violation. No automatic permanent bans.


## 🤫 Group Whisper System

- `/whisper @username message` — create a protected group whisper
- Reply to a user's message with `/whisper message` — whisper to that user
- Only the sender and recipient can open a whisper
- Protected two-way conversation replies
- Anonymous content is not posted publicly
- `/whisperowner` — group owner read-only Whisper Vault
- Owner can inspect every stored whisper without marking it read, changing expiry, or modifying the conversation
- Whisper content is encrypted at rest
- Set `WHISPER_ENCRYPTION_KEY` to a Fernet key for a stable encryption key. If omitted, the bot derives a stable key from `BOT_TOKEN`.
- Owner audit access is intentionally owner-only; sudo users do not receive whisper-content access automatically.

### Privacy note
The Owner Vault is an explicit group-owner moderation feature. The bot stores whisper content server-side in encrypted form so the owner can perform read-only audits. This should be disclosed to group members in your own privacy policy/rules.
