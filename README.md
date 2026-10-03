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


## Optional: Telegram name-history lookup

The `/history USER_ID` command asks the configured history-source bot on demand and relays its text reply into this bot's chat. It does not automatically collect profile changes. Telegram does not provide a public API for all historical names; results depend on the external source's records, privacy settings, and quotas.

This integration uses a separately authenticated Telegram user session because bot accounts cannot message other bots. Configure these Heroku Config Vars:

- `API_ID` and `API_HASH` from https://my.telegram.org/apps (the `TELEGRAM_API_ID` / `TELEGRAM_API_HASH` aliases also work)
- `SESSION_STRING` generated locally with `python generate_history_session.py` after installing `requirements.txt` (the `TELEGRAM_USER_SESSION` alias also works)
- `BOT_OWNER_IDS` with your numeric Telegram user ID(s), comma-separated; only these owners can run `/history`
- `HISTORY_SOURCE_BOT` (defaults to `sangmata_bot`)

Keep `TELEGRAM_USER_SESSION` private. It grants access to the Telegram account used to create it. Do not commit it to GitHub or share it. Use an account you control, follow the source bot's rules and quota, and disable the integration by clearing these three config vars.

Example: `/history 6446674912`. The account used for the session must be able to open and message the configured history bot.
