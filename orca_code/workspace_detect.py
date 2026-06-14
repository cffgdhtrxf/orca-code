"""orca_code.workspace_detect — Auto-detect project structure (P2-34).

Scans the working directory for known project markers and builds
a context summary that can be injected into the system prompt.

Detects:
  - Languages: Python, TypeScript, JavaScript, Rust, Go, Java, C/C++, etc.
  - Frameworks: React, Next.js, FastAPI, Django, Flask, etc.
  - Package managers: pip, npm, yarn, bun, cargo, go mod
  - Git repository info
  - Config files: CLAUDE.md, AGENTS.md, .cursorrules, etc.
  - LSP/Formatter configs

Usage:
    from orca_code.workspace_detect import detect_workspace
    info = detect_workspace()
    print(info.summary)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class WorkspaceInfo:
    language: str = "unknown"
    framework: str = ""
    package_manager: str = ""
    is_git_repo: bool = False
    git_branch: str = ""
    marker_files: list[str] = field(default_factory=list)
    config_files: list[str] = field(default_factory=list)
    summary: str = ""

    @property
    def has_project(self) -> bool:
        return self.language != "unknown" or bool(self.framework)


# ── Detection maps ──────────────────────────────────────────────────────────

LANGUAGE_MARKERS: dict[str, str] = {
    "pyproject.toml": "Python",
    "setup.py": "Python",
    "requirements.txt": "Python",
    "package.json": "TypeScript/JavaScript",
    "tsconfig.json": "TypeScript",
    "Cargo.toml": "Rust",
    "go.mod": "Go",
    "pom.xml": "Java",
    "build.gradle": "Java/Groovy",
    "CMakeLists.txt": "C/C++",
    "Makefile": "C/C++",
    "Gemfile": "Ruby",
    "composer.json": "PHP",
    "mix.exs": "Elixir",
    "Cargo.lock": "Rust",
    "bun.lock": "TypeScript/JavaScript (Bun)",
}

FRAMEWORK_MARKERS: dict[str, str] = {
    "next.config.js": "Next.js",
    "next.config.ts": "Next.js",
    "vite.config.ts": "Vite",
    "vite.config.js": "Vite",
    "svelte.config.js": "Svelte",
    "tailwind.config.js": "Tailwind CSS",
    "tailwind.config.ts": "Tailwind CSS",
    "django": "Django (detected in pyproject)",
    "fastapi": "FastAPI (detected in pyproject)",
    "flask": "Flask (detected in pyproject)",
}

CONFIG_FILE_MARKERS: list[str] = [
    "CLAUDE.md", "AGENTS.md", ".cursorrules", ".clinerules",
    ".windsurfrules", ".gemini", "COPILOT.md",
    ".editorconfig", ".prettierrc", ".eslintrc.js", ".eslintrc.json",
    "biome.json", "rustfmt.toml", ".ruff.toml", "pyproject.toml",
]

PACKAGE_MANAGER_MARKERS: dict[str, str] = {
    "pyproject.toml": "pip/poetry/uv",
    "requirements.txt": "pip",
    "package.json": "npm/yarn/bun",
    "bun.lock": "bun",
    "yarn.lock": "yarn",
    "package-lock.json": "npm",
    "Cargo.toml": "cargo",
    "go.mod": "go modules",
    "pom.xml": "maven",
    "build.gradle": "gradle",
}


def detect_workspace(root_dir: Path | None = None) -> WorkspaceInfo:
    """Scan the working directory for project structure.

    Args:
        root_dir: Directory to scan. Default: current working directory.

    Returns:
        WorkspaceInfo with detected project characteristics.
    """
    if root_dir is None:
        from orca_code.config import WORKING_DIR
        root_dir = WORKING_DIR

    root = Path(root_dir)
    info = WorkspaceInfo()

    # List all files in root (non-recursive, fast)
    try:
        root_files = {f.name for f in root.iterdir() if f.is_file()}
    except Exception:
        root_files = set()

    # Detect language
    for marker, lang in LANGUAGE_MARKERS.items():
        if marker in root_files:
            if not info.language or info.language == "unknown":
                info.language = lang
            info.marker_files.append(marker)

    # Detect framework
    for marker, framework in FRAMEWORK_MARKERS.items():
        if marker in root_files:
            info.framework = framework
            info.marker_files.append(marker)
            break

    # Deep check for Python frameworks in pyproject.toml
    if "pyproject.toml" in root_files:
        try:
            content = (root / "pyproject.toml").read_text(encoding="utf-8", errors="replace").lower()
            for kw in ["django", "fastapi", "flask"]:
                if kw in content:
                    info.framework = kw.title()
                    break
        except Exception:
            pass

    # Deep check for JS frameworks in package.json
    if "package.json" in root_files:
        try:
            import json
            pkg = json.loads((root / "package.json").read_text(encoding="utf-8"))
            deps = {**pkg.get("dependencies", {}), **pkg.get("devDependencies", {})}
            for kw in ["next", "react", "vue", "svelte", "express", "fastify"]:
                if kw in deps:
                    if not info.framework:
                        info.framework = kw.title()
                    break
        except Exception:
            pass

    # Detect package manager
    for marker, pm in PACKAGE_MANAGER_MARKERS.items():
        if marker in root_files:
            info.package_manager = pm
            break

    # Detect config files
    for cf in CONFIG_FILE_MARKERS:
        if cf in root_files:
            info.config_files.append(cf)

    # Git detection
    if (root / ".git").exists():
        info.is_git_repo = True
        try:
            import subprocess
            result = subprocess.run(
                ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                cwd=str(root), capture_output=True, text=True, timeout=5,
            )
            info.git_branch = result.stdout.strip()
        except Exception:
            info.git_branch = "unknown"

    # Build summary
    parts = []
    if info.language != "unknown":
        parts.append(f"语言: {info.language}")
    if info.framework:
        parts.append(f"框架: {info.framework}")
    if info.package_manager:
        parts.append(f"包管理: {info.package_manager}")
    if info.is_git_repo:
        parts.append(f"Git 分支: {info.git_branch or 'unknown'}")
    if info.config_files:
        parts.append(f"配置文件: {', '.join(info.config_files[:5])}")

    info.summary = " · ".join(parts) if parts else "无项目结构检测到"

    return info


def get_workspace_context() -> str:
    """Get a compact workspace summary for system prompt injection."""
    info = detect_workspace()
    if not info.has_project and not info.is_git_repo:
        return ""

    lines = ["[项目上下文]"]
    if info.language != "unknown":
        lines.append(f"语言: {info.language}")
    if info.framework:
        lines.append(f"框架: {info.framework}")
    if info.package_manager:
        lines.append(f"包管理: {info.package_manager}")
    if info.git_branch:
        lines.append(f"Git: {info.git_branch}")
    if info.config_files:
        lines.append(f"配置: {', '.join(info.config_files[:3])}")
    lines.append("")

    return "\n".join(lines)
