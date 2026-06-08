"""orca_code.permissions — Claude Code-style tool permission system.

Three modes:
  read-only — read tools auto-approved, write/exec prompt once (rememberable)
  auto      — all tools prompt on first use, choice saved for session
  yolo      — all tools auto-approved (no prompts)

Tools self-declare their risk level. User rules in config.json override.
"""

from __future__ import annotations

import json
from enum import Enum
from pathlib import Path
from typing import Dict, Optional


class RiskLevel(Enum):
    """Tool risk classification — tools declare this themselves."""
    READ = "read"     # reads data, no mutation (read_file, list_files, search_*, etc.)
    WRITE = "write"   # mutates files but no arbitrary code (write_file, write_excel, etc.)
    EXEC = "exec"     # executes code, shells out, drives browser/GUI (execute_command, gui_*, etc.)


class PermissionMode(Enum):
    """Global permission mode set by user."""
    READ_ONLY = "read-only"  # only READ tools auto-approved
    AUTO = "auto"            # first use asks, choice remembered for session
    YOLO = "yolo"            # everything auto-approved


class PermissionDecision(Enum):
    ALLOW = "allow"
    ASK = "ask"
    DENY = "deny"


# ─── Tool risk registry ─────────────────────────────────────────────────────
# Every tool must be listed here with its risk level.
# Tools NOT listed default to EXEC (safe default).

TOOL_RISK: Dict[str, RiskLevel] = {
    # ---- READ ----
    "read_file":          RiskLevel.READ,
    "list_files":         RiskLevel.READ,
    "search_files":       RiskLevel.READ,
    "search_content":     RiskLevel.READ,
    "get_system_info":    RiskLevel.READ,
    "get_weather":        RiskLevel.READ,
    "get_location":       RiskLevel.READ,
    "git_status":         RiskLevel.READ,
    "git_diff":           RiskLevel.READ,
    "git_log":            RiskLevel.READ,
    "git_blame":          RiskLevel.READ,
    "go_to_definition":   RiskLevel.READ,
    "find_references":    RiskLevel.READ,
    "list_skills":        RiskLevel.READ,
    "list_md_skills":     RiskLevel.READ,
    "list_tasks":         RiskLevel.READ,
    "recall_conversation": RiskLevel.READ,
    "ocr_image":           RiskLevel.READ,

    # ---- WRITE ----
    "write_file":         RiskLevel.WRITE,
    "edit_file":          RiskLevel.WRITE,
    "apply_diff":         RiskLevel.WRITE,
    "write_excel":        RiskLevel.WRITE,
    "write_word":         RiskLevel.WRITE,
    "read_excel":         RiskLevel.WRITE,  # opens files, could trigger macros
    "read_word":          RiskLevel.WRITE,
    "take_screenshot":    RiskLevel.WRITE,  # writes image files
    "create_skill":       RiskLevel.WRITE,
    "edit_skill":         RiskLevel.WRITE,
    "add_task":           RiskLevel.WRITE,
    "remove_task":        RiskLevel.WRITE,
    "update_profile":     RiskLevel.WRITE,
    "speak_text":         RiskLevel.WRITE,  # uses system TTS
    "capture_camera":     RiskLevel.WRITE,  # accesses camera
    "web_fetch":          RiskLevel.WRITE,  # makes network requests
    "read_webpage":       RiskLevel.WRITE,
    "web_search":         RiskLevel.WRITE,

    # ---- EXEC ----
    "execute_command":    RiskLevel.EXEC,
    "execute_python":     RiskLevel.EXEC,
    "analyze_image":      RiskLevel.EXEC,  # calls vision API
    "analyse_image":      RiskLevel.EXEC,
    "load_skill":         RiskLevel.EXEC,  # loads and runs code
    "load_md_skill":      RiskLevel.EXEC,
    "gui_click":          RiskLevel.EXEC,
    "gui_type":           RiskLevel.EXEC,
    "gui_move":           RiskLevel.EXEC,
    "gui_hotkey":         RiskLevel.EXEC,
    "gui_press":          RiskLevel.EXEC,
    "window_focus":       RiskLevel.EXEC,
    "find_on_screen":     RiskLevel.EXEC,
    "browser_open":       RiskLevel.EXEC,
    "browser_click":      RiskLevel.EXEC,
    "browser_type":       RiskLevel.EXEC,
    "browser_screenshot": RiskLevel.EXEC,
    "browser_close":      RiskLevel.EXEC,
    # ---- Sub-agents ----
    "agent_open":         RiskLevel.EXEC,
    "agent_eval":         RiskLevel.READ,
    "agent_close":        RiskLevel.WRITE,
    # ---- LSP ----
    "lsp_diagnostics":    RiskLevel.READ,
    "lsp_references":     RiskLevel.READ,
    "lsp_definition":     RiskLevel.READ,
}


class PermissionStore:
    """Persists user permission choices within a session.

    Stores to ~/.orca_permissions.json so choices survive restarts
    when the user selects 'always allow'."""

    def __init__(self, store_path: Optional[Path] = None):
        if store_path is None:
            store_path = Path.home() / ".orca_permissions.json"
        self._path = store_path
        self._session: Dict[str, str] = {}  # tool_name -> "allow"|"deny"
        self._load()

    def _load(self):
        try:
            if self._path.exists():
                data = json.loads(self._path.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    self._session = data
        except Exception:
            self._session = {}

    def _save(self):
        try:
            self._path.write_text(
                json.dumps(self._session, indent=2, ensure_ascii=False),
                encoding="utf-8"
            )
        except Exception:
            pass

    def get(self, tool_name: str) -> Optional[str]:
        """Return 'allow', 'deny', or None if no saved choice."""
        return self._session.get(tool_name)

    def set(self, tool_name: str, decision: str):
        """Save user's choice for this tool."""
        self._session[tool_name] = decision
        self._save()

    def clear(self, tool_name: Optional[str] = None):
        """Clear saved choices. If tool_name is None, clear all."""
        if tool_name is None:
            self._session.clear()
        else:
            self._session.pop(tool_name, None)
        self._save()


# Global permission store instance (initialized in config.py)
perm_store: Optional[PermissionStore] = None


def get_risk(tool_name: str) -> RiskLevel:
    """Get the risk level for a tool. Default: EXEC (safe default)."""
    return TOOL_RISK.get(tool_name, RiskLevel.EXEC)


def check_permission(
    tool_name: str,
    mode: PermissionMode,
    user_rules: Optional[Dict[str, str]] = None
) -> PermissionDecision:
    """Check whether a tool call should be allowed, denied, or prompted.

    Resolution order:
    1. User rule in config.json → always wins
    2. Saved choice in permission store → remembered from previous prompt
    3. Mode-based auto-approval:
       - YOLO: everything allowed
       - read-only: READ allowed, WRITE/EXEC → ASK
       - auto: READ allowed, WRITE/EXEC → ASK on first use

    Returns PermissionDecision.ALLOW, .ASK, or .DENY.
    """
    user_rules = user_rules or {}

    # 1. User rule in config.json always wins
    if tool_name in user_rules:
        rule = user_rules[tool_name]
        if rule == "allow":
            return PermissionDecision.ALLOW
        elif rule == "deny":
            return PermissionDecision.DENY
        elif rule == "ask":
            return PermissionDecision.ASK

    # 2. Saved choice from previous prompt
    if perm_store is not None:
        saved = perm_store.get(tool_name)
        if saved == "allow":
            return PermissionDecision.ALLOW
        elif saved == "deny":
            return PermissionDecision.DENY

    # 3. Mode-based auto-approval
    if mode == PermissionMode.YOLO:
        return PermissionDecision.ALLOW

    risk = get_risk(tool_name)

    if mode == PermissionMode.READ_ONLY:
        if risk == RiskLevel.READ:
            return PermissionDecision.ALLOW
        else:
            return PermissionDecision.ASK

    # AUTO mode: READ auto-approve, WRITE/EXEC ask on first use
    if mode == PermissionMode.AUTO:
        if risk == RiskLevel.READ:
            return PermissionDecision.ALLOW
        else:
            return PermissionDecision.ASK

    # Fallback
    return PermissionDecision.ASK


def prompt_user_for_permission(tool_name: str, args: dict, risk: RiskLevel) -> str:
    """Show an interactive permission prompt. Returns 'allow', 'deny', or 'always_allow'.

    Returns empty string if user cancels / interrupts.
    """
    risk_colors = {
        RiskLevel.READ: "green",
        RiskLevel.WRITE: "yellow",
        RiskLevel.EXEC: "red",
    }
    color = risk_colors.get(risk, "white")

    # Format args for display
    args_str = json.dumps(args, ensure_ascii=False)
    if len(args_str) > 100:
        args_str = args_str[:97] + "..."

    prompt = (
        f"\n[{color}]⚡ {tool_name}[/{color}] [dim]({risk.value})[/dim]\n"
        f"  [dim]{args_str}[/dim]\n"
        f"  [dim][a]llow  [d]eny  al[w]ays allow[/dim] "
    )

    try:
        import sys as _sys
        _sys.stdout.write(prompt)
        _sys.stdout.flush()
        if _sys.platform == "win32":
            import msvcrt
            while True:
                ch = msvcrt.getwch().lower()
                if ch == 'a':
                    print("allow")
                    return "allow"
                elif ch == 'd':
                    print("deny")
                    return "deny"
                elif ch == 'w':
                    print("always allow")
                    return "always_allow"
                elif ch in ('\x1b', '\x03', 'q'):
                    print("cancelled")
                    return ""
        else:
            import termios, tty
            fd = _sys.stdin.fileno()
            old = termios.tcgetattr(fd)
            try:
                tty.setraw(fd)
                ch = _sys.stdin.read(1).lower()
                if ch == 'a':
                    print("allow")
                    return "allow"
                elif ch == 'd':
                    print("deny")
                    return "deny"
                elif ch == 'w':
                    print("always allow")
                    return "always_allow"
                else:
                    print("cancelled")
                    return ""
            finally:
                termios.tcsetattr(fd, termios.TCSADRAIN, old)
    except Exception:
        return ""


def resolve_permission(tool_name: str, args: dict, mode: PermissionMode,
                       user_rules: Optional[Dict[str, str]] = None) -> bool:
    """Full permission resolution with interactive prompt if needed.

    Returns True if the tool call is allowed, False if denied.
    In ASK mode, shows a prompt and remembers the choice.

    This is the main entry point called by the tool execution loop.
    """
    decision = check_permission(tool_name, mode, user_rules)

    if decision == PermissionDecision.ALLOW:
        return True
    elif decision == PermissionDecision.DENY:
        return False

    # ASK — show interactive prompt
    risk = get_risk(tool_name)
    choice = prompt_user_for_permission(tool_name, args, risk)

    if choice == "always_allow":
        if perm_store is not None:
            perm_store.set(tool_name, "allow")
        return True
    elif choice == "allow":
        return True
    else:
        # deny or cancelled
        return False
