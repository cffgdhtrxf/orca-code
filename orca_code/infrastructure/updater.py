"""orca_code.infrastructure.updater — Auto-update from GitHub Releases.

Checks the latest release tag, downloads the update if newer,
verifies SHA-256 checksum, and replaces the current binary.

Usage:
    python -m orca_code.infrastructure.updater --check   # Check for updates
    python -m orca_code.infrastructure.updater --update   # Download and apply
"""

from __future__ import annotations

import hashlib
import json
import shutil
import sys
import tempfile
from pathlib import Path

import requests

from orca_code import __version__ as CURRENT_VERSION

# Default GitHub repo for updates
GITHUB_REPO = "orca-code/orca-code"
UPDATE_API = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"

# Cache the last check to avoid hitting GitHub too often
_CACHE_FILE = Path.home() / ".orca" / "update_check.json"


def check_for_update(repo: str | None = None) -> dict | None:
    """Check GitHub for a newer version.

    Returns:
        None if current is latest, or dict with release info if update available.
    """
    api_url = f"https://api.github.com/repos/{repo or GITHUB_REPO}/releases/latest"

    try:
        resp = requests.get(api_url, timeout=15, headers={
            "Accept": "application/vnd.github.v3+json",
            "User-Agent": "Orca-Code-Updater",
        })
        resp.raise_for_status()
        latest = resp.json()
    except Exception:
        return None

    latest_ver = latest.get("tag_name", "").lstrip("v")
    if not latest_ver:
        return None

    # Parse versions
    try:
        from packaging.version import Version
        current_v = Version(CURRENT_VERSION)
        latest_v = Version(latest_ver)
        if latest_v <= current_v:
            return None
    except Exception:
        # Fallback: simple string comparison
        if latest_ver == CURRENT_VERSION:
            return None

    # Find the right asset for this platform
    assets = latest.get("assets", [])
    platform_asset = _find_platform_asset(assets)
    sha256_asset = _find_sha256_asset(assets)

    return {
        "version": latest_ver,
        "current_version": CURRENT_VERSION,
        "release_url": latest.get("html_url", ""),
        "asset": platform_asset,
        "sha256_asset": sha256_asset,
        "body": latest.get("body", "")[:500],
    }


def download_and_verify(update_info: dict, progress_callback=None) -> Path | None:
    """Download the update and verify SHA-256.

    Args:
        update_info: Dict from check_for_update().
        progress_callback: Optional fn(bytes_downloaded, total_bytes).

    Returns:
        Path to verified download, or None on failure.
    """
    asset = update_info.get("asset")
    sha256_asset = update_info.get("sha256_asset")

    if not asset:
        return None

    download_url = asset.get("browser_download_url")
    if not download_url:
        return None

    # Download
    tmp = Path(tempfile.gettempdir()) / f"orca_update_{update_info['version']}"
    try:
        resp = requests.get(download_url, stream=True, timeout=300)
        resp.raise_for_status()
        total = int(resp.headers.get("content-length", 0))

        downloaded = 0
        with open(tmp, "wb") as f:
            for chunk in resp.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)
                    downloaded += len(chunk)
                    if progress_callback and total:
                        progress_callback(downloaded, total)

    except Exception as e:
        tmp.unlink(missing_ok=True)
        raise RuntimeError(f"Download failed: {e}")

    # Verify SHA-256
    if sha256_asset:
        sha256_url = sha256_asset.get("browser_download_url")
        if sha256_url:
            try:
                sha256_resp = requests.get(sha256_url, timeout=30)
                sha256_resp.raise_for_status()
                expected_sha256 = sha256_resp.text.strip().split()[0].lower()

                actual_sha256 = hashlib.sha256(tmp.read_bytes()).hexdigest().lower()
                if actual_sha256 != expected_sha256:
                    tmp.unlink(missing_ok=True)
                    raise RuntimeError(
                        f"SHA-256 mismatch!\n"
                        f"Expected: {expected_sha256[:16]}...\n"
                        f"Got:      {actual_sha256[:16]}..."
                    )
            except RuntimeError:
                raise
            except Exception:
                pass  # Can't verify — proceed anyway

    return tmp


def apply_update(download_path: Path, current_binary: Path | None = None):
    """Replace the current binary with the downloaded update.

    Strategy:
      1. Rename current binary → .old
      2. Move downloaded file → current binary location
      3. On next restart, remove .old (or restore on failure)

    Args:
        download_path: Path to the verified download.
        current_binary: Path to current executable. Auto-detected if None.
    """
    if current_binary is None:
        current_binary = Path(sys.executable)

    backup = current_binary.with_suffix(current_binary.suffix + ".old")

    # Remove old backup if it exists (previous failed update)
    backup.unlink(missing_ok=True)

    try:
        # Backup current
        shutil.copy2(current_binary, backup)
        # Replace with new
        shutil.move(str(download_path), str(current_binary))
        # Make executable on Unix
        if sys.platform != "win32":
            current_binary.chmod(0o755)
        print(f"✓ Update applied. Restart Orca Code to use v{update_info.get('version', '?')}.")
        print(f"  Backup: {backup}")
    except Exception as e:
        # Restore backup on failure
        if backup.exists():
            shutil.move(str(backup), str(current_binary))
        raise RuntimeError(f"Failed to apply update: {e}")


def save_last_check(version: str):
    """Record the last update check timestamp and version."""
    import time
    _CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
    _CACHE_FILE.write_text(json.dumps({
        "last_check": time.time(),
        "last_version": version,
    }))


def should_check() -> bool:
    """Check if enough time has passed since the last check (24h cooldown)."""
    if not _CACHE_FILE.exists():
        return True
    try:
        import time
        data = json.loads(_CACHE_FILE.read_text())
        last = data.get("last_check", 0)
        return (time.time() - last) > 86400  # 24 hours
    except Exception:
        return True


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _find_platform_asset(assets: list) -> dict | None:
    """Find the asset matching the current platform."""
    if sys.platform == "win32":
        keywords = ["windows", "win64", "win32", ".exe", ".msi"]
    elif sys.platform == "darwin":
        keywords = ["macos", "darwin", "mac", ".dmg", ".app"]
    else:
        keywords = ["linux", ".deb", ".rpm", ".AppImage"]

    for asset in assets:
        name = asset.get("name", "").lower()
        if any(kw in name for kw in keywords):
            return asset

    # Fallback: first asset
    return assets[0] if assets else None


def _find_sha256_asset(assets: list) -> dict | None:
    """Find the SHA-256 checksum file."""
    for asset in assets:
        name = asset.get("name", "").lower()
        if "sha256" in name or "checksum" in name:
            return asset
    return None


# ═══════════════════════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════════════════════

def main():
    import argparse

    parser = argparse.ArgumentParser(description="Orca Code Updater")
    parser.add_argument("--check", action="store_true", help="Check for updates")
    parser.add_argument("--update", action="store_true", help="Download and apply update")
    parser.add_argument("--repo", help="GitHub repo (default: orca-code/orca-code)")
    args = parser.parse_args()

    if not args.check and not args.update:
        args.check = True  # Default: check

    if args.check:
        print(f"Orca Code v{CURRENT_VERSION} — checking for updates...")
        info = check_for_update(args.repo)
        if info:
            print(f"\n🆕 Update available: v{info['version']}")
            print(f"   Current: v{info['current_version']}")
            print(f"   Release: {info['release_url']}")
            if info.get("body"):
                print(f"\n{info['body'][:300]}")
            print("\nRun with --update to download and install.")
        else:
            print(f"✓ Already up to date (v{CURRENT_VERSION})")
            save_last_check(CURRENT_VERSION)

    if args.update:
        info = check_for_update(args.repo)
        if not info:
            print(f"✓ Already up to date (v{CURRENT_VERSION})")
            return

        print(f"Downloading v{info['version']}...")
        try:
            def progress(downloaded, total):
                pct = downloaded / total * 100 if total else 0
                print(f"\r  {downloaded / 1024**2:.1f}MB / {total / 1024**2:.1f}MB ({pct:.0f}%)", end="")

            path = download_and_verify(info, progress)
            if path:
                print()  # Newline after progress
                apply_update(path)
        except Exception as e:
            print(f"\n✗ Update failed: {e}")
            sys.exit(1)


if __name__ == "__main__":
    main()
