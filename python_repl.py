"""
python_repl.py — Persistent Python REPL for Orca Code.
Maintains a long-lived subprocess so variables persist across calls.
Uses IPython if available, falls back to plain Python.
Windows-compatible: uses threads for stderr reading (no select).
"""
import subprocess
import sys
import re
import ast as _ast
import threading
from pathlib import Path
from typing import Optional

# ---- Dangerous patterns (regex fallback after AST scan) ----
_DANGEROUS_PATTERNS = [
    r'os\.system\s*\(', r'subprocess\.', r'os\.popen\s*\(',
    r'__import__\s*\(\s*[\'"]os[\'"]', r'__import__\s*\(\s*[\'"]subprocess[\'"]',
    r'eval\s*\(', r'exec\s*\(', r'compile\s*\(',
    r'open\s*\([^)]*[\'"]w', r'__builtins__',
    r'rm\s+-rf\s+/', r'dd\s+if=', r'mkfs\.',
    r'shutil\.rmtree', r'shutil\.move', r'shutil\.copy',
    r'os\.remove\s*\(', r'os\.unlink\s*\(', r'os\.rmdir\s*\(',
    r'os\.chmod\s*\(', r'os\.chown\s*\(',
    r'socket\.', r'requests\.', r'urllib\.',
    r'ctypes\.', r'signal\.',
    r'sys\.exit\s*\(', r'os\._exit\s*\(',
]

# ---- AST-level blocklists for sandbox ----
_AST_FORBIDDEN_FUNCS = {
    'eval', 'exec', 'compile', 'open', '__import__',
    'getattr', 'setattr', 'delattr',
}
_AST_FORBIDDEN_ATTRS = {
    'system', 'popen', 'call', 'check_call', 'check_output', 'run',
    '__class__', '__bases__', '__subclasses__', '__mro__',
    '__globals__', '__builtins__', '__builtin__', '__import__',
    '__dict__', '__code__', '__closure__', '__func__', '__self__',
    '__init__', '__new__', '__del__', '__reduce__', '__reduce_ex__',
    '__getattribute__', '__getattr__', '__setattr__',
}
_AST_FORBIDDEN_MODULES = set()


def _scan_code_ast(code: str) -> Optional[str]:
    """AST-level security scan. Returns error string or None if safe."""
    try:
        tree = _ast.parse(code)
    except SyntaxError:
        return None  # Let the subprocess handle syntax errors

    for node in _ast.walk(tree):
        # [FIX] Allow safe data-science imports; block only dangerous modules
        if isinstance(node, (_ast.Import, _ast.ImportFrom)):
            if isinstance(node, _ast.ImportFrom):
                module_name = node.module or ''
            else:
                module_name = node.names[0].name if node.names else ''

            # Block dangerous modules
            if any(module_name == m or module_name.startswith(m + '.')
                   for m in _AST_FORBIDDEN_MODULES):
                return f"Error: dangerous import blocked — {module_name}"
            # Allow everything else (numpy, matplotlib, pandas, PIL, etc.)
            # The REPL runs in a subprocess, so imports only affect that process.
            continue

        # Block dangerous function calls
        if isinstance(node, _ast.Call):
            if isinstance(node.func, _ast.Name):
                if node.func.id in _AST_FORBIDDEN_FUNCS:
                    return f"Error: dangerous pattern blocked — {node.func.id}"

        # Block dangerous attribute access
        if isinstance(node, _ast.Attribute):
            if node.attr in _AST_FORBIDDEN_ATTRS:
                return f"Error: dangerous pattern blocked — .{node.attr}"
            if isinstance(node.value, _ast.Name):
                if node.value.id in _AST_FORBIDDEN_MODULES:
                    return f"Error: dangerous pattern blocked — {node.value.id}.{node.attr}"

    return None

_SENTINEL = "___ULTIMATE_REPL_DONE___"


class PythonREPL:
    def __init__(self, timeout: int = 30, use_ipython: bool = True):
        self.timeout = timeout
        self.use_ipython = use_ipython
        self._process = None
        self._lock = threading.Lock()
        self._stderr_lines = []
        self._stderr_thread = None
        self._start_process()

    def _find_python(self) -> str:
        if self.use_ipython:
            for name in ["ipython", "ipython3"]:
                try:
                    subprocess.run(
                        [name, "--version"], capture_output=True, timeout=5,
                        creationflags=0x08000000 if sys.platform == "win32" else 0
                    )
                    return name
                except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
                    continue
        return sys.executable

    def _stderr_reader(self):
        """Thread target: continuously read stderr into buffer."""
        try:
            for line in self._process.stderr:
                if _SENTINEL in line:
                    continue
                self._stderr_lines.append(line)
        except (ValueError, OSError):
            pass

    def _start_process(self):
        python_exe = self._find_python()
        is_ipython = "ipython" in Path(python_exe).name

        if is_ipython:
            args = [
                python_exe,
                "--no-autoindent", "--no-term-title",
                "--colors=NoColor", "--no-confirm-exit",
                "-c", IPYTHON_BOOTSTRAP,
            ]
        else:
            args = [python_exe, "-u", "-c", PYTHON_BOOTSTRAP]

        creationflags = 0x08000000 if sys.platform == "win32" else 0
        self._process = subprocess.Popen(
            args,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
            creationflags=creationflags,
        )

        # Start stderr reader thread
        self._stderr_lines = []
        self._stderr_thread = threading.Thread(target=self._stderr_reader, daemon=True)
        self._stderr_thread.start()

        # Read the ready signal
        try:
            self._read_until_sentinel(timeout=10)
        except Exception as e:
            self._process.kill()
            raise RuntimeError(f"REPL startup failed: {e}")

    def _read_until_sentinel(self, timeout: float = None) -> str:
        timeout = timeout or self.timeout
        lines = []
        start = __import__('time').time()

        while True:
            if timeout and (__import__('time').time() - start) > timeout:
                raise TimeoutError("REPL read timeout")

            line = self._process.stdout.readline()
            if not line:
                if self._process.poll() is not None:
                    stderr = "".join(self._stderr_lines[-20:])
                    raise RuntimeError(f"REPL process died. stderr: {stderr[:500]}")
                import time as _t
                _t.sleep(0.01)  # Fix busy-loop: avoid 100% CPU when stdout buffer is empty
                continue

            if _SENTINEL in line:
                break
            lines.append(line)

        return "".join(lines)

    def _drain_stderr(self) -> str:
        """Collect stderr accumulated since last drain."""
        lines = self._stderr_lines[:]
        self._stderr_lines.clear()
        return "".join(lines)

    def execute(self, code: str) -> str:
        code = code.strip()
        if not code:
            return "(empty input)"

        # [Security] AST-level scan first (catches structural bypasses like getattr(__import__('os'),'system'))
        ast_error = _scan_code_ast(code)
        if ast_error:
            return ast_error

        # [Security] Regex fallback for text patterns AST may miss
        for pat in _DANGEROUS_PATTERNS:
            if re.search(pat, code, re.IGNORECASE):
                return f"Error: dangerous pattern blocked — {pat}"

        with self._lock:
            if self._process.poll() is not None:
                try:
                    self._start_process()
                except Exception as e:
                    return f"Error: REPL restart failed — {e}"

            try:
                # Drain any stale stderr before execution
                self._drain_stderr()

                # Write code + sentinel line (exactly 2 lines: code, sentinel-printer)
                self._process.stdin.write(code + "\n")
                self._process.stdin.write(f'print("{_SENTINEL}")\n')
                self._process.stdin.flush()

                output = self._read_until_sentinel(timeout=self.timeout)

                # Wait for stderr to settle
                import time as _time
                _time.sleep(0.1)
                stderr_out = self._drain_stderr()

            except TimeoutError:
                self._process.kill()
                self._start_process()
                return f"Error: code execution timed out ({self.timeout}s). REPL restarted."

            except Exception as e:
                try:
                    self._start_process()
                except Exception:
                    pass
                return f"Error: REPL execution failed — {e}"

        result = output.strip()
        result = re.sub(r'^(Out\[\d+\]:\s*)+', '', result, flags=re.MULTILINE)
        result = re.sub(r'^In\s*\[\d+\]:.*\n?', '', result, flags=re.MULTILINE)

        if stderr_out and stderr_out.strip():
            stderr_clean = stderr_out.strip()
            stderr_clean = re.sub(r'.*IPython.*--.*\n?', '', stderr_clean)
            stderr_clean = re.sub(r'.*Jupyter.*\n?', '', stderr_clean)
            if stderr_clean:
                result = result + ("\n" if result else "") + stderr_clean

        if not result:
            result = "(no output)"

        if len(result) > 4000:
            result = result[:4000] + "\n... (truncated)"

        return result

    def reset(self) -> str:
        with self._lock:
            try:
                self._process.kill()
            except Exception:
                pass
            try:
                self._start_process()
                return "REPL restarted (all state cleared)"
            except Exception as e:
                return f"Error: REPL restart failed — {e}"

    def close(self):
        try:
            self._process.kill()
        except Exception:
            pass


# ---- Bootstrap scripts ----

IPYTHON_BOOTSTRAP = r"""
import sys
sys.path.insert(0, '.')
from IPython.terminal.interactiveshell import TerminalInteractiveShell
shell = TerminalInteractiveShell.instance(colors='NoColor', confirm_exit=False)
shell.prompts = type('P', (), {
    'in_prompt': lambda self: '',
    'out_prompt': lambda self: '',
    'continuation_prompt': lambda self: '',
    'rewrite_prompt': lambda self: '',
})()
shell.autoindent = False
print("___ULTIMATE_REPL_DONE___")
while True:
    try:
        code_lines = []
        while True:
            line = sys.stdin.readline()
            if not line:
                sys.exit(0)
            code_lines.append(line)
            if '___ULTIMATE_REPL_DONE___' in line:
                break
        code = ''.join(code_lines[:-1])
        if code.strip():
            shell.run_cell(code, store_history=False)
        print("___ULTIMATE_REPL_DONE___")
        sys.stdout.flush()
    except KeyboardInterrupt:
        print("___ULTIMATE_REPL_DONE___")
    except Exception as e:
        print(f"REPL error: {e}")
        print("___ULTIMATE_REPL_DONE___")
"""

PYTHON_BOOTSTRAP = r"""
import sys
sys.path.insert(0, '.')
# Ensure unbuffered stdout
sys.stdout.reconfigure(line_buffering=True)
print("___ULTIMATE_REPL_DONE___", flush=True)
_globals = {}
_locals = {}
while True:
    try:
        code_lines = []
        while True:
            line = sys.stdin.readline()
            if not line:
                sys.exit(0)
            code_lines.append(line)
            if '___ULTIMATE_REPL_DONE___' in line:
                break
        code = ''.join(code_lines[:-1])
        if code.strip():
            try:
                exec(compile(code, '<repl>', 'exec'), _globals, _locals)
            except SystemExit:
                pass
            except Exception:
                import traceback
                traceback.print_exc(file=sys.stdout)
        sys.stdout.flush()
        sys.stdout.write("___ULTIMATE_REPL_DONE___\n")
        sys.stdout.flush()
    except KeyboardInterrupt:
        sys.stdout.write("\n___ULTIMATE_REPL_DONE___\n")
        sys.stdout.flush()
    except Exception:
        import traceback
        traceback.print_exc(file=sys.stdout)
        sys.stdout.write("___ULTIMATE_REPL_DONE___\n")
        sys.stdout.flush()
"""


# ---- Module-level singleton ----
_repl_instance = None
_repl_lock = threading.Lock()


def get_repl(timeout: int = 30, use_ipython: bool = True) -> PythonREPL:
    global _repl_instance
    with _repl_lock:
        if _repl_instance is None:
            _repl_instance = PythonREPL(timeout=timeout, use_ipython=use_ipython)
        return _repl_instance


def execute_python(code: str, timeout: int = 30) -> str:
    """Execute Python code in a persistent REPL session. State persists across calls.

    Use for calculations, data analysis, string manipulation, or testing logic.
    Variables persist - define once, reuse across calls.

    Special commands:
      __reset__  — restart REPL, clear all variables
      __info__   — show REPL status
    """
    repl = get_repl(timeout=timeout)

    if code.strip() == "__reset__":
        return repl.reset()

    if code.strip() == "__info__":
        return (
            f"REPL Info:\n"
            f"  Python: {sys.executable}\n"
            f"  IPython enabled: {repl.use_ipython}\n"
            f"  Timeout: {repl.timeout}s\n"
            f"  Alive: {repl._process.poll() is None if repl._process else 'N/A'}\n"
        )

    return repl.execute(code)
