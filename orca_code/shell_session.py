"""orca_code.shell_session — Persistent shell sessions (P2-36).

Inspired by omp's brush-shell: keeps shell state (env vars, cwd, aliases)
across execute_command calls. Runs a persistent subprocess with PTY.

Benefits over one-shot subprocess:
  - Environment variables persist (export FOO=bar)
  - Working directory persists (cd /path)
  - Shell aliases and functions survive
  - Faster: no process spawn overhead per command

Usage:
    from orca_code.shell_session import ShellSession

    shell = ShellSession()
    shell.start()
    out1 = shell.run("cd /tmp && pwd")
    out2 = shell.run("touch test.txt && ls")  # still in /tmp
    shell.stop()
"""

from __future__ import annotations

import os
import re
import subprocess
import threading
import time
from pathlib import Path


class ShellSession:
    """Persistent shell session that maintains state across commands.

    Uses a subprocess with PTY (pseudo-terminal) so the shell
    behaves interactively — .bashrc/.zshrc are sourced, prompts
    are printed, and state persists.
    """

    def __init__(self, shell: str | None = None, session_id: str = "default"):
        if shell is None:
            shell = os.environ.get("SHELL", "bash" if os.name != "nt" else "cmd")
        self.shell = shell
        self.session_id = session_id
        self._process: subprocess.Popen | None = None
        self._lock = threading.Lock()
        self._started = False
        self._command_count = 0
        self._cwd: str = str(Path.cwd())
        self._env_vars: dict[str, str] = {}

    def start(self, cwd: str | None = None, env: dict[str, str] | None = None) -> bool:
        """Start the persistent shell subprocess.

        Args:
            cwd: Initial working directory. Default: current working dir.
            env: Extra environment variables to set.

        Returns:
            True if started successfully.
        """
        if self._started and self._process and self._process.poll() is None:
            return True

        if cwd:
            self._cwd = cwd
        full_env = {**os.environ, **(env or {})}

        try:
            if os.name == "nt":
                self._process = subprocess.Popen(
                    ["cmd.exe"],
                    stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    cwd=self._cwd, env=full_env,
                    text=False, bufsize=0,
                )
            else:
                self._process = subprocess.Popen(
                    [self.shell, "--norc", "--noprofile"],
                    stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    cwd=self._cwd, env=full_env,
                    text=False, bufsize=0,
                )

            self._started = True
            # Drain initial output (shell greeting, prompt)
            self._drain_output(timeout=0.3)
            # Set basic env if provided
            if env:
                for k, v in env.items():
                    if os.name == "nt":
                        self._send(f"set {k}={v}\r\n")
                    else:
                        self._send(f"export {k}='{v}'\n")
                self._drain_output(timeout=0.2)
            return True

        except Exception:
            return False

    def run(self, command: str, timeout: float = 30.0, cwd: str | None = None) -> str:
        """Run a command in the persistent shell and return output.

        Args:
            command: The shell command to execute.
            timeout: Max seconds to wait for output.
            cwd: Change to this directory first (persists after command).

        Returns:
            Combined stdout+stderr output.
        """
        if not self._started or not self._process:
            # Fall back to one-shot execution
            return self._run_oneshot(command, timeout)

        with self._lock:
            self._command_count += 1

            # Change directory if needed
            if cwd and cwd != self._cwd:
                self._cwd = cwd
                cd_cmd = f"cd /d {cwd}" if os.name == "nt" else f"cd '{cwd}'"
                self._send(cd_cmd + "\n")
                self._drain_output(timeout=0.2)

            # Use a unique marker to detect command completion
            marker = f"__ORCA_CMD_{self._command_count}__"
            if os.name == "nt":
                full_cmd = f"{command}\r\necho {marker}\r\n"
            else:
                full_cmd = f"{command}\necho {marker}\n"

            try:
                self._process.stdin.write(full_cmd.encode("utf-8", errors="replace"))
                self._process.stdin.flush()
            except (BrokenPipeError, OSError):
                # Process died — restart and fall back
                self._started = False
                return self._run_oneshot(command, timeout)

            # Read output until marker
            output = self._read_until(marker, timeout)

            # Clean up output: remove command echo and marker
            output = self._clean_output(output, command, marker)

            return output

    def _send(self, text: str):
        """Send text to the shell subprocess."""
        if self._process and self._process.stdin:
            try:
                self._process.stdin.write(text.encode("utf-8", errors="replace"))
                self._process.stdin.flush()
            except Exception:
                pass

    def _drain_output(self, timeout: float = 0.5):
        """Read and discard any pending output."""
        if not self._process:
            return
        try:
            import select
            end = time.time() + timeout
            while time.time() < end:
                r, _, _ = select.select([self._process.stdout], [], [], 0.1)
                if not r:
                    break
                chunk = self._process.stdout.read(4096)
                if not chunk:
                    break
        except Exception:
            pass

    def _read_until(self, marker: str, timeout: float) -> str:
        """Read from the shell until the marker string is found."""
        output = b""
        marker_bytes = marker.encode()
        start = time.time()

        try:
            import select
            while time.time() - start < timeout:
                r, _, _ = select.select([self._process.stdout], [], [], 0.5)
                if not r:
                    continue
                chunk = self._process.stdout.read(4096)
                if not chunk:
                    break
                output += chunk
                if marker_bytes in output:
                    break
        except Exception:
            pass

        # Also drain any remaining output
        self._drain_output(timeout=0.1)

        return output.decode("utf-8", errors="replace")

    def _clean_output(self, raw: str, command: str, marker: str) -> str:
        """Clean shell output: remove command echo, prompt, and marker."""
        lines = raw.split("\n")
        cleaned = []

        for line in lines:
            # Skip the echoed command
            if command in line and len(line) < len(command) + 10:
                continue
            # Skip the marker
            if marker in line:
                continue
            # Skip empty prompt lines
            stripped = line.strip()
            if stripped in ("$", "#", ">", "$ ", "# ", ">"):
                continue
            cleaned.append(line)

        result = "\n".join(cleaned).strip()

        # Track cd for cwd changes
        if command.strip().startswith("cd "):
            parts = command.strip().split(maxsplit=1)
            if len(parts) == 2:
                new_dir = parts[1].strip().strip("'\"")
                try:
                    new_path = Path(new_dir)
                    if not new_path.is_absolute():
                        new_path = Path(self._cwd) / new_dir
                    if new_path.exists():
                        self._cwd = str(new_path.resolve())
                except Exception:
                    pass

        # Track export for env changes
        for env_match in re.finditer(r'export\s+(\w+)=[\'"]?([^\'"]+)[\'"]?', command):
            self._env_vars[env_match.group(1)] = env_match.group(2)

        return result

    def _run_oneshot(self, command: str, timeout: float) -> str:
        """Fallback: run command in a one-shot subprocess."""
        try:
            result = subprocess.run(
                command, shell=True,
                capture_output=True, text=True,
                timeout=timeout, cwd=self._cwd,
                env={**os.environ, **self._env_vars},
            )
            output = result.stdout
            if result.stderr:
                output += "\n" + result.stderr
            return output.strip() or "(no output)"
        except subprocess.TimeoutExpired:
            return f"命令超时 ({timeout}秒)"
        except Exception as e:
            return f"命令执行失败: {e}"

    def stop(self):
        """Terminate the persistent shell subprocess."""
        if self._process:
            try:
                if os.name == "nt":
                    self._send("exit\r\n")
                else:
                    self._send("exit\n")
                self._process.wait(timeout=3)
            except Exception:
                self._process.kill()
            finally:
                self._process = None
                self._started = False

    @property
    def cwd(self) -> str:
        return self._cwd

    @property
    def is_running(self) -> bool:
        return self._started and self._process is not None and self._process.poll() is None

    @property
    def command_count(self) -> int:
        return self._command_count


# ═══════════════════════════════════════════════════════════════════════════════
# Session manager
# ═══════════════════════════════════════════════════════════════════════════════

_sessions: dict[str, ShellSession] = {}
_lock = threading.Lock()


def get_shell_session(session_id: str = "default", shell: str | None = None) -> ShellSession:
    """Get or create a persistent shell session.

    Args:
        session_id: Unique session identifier. "default" if not specified.
        shell: Shell to use (bash, zsh, etc.). Default: from $SHELL or bash.

    Returns:
        A ShellSession instance that persists state across calls.
    """
    with _lock:
        if session_id not in _sessions or not _sessions[session_id].is_running:
            sess = ShellSession(shell=shell, session_id=session_id)
            sess.start()
            _sessions[session_id] = sess
        return _sessions[session_id]


def stop_all_shells():
    """Stop all persistent shell sessions."""
    with _lock:
        for sess in _sessions.values():
            sess.stop()
        _sessions.clear()
