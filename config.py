import os

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
MONGO_URI = os.getenv("MONGO_URI", "")
MONGO_DB = os.getenv("MONGO_DB", "antispam_bot")
LOGGER_CHAT_ID = int(os.getenv("LOGGER_CHAT_ID", "0") or 0)
WHISPER_ENCRYPTION_KEY = os.getenv("WHISPER_ENCRYPTION_KEY", "")

DEFAULT_SETTINGS = {
    "enabled": True,
    "antilink": True,
    "antisticker": False, "antiphoto": False, "antivideo": False,
    "antigif": False, "antidocument": False,
    "antiforward": True, "antimention": True, "antiflood": True,
    "antiduplicate": True, "badwords": True,
    "max_messages": 8, "window_seconds": 10,
    "max_duplicate": 4, "max_mentions": 8,
    "mute_minutes": 10,
    "auto_mute_after": 3,
    # Advanced safe moderation: violations decay after a clean period.
    "violation_decay_hours": 24,
    # First punishments are warnings only; escalation is per-user and per-group.
    "max_mute_minutes": 1440,
    "trust_messages": 25,
    "trusted_relaxation": 2,
    "new_user_grace_minutes": 2,
    "silent_mode": False,
    "reason_cooldown_seconds": 30,
    "smart_risk_enabled": True,
    "reputation_enabled": True,
    "anti_raid": True,
    "raid_join_threshold": 8,
    "raid_window_seconds": 60,
    "notify_warnings": True,
    "custom_filters": [],
    # Premium intelligence controls
    "mode": "adaptive",
    "threat_level": "SAFE",
    "lockdown": False,
    "similarity_enabled": True,
    "similarity_risk": True,
    "adaptive_baseline": True,
    "review_threshold": 70,
    "auto_action_threshold": 82,
    # Sticker safety: exact sticker IDs/packs are admin-managed; optional external
    # vision moderation can be integrated later if an API is configured.
    "nsfw_sticker_protection": True,
    "nsfw_sticker_ids": [],
    "blocked_sticker_sets": [],
    "sticker_limit": 6,
    "sticker_window_seconds": 12,
    "sticker_repeat_limit": 3,
    "security_panel": True,
    "review_queue_enabled": True,
    "new_member_message_limit": 10,
    "auto_raid_lockdown": True,
    "domain_whitelist": [],
    "domain_blacklist": [],
    "appeals_enabled": True,
}

# Optional external visual NSFW classifier. Leave empty to use conservative admin review only.
NSFW_CLASSIFIER_URL = os.getenv("NSFW_CLASSIFIER_URL", "")
NSFW_CLASSIFIER_API_KEY = os.getenv("NSFW_CLASSIFIER_API_KEY", "")
