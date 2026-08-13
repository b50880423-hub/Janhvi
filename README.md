# Ultra Telegram Group Security Bot

Advanced Python Telegram group security bot with MongoDB persistence, group-specific filters, automatic moderation, warnings, escalating mutes, logs, statistics, whitelist, inline-ready settings foundation, and Render health endpoint.

## Automatic punishment
- 1st violation: Delete + warning
- 2nd: Delete + warning
- 3rd: Delete + warning
- 4th: Delete + 20 minute mute
- 5th: Delete + 1 hour mute
- 6th: Delete + 2 hour mute
- 7th: Delete + 6 hour mute
- 8th+: Delete + 24 hour mute
- Never automatically bans.

## Commands

### Admin
`/settings`
`/antispam on`
`/antispam off`
`/lock TYPE`
`/unlock TYPE`
`/filter add WORD`
`/filter remove WORD`
`/filter list`
`/filter clear`
`/filter on`
`/filter off`
`/warn` (reply)
`/warnings` (reply)
`/resetwarnings` (reply)
`/mute [minutes]` (reply)
`/unmute` (reply)
`/whitelist` (reply)
`/unwhitelist` (reply)
`/userinfo` (reply)
`/stats`
`/logs`
`/status`
`/help`

Lock types:
`links stickers photos videos gifs documents forwards mentions flood duplicate badwords all`

## Per-group filters
Each group has its own MongoDB filter collection. A word added in Group A does not affect Group B.

## Render
Web Service:
- Build: `pip install -r requirements.txt`
- Start: `python bot.py`
- Health path: `/health`
- Instances: `1`

External pinger URL:
`https://YOUR-SERVICE.onrender.com/health`

## Telegram permissions
Make the bot an administrator with:
- Delete messages
- Restrict members

Do not run two polling instances with the same bot token; Telegram returns 409 Conflict.
