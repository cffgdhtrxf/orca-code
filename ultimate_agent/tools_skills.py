"""ultimate_agent.tools_skills — Skill system + scheduler."""

import os, json, re, threading, time
import ast as _ast
from pathlib import Path
from typing import Optional, Dict
from datetime import datetime
from ultimate_agent.config import (CONFIG, SKILLS_DIR, LOGS_DIR, SCRIPT_DIR,
    console)
from ultimate_agent.security import (_SKILL_BLACKLIST, _SKILL_DANGEROUS_ATTRS,
    _SKILL_SAFE_BUILTINS, _scan_skill_ast, _safe_exec_skill)
from ultimate_agent.tools_core import execute_command
from ultimate_agent.tools_web import web_search

# Skill system globals
_loaded_skills: Dict[str, str] = {}
_md_skill_cache: Dict[str, Dict] = {}
_autoload_skills_cache: set = set()

def _parse_skill_md(filepath) -> Optional[Dict]:
    """Parse SKILL.md file with YAML frontmatter. Returns {meta, body} or None."""
    try:
        text = filepath.read_text(encoding="utf-8")
    except Exception:
        return None
    if not text.startswith("---"):
        return None
    parts = text.split("---", 2)
    if len(parts) < 3:
        return None
    raw_meta = parts[1].strip()
    body = parts[2].strip()
    meta = {}
    current_key = None
    for line in raw_meta.split("\n"):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if ":" in stripped:
            # Check if it's a key: value line vs a list item
            key_part, _, val_part = stripped.partition(":")
            key = key_part.strip()
            val = val_part.strip()
            if val:
                # key: value pair
                meta[key] = val
                current_key = key
            else:
                # key: with value on next line (start of list)
                current_key = key
                meta[key] = []
        elif stripped.startswith("- ") and current_key and isinstance(meta.get(current_key), list):
            meta[current_key].append(stripped[2:].strip())
    return {"meta": meta, "body": body}
def load_skill(name: str) -> str:
    p = SKILLS_DIR / f"{name}.py"
    if not p.exists():
        return f"错误: 技能文件不存在 - {p}"
    try:
        code = p.read_text(encoding="utf-8")
        ns = _safe_exec_skill(code, name)
        if isinstance(ns, str):
            return f"错误: {ns}"
        added = []
        for key, val in ns.items():
            if callable(val) and not key.startswith("_"):
                from ultimate_agent.main import TOOL_MAP
                TOOL_MAP[key] = val
                _loaded_skills[key] = name
                added.append(key)
        return f"已加载技能 '{name}'，注册工具: {', '.join(added) if added else '(无公开函数)'}"
    except Exception as e:
        return f"错误: 技能加载失败 - {e}"
def create_skill(name: str, code: str) -> str:
    p = SKILLS_DIR / f"{name}.py"
    try:
        p.write_text(code, encoding="utf-8")
        return f"已创建技能: {p}"
    except Exception as e:
        return f"错误: {e}"
def edit_skill(name: str, code: str) -> str:
    p = SKILLS_DIR / f"{name}.py"
    if not p.exists():
        return f"错误: 技能文件不存在 - {p}"
    try:
        p.write_text(code, encoding="utf-8")
        return f"已更新技能: {p}"
    except Exception as e:
        return f"错误: {e}"
def list_skills() -> str:
    py_files = sorted(SKILLS_DIR.glob("*.py"))
    md_files = sorted(SKILLS_DIR.glob("*.md"))
    lines = []
    if py_files:
        lines.append("[工具技能 .py]")
        for f in py_files:
            lines.append(f"  {f.stem}")
    else:
        lines.append("[工具技能 .py] (无)")
    if md_files:
        lines.append("[行为技能 .md]")
        for f in md_files:
            cached = _md_skill_cache.get(f.stem, {})
            desc = cached.get("meta", {}).get("description", "")
            label = f"  {f.stem}"
            if desc:
                label += f" — {desc}"
            lines.append(label)
    else:
        lines.append("[行为技能 .md] (无)")
    if not py_files and not md_files:
        return "skills/ 目录为空"
    return "\n".join(lines)
def list_md_skills() -> str:
    """列出所有可用的 .md 行为技能及其 trigger"""
    files = sorted(SKILLS_DIR.glob("*.md"))
    if not files:
        return "没有可用的 .md 行为技能"
    lines = []
    for f in files:
        parsed = _md_skill_cache.get(f.stem) or _parse_skill_md(f)
        if parsed:
            _md_skill_cache[f.stem] = parsed
            meta = parsed["meta"]
            desc = meta.get("description", "")
            triggers = meta.get("triggers", [])
            line = f"  {f.stem}"
            if desc:
                line += f" — {desc}"
            lines.append(line)
            if triggers:
                lines.append(f"    触发: {', '.join(triggers)}")
        else:
            lines.append(f"  {f.stem}")
    return "\n".join(lines)
def load_md_skill(name: str) -> str:
    """加载一个 .md 行为技能，注入其 body 到对话上下文"""
    p = SKILLS_DIR / f"{name}.md"
    if not p.exists():
        return f"错误: 技能文件不存在 - {p}"
    parsed = _parse_skill_md(p)
    if not parsed:
        return f"错误: 无法解析 {name}.md 的 frontmatter"
    _md_skill_cache[name] = parsed
    meta = parsed["meta"]
    body = parsed["body"]
    # Inject as user message (not system — system gets rebuilt each turn)
    prompt = (
        f"[Active Skill: {name}]\n"
        f"激活此行为技能。严格遵循以下协议，直到用户卸载此技能：\n\n"
        f"{body}"
    )
    from ultimate_agent.session import session
    session.messages.append({"role": "user", "content": prompt})
    _autoload_skills_cache.add(name)
    desc = meta.get("description", "")
    triggers = meta.get("triggers", [])
    extra = ""
    if desc:
        extra += f" — {desc}"
    if triggers:
        extra += f" [触发: {', '.join(triggers)}]"
    return f"已加载行为技能: {name}{extra}"
_scheduler_tasks: Dict[str, Dict] = {}
_scheduler_lock = threading.Lock()
_scheduler_shutdown = threading.Event()
def _parse_cron(cron_str: str) -> Optional[Dict]:
    parts = cron_str.strip().split()
    if len(parts) != 5:
        return None
    return {k: v for k, v in zip(("minute", "hour", "day", "month", "weekday"), parts)}
def _cron_match(now: datetime, cron: dict) -> bool:
    def match(value, pattern):
        return pattern == "*" or str(value) == pattern

    return (
        match(now.minute, cron.get("minute", "*")) and
        match(now.hour, cron.get("hour", "*")) and
        match(now.day, cron.get("day", "*")) and
        match(now.month, cron.get("month", "*")) and
        match(now.weekday(), cron.get("weekday", "*"))
    )
def _run_task(name: str, action: str, params: dict):
    log_line = f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 执行任务: {name} | action={action}"
    try:
        if action == "execute_command":
            result = execute_command(params.get("command", ""))
        elif action == "web_search":
            result = web_search(params.get("query", ""))
        elif action == "ai_review":
            result = web_search(f"复盘: {params.get('topic', '今日工作')}")
        else:
            result = f"未知 action: {action}"
        log_line += f" | 结果: {result[:100]}"
    except Exception as e:
        log_line += f" | 错误: {e}"
    try:
        with open(LOGS_DIR / "scheduler.log", "a", encoding="utf-8") as f:
            f.write(log_line + "\n")
    except Exception:
        pass
    console.print(f"[dim]{log_line}[/dim]")
def _schedule_loop():
    while not _scheduler_shutdown.is_set():
        try:
            now = datetime.now()
            with _scheduler_lock:
                tasks = list(_scheduler_tasks.values())
            for task in tasks:
                if task["mode"] == "interval":
                    if time.time() - task.get("last_run", 0) >= float(task["schedule"]):
                        task["last_run"] = time.time()
                        threading.Thread(
                            target=_run_task,
                            args=(task["name"], task["action"], task.get("params", {})),
                            daemon=True
                        ).start()
                elif task["mode"] == "cron":
                    cron = task.get("_cron_parsed")
                    if cron and _cron_match(now, cron):
                        current_min = now.replace(second=0, microsecond=0).timestamp()
                        if task.get("_last_executed", 0) < current_min:
                            task["_last_executed"] = current_min
                            threading.Thread(
                                target=_run_task,
                                args=(task["name"], task["action"], task.get("params", {})),
                                daemon=True
                            ).start()
        except Exception:
            pass
        _scheduler_shutdown.wait(30)  # [FIX] interruptible sleep instead of time.sleep(30)
_scheduler_thread = threading.Thread(target=_schedule_loop, daemon=True)
def add_task(name: str, mode: str, schedule: str, action: str, params: str = None) -> str:
    try:
        parsed_params = json.loads(params) if params else {}
    except Exception:
        parsed_params = {}
    task = {"name": name, "mode": mode, "schedule": schedule,
            "action": action, "params": parsed_params, "last_run": 0}
    if mode == "cron":
        cron = _parse_cron(schedule)
        if not cron:
            return "错误: cron 格式不正确，应为 '分 时 日 月 周'"
        task["_cron_parsed"] = cron
    with _scheduler_lock:
        _scheduler_tasks[name] = task
    console.print(f"[green]已添加任务: {name}[/green]")
    return f"任务 '{name}' 已添加 ({mode}={schedule})"
def list_tasks() -> str:
    with _scheduler_lock:
        if not _scheduler_tasks:
            return "暂无定时任务"
        return "\n".join(
            f"  {t['name']}: {t['mode']}={t['schedule']} -> {t['action']}"
            for t in _scheduler_tasks.values()
        )
def remove_task(name: str) -> str:
    with _scheduler_lock:
        if name in _scheduler_tasks:
            del _scheduler_tasks[name]
            return f"已移除任务: {name}"
        return f"错误: 任务不存在 - {name}"