"""orca_code.daemon — Background persistent assistant.

Runs Orca Code as a background daemon process with:
  - Proactive thread: detects idle time → suggests work
  - Dream thread: periodic memory consolidation (every 24h)
  - PID lock: prevents multiple daemon instances
  - Status/logs commands for monitoring

Usage:
    orca daemon start     — Start in background
    orca daemon status    — Check if running
    orca daemon stop      — Stop gracefully
    orca daemon logs      — Show today's log
    orca daemon run       — Run in foreground (for debugging)

Inspired by Claude Code's KAIROS persistent assistant.
"""

from __future__ import annotations

import os
import signal
import sys
import threading
import time
from datetime import UTC, datetime
from pathlib import Path

# ═══════════════════════════════════════════════════════════════════════════════
# Paths
# ═══════════════════════════════════════════════════════════════════════════════

ORCA_DIR = Path.home() / ".orca"
LOCK_FILE = ORCA_DIR / "daemon.lock"
LOG_DIR = ORCA_DIR / "logs"
DAILY_LOG_FILE = LOG_DIR / f"daemon_{datetime.now().strftime('%Y%m%d')}.log"


def _ensure_dirs():
    for d in (ORCA_DIR, LOG_DIR):
        d.mkdir(parents=True, exist_ok=True)


# ═══════════════════════════════════════════════════════════════════════════════
# PID Lock
# ═══════════════════════════════════════════════════════════════════════════════

def acquire_lock() -> bool:
    """Try to acquire the daemon lock. Returns True on success."""
    _ensure_dirs()
    if LOCK_FILE.exists():
        try:
            pid = int(LOCK_FILE.read_text().strip())
            # Check if process is still alive
            os.kill(pid, 0)
            return False  # Process exists
        except (ValueError, OSError):
            # Stale lock — clean up
            LOCK_FILE.unlink(missing_ok=True)

    LOCK_FILE.write_text(str(os.getpid()))
    return True


def release_lock():
    """Release the daemon lock."""
    try:
        if LOCK_FILE.exists():
            pid = int(LOCK_FILE.read_text().strip())
            if pid == os.getpid():
                LOCK_FILE.unlink(missing_ok=True)
    except Exception:
        pass


def get_lock_pid() -> int | None:
    """Return the PID of the running daemon, or None."""
    if not LOCK_FILE.exists():
        return None
    try:
        pid = int(LOCK_FILE.read_text().strip())
        os.kill(pid, 0)
        return pid
    except (ValueError, OSError):
        return None


# ═══════════════════════════════════════════════════════════════════════════════
# Logging
# ═══════════════════════════════════════════════════════════════════════════════

def _log(level: str, message: str):
    """Write a log entry to the daily log file."""
    _ensure_dirs()
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    entry = f"[{ts}] [{level}] {message}\n"
    try:
        with open(DAILY_LOG_FILE, "a", encoding="utf-8", errors="replace") as f:
            f.write(entry)
    except Exception:
        pass


# ═══════════════════════════════════════════════════════════════════════════════
# Daemon Core
# ═══════════════════════════════════════════════════════════════════════════════

class Daemon:
    """Persistent background assistant.

    Runs three loops:
      - Main loop: signal handling, heartbeat
      - Proactive loop: detects idle → suggests work (every 5 min)
      - Dream loop: memory consolidation (every 24h)
    """

    IDLE_THRESHOLD = 900  # 15 minutes → suggest work
    PROACTIVE_INTERVAL = 300  # Check every 5 minutes
    DREAM_INTERVAL = 86400  # 24 hours

    def __init__(self):
        self._running = False
        self._last_activity = time.time()
        self._last_dream = time.time()
        self._proactive_thread: threading.Thread | None = None
        self._dream_thread: threading.Thread | None = None

    # ── Start / Stop ─────────────────────────────────────────────────────────

    def start(self, foreground: bool = False):
        """Start the daemon.

        Args:
            foreground: If True, run in foreground (don't detach).
        """
        if not acquire_lock():
            existing_pid = get_lock_pid()
            raise RuntimeError(f"Daemon already running (PID {existing_pid})")

        self._running = True
        _log("INFO", f"Daemon started (PID {os.getpid()})")

        # Register signal handlers
        signal.signal(signal.SIGTERM, lambda s, f: self.stop())
        signal.signal(signal.SIGINT, lambda s, f: self.stop())

        # Start worker threads
        self._proactive_thread = threading.Thread(
            target=self._proactive_loop, daemon=True, name="orca-proactive"
        )
        self._proactive_thread.start()

        self._dream_thread = threading.Thread(
            target=self._dream_loop, daemon=True, name="orca-dream"
        )
        self._dream_thread.start()

        print(f"🐋 Orca Code Daemon started (PID {os.getpid()})")
        print(f"   Log: {DAILY_LOG_FILE}")

        if foreground:
            # Stay in foreground
            try:
                while self._running:
                    time.sleep(1)
            except KeyboardInterrupt:
                self.stop()
        else:
            print("   Running in background. Use 'orca daemon status' to check.")
            # Detach: parent exits, child continues
            if sys.platform != "win32":
                if os.fork() > 0:
                    os._exit(0)

    def stop(self):
        """Stop the daemon gracefully."""
        self._running = False
        _log("INFO", "Daemon stopping")
        release_lock()

    # ── Status ────────────────────────────────────────────────────────────────

    def status(self) -> dict:
        """Return current daemon status."""
        lock_pid = get_lock_pid()
        return {
            "running": lock_pid is not None,
            "pid": lock_pid,
            "this_pid": os.getpid(),
            "idle_minutes": (time.time() - self._last_activity) / 60 if self._running else 0,
            "hours_since_dream": (time.time() - self._last_dream) / 3600,
            "log_file": str(DAILY_LOG_FILE),
        }

    # ── Proactive Loop ────────────────────────────────────────────────────────

    def _proactive_loop(self):
        """Periodically check if the user needs assistance."""
        _log("INFO", "Proactive loop started")
        while self._running:
            time.sleep(self.PROACTIVE_INTERVAL)
            if not self._running:
                break

            idle_minutes = (time.time() - self._last_activity) / 60
            if idle_minutes * 60 >= self.IDLE_THRESHOLD:
                _log("INFO", f"User idle for {idle_minutes:.0f} min — suggesting work")
                self._suggest_work()

    def _suggest_work(self):
        """Generate a proactive suggestion based on recent activity."""
        try:
            from _memory_manager import MemoryManager
            from orca_code.config import SCRIPT_DIR

            db_path = str(SCRIPT_DIR / "memory" / "orca_memory.db")
            if not Path(db_path).exists():
                _log("DEBUG", "No memory DB, skipping suggestion")
                return

            mgr = MemoryManager(db_path)
            recent = mgr.get_recent_turns(limit=5)

            # Build a simple summary
            if recent:
                topics = set()
                for r in recent:
                    content = r.get("content", "")[:100]
                    # Extract key terms
                    import re
                    terms = re.findall(r'\b\w{4,}\b', content.lower())
                    topics.update(t for t in terms[:5] if t not in (
                        'this', 'that', 'with', 'from', 'your', 'have', 'what', 'when',
                    ))

                suggestion = (
                    f"Idle suggestion: based on recent topics ({', '.join(list(topics)[:5])}), "
                    f"consider reviewing recent changes or writing tests."
                )
                _log("SUGGEST", suggestion)

            mgr.close()
        except Exception as e:
            _log("ERROR", f"Proactive suggestion failed: {e}")

    # ── Dream Loop ────────────────────────────────────────────────────────────

    def _dream_loop(self):
        """Periodic memory consolidation (every 24h)."""
        _log("INFO", "Dream loop started")
        while self._running:
            time.sleep(3600)  # Check every hour
            if not self._running:
                break

            hours_since = (time.time() - self._last_dream) / 3600
            if hours_since >= 24:
                _log("INFO", "Starting dream cycle (memory consolidation)")
                self._run_dream()
                self._last_dream = time.time()

    def _run_dream(self):
        """Run memory consolidation: Orient → Gather → Consolidate → Prune."""
        try:
            from _memory_manager import MemoryManager
            from orca_code.config import SCRIPT_DIR

            db_path = str(SCRIPT_DIR / "memory" / "orca_memory.db")
            if not Path(db_path).exists():
                _log("INFO", "No memory DB, skipping dream")
                return

            mgr = MemoryManager(db_path)

            # Orient: check what we have
            total = mgr.get_memory_count()
            if total < 10:
                _log("INFO", f"Only {total} memories — skipping dream")
                mgr.close()
                return

            # Gather: get recent topics
            recent = mgr.get_recent_turns(limit=50)
            topics = []
            for r in recent:
                content = r.get("content", "")[:200]
                if content and len(content) > 30:
                    topics.append(content)

            # Consolidate: build a rolling summary
            summary_lines = []
            for t in topics[:10]:
                summary_lines.append(f"- {t[:120]}")

            summary = "Recent topics:\n" + "\n".join(summary_lines)
            if len(summary) > 2000:
                summary = summary[:2000]

            # Save consolidated summary
            mgr.set_meta("rolling_summary", summary)
            mgr.set_meta("rolling_summary_range", datetime.now().strftime("%Y-%m-%d"))
            mgr.set_meta("last_dream", datetime.now(UTC).isoformat())

            _log("DREAM", f"Consolidated {total} memories → summary ({len(summary)} chars)")
            mgr.close()

        except Exception as e:
            _log("ERROR", f"Dream cycle failed: {e}")

    # ── Activity tracking ─────────────────────────────────────────────────────

    def touch(self):
        """Mark user activity (call when the user sends a message)."""
        self._last_activity = time.time()


# ═══════════════════════════════════════════════════════════════════════════════
# CLI Commands
# ═══════════════════════════════════════════════════════════════════════════════

def cmd_status():
    """CLI: orca daemon status"""
    pid = get_lock_pid()
    if pid:
        print(f"🐋 Orca Code Daemon: [green]RUNNING[/green] (PID {pid})")
        print(f"   Lock: {LOCK_FILE}")
        print(f"   Logs: {LOG_DIR}")

        # Show recent log entries
        today_log = LOG_DIR / f"daemon_{datetime.now().strftime('%Y%m%d')}.log"
        if today_log.exists():
            lines = today_log.read_text(encoding="utf-8").strip().split("\n")[-5:]
            if lines:
                print("   Recent log:")
                for line in lines:
                    print(f"   {line}")
    else:
        print("🐋 Orca Code Daemon: [yellow]NOT RUNNING[/yellow]")


def cmd_stop():
    """CLI: orca daemon stop"""
    pid = get_lock_pid()
    if not pid:
        print("[yellow]Daemon is not running[/yellow]")
        return
    try:
        if sys.platform == "win32":
            os.kill(pid, signal.SIGTERM)
        else:
            os.kill(pid, signal.SIGTERM)
        print(f"[green]Sent stop signal to PID {pid}[/green]")
    except Exception as e:
        print(f"[red]Failed to stop daemon: {e}[/red]")


def cmd_logs(lines: int = 20):
    """CLI: orca daemon logs"""
    today_log = LOG_DIR / f"daemon_{datetime.now().strftime('%Y%m%d')}.log"
    if not today_log.exists():
        print("[yellow]No logs for today[/yellow]")
        return

    content = today_log.read_text(encoding="utf-8")
    log_lines = content.strip().split("\n")
    for line in log_lines[-lines:]:
        print(line)


# ═══════════════════════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════════════════════

def main():
    import argparse

    parser = argparse.ArgumentParser(description="Orca Code Daemon")
    sub = parser.add_subparsers(dest="cmd")

    sub.add_parser("start", help="Start daemon in background")
    sub.add_parser("run", help="Run daemon in foreground (debug)")
    sub.add_parser("status", help="Check daemon status")
    sub.add_parser("stop", help="Stop running daemon")
    logs_p = sub.add_parser("logs", help="Show daemon logs")
    logs_p.add_argument("-n", type=int, default=20, help="Number of lines")

    args = parser.parse_args()

    if args.cmd == "start":
        daemon = Daemon()
        daemon.start(foreground=False)

    elif args.cmd == "run":
        daemon = Daemon()
        daemon.start(foreground=True)

    elif args.cmd == "status":
        cmd_status()

    elif args.cmd == "stop":
        cmd_stop()

    elif args.cmd == "logs":
        cmd_logs(args.n)

    else:
        parser.print_help()


if __name__ == "__main__":
    main()
