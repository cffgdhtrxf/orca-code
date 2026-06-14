"""orca_code.infrastructure.helpers — Utility functions extracted from config.py.

These are infrastructure concerns, not configuration:
  - get_api_balance() — query DeepSeek API for account balance
  - ensure_pkg() — auto-install missing Python packages
  - search_cache — simple dict cache for web search results
"""

from __future__ import annotations

import subprocess
import sys

# ─── Simple search cache ──────────────────────────────────────────────────────

search_cache: dict = {}


# ─── Package auto-install ─────────────────────────────────────────────────────

def ensure_pkg(pkg_name: str, import_name: str = "") -> bool:
    """Ensure a Python package is installed. Returns True if available."""
    if not import_name:
        import_name = pkg_name
    try:
        __import__(import_name)
        return True
    except ImportError:
        from orca_code.config import AUTO_INSTALL_DEPS
        if AUTO_INSTALL_DEPS:
            try:
                subprocess.check_call(
                    [sys.executable, "-m", "pip", "install", pkg_name],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                )
                return True
            except Exception:
                return False
        return False


# ─── API balance query ────────────────────────────────────────────────────────

_balance_cache: dict = {"value": "N/A", "ts": 0.0}


def get_api_balance() -> str:
    """Query DeepSeek API for account balance. Cached for 60 seconds."""
    import time as _time
    now = _time.time()
    if now - _balance_cache["ts"] < 60:
        return _balance_cache["value"]

    from orca_code.config import API_KEY, BASE_URL, IS_LOCAL
    if not API_KEY or IS_LOCAL:
        return "N/A"

    try:
        if "deepseek" in BASE_URL.lower():
            import requests
            resp = requests.get(
                "https://api.deepseek.com/user/balance",
                headers={"Authorization": f"Bearer {API_KEY}"},
                timeout=10,
            )
            if resp.status_code == 200:
                data = resp.json()
                bal = data.get("balance_infos", [{}])[0].get("total_balance", "?")
                _balance_cache["value"] = str(bal)
                _balance_cache["ts"] = now
                return str(bal)
    except Exception:
        pass
    return "N/A"
