"""orca_code.worktree — Sub-agent worktree isolation (P2-14).

Inspired by omp's crates/pi-iso/ (APFS/btrfs/ZFS snapshot isolation).
Provides filesystem isolation for sub-agents using git worktrees.

Each sub-agent can run in an isolated working directory that:
  - Shares the git history (lightweight copy-on-write)
  - Has its own working tree for file modifications
  - Is cleaned up when the sub-agent completes
  - Falls back to temp directory copy if not in a git repo

Usage:
    from orca_code.worktree import WorktreeManager

    mgr = WorktreeManager()
    with mgr.create("sub-agent-abc") as workspace:
        # workspace is a Path to the isolated directory
        result = run_subagent(cwd=workspace)
    # workspace cleaned up automatically
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


class WorktreeError(Exception):
    """Failed to create or clean up a worktree."""


class WorktreeManager:
    """Manages isolated workspaces for sub-agents.

    Strategy (tried in order):
      1. git worktree — fastest, uses git's built-in worktree support
      2. directory copy — fallback for non-git repos
    """

    def __init__(self, base_dir: Path | None = None):
        if base_dir is None:
            from orca_code.config import TEMP_DIR
            base_dir = TEMP_DIR / "worktrees"
        self._base_dir = Path(base_dir)
        self._base_dir.mkdir(parents=True, exist_ok=True)
        self._active: set[Path] = set()

    def _is_git_repo(self, path: Path) -> bool:
        """Check if a directory is inside a git repository."""
        try:
            result = subprocess.run(
                ["git", "rev-parse", "--git-dir"],
                cwd=str(path),
                capture_output=True,
                text=True,
                timeout=5,
            )
            return result.returncode == 0
        except Exception:
            return False

    def _get_repo_root(self, path: Path) -> Path:
        """Get the root of the git repository containing path."""
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=str(path),
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode != 0:
            raise WorktreeError(f"Not a git repository: {path}")
        return Path(result.stdout.strip())

    @contextmanager
    def create(self, name: str = "", source_dir: Path | None = None) -> Iterator[Path]:
        """Create an isolated workspace and yield its path.

        Cleans up automatically when the context exits.

        Args:
            name: Human-readable name for the worktree (used in directory name).
            source_dir: Source directory to isolate. Default: current working dir.

        Yields:
            Path to the isolated workspace directory.
        """
        if source_dir is None:
            from orca_code.config import WORKING_DIR
            source_dir = WORKING_DIR

        source_dir = Path(source_dir).resolve()
        safe_name = name.replace("/", "_").replace("\\", "_").replace(" ", "-") or "agent"
        unique_id = str(uuid.uuid4())[:8]
        workspace_name = f"{safe_name}-{unique_id}"

        # Strategy 1: git worktree
        if self._is_git_repo(source_dir):
            workspace_path = self._create_git_worktree(source_dir, workspace_name)
        else:
            # Strategy 2: directory copy (slower but always works)
            workspace_path = self._create_dir_copy(source_dir, workspace_name)

        self._active.add(workspace_path)

        try:
            yield workspace_path
        finally:
            self._cleanup(workspace_path)

    def _create_git_worktree(self, repo_root: Path, name: str) -> Path:
        """Create a git worktree in the base directory."""
        repo_root = self._get_repo_root(repo_root)
        worktree_path = self._base_dir / name

        # Determine the base branch
        try:
            result = subprocess.run(
                ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                cwd=str(repo_root),
                capture_output=True,
                text=True,
                timeout=5,
            )
            branch = result.stdout.strip() or "main"
        except Exception:
            branch = "main"

        # Create a new branch for the worktree
        wt_branch = f"orca-wt/{name}"

        try:
            subprocess.run(
                ["git", "worktree", "add", "-b", wt_branch, str(worktree_path), branch],
                cwd=str(repo_root),
                capture_output=True,
                text=True,
                timeout=30,
                check=True,
            )
        except subprocess.CalledProcessError as e:
            # Branch might already exist — try without -b
            try:
                subprocess.run(
                    ["git", "worktree", "add", str(worktree_path), branch],
                    cwd=str(repo_root),
                    capture_output=True,
                    text=True,
                    timeout=30,
                    check=True,
                )
            except subprocess.CalledProcessError:
                raise WorktreeError(
                    f"Failed to create git worktree at {worktree_path}: {e.stderr}"
                )

        return worktree_path

    def _create_dir_copy(self, source_dir: Path, name: str) -> Path:
        """Create a copy of the source directory (fallback for non-git repos)."""
        dest = self._base_dir / name

        try:
            shutil.copytree(
                source_dir,
                dest,
                symlinks=True,
                ignore=shutil.ignore_patterns(
                    ".git", "__pycache__", "*.pyc", ".venv",
                    "node_modules", ".cache", "*.egg-info",
                    "temp", "save", "logs", "output",
                ),
            )
        except Exception as e:
            raise WorktreeError(f"Failed to copy directory to {dest}: {e}")

        return dest

    def _cleanup(self, workspace_path: Path):
        """Remove the workspace and its git worktree registration."""
        self._active.discard(workspace_path)

        if not workspace_path.exists():
            return

        # Check if it's a git worktree
        if (workspace_path / ".git").exists():
            try:
                # Prune the worktree from git
                repo_root = self._get_repo_root(workspace_path)
                subprocess.run(
                    ["git", "worktree", "remove", "--force", str(workspace_path)],
                    cwd=str(repo_root),
                    capture_output=True,
                    timeout=10,
                )
                # Also prune the branch
                wt_branch = f"orca-wt/{workspace_path.name}"
                subprocess.run(
                    ["git", "branch", "-D", wt_branch],
                    cwd=str(repo_root),
                    capture_output=True,
                    timeout=5,
                )
            except Exception:
                pass

        # Force remove any remaining files
        try:
            if workspace_path.exists():
                shutil.rmtree(workspace_path, ignore_errors=True)
        except Exception:
            pass

    def cleanup_all(self):
        """Clean up all active workspaces."""
        for path in list(self._active):
            self._cleanup(path)
        self._active.clear()

    @property
    def active_count(self) -> int:
        return len(self._active)


# ═══════════════════════════════════════════════════════════════════════════════
# Singleton
# ═══════════════════════════════════════════════════════════════════════════════

_worktree_manager: WorktreeManager | None = None


def get_worktree_manager() -> WorktreeManager:
    """Get or create the global worktree manager singleton."""
    global _worktree_manager
    if _worktree_manager is None:
        _worktree_manager = WorktreeManager()
    return _worktree_manager
