import base64, hashlib, os
from cryptography.fernet import Fernet, InvalidToken
from config import BOT_TOKEN, WHISPER_ENCRYPTION_KEY

def _fernet():
    key = WHISPER_ENCRYPTION_KEY.strip() if WHISPER_ENCRYPTION_KEY else ""
    if not key:
        key = base64.urlsafe_b64encode(hashlib.sha256(BOT_TOKEN.encode()).digest()).decode()
    return Fernet(key.encode())

def encrypt_text(value: str) -> str:
    return _fernet().encrypt(value.encode("utf-8")).decode("utf-8")

def decrypt_text(value: str) -> str:
    try:
        return _fernet().decrypt(value.encode("utf-8")).decode("utf-8")
    except InvalidToken:
        return "[Message unavailable: encryption key changed or data is invalid]"
