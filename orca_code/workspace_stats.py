"""orca_code.workspace_stats — Workspace statistics (P2-87).

Counts files, lines of code by language, git stats.
"""
from __future__ import annotations
from pathlib import Path
from collections import defaultdict

EXT_MAP = {".py":"Python",".ts":"TypeScript",".tsx":"TSX",".js":"JavaScript",".rs":"Rust",
           ".go":"Go",".java":"Java",".c":"C",".cpp":"C++",".toml":"TOML",".json":"JSON",
           ".md":"Markdown",".txt":"Text",".html":"HTML",".css":"CSS"}

def get_workspace_stats(root: Path | None = None) -> dict:
    if root is None:
        from orca_code.config import WORKING_DIR
        root = WORKING_DIR
    root = Path(root)
    files_by_lang: dict[str, int] = defaultdict(int)
    lines_by_lang: dict[str, int] = defaultdict(int)
    total_files = 0
    total_lines = 0
    try:
        for f in root.rglob("*"):
            if f.is_file() and not any(p in str(f) for p in [".git","__pycache__","node_modules",".venv","target"]):
                total_files += 1
                lang = EXT_MAP.get(f.suffix, f"other({f.suffix})")
                files_by_lang[lang] += 1
                try:
                    lc = len(f.read_text(encoding="utf-8",errors="replace").splitlines())
                    lines_by_lang[lang] += lc
                    total_lines += lc
                except: pass
    except: pass
    return {"total_files": total_files, "total_lines": total_lines,
            "files_by_language": dict(files_by_lang), "lines_by_language": dict(lines_by_lang)}

def format_workspace_stats(stats: dict | None = None) -> str:
    if stats is None: stats = get_workspace_stats()
    lines = [f"工作区: {stats['total_files']} 文件, {stats['total_lines']:,} 行"]
    for lang, count in sorted(stats.get("files_by_language",{}).items(), key=lambda x:-x[1])[:8]:
        lc = stats.get("lines_by_language",{}).get(lang,0)
        lines.append(f"  {lang}: {count} files, {lc:,} lines")
    return "\n".join(lines)
