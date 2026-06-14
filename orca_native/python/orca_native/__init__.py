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
            # Phase 5: try new tokenizer and encoding functions
            try:
                _native_count_tokens = _native_rs.count_tokens
                _native_count_tokens_batch = _native_rs.count_tokens_batch
                _native_detect_encoding = _native_rs.detect_encoding
                _HAS_NATIVE_TOKENIZER = True
            except AttributeError:
                _HAS_NATIVE_TOKENIZER = False
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


# ── Phase 5: Tokenizer ─────────────────────────────────────────────────────

_HAS_NATIVE_TOKENIZER = False


def count_tokens(text: str) -> int:
    """Fast token count estimate (cl100k_base approximation).

    Uses Rust native implementation when available; falls back to
    word-based estimator in pure Python.
    """
    if _HAS_NATIVE and _HAS_NATIVE_TOKENIZER:
        try:
            return _native_count_tokens(text)
        except Exception:
            pass
    return _py_count_tokens(text)


def count_tokens_batch(texts: list[str]) -> list[int]:
    """Batch token count (parallel when native is available)."""
    if _HAS_NATIVE and _HAS_NATIVE_TOKENIZER:
        try:
            return _native_count_tokens_batch(texts)
        except Exception:
            pass
    return [_py_count_tokens(t) for t in texts]


def _py_count_tokens(text: str) -> int:
    """Pure Python token estimator (cl100k_base approximation)."""
    if not text:
        return 0
    import unicodedata
    count = 0
    for ch in text:
        cat = unicodedata.category(ch)
        if cat.startswith('L') and unicodedata.east_asian_width(ch) in ('W', 'F'):
            count += 1
        elif cat.startswith('L') or cat.startswith('N'):
            count += 0.25
        elif ch.isspace():
            count += 1
        else:
            count += 1
    return max(1, int(count * 1.05))


# ── Phase 5: Encoding Detection ─────────────────────────────────────────────

def detect_encoding(path: str):
    """Detect file encoding. Returns EncodingInfo or tuple (encoding, confidence, has_bom).

    Uses Rust native implementation when available.
    """
    if _HAS_NATIVE and _HAS_NATIVE_TOKENIZER:
        try:
            return _native_detect_encoding(path)
        except Exception:
            pass
    return _py_detect_encoding(path)


def _py_detect_encoding(path: str):
    """Pure Python encoding detection (BOM + chardet fallback)."""
    p = Path(path)
    if not p.exists():
        return ("unknown", 0.0, False)

    data = p.read_bytes()[:65536]
    if not data:
        return ("ascii", 1.0, False)

    # BOM detection
    if len(data) >= 3 and data[:3] == b'\xef\xbb\xbf':
        return ("utf-8", 1.0, True)
    if len(data) >= 2 and data[:2] == b'\xfe\xff':
        return ("utf-16-be", 1.0, True)
    if len(data) >= 2 and data[:2] == b'\xff\xfe':
        return ("utf-16-le", 1.0, True)

    # UTF-8 validation
    try:
        data.decode('utf-8')
        return ("utf-8", 0.99, False)
    except UnicodeDecodeError:
        pass

    # Try charset-normalizer if available
    try:
        from charset_normalizer import from_bytes
        results = from_bytes(data)
        if results:
            best = results.best()
            if best:
                return (best.encoding or "unknown", best.fingerprint.confidence or 0.5, False)
    except ImportError:
        pass

    return ("unknown", 0.0, False)
