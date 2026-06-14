"""orca_code.session_tags — Session tagging for organization (P2-58).

Tags sessions with labels. Auto-tags based on project detection.
Filter sessions by tag. Store tags in session metadata.

Usage:
    from orca_code.session_tags import add_tag, remove_tag, get_tags, filter_by_tag
    add_tag("session_abc", "bug-fix")
    sessions = filter_by_tag("bug-fix")
"""

from __future__ import annotations

from pathlib import Path


def _meta_path(session_id: str, save_dir: Path | None = None) -> Path:
    if save_dir is None:
        from orca_code.config import SAVE_DIR
        save_dir = SAVE_DIR
    return save_dir / f"{session_id}.meta.json"


def _read_meta(session_id: str, save_dir: Path | None = None) -> dict:
    p = _meta_path(session_id, save_dir)
    if p.exists():
        import json
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def _write_meta(session_id: str, meta: dict, save_dir: Path | None = None):
    import json
    p = _meta_path(session_id, save_dir)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")


def add_tag(session_id: str, tag: str, save_dir: Path | None = None):
    meta = _read_meta(session_id, save_dir)
    tags: list = meta.get("tags", [])
    if tag not in tags:
        tags.append(tag)
    meta["tags"] = tags
    _write_meta(session_id, meta, save_dir)


def remove_tag(session_id: str, tag: str, save_dir: Path | None = None):
    meta = _read_meta(session_id, save_dir)
    tags: list = meta.get("tags", [])
    if tag in tags:
        tags.remove(tag)
    meta["tags"] = tags
    _write_meta(session_id, meta, save_dir)


def get_tags(session_id: str, save_dir: Path | None = None) -> list[str]:
    return _read_meta(session_id, save_dir).get("tags", [])


def filter_by_tag(tag: str, save_dir: Path | None = None) -> list[str]:
    """Return session IDs that have the given tag."""
    if save_dir is None:
        from orca_code.config import SAVE_DIR
        save_dir = SAVE_DIR
    results = []
    for meta_file in save_dir.glob("*.meta.json"):
        sid = meta_file.stem.replace(".meta", "")
        if tag in get_tags(sid, save_dir):
            results.append(sid)
    return results


def auto_tag(session_id: str, save_dir: Path | None = None):
    """Auto-tag session based on project detection."""
    try:
        from orca_code.workspace_detect import detect_workspace
        ws = detect_workspace()
        if ws.language != "unknown":
            add_tag(session_id, ws.language.lower(), save_dir)
        if ws.framework:
            add_tag(session_id, ws.framework.lower(), save_dir)
        if ws.is_git_repo:
            add_tag(session_id, "git", save_dir)
    except Exception:
        pass
