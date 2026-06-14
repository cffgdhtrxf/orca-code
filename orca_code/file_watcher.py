"""orca_code.file_watcher — External file change watcher (P2-77).

Watches workspace files for external modifications. Notifies when files
are changed outside the agent, helping prevent stale context issues.

Uses polling (os.stat mtime) with configurable interval.
"""
from __future__ import annotations
import threading, time, os
from pathlib import Path

class FileWatcher:
    def __init__(self, root_dir: Path | None = None, interval: float = 2.0):
        if root_dir is None:
            from orca_code.config import WORKING_DIR
            root_dir = WORKING_DIR
        self._root = Path(root_dir)
        self._interval = interval
        self._mtimes: dict[str, float] = {}
        self._changes: list[dict] = []
        self._running = False
        self._thread: threading.Thread | None = None
    def start(self):
        if self._running: return
        self._running = True
        self._thread = threading.Thread(target=self._poll, daemon=True)
        self._thread.start()
    def stop(self):
        self._running = False
    def _poll(self):
        while self._running:
            try:
                for f in list(self._root.rglob("*"))[:200]:
                    if f.is_file() and not any(p in str(f) for p in [".git","__pycache__","node_modules",".venv"]):
                        key = str(f)
                        mtime = f.stat().st_mtime
                        if key in self._mtimes and self._mtimes[key] != mtime:
                            self._changes.append({"path": key, "time": time.time()})
                            if len(self._changes) > 100: self._changes.pop(0)
                        self._mtimes[key] = mtime
            except Exception: pass
            time.sleep(self._interval)
    @property
    def recent_changes(self) -> list[dict]:
        now = time.time()
        return [c for c in self._changes if now - c["time"] < 60]
    @property
    def change_count(self) -> int: return len(self.recent_changes)

_watcher: FileWatcher | None = None
def get_file_watcher() -> FileWatcher:
    global _watcher
    if _watcher is None: _watcher = FileWatcher(); _watcher.start()
    return _watcher
