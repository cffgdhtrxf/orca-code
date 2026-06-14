"""orca_code.orcaignore — .orcaignore file support (P2-71).

Respects .orcaignore patterns when scanning files.
Same syntax as .gitignore. Falls back to .gitignore if .orcaignore not found.

Usage:
    from orca_code.orcaignore import should_ignore
    if should_ignore("node_modules/some_file.js"):
        skip  # Don't include in search results
"""

from __future__ import annotations

import os
from pathlib import Path


def _load_patterns(root_dir: Path) -> list[str]:
    """Load ignore patterns from .orcaignore or .gitignore."""
    # Try .orcaignore first, then .gitignore
    for name in [".orcaignore", ".gitignore"]:
        p = root_dir / name
        if p.exists():
            try:
                return [
                    line.strip()
                    for line in p.read_text(encoding="utf-8", errors="replace").splitlines()
                    if line.strip() and not line.strip().startswith("#")
                ]
            except Exception:
                pass
    return []


def _match_pattern(path: str, pattern: str) -> bool:
    """Simple glob-style pattern matching."""
    import fnmatch
    # Normalize path separators
    normalized = path.replace("\\", "/")
    # Handle directory patterns (ending with /)
    if pattern.endswith("/"):
        pattern = pattern[:-1]
        # Match directory name anywhere in path
        parts = normalized.split("/")
        return any(fnmatch.fnmatch(p, pattern) for p in parts)
    # Handle ** patterns
    if "**" in pattern:
        # Simple ** support: matches any number of directories
        regex_pattern = pattern.replace(".", "\\.").replace("**", ".*").replace("*", "[^/]*")
        import re
        return bool(re.match(f"^{regex_pattern}$", normalized))
    # Standard glob
    return fnmatch.fnmatch(normalized, pattern) or fnmatch.fnmatch(
        normalized.split("/")[-1], pattern
    )


def should_ignore(file_path: str, root_dir: Path | None = None) -> bool:
    """Check if a file should be ignored based on .orcaignore patterns."""
    if root_dir is None:
        from orca_code.config import WORKING_DIR
        root_dir = WORKING_DIR

    patterns = _load_patterns(root_dir)
    if not patterns:
        return False

    # Make path relative to root
    try:
        rel_path = os.path.relpath(file_path, str(root_dir))
    except ValueError:
        rel_path = file_path

    for pattern in patterns:
        if _match_pattern(rel_path, pattern):
            return True

    return False
