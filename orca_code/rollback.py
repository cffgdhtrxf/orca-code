"""orca_code.rollback — File change tracking and rollback (P2-32).

Tracks all file modifications made by tools (write_file, edit_file, apply_diff).
Allows undo of recent file operations. Stores snapshots before each modification.

Usage:
    from orca_code.rollback import FileTracker

    tracker = FileTracker()
    tracker.snapshot("/path/to/file.py")  # called BEFORE modification
    # ... tool modifies file ...
    tracker.record_change("/path/to/file.py", "edit_file")

    # Later, undo last operation:
    tracker.undo_last()  # restores file from snapshot

Commands:
    /undo         — undo last file operation
    /undo N       — undo last N operations
    /undo list    — list trackable changes
"""

from __future__ import annotations

import json
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class FileChange:
    """Record of a single file modification."""
    file_path: str
    tool_name: str
    snapshot_path: str | None = None  # path to backup file
    timestamp: float = field(default_factory=time.time)
    size_before: int = 0

    @property
    def age_seconds(self) -> float:
        return time.time() - self.timestamp


class FileTracker:
    """Tracks file changes and supports rollback.

    Stores file snapshots in a temp directory before each modification.
    Supports undo of recent operations.
    """

    def __init__(self, snapshot_dir: Path | None = None, max_snapshots: int = 50):
        if snapshot_dir is None:
            from orca_code.config import TEMP_DIR
            snapshot_dir = TEMP_DIR / "file_snapshots"
        self._dir = Path(snapshot_dir)
        self._dir.mkdir(parents=True, exist_ok=True)
        self._max_snapshots = max_snapshots
        self._changes: list[FileChange] = []

    def snapshot(self, file_path: str) -> str | None:
        """Create a backup of the file before modification.

        Returns the snapshot path, or None if the file doesn't exist.
        """
        p = Path(file_path)
        if not p.exists():
            return None

        ts = int(time.time() * 1000)
        snapshot_name = f"{p.name}.{ts}.bak"
        snapshot_path = self._dir / snapshot_name

        try:
            shutil.copy2(str(p), str(snapshot_path))
            return str(snapshot_path)
        except Exception:
            return None

    def record_change(self, file_path: str, tool_name: str, snapshot_path: str | None = None):
        """Record a file modification for potential rollback."""
        p = Path(file_path)
        size_before = 0
        if snapshot_path:
            try:
                size_before = Path(snapshot_path).stat().st_size
            except Exception:
                pass

        change = FileChange(
            file_path=str(p.resolve()),
            tool_name=tool_name,
            snapshot_path=snapshot_path,
            size_before=size_before,
        )
        self._changes.append(change)

        # Prune old snapshots
        while len(self._changes) > self._max_snapshots:
            old = self._changes.pop(0)
            if old.snapshot_path:
                try:
                    Path(old.snapshot_path).unlink(missing_ok=True)
                except Exception:
                    pass

    def undo_last(self) -> str:
        """Undo the most recent file change. Returns status message."""
        if not self._changes:
            return "没有可回滚的操作"

        change = self._changes.pop()
        if not change.snapshot_path:
            return f"无法回滚 '{change.file_path}': 没有快照"

        snapshot = Path(change.snapshot_path)
        target = Path(change.file_path)

        if not snapshot.exists():
            return f"无法回滚 '{change.file_path}': 快照已丢失"

        try:
            # Restore from snapshot
            shutil.copy2(str(snapshot), str(target))
            snapshot.unlink(missing_ok=True)
            return f"已回滚: {change.file_path} (工具: {change.tool_name}, {(time.time() - change.timestamp):.0f}秒前)"
        except Exception as e:
            return f"回滚失败: {e}"

    def undo_last_n(self, n: int) -> str:
        """Undo the last N file changes. Returns status message."""
        if n <= 0:
            return "请指定正整数"
        if n > len(self._changes):
            n = len(self._changes)

        results = []
        for _ in range(n):
            results.append(self.undo_last())

        return "\n".join(results)

    def list_changes(self) -> list[dict]:
        """List all trackable changes for display."""
        return [
            {
                "index": i + 1,
                "file": c.file_path,
                "tool": c.tool_name,
                "age_seconds": c.age_seconds,
                "size_kb": c.size_before // 1024 if c.size_before else 0,
            }
            for i, c in enumerate(self._changes)
        ]

    def format_changes(self) -> str:
        """Format the change list for display."""
        changes = self.list_changes()
        if not changes:
            return "(暂无文件变更记录)"

        lines = [f"最近 {len(changes)} 次文件变更:"]
        for c in reversed(changes[-10:]):  # Show last 10
            age = f"{c['age_seconds']:.0f}秒前" if c['age_seconds'] < 120 else f"{c['age_seconds'] / 60:.1f}分前"
            lines.append(f"  #{c['index']}: {c['file']} ({c['tool']}, {age}, {c['size_kb']}KB)")
        return "\n".join(lines)

    def clear(self):
        """Clear all tracked changes and delete snapshots."""
        for change in self._changes:
            if change.snapshot_path:
                try:
                    Path(change.snapshot_path).unlink(missing_ok=True)
                except Exception:
                    pass
        self._changes.clear()

    @property
    def pending_count(self) -> int:
        return len(self._changes)


# ═══════════════════════════════════════════════════════════════════════════════
# Singleton
# ═══════════════════════════════════════════════════════════════════════════════

_file_tracker: FileTracker | None = None


def get_file_tracker() -> FileTracker:
    """Get or create the global file tracker singleton."""
    global _file_tracker
    if _file_tracker is None:
        _file_tracker = FileTracker()
    return _file_tracker
