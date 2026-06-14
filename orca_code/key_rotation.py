"""orca_code.key_rotation — API key rotation with multiple keys (P2-72).

Supports multiple API keys with round-robin rotation. When one key hits
rate limit, automatically switches to the next. Tracks per-key usage.

Config: {"api_keys": ["sk-key1", "sk-key2"], "api_key": "sk-default"}
If api_keys is provided, rotation is enabled. Falls back to api_key.
"""
from __future__ import annotations
import threading, time

class KeyRotator:
    def __init__(self, keys: list[str]):
        self._keys = keys
        self._idx = 0
        self._cooldowns: dict[int, float] = {}
        self._usage: dict[str, int] = {k:0 for k in keys}
        self._lock = threading.Lock()
    def next(self) -> str | None:
        with self._lock:
            now = time.time()
            for _ in range(len(self._keys)):
                key = self._keys[self._idx]
                self._idx = (self._idx + 1) % len(self._keys)
                if self._cooldowns.get(hash(key) % 1000, 0) < now:
                    self._usage[key] = self._usage.get(key, 0) + 1
                    return key
        return self._keys[0]  # all in cooldown, use first anyway
    def cooldown(self, key: str, seconds: float = 60):
        with self._lock:
            self._cooldowns[hash(key) % 1000] = time.time() + seconds
    @property
    def stats(self) -> dict:
        return {"keys": len(self._keys), "usage": dict(self._usage)}

_rotator: KeyRotator | None = None
def get_key_rotator() -> KeyRotator | None:
    global _rotator
    if _rotator is None:
        from orca_code.config import CONFIG
        keys = CONFIG.get("api_keys", [])
        if keys and isinstance(keys, list):
            _rotator = KeyRotator(keys)
    return _rotator
