"""orca_native — Rust-accelerated operations with Python fallbacks.

Provides:
  search_content(pattern, directory, file_filter, max_results, context_lines)
  apply_diff(file_path, diff_text)
  walk_files(directory, pattern, max_files)

When the compiled Rust extension is available, these run 10-100x faster.
When not available (e.g., during development), pure Python fallbacks are used.
"""

from __future__ import annotations

import fnmatch
import os
import re
import subprocess
from pathlib import Path
from typing import Optional


# ── Try to load the compiled Rust module ────────────────────────────────────
_HAS_NATIVE = False
# The Rust lib exports PyInit_orca_native, but the Python package is also
# named orca_native. We load the .pyd via importlib and stash it under a
# private name to avoid the conflict.
_RUST_LIB = Path(__file__).parent.parent.parent / "target" / "release" / "orca_native.pyd"
if not _RUST_LIB.exists():
    _RUST_LIB = Path(__file__).parent.parent.parent / "target" / "release" / "orca_native.so"
if not _RUST_LIB.exists():
    _RUST_LIB = Path(__file__).parent.parent.parent / "target" / "release" / "orca_native.dll"

if _RUST_LIB.exists():
    try:
        import importlib.util
        import sys as _sys
        # Module name MUST be 'orca_native' to match PyInit_orca_native export.
        # But exec_module() adds it to sys.modules, shadowing this package.
        # Workaround: save our package ref, let loader run, then restore.
        _pkg = _sys.modules.get(__name__)
        spec = importlib.util.spec_from_file_location(
            "orca_native", str(_RUST_LIB)
        )
        if spec and spec.loader:
            _native_rs = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(_native_rs)
            _native_search = _native_rs.search_content
            _native_diff = _native_rs.apply_diff
            _native_walk = _native_rs.walk_files
            # Restore this package in sys.modules (loader overwrote it)
            if _pkg is not None:
                _sys.modules[__name__] = _pkg
            _HAS_NATIVE = True
    except Exception:
        pass


# ── Python fallback: search_content ──────────────────────────────────────────

def _py_search_content(
    pattern: str,
    directory: str,
    file_filter: Optional[str] = None,
    max_results: int = 100,
    context_lines: int = 0,
) -> str:
    """Pure Python fallback for code search."""
    base = Path(directory)
    if not base.is_dir():
        return f"Error: not a directory — {directory}"

    # Try ripgrep first (fastest Python-accessible path)
    try:
        cmd = ["rg", "--no-heading", "--line-number", "--max-count=100", pattern]
        if file_filter:
            cmd.extend(["--glob", file_filter])
        result = subprocess.run(
            cmd, cwd=str(base), capture_output=True, text=True, timeout=30,
            encoding="utf-8", errors="replace"
        )
        output = result.stdout.strip()
        if output:
            return "\n".join(output.split("\n")[:max_results])
    except (FileNotFoundError, Exception):
        pass

    # Fallback: Python rglob with regex
    pattern_re = re.compile(pattern, re.IGNORECASE)
    glob_pat = file_filter or "*"
    results = []
    file_count = 0
    max_files = 2000

    for f in base.rglob(glob_pat):
        if not f.is_file() or f.stat().st_size > 1_048_576:  # skip > 1MB
            continue
        file_count += 1
        if file_count > max_files:
            results.append(f"... (search truncated at {max_files} files)")
            break

        try:
            text = f.read_text(encoding="utf-8", errors="replace")
            for i, line in enumerate(text.splitlines(), 1):
                if pattern_re.search(line):
                    short = line.strip()[:300]
                    results.append(f"{f.relative_to(base)}:{i}: {short}")
                    if len(results) >= max_results:
                        break
        except Exception:
            continue
        if len(results) >= max_results:
            break

    if not results:
        return f"No matches found for '{pattern}'"
    return "\n".join(results)


# ── Python fallback: apply_diff ─────────────────────────────────────────────

def _py_apply_diff(file_path: str, diff_text: str) -> str:
    """Pure Python unified diff application."""
    import json

    path = Path(file_path)
    try:
        original = path.read_text(encoding="utf-8")
    except Exception as e:
        return json.dumps({"error": f"Cannot read file: {e}"})

    orig_lines = original.splitlines(keepends=True)
    result_lines = []
    orig_idx = 0

    # Parse hunks
    hunk_re = re.compile(r"^@@ -(\d+),?(\d*) \+(\d+),?(\d*) @@?(.*)$")
    hunks = []
    current = None

    for line in diff_text.splitlines():
        m = hunk_re.match(line)
        if m:
            if current:
                hunks.append(current)
            old_start = int(m.group(1))
            old_count = int(m.group(2)) if m.group(2) else 1
            new_start = int(m.group(3))
            new_count = int(m.group(4)) if m.group(4) else 1
            current = {"old_start": old_start, "old_count": old_count,
                       "new_start": new_start, "new_count": new_count, "lines": []}
        elif current:
            if line.startswith('+') and not line.startswith('+++'):
                current["lines"].append(('+', line[1:]))
            elif line.startswith('-') and not line.startswith('---'):
                current["lines"].append(('-', line[1:]))
            elif line.startswith(' ') or line == '':
                current["lines"].append((' ', line[1:] if line else ''))
    if current:
        hunks.append(current)

    if not hunks:
        return json.dumps({"error": "No hunks found in diff"})

    applied = 0
    for hunk in hunks:
        hunk_start = max(0, hunk["old_start"] - 1)

        # Lines before hunk
        while orig_idx < hunk_start and orig_idx < len(orig_lines):
            result_lines.append(orig_lines[orig_idx])
            orig_idx += 1

        for tag, text in hunk["lines"]:
            if tag == ' ':
                if orig_idx < len(orig_lines):
                    result_lines.append(orig_lines[orig_idx])
                    orig_idx += 1
                else:
                    result_lines.append(text + '\n')
            elif tag == '+':
                result_lines.append(text + '\n')
            elif tag == '-':
                if orig_idx < len(orig_lines):
                    orig_idx += 1

        applied += 1

    # Remaining lines
    while orig_idx < len(orig_lines):
        result_lines.append(orig_lines[orig_idx])
        orig_idx += 1

    new_content = ''.join(result_lines)

    # Atomic write
    tmp = path.with_suffix(path.suffix + '.tmp')
    tmp.write_text(new_content, encoding='utf-8')
    tmp.replace(path)

    return json.dumps({
        "applied": applied,
        "failed": 0,
        "total_hunks": len(hunks),
        "new_size": len(new_content),
    })


# ── Python fallback: walk_files ─────────────────────────────────────────────

def _py_walk_files(directory: str, pattern: str = "*", max_files: int = 5000) -> str:
    """Pure Python file walker with fnmatch."""
    base = Path(directory)
    if not base.is_dir():
        return f"Error: not a directory — {directory}"

    results = []
    count = 0
    for f in base.rglob(pattern):
        if f.is_file():
            results.append(str(f.relative_to(base)))
            count += 1
            if count >= max_files:
                results.append(f"... (truncated at {max_files})")
                break

    if not results:
        return f"No files matching '{pattern}'"
    return "\n".join(results)


# ── Public API ──────────────────────────────────────────────────────────────

def search_content(
    pattern: str,
    directory: str,
    file_filter: Optional[str] = None,
    max_results: int = 100,
    context_lines: int = 0,
) -> str:
    """Search file contents. Uses Rust ripgrep engine when available."""
    if _HAS_NATIVE:
        try:
            return _native_search(pattern, directory, file_filter, max_results, context_lines)
        except Exception:
            pass
    return _py_search_content(pattern, directory, file_filter, max_results, context_lines)


def apply_diff(file_path: str, diff_text: str) -> str:
    """Apply unified diff to a file. Uses Rust engine when available."""
    if _HAS_NATIVE:
        try:
            return _native_diff(file_path, diff_text)
        except Exception:
            pass
    return _py_apply_diff(file_path, diff_text)


def walk_files(directory: str, pattern: str = "*", max_files: int = 5000) -> str:
    """Walk directory tree with .gitignore support. Uses Rust when available."""
    if _HAS_NATIVE:
        try:
            return _native_walk(directory, pattern, max_files)
        except Exception:
            pass
    return _py_walk_files(directory, pattern, max_files)


def is_native_available() -> bool:
    """Check if the Rust native module is loaded."""
    return _HAS_NATIVE
