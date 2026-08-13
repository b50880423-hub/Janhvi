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


## Sticker & explicit-content protection

Normal stickers are allowed up to **10 stickers in 10 seconds per user**.
The 11th sticker within the rolling 10-second window is treated as sticker
spam and follows the normal violation escalation.

Explicit-content protection runs before ordinary spam rules. The project
supports explicit keyword detection in captions/text and a known-media-ID
hook. Telegram does not provide a native reliable NSFW/porn classification
flag for stickers, GIFs, photos, or videos, so a true visual classifier must
be connected to `services/media_safety.py:classify_media()` if you want
automatic visual detection of nude/sexual imagery.

When explicit content is positively classified, the intended action is:
**delete immediately + 24-hour mute on the first occurrence**.


## Real visual NSFW moderation

This version can perform actual visual moderation of Telegram photos, GIFs,
stickers and videos when Sightengine credentials are configured. Sightengine
documents that its nudity model works with images, GIFs and videos and returns
fine-grained classes such as `sexual_activity`, `sexual_display` and `erotica`.

Add these Render environment variables:

- `SIGHTENGINE_API_USER`
- `SIGHTENGINE_API_SECRET`
- `SIGHTENGINE_MODEL=nudity-2.1`
- `EXPLICIT_MUTE_MINUTES=1440`

The bot downloads the Telegram media temporarily, sends it to the moderation
API, deletes the temporary file, and then applies the action.

### Explicit-content action

A positively classified explicit item is handled immediately on its first
occurrence:

`Delete message -> 24-hour mute -> logger event`

Normal stickers are still allowed up to 10 in a rolling 10-second window.
The 11th+ sticker in that window follows the normal spam escalation.

If the visual moderation credentials are not configured, the bot does NOT
pretend it can identify nudity visually; it only uses explicit text/domain
signals.
