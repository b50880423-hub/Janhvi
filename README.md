# Janhvi Ultimate

Professional Telegram group management and moderation bot.

## Highlights
- Welcome/goodbye systems
- Moderation: warn, mute, tempmute, ban, tempban, unban, kick, purge
- Notes and custom commands
- Filters and Rose-style aliases: /filters, /stop, /stopall
- Content locks and /locks status
- Rules management: /setrules, /clearrules, /rules
- Anti-spam, anti-flood, anti-raid and adaptive security
- Reports with moderator action buttons
- Persistent temporary actions with MongoDB
- Group-specific settings and logs
- Multi-language setting support (English, Hindi, Bengali)
- Clean /janhvi command panel

## Deployment
Set BOT_TOKEN, MONGO_URI and MONGO_DB in Heroku config vars. The Procfile runs `python bot.py`.


## Ultimate v3 improvements
- Polished categorized /help command
- Fixed /report actions when the log destination is a separate chat
- Temporary mutes restore saved group default permissions when available
- Cleaned the /janhvi handler naming


## Profile history tracker

`/history USER_ID` or `/history @username` shows profile snapshots this bot has observed and, when configured, asks the configured third-party history source for older records. Source responses are cached in MongoDB so they remain available after redeployments. Third-party access, historical coverage, and quotas are controlled by that source; this bot cannot recover names Telegram never exposed to it.

The tracker stores a snapshot when a user sends a message to the bot or appears in supported group updates. It records a new row only when the observed display name or username changes. This is not retroactive: local history begins when the bot first observes a profile. Display-name search only searches locally observed profiles and names are not unique.

Optional external backfill requires `TELEGRAM_API_ID`, `TELEGRAM_API_HASH`, `TELEGRAM_USER_SESSION`, and `HISTORY_SOURCE_BOT`. Generate the session locally using `python generate_history_session.py`. Keep the session secret; it grants access to the Telegram account. If the source quota is exhausted, local tracking and previously cached reports still work.
