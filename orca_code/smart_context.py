"""orca_code.smart_context — Smart context injection (P2-65).

Detects relevant project files based on user query keywords and injects
their summaries into the system context. Helps the model understand
the codebase without manually reading every file.

Strategy:
  - Scan recent tool outputs for file paths
  - Match file names/paths against query terms
  - Inject short file summaries (first N lines) into context
"""

from __future__ import annotations

from pathlib import Path


def find_relevant_files(query: str, root_dir: Path | None = None,
                        max_files: int = 5) -> list[Path]:
    """Find project files relevant to a query.

    Searches common project files (CLAUDE.md, README, *.py, etc.)
    whose names or paths contain query keywords.
    """
    if root_dir is None:
        from orca_code.config import WORKING_DIR
        root_dir = WORKING_DIR

    keywords = query.lower().split()
    if not keywords:
        return []

    matches: list[tuple[int, Path]] = []

    # Priority files to check
    priority = ["CLAUDE.md", "AGENTS.md", "README.md", "pyproject.toml",
                "package.json", "Cargo.toml", "Makefile"]

    for name in priority:
        p = root_dir / name
        if p.exists():
            score = sum(2 for kw in keywords if kw in name.lower())
            if score > 0:
                matches.append((score + 10, p))  # Priority bonus

    # Scan for source files matching keywords
    try:
        for ext in [".py", ".ts", ".tsx", ".js", ".rs", ".go", ".toml", ".json"]:
            for p in list(root_dir.glob(f"*{ext}"))[:20]:
                name_lower = p.name.lower()
                score = sum(1 for kw in keywords if kw in name_lower)
                if score > 0:
                    matches.append((score, p))
    except Exception:
        pass

    matches.sort(key=lambda x: x[0], reverse=True)
    return [m[1] for m in matches[:max_files]]


def get_context_snippet(file_path: Path, max_lines: int = 30) -> str:
    """Get a short summary of a file for context injection."""
    try:
        content = file_path.read_text(encoding="utf-8", errors="replace")
        lines = content.split("\n")[:max_lines]
        lang = file_path.suffix.lstrip(".")
        return f"--- {file_path.name} ({lang}) ---\n" + "\n".join(lines) + \
               ("\n... (truncated)" if len(content.split("\n")) > max_lines else "")
    except Exception:
        return f"--- {file_path.name} (unreadable) ---"


def build_smart_context(query: str, max_total_lines: int = 100) -> str:
    """Build a smart context block for injection into the system prompt.

    Args:
        query: The user's current question/message.
        max_total_lines: Max total lines of context to inject.

    Returns:
        A string to inject into the system prompt, or "" if nothing relevant.
    """
    files = find_relevant_files(query)
    if not files:
        return ""

    lines_per_file = max(10, max_total_lines // max(len(files), 1))
    snippets = []
    total_lines = 0

    for f in files:
        snippet = get_context_snippet(f, lines_per_file)
        snippet_lines = snippet.count("\n")
        if total_lines + snippet_lines > max_total_lines:
            break
        snippets.append(snippet)
        total_lines += snippet_lines

    if not snippets:
        return ""

    header = "[自动检测到的相关文件]\n"
    return header + "\n\n".join(snippets)
