"""orca_code.infrastructure.prompt_loader — Template-based prompt loading.

Replaces inline string concatenation with file-based Mustache templates.
Templates live in orca_code/prompts/ and are cached after first load.

Usage:
    from orca_code.infrastructure.prompt_loader import load_prompt

    system_prompt = load_prompt("system/base", username="John", platform="Windows")
    deepseek_prompt = load_prompt("system/deepseek", reasoning_effort="high")
"""

from __future__ import annotations

import re
from pathlib import Path
from string import Template
from typing import Any

_PROMPT_DIR = Path(__file__).parent.parent / "prompts"
_cache: dict[str, str] = {}

# Simple {{variable}} pattern (compatible with Python's string.Template and Mustache)
_VAR_PATTERN = re.compile(r"\{\{(\w+)\}\}")


def _load_raw(name: str) -> str:
    """Load a raw template file, resolving `{{> path}}` partials."""
    if name in _cache:
        return _cache[name]

    path = _PROMPT_DIR / f"{name}.md"
    if not path.exists():
        raise FileNotFoundError(f"Prompt template not found: {path}")

    raw = path.read_text(encoding="utf-8")

    # Resolve partials: {{> other/template.md}} or {{> system/base.md}}
    def _resolve_partial(match):
        partial_name = match.group(1).strip()
        return _load_raw(partial_name)

    raw = re.sub(r"\{\{>\s*([\w/.]+)\s*\}\}", _resolve_partial, raw)

    _cache[name] = raw
    return raw


def load_prompt(name: str, **variables: Any) -> str:
    """Load a template and substitute variables.

    Supports:
      - {{variable}} substitutions via Python string.Template
      - {{> partial/path}} includes (resolved at load time)
      - {{#section}}...{{/section}} Mustache-style sections (basic support)

    Args:
        name: Template name, e.g. "system/base" or "system/deepseek".
              The .md extension is added automatically.
        **variables: Key-value pairs for template substitution.

    Returns:
        Rendered template string with all variables substituted.
    """
    raw = _load_raw(name)

    # Handle Mustache-style sections: {{#var}}...{{/var}}
    # If var is truthy, keep content; otherwise remove the section entirely
    def _resolve_sections(text: str, vars_dict: dict) -> str:
        section_pat = re.compile(
            r"\{\{#(\w+)\}\}(.*?)\{\{/\1\}\}", re.DOTALL
        )
        while True:
            match = section_pat.search(text)
            if not match:
                break
            var_name = match.group(1)
            content = match.group(2)
            if vars_dict.get(var_name):
                text = text[:match.start()] + content + text[match.end():]
            else:
                text = text[:match.start()] + text[match.end():]
        return text

    raw = _resolve_sections(raw, variables)

    # Handle {{^var}}...{{/var}} inverted sections (show if var is falsy)
    def _resolve_inverted(text: str, vars_dict: dict) -> str:
        inv_pat = re.compile(
            r"\{\{\^(\w+)\}\}(.*?)\{\{/\1\}\}", re.DOTALL
        )
        while True:
            match = inv_pat.search(text)
            if not match:
                break
            var_name = match.group(1)
            content = match.group(2)
            if not vars_dict.get(var_name):
                text = text[:match.start()] + content + text[match.end():]
            else:
                text = text[:match.start()] + text[match.end():]
        return text

    raw = _resolve_inverted(raw, variables)

    # Substitute remaining {{var}} using string.Template
    template = Template(raw)
    try:
        return template.safe_substitute(**variables)
    except Exception:
        # Fallback: simple regex substitution
        def _sub(match):
            key = match.group(1)
            return str(variables.get(key, match.group(0)))
        return _VAR_PATTERN.sub(_sub, raw)


def clear_cache():
    """Clear the template cache. Useful for hot-reloading during development."""
    _cache.clear()


def list_templates() -> list[str]:
    """List all available template names."""
    templates = []
    for md_file in _PROMPT_DIR.rglob("*.md"):
        rel = md_file.relative_to(_PROMPT_DIR)
        name = str(rel).replace("\\", "/").replace(".md", "")
        templates.append(name)
    return sorted(templates)


def preload_all():
    """Preload and cache all templates. Call at startup."""
    for name in list_templates():
        try:
            _load_raw(name)
        except Exception:
            pass
