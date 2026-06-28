"""orca_code.version_check — Auto-update version checker (P2-76).

Checks for newer versions on startup. Shows notification if update available.
Uses GitHub releases API or a custom endpoint.
"""
from __future__ import annotations

import json
import threading
import time
import urllib.request

CURRENT_VERSION = "5.3.0"
CHECK_URL = "https://api.github.com/repos/user/orca-code/releases/latest"
_check_result: dict | None = None
_last_check = 0.0

def check_version_async():
    global _check_result, _last_check
    def _check():
        global _check_result, _last_check
        try:
            req = urllib.request.Request(CHECK_URL, headers={"User-Agent": "orca-code"})
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read())
                latest = data.get("tag_name", "").lstrip("v")
                if latest and latest != CURRENT_VERSION:
                    _check_result = {"update_available": True, "latest": latest,
                                     "current": CURRENT_VERSION,
                                     "url": data.get("html_url", "")}
                else:
                    _check_result = {"update_available": False, "current": CURRENT_VERSION}
        except Exception:
            _check_result = None
        _last_check = time.time()
    t = threading.Thread(target=_check, daemon=True)
    t.start()

def get_update_status() -> dict:
    return _check_result or {"update_available": False, "current": CURRENT_VERSION, "checked": False}
