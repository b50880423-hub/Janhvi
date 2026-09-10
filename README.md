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
