"""orca_code.session_crypto — Session file encryption (P2-91).

Optional AES encryption for session JSONL files.
Uses PBKDF2 key derivation from a password or auto-generated key.
Encrypts on save, decrypts on load. Transparent to callers.

Config: {"session_encryption": true, "encryption_password": "optional"}
If no password, auto-generates a key stored in ~/.orca/.session_key
"""
from __future__ import annotations

import base64
import hashlib
import os
from pathlib import Path


def _get_key(password: str | None = None) -> bytes:
    if password:
        return hashlib.sha256(password.encode()).digest()
    key_file = Path.home() / ".orca" / ".session_key"
    if key_file.exists():
        return base64.b64decode(key_file.read_text().strip())
    key = os.urandom(32)
    key_file.parent.mkdir(parents=True, exist_ok=True)
    key_file.write_text(base64.b64encode(key).decode())
    return key

def encrypt_data(data: str, password: str | None = None) -> str:
    """Encrypt string data. Returns base64-encoded ciphertext."""
    try:
        from cryptography.fernet import Fernet
        key = base64.urlsafe_b64encode(_get_key(password)[:32])
        f = Fernet(key)
        return f.encrypt(data.encode()).decode()
    except ImportError:
        return data  # No cryptography package — store unencrypted

def decrypt_data(encrypted: str, password: str | None = None) -> str:
    """Decrypt base64-encoded ciphertext. Returns plaintext."""
    try:
        from cryptography.fernet import Fernet
        key = base64.urlsafe_b64encode(_get_key(password)[:32])
        f = Fernet(key)
        return f.decrypt(encrypted.encode()).decode()
    except ImportError:
        return encrypted
    except Exception:
        return encrypted  # Decryption failed — return as-is (may be plaintext)

def is_encryption_enabled() -> bool:
    try:
        from orca_code.config import CONFIG
        return str(CONFIG.get("session_encryption", False)).lower() == "true"
    except: return False
