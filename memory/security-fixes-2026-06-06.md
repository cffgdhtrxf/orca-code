---
name: security-fixes-2026-06-06
description: 2026-06-06 security and stability fixes applied to ultimate_agent.py
metadata:
  type: project
---

Security and stability fixes applied on 2026-06-06:

**FATAL fixes (3):**
1. Skill sandbox escape — removed json/re/datetime from `_safe_exec_skill` namespace; added math only. AST sandbox already blocks `__subclasses__`, `__class__`, `__mro__` etc.
2. Command injection — split Windows `_CMD_BUILTINS` into SAFE (type/dir/echo/etc) and BLOCKED (del/copy/move/ren/mkdir/rmdir/set). Shell metachars (&|;$ etc) blocked in cmd /c path.
3. PS1 integrity — SHA256 hash of test_location.ps1 verified before execution with `-ExecutionPolicy Bypass`.

**WARNING fixes (8):**
4. TXT config type coercion — int and bool keys now coerced in `_load_txt_config`.
5. Scheduler graceful shutdown — `_scheduler_shutdown` Event added; wait(30) replaces sleep(30); main() exit paths call set().
6. Browser resource leak — exception handler cleans up context, playwright, and temp profile.
7. smart_trim_messages — fallback to keep last N when no system message.
8. TTS worker COM init — `pythoncom.CoInitialize()` at thread start.
9. Silent exception swallowing — 7 critical bare `except Exception: pass` changed to `logging.debug(...)`.
10. Hard exit — `load_config()` returns defaults instead of `sys.exit(0)`.
11. Atomic writes — `write_file()` uses temp file + replace().
12. search_content — ripgrep fast path (Unix) + 2000 file limit guard.

**Why:** Original code review identified 3 fatal + 8 warning issues. All backward-compatible.

**How to apply:** These are already applied. Verify with `python -c "import py_compile; py_compile.compile('ultimate_agent.py', doraise=True)"`.
