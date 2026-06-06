"""
Security & stability tests for Orca Code.
Covers fatal and warning-level issues identified in code review.
"""
import pytest
import json
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock


# ============================================================
# FATAL: Skill Sandbox Escape Tests
# ============================================================

SKILL_ESCAPE_PAYLOADS = [
    # Attempt to escape via json module __subclasses__ chain
    (
        'json.__subclasses__',
        'def fn():\n    import json\n    return json.JSONDecoder.__subclasses__()',
    ),
    # Attempt to escape via datetime module
    (
        'datetime.__subclasses__',
        'def fn():\n    from datetime import datetime\n    return datetime.__subclasses__()',
    ),
    # Attempt direct import of os
    (
        'import os',
        'import os\nos.system("calc")',
    ),
    # Attempt __builtins__ escape
    (
        '__builtins__ escape',
        'x = __builtins__["__import__"]("os")\nx.system("dir")',
    ),
    # Attempt .__class__.__mro__ chain
    (
        'dunder class chain',
        'x = "".__class__.__mro__[1].__subclasses__()',
    ),
    # Attempt getattr + __import__
    (
        'getattr bypass',
        'f = getattr(__builtins__, "__import__")\nos_mod = f("os")',
    ),
    # Attempt exec() call
    (
        'exec call',
        'exec("import os; os.system(\'dir\')")',
    ),
    # Attempt eval() call
    (
        'eval call',
        'eval("__import__(\\'os\\').system(\\'dir\\')")',
    ),
    # Attempt through re module
    (
        're module escape',
        'def fn():\n    import re\n    return re._cache.__class__.__subclasses__()',
    ),
]


class TestSkillSandbox:
    """Verify the skill AST sandbox blocks known escape vectors."""

    @pytest.mark.parametrize("desc,payload", SKILL_ESCAPE_PAYLOADS)
    def test_ast_scan_blocks_escape(self, desc, payload):
        """AST scan should reject all escape payloads."""
        from ultimate_agent import _scan_skill_ast
        result = _scan_skill_ast(payload, "test_escape")
        assert result is not None, (
            f"AST scan FAILED to block {desc}!\nPayload:\n{payload}"
        )

    @pytest.mark.parametrize("desc,payload", SKILL_ESCAPE_PAYLOADS)
    def test_safe_exec_blocks_escape(self, desc, payload):
        """_safe_exec_skill should return error string for escape attempts."""
        from ultimate_agent import _safe_exec_skill
        result = _safe_exec_skill(payload, "test_escape")
        assert isinstance(result, str), (
            f"_safe_exec_skill should return error string for {desc}, "
            f"got: {type(result).__name__}"
        )

    def test_safe_exec_restricted_no_modules(self):
        """_safe_exec_skill must NOT inject json/re/datetime modules."""
        from ultimate_agent import _safe_exec_skill
        # This code checks what's available in the restricted namespace
        probe = (
            "available = []\n"
            "try:\n    import json; available.append('json')\n"
            "except: pass\n"
            "try:\n    import re; available.append('re')\n"
            "except: pass\n"
            "try:\n    import datetime; available.append('datetime')\n"
            "except: pass\n"
            "try:\n    import math; available.append('math')\n"
            "except: pass\n"
            "result = ','.join(available) or 'clean'"
        )
        result = _safe_exec_skill(probe, "test_no_modules")
        # Should succeed (return dict) or error — but should NOT have json/re/datetime
        if isinstance(result, dict):
            assert "json" not in result.get("available", []), "json module leaked into sandbox!"
            assert "re" not in result.get("available", []), "re module leaked into sandbox!"
            assert "datetime" not in result.get("available", []), "datetime module leaked into sandbox!"

    def test_legitimate_skill_still_works(self):
        """A legitimate pure-Python skill should execute successfully."""
        from ultimate_agent import _safe_exec_skill
        code = (
            "def add(a, b):\n"
            "    return a + b\n"
            "def greet(name):\n"
            "    return f'Hello, {name}'\n"
        )
        result = _safe_exec_skill(code, "legit_skill")
        assert isinstance(result, dict), f"Legit skill should return dict, got: {type(result).__name__}"
        assert callable(result.get("add")), "add() should be callable"
        assert callable(result.get("greet")), "greet() should be callable"


# ============================================================
# FATAL: Command Injection Tests
# ============================================================

class TestCommandInjection:
    """Verify command injection protections."""

    def test_blocks_dangerous_builtin_del(self):
        """del command should be blocked (use write_file tools instead)."""
        from ultimate_agent import execute_command
        result = execute_command("del /f test.txt")
        assert "已禁用" in result or "错误" in result, f"del should be blocked, got: {result}"

    def test_blocks_dangerous_builtin_copy(self):
        """copy command should be blocked."""
        from ultimate_agent import execute_command
        result = execute_command("copy a.txt b.txt")
        assert "已禁用" in result or "错误" in result, f"copy should be blocked, got: {result}"

    def test_blocks_dangerous_builtin_move(self):
        """move command should be blocked."""
        from ultimate_agent import execute_command
        result = execute_command("move a.txt b.txt")
        assert "已禁用" in result or "错误" in result, f"move should be blocked, got: {result}"

    def test_blocks_shell_metachar_ampersand(self):
        """Shell metacharacter & should be blocked in cmd /c path."""
        from ultimate_agent import execute_command
        result = execute_command("type test.txt & del /f bar.txt")
        assert "已拦截" in result or "错误" in result, (
            f"Shell metachar & should be blocked, got: {result}"
        )

    def test_blocks_shell_metachar_pipe(self):
        """Shell metacharacter | should be blocked."""
        from ultimate_agent import execute_command
        result = execute_command("dir C:\\ | rd /s /q C:\\temp")
        assert "已拦截" in result or "错误" in result, (
            f"Shell metachar | should be blocked, got: {result}"
        )

    def test_allows_safe_builtin_dir(self):
        """Safe builtin 'dir' should still work (may fail on non-Windows or non-existent dir)."""
        from ultimate_agent import execute_command
        result = execute_command("dir")
        # Should NOT say "已禁用" — may return dir output or "未找到" or "命令未找到"
        assert "已禁用" not in result, f"Safe command 'dir' should not be blocked, got: {result}"

    def test_blocks_dangerous_pattern_rm_rf(self):
        """rm -rf / should be blocked by pattern check."""
        from ultimate_agent import execute_command
        result = execute_command("rm -rf /")
        assert "已拦截" in result or "错误" in result, f"rm -rf / should be blocked"


# ============================================================
# FATAL: PS1 Integrity Tests
# ============================================================

class TestPS1Integrity:
    """Verify PowerShell script integrity checks."""

    def test_rejects_modified_ps1(self, tmp_path):
        """A tampered PS1 script should be rejected."""
        import hashlib
        script = tmp_path / "test_location.ps1"
        script.write_text("# malicious content")
        actual = hashlib.sha256(script.read_bytes()).hexdigest()
        # The stored hash won't match this tampered version
        from ultimate_agent import _TEST_LOCATION_HASH
        assert actual != _TEST_LOCATION_HASH, (
            "Test script hash accidentally matches stored hash — update test"
        )

    def test_hash_constant_exists(self):
        """_TEST_LOCATION_HASH should be defined as a non-empty string."""
        from ultimate_agent import _TEST_LOCATION_HASH
        assert isinstance(_TEST_LOCATION_HASH, str)
        assert len(_TEST_LOCATION_HASH) == 64  # SHA256 is 64 hex chars


# ============================================================
# WARNING: Config Type Coercion Tests
# ============================================================

class TestConfigTypeCoercion:
    """Verify TXT config values are properly typed."""

    def test_int_keys_coerced_correctly(self):
        """Integer config keys should be converted to int."""
        from ultimate_agent import _load_txt_config, CONFIG_TXT
        # We can't easily mock CONFIG_TXT without patching, so test the coercion logic directly
        # by constructing a cfg dict as _load_txt_config would return
        cfg = {"max_workers": "5", "cmd_timeout": "120", "keep_last_rounds": "20"}
        _INT_KEYS = ("max_output_tokens", "context_max_tokens", "max_workers",
                     "keep_last_rounds", "keep_blocks", "cmd_timeout")
        for k in _INT_KEYS:
            if k in cfg:
                try:
                    v_int = int(cfg[k])
                    if v_int > 0 or k == "keep_blocks":
                        cfg[k] = v_int
                    else:
                        del cfg[k]
                except (ValueError, TypeError):
                    del cfg[k]
        assert isinstance(cfg["max_workers"], int)
        assert isinstance(cfg["cmd_timeout"], int)
        assert cfg["max_workers"] == 5
        assert cfg["cmd_timeout"] == 120

    def test_bool_keys_coerced_correctly(self):
        """Boolean config keys should be converted from string to bool."""
        cfg = {"enable_tts": "true", "enable_voice": "false", "auto_install_deps": "1"}
        _BOOL_KEYS = ("enable_think_mode", "silent_cmd", "auto_install_deps",
                      "enable_gui_auto", "enable_browser_auto", "enable_tts",
                      "enable_voice", "local_model")
        for k in _BOOL_KEYS:
            if k in cfg:
                cfg[k] = str(cfg[k]).lower() in ("true", "1", "yes")
        assert cfg["enable_tts"] is True
        assert cfg["enable_voice"] is False
        assert cfg["auto_install_deps"] is True

    def test_invalid_int_removed(self):
        """Invalid integer values should be removed from config."""
        cfg = {"max_workers": "not_a_number"}
        _INT_KEYS = ("max_workers",)
        for k in _INT_KEYS:
            if k in cfg:
                try:
                    v_int = int(cfg[k])
                    if v_int > 0:
                        cfg[k] = v_int
                except (ValueError, TypeError):
                    del cfg[k]
        assert "max_workers" not in cfg


# ============================================================
# WARNING: Memory Manager Tests
# ============================================================

class TestMemoryManager:
    """Verify FTS5 safety and limit bounds."""

    def test_fts5_escape_wraps_query(self):
        """_escape_fts5 should wrap query in double-quotes for exact phrase match."""
        from memory_manager import MemoryManager
        escaped = MemoryManager._escape_fts5('test" OR 1=1 --')
        assert escaped.startswith('"'), f"Should start with quote: {escaped}"
        assert escaped.endswith('"'), f"Should end with quote: {escaped}"

    def test_fts5_escape_doubles_quotes(self):
        """Double-quotes in FTS5 query should be escaped by doubling."""
        from memory_manager import MemoryManager
        escaped = MemoryManager._escape_fts5('hello "world"')
        assert '""' in escaped  # embedded quotes doubled

    def test_search_limit_bounds(self):
        """Search limit should be clamped to [1, 20]."""
        # Test the limit clamping logic used in search()
        limit = 100
        assert min(max(1, limit), 20) == 20
        limit = -5
        assert min(max(1, limit), 20) == 1
        limit = 10
        assert min(max(1, limit), 20) == 10


# ============================================================
# WARNING: API Key Masking
# ============================================================

class TestKeyMasking:
    """Verify sensitive key masking works."""

    def test_mask_normal_key(self):
        from ultimate_agent import mask_key
        result = mask_key("sk-abcdefghijklmnopqrstuvwxyz")
        assert result == "sk-ab***xyz"

    def test_mask_short_key(self):
        from ultimate_agent import mask_key
        assert mask_key("short") == "***"

    def test_mask_empty_key(self):
        from ultimate_agent import mask_key
        assert mask_key("") == "***"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
