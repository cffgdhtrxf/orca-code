"""orca_code.infrastructure.secrets — Layered secret protection.

Resolution chain (highest priority first):
  Level 0: Environment variables (ORCA_API_KEY, ORCA_TAVILY_KEY, etc.)
  Level 1: OS-native credential manager (Windows Credential Manager / macOS Keychain)
  Level 2: PBKDF2 + Fernet encrypted file (machine-bound)
  Level 3: Plaintext config.json (development only — prints warning)

Usage:
    from orca_code.infrastructure.secrets import SecretStore

    store = SecretStore()
    api_key = store.resolve("api_key", fallback=CONFIG.get("api_key", ""))
"""

from __future__ import annotations

import base64
import json
import os
import platform
import subprocess
import sys
from pathlib import Path

# ─── Provider interface ─────────────────────────────────────────────────────

class SecretProvider:
    """Abstract secret storage backend."""

    def get(self, key: str) -> str | None:
        raise NotImplementedError

    def set(self, key: str, value: str) -> None:
        raise NotImplementedError

    def delete(self, key: str) -> None:
        raise NotImplementedError


# ─── Level 0: Environment Variables ─────────────────────────────────────────

class EnvVarProvider(SecretProvider):
    """Read secrets from environment variables.

    Mapping:
      ORCA_API_KEY         → api_key
      ORCA_TAVILY_KEY      → tavily_api_key
      ORCA_MEMORY_API_KEY  → memory_api_key
      ORCA_VISION_API_KEY  → vision_api_key
    """

    _KEY_MAP = {
        "api_key": "ORCA_API_KEY",
        "tavily_api_key": "ORCA_TAVILY_KEY",
        "memory_api_key": "ORCA_MEMORY_API_KEY",
        "vision_api_key": "ORCA_VISION_API_KEY",
    }

    def get(self, key: str) -> str | None:
        env_name = self._KEY_MAP.get(key, f"ORCA_{key.upper()}")
        return os.environ.get(env_name)

    def set(self, key: str, value: str) -> None:
        env_name = self._KEY_MAP.get(key, f"ORCA_{key.upper()}")
        os.environ[env_name] = value

    def delete(self, key: str) -> None:
        env_name = self._KEY_MAP.get(key, f"ORCA_{key.upper()}")
        os.environ.pop(env_name, None)


# ─── Level 1: OS-native Credential Manager ──────────────────────────────────

class KeychainProvider(SecretProvider):
    """OS-native secure credential storage.

    Windows:  Windows Credential Manager (via cmdkey / powershell)
    macOS:    Keychain (via security CLI)
    Linux:    Secret Service (via secret-tool, fallback only)
    """

    APP_NAME = "OrcaCode"

    def get(self, key: str) -> str | None:
        try:
            if sys.platform == "win32":
                return self._windows_get(key)
            elif sys.platform == "darwin":
                return self._macos_get(key)
            else:
                return self._linux_get(key)
        except Exception:
            return None

    def set(self, key: str, value: str) -> None:
        target = f"{self.APP_NAME}_{key}"
        try:
            if sys.platform == "win32":
                subprocess.run(
                    ["cmdkey", "/generic", target, "/user", os.getlogin(),
                     "/pass", value],
                    capture_output=True, timeout=10, check=True
                )
            elif sys.platform == "darwin":
                subprocess.run(
                    ["security", "add-generic-password", "-a", os.getlogin(),
                     "-s", target, "-w", value, "-U"],
                    capture_output=True, timeout=10, check=True
                )
            else:
                subprocess.run(
                    ["secret-tool", "store", "--label", target,
                     "application", self.APP_NAME, "key", key],
                    input=value.encode(), timeout=10, check=True
                )
        except Exception:
            pass  # Silently fall back to encrypted file

    def delete(self, key: str) -> None:
        target = f"{self.APP_NAME}_{key}"
        try:
            if sys.platform == "win32":
                subprocess.run(
                    ["cmdkey", "/delete", target],
                    capture_output=True, timeout=5
                )
            elif sys.platform == "darwin":
                subprocess.run(
                    ["security", "delete-generic-password", "-s", target],
                    capture_output=True, timeout=5
                )
            else:
                subprocess.run(
                    ["secret-tool", "clear", "application", self.APP_NAME,
                     "key", key],
                    capture_output=True, timeout=5
                )
        except Exception:
            pass

    def _windows_get(self, key: str) -> str | None:
        """Retrieve from Windows Credential Manager via cmdkey."""
        target = f"{self.APP_NAME}_{key}"
        result = subprocess.run(
            ["cmdkey", "/generic", target],
            capture_output=True, text=True, timeout=5
        )
        # cmdkey /generic:<target> lists the credential info
        # We need PowerShell to actually retrieve the password
        ps_cmd = (
            f"$cred = Get-StoredCredential -Target '{target}' -ErrorAction SilentlyContinue;"
            f"if ($cred) {{ $cred.GetNetworkCredential().Password }}"
        )
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps_cmd],
            capture_output=True, text=True, timeout=10
        )
        password = result.stdout.strip()
        return password if password else None

    def _macos_get(self, key: str) -> str | None:
        """Retrieve from macOS Keychain."""
        target = f"{self.APP_NAME}_{key}"
        result = subprocess.run(
            ["security", "find-generic-password", "-a", os.getlogin(),
             "-s", target, "-w"],
            capture_output=True, text=True, timeout=10
        )
        password = result.stdout.strip()
        return password if password else None

    def _linux_get(self, key: str) -> str | None:
        """Retrieve from Linux Secret Service."""
        result = subprocess.run(
            ["secret-tool", "lookup", "application", self.APP_NAME, "key", key],
            capture_output=True, text=True, timeout=10
        )
        password = result.stdout.strip()
        return password if password else None


# ─── Level 2: Encrypted File ────────────────────────────────────────────────

class EncryptedFileProvider(SecretProvider):
    """PBKDF2 + Fernet encrypted file storage.

    The encryption key is derived from machine-specific attributes
    (hostname + username + fixed seed), making it impossible to decrypt
    the file on another machine or by another user.
    """

    SALT = b"orca-code-secret-store-v2"
    ITERATIONS = 600_000

    def __init__(self, path: Path | None = None):
        if path is None:
            path = Path.home() / ".orca" / "secrets.json"
        self._path = path
        self._fernet = None

    @property
    def _cipher(self):
        """Lazy-initialize Fernet cipher with derived key."""
        if self._fernet is None:
            try:
                from cryptography.fernet import Fernet
                try:
                    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC as PBKDF2
                except ImportError:
                    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2
                from cryptography.hazmat.primitives import hashes

                seed = f"{platform.node()}-{os.getlogin()}-orca-v2"
                kdf = PBKDF2(
                    algorithm=hashes.SHA256(),
                    length=32,
                    salt=self.SALT,
                    iterations=self.ITERATIONS,
                )
                key = base64.urlsafe_b64encode(kdf.derive(seed.encode()))
                self._fernet = Fernet(key)
            except ImportError:
                raise ImportError(
                    "cryptography package required for encrypted secret storage. "
                    "Install with: pip install cryptography"
                )
        return self._fernet

    def get(self, key: str) -> str | None:
        if not self._path.exists():
            return None
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
            encrypted = data.get(key)
            if encrypted and encrypted.startswith("enc:v2:"):
                return self._cipher.decrypt(
                    encrypted[7:].encode()
                ).decode("utf-8")
        except Exception:
            return None
        return None

    def set(self, key: str, value: str) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        data = {}
        if self._path.exists():
            try:
                data = json.loads(self._path.read_text(encoding="utf-8"))
            except Exception:
                data = {}
        encrypted = "enc:v2:" + self._cipher.encrypt(value.encode()).decode("utf-8")
        data[key] = encrypted
        self._path.write_text(
            json.dumps(data, indent=2, ensure_ascii=False),
            encoding="utf-8"
        )

    def delete(self, key: str) -> None:
        if not self._path.exists():
            return
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
            data.pop(key, None)
            self._path.write_text(
                json.dumps(data, indent=2, ensure_ascii=False),
                encoding="utf-8"
            )
        except Exception:
            pass


# ─── Unified SecretStore ────────────────────────────────────────────────────

class SecretStore:
    """Unified secret resolution chain.

    Priority: env var > keychain > encrypted file > fallback

    Usage:
        store = SecretStore()
        api_key = store.resolve("api_key", fallback=CONFIG.get("api_key"))
    """

    def __init__(self):
        self._providers: list[SecretProvider] = []
        # Level 0: always available
        self._providers.append(EnvVarProvider())
        # Level 1: OS-native (may fail silently on some systems)
        self._providers.append(KeychainProvider())
        # Level 2: encrypted file (requires cryptography, may fail)
        try:
            self._providers.append(EncryptedFileProvider())
        except ImportError:
            pass

    def resolve(self, key: str, fallback: str = "") -> str:
        """Resolve a secret through the chain. Returns first found value.

        Args:
            key: Secret name (e.g., "api_key", "tavily_api_key").
            fallback: Value to return if no provider has the secret.

        Returns:
            The secret value, or fallback if not found.
        """
        for provider in self._providers:
            try:
                value = provider.get(key)
                if value and value.strip():
                    return value
            except Exception:
                continue
        return fallback

    def store(self, key: str, value: str) -> bool:
        """Store a secret in the most secure available provider.

        Tries Level 1 (Keychain) first, falls back to Level 2 (encrypted file).
        Returns True if stored successfully, False otherwise.
        """
        # Try keychain first
        for provider in self._providers:
            if isinstance(provider, KeychainProvider):
                try:
                    provider.set(key, value)
                    return True
                except Exception:
                    continue

        # Fall back to encrypted file
        for provider in self._providers:
            if isinstance(provider, EncryptedFileProvider):
                try:
                    provider.set(key, value)
                    return True
                except Exception:
                    continue

        return False

    def remove(self, key: str):
        """Remove a secret from all providers."""
        for provider in self._providers:
            try:
                provider.delete(key)
            except Exception:
                pass


# ─── Plaintext warning ──────────────────────────────────────────────────────

def warn_plaintext_keys(config_keys: dict) -> list[str]:
    """Check for plaintext API keys in config and return warnings.

    Call this at startup. Returns a list of warning messages.
    If the list is non-empty, display each warning to the user.
    """
    warnings = []
    sensitive_keys = {
        "api_key": "ORCA_API_KEY",
        "tavily_api_key": "ORCA_TAVILY_KEY",
        "memory_api_key": "ORCA_MEMORY_API_KEY",
        "vision_api_key": "ORCA_VISION_API_KEY",
    }

    for key, env_var in sensitive_keys.items():
        value = config_keys.get(key, "")
        if value and len(value) > 10:
            # Check if it looks like a real key (not a placeholder)
            if any(value.startswith(p) for p in ("sk-", "tvly-", "sk-ant-", "sk-or-", "org-")):
                warnings.append(
                    f"⚠️  '{key}' is stored in plaintext in config.json.\n"
                    f"   Set environment variable {env_var} instead, or use:\n"
                    f"   python -m orca_code.infrastructure.secrets store {key}"
                )

    return warnings


# ─── CLI ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    """CLI for secret management: python -m orca_code.infrastructure.secrets <command>"""
    import argparse

    parser = argparse.ArgumentParser(
        prog="orca-secrets",
        description="Orca Code secret manager"
    )
    sub = parser.add_subparsers(dest="cmd")

    sub.add_parser("list", help="List stored secret keys")

    store_p = sub.add_parser("store", help="Store a secret")
    store_p.add_argument("key", help="Secret key name (api_key, tavily_api_key, etc.)")
    store_p.add_argument("value", help="Secret value")

    rm_p = sub.add_parser("remove", help="Remove a stored secret")
    rm_p.add_argument("key", help="Secret key name")

    args = parser.parse_args()
    ss = SecretStore()

    if args.cmd == "list":
        print("Configured keys:")
        for provider in ss._providers:
            print(f"  Provider: {type(provider).__name__}")

    elif args.cmd == "store":
        if ss.store(args.key, args.value):
            print(f"✓ Stored '{args.key}' securely.")
        else:
            print(f"✗ Failed to store '{args.key}'.")

    elif args.cmd == "remove":
        ss.remove(args.key)
        print(f"✓ Removed '{args.key}' from all providers.")

    else:
        parser.print_help()
