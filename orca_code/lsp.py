"""orca_code.lsp — Minimal LSP integration for diagnostics and references.

Spins up language servers via stdio JSON-RPC and provides:
  - lsp_diagnostics(path) — get errors/warnings for a file
  - lsp_references(path, line, col) — find symbol references

Supports: Python (pylsp), TypeScript (ts-ls), Rust (rust-analyzer).
Auto-detects language from file extension.
"""

from __future__ import annotations

import json
import os
import subprocess
import threading
from pathlib import Path

# ═══════════════════════════════════════════════════════════════════════════════
# Language server definitions
# ═══════════════════════════════════════════════════════════════════════════════

_LS_DEFS = {
    ".py": {
        "name": "pylsp",
        "cmd": ["pylsp"],
        "init_options": {},
    },
    ".rs": {
        "name": "rust-analyzer",
        "cmd": ["rust-analyzer"],
        "init_options": {},
    },
    ".ts": {
        "name": "typescript-language-server",
        "cmd": ["typescript-language-server", "--stdio"],
        "init_options": {},
    },
    ".tsx": {
        "name": "typescript-language-server",
        "cmd": ["typescript-language-server", "--stdio"],
        "init_options": {},
    },
    ".js": {
        "name": "typescript-language-server",
        "cmd": ["typescript-language-server", "--stdio"],
        "init_options": {},
    },
    ".jsx": {
        "name": "typescript-language-server",
        "cmd": ["typescript-language-server", "--stdio"],
        "init_options": {},
    },
    ".go": {
        "name": "gopls",
        "cmd": ["gopls"],
        "init_options": {},
    },
}


class LspClient:
    """Minimal LSP client over stdio JSON-RPC.

    Manages one language server process. Supports:
      - initialize / shutdown
      - textDocument/didOpen, textDocument/didChange
      - textDocument/diagnostic (or publishDiagnostics)
      - textDocument/references
      - textDocument/definition
    """

    def __init__(self, root_uri: str, language_id: str):
        self.root_uri = root_uri
        self.language_id = language_id
        self._process: subprocess.Popen | None = None
        self._seq = 0
        self._lock = threading.Lock()
        self._initialized = False
        self._diagnostics: dict[str, list[dict]] = {}  # uri -> list of diagnostics

    def _get_cmd(self) -> list[str] | None:
        """Find the language server command for our extension."""
        # Map language_id back to a file extension
        lang_to_ext = {
            "python": ".py", "rust": ".rs",
            "typescript": ".ts", "typescriptreact": ".tsx",
            "javascript": ".js", "javascriptreact": ".jsx",
            "go": ".go",
        }
        ext = lang_to_ext.get(self.language_id, "")
        # Try extension-based lookup
        for exts, defn in _LS_DEFS.items():
            if self.language_id == defn.get("name") or self.language_id in str(defn.get("cmd")):
                return defn["cmd"]
        # Fallback: search by extension
        for exts in [".py", ".rs", ".ts", ".tsx", ".js", ".jsx", ".go"]:
            if self.language_id in ("python", "rust", "typescript", "typescriptreact",
                                     "javascript", "javascriptreact", "go"):
                defn = _LS_DEFS.get(exts, _LS_DEFS.get(".py"))
                return defn["cmd"] if defn else None
        # Final fallback: try pylsp for Python, else None
        for defn in _LS_DEFS.values():
            if defn["cmd"][0] in self.language_id:
                return defn["cmd"]
        return None

    def start(self, workspace_path: str) -> bool:
        """Start the language server process."""
        cmd = self._get_cmd()
        if not cmd:
            return False

        # Check if the binary exists
        import shutil
        binary = cmd[0]
        if shutil.which(binary) is None:
            return False

        try:
            self._process = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=workspace_path,
            )
        except Exception:
            return False

        # Initialize
        root_path = workspace_path.replace("\\", "/")
        if not root_path.startswith("file://"):
            root_path = f"file:///{root_path}"

        init_params = {
            "processId": os.getpid(),
            "rootUri": root_path,
            "capabilities": {
                "textDocument": {
                    "diagnostic": {"dynamicRegistration": True},
                    "references": {"dynamicRegistration": True},
                    "definition": {"dynamicRegistration": True},
                }
            },
        }

        result = self._send_request("initialize", init_params)
        if result is None:
            return False

        self._send_notification("initialized", {})
        self._initialized = True
        return True

    def stop(self):
        """Shutdown the language server."""
        if self._process and self._initialized:
            try:
                self._send_request("shutdown", {})
                self._send_notification("exit", {})
            except Exception:
                pass
            try:
                self._process.terminate()
                self._process.wait(timeout=5)
            except Exception:
                try:
                    self._process.kill()
                except Exception:
                    pass
            self._process = None
            self._initialized = False

    def _send_request(self, method: str, params: dict, timeout: float = 10.0) -> dict | None:
        """Send a JSON-RPC request and wait for response."""
        if not self._process or self._process.stdin is None:
            return None

        with self._lock:
            self._seq += 1
            seq = self._seq

        request = json.dumps({
            "jsonrpc": "2.0",
            "id": seq,
            "method": method,
            "params": params,
        })

        try:
            header = f"Content-Length: {len(request.encode('utf-8'))}\r\n\r\n"
            self._process.stdin.write((header + request).encode("utf-8"))
            self._process.stdin.flush()

            # Read response
            return self._read_response(timeout)
        except Exception:
            return None

    def _send_notification(self, method: str, params: dict):
        """Send a JSON-RPC notification (no response expected)."""
        if not self._process or self._process.stdin is None:
            return

        notification = json.dumps({
            "jsonrpc": "2.0",
            "method": method,
            "params": params,
        })

        try:
            header = f"Content-Length: {len(notification.encode('utf-8'))}\r\n\r\n"
            self._process.stdin.write((header + notification).encode("utf-8"))
            self._process.stdin.flush()
        except Exception:
            pass

    def _read_response(self, timeout: float = 10.0) -> dict | None:
        """Read a single JSON-RPC response from stdout."""
        if not self._process or self._process.stdout is None:
            return None

        try:
            # Read Content-Length header
            header = b""
            while not header.endswith(b"\r\n\r\n"):
                ch = self._process.stdout.read(1)
                if not ch:
                    return None
                header += ch

            header_str = header.decode("utf-8")
            content_length = 0
            for line in header_str.split("\r\n"):
                if line.lower().startswith("content-length:"):
                    content_length = int(line.split(":", 1)[1].strip())
                    break

            if content_length <= 0:
                return None

            # Read body
            body = self._process.stdout.read(content_length)
            if not body:
                return None

            return json.loads(body.decode("utf-8"))
        except Exception:
            return None

    def open_file(self, file_path: str):
        """Notify the server that a file is open."""
        uri = Path(file_path).resolve().as_uri()
        try:
            text = Path(file_path).read_text(encoding="utf-8", errors="replace")
        except Exception:
            return

        self._send_notification("textDocument/didOpen", {
            "textDocument": {
                "uri": uri,
                "languageId": self.language_id,
                "version": 1,
                "text": text,
            }
        })

    def get_diagnostics(self, file_path: str) -> str:
        """Get diagnostics (errors/warnings) for a file.

        Returns formatted string of diagnostics or empty string.
        """
        uri = Path(file_path).resolve().as_uri()
        result = self._send_request("textDocument/diagnostic", {
            "textDocument": {"uri": uri},
        })

        if not result or "result" not in result:
            # Fallback: try older publishDiagnostics style
            diags = self._diagnostics.get(uri, [])
            return self._format_diagnostics(file_path, diags)

        return self._format_diagnostics(file_path, result.get("result", {}).get("items", []))

    def get_references(self, file_path: str, line: int, col: int) -> str:
        """Find all references to the symbol at position (1-based line, col)."""
        uri = Path(file_path).resolve().as_uri()
        result = self._send_request("textDocument/references", {
            "textDocument": {"uri": uri},
            "position": {"line": line - 1, "character": col},
            "context": {"includeDeclaration": True},
        })

        if not result or "result" not in result:
            return f"No references found at {file_path}:{line}:{col}"

        refs = result["result"]
        if not refs:
            return f"No references found at {file_path}:{line}:{col}"

        lines = []
        for ref in refs[:20]:
            ref_uri = ref.get("uri", "")
            ref_line = ref.get("range", {}).get("start", {}).get("line", 0) + 1
            ref_col = ref.get("range", {}).get("start", {}).get("character", 0) + 1
            ref_path = ref_uri.replace("file:///", "").replace("file://", "")
            lines.append(f"  {ref_path}:{ref_line}:{ref_col}")

        return f"References ({len(refs)}):\n" + "\n".join(lines)

    def get_definition(self, file_path: str, line: int, col: int) -> str:
        """Find the definition of the symbol at position."""
        uri = Path(file_path).resolve().as_uri()
        result = self._send_request("textDocument/definition", {
            "textDocument": {"uri": uri},
            "position": {"line": line - 1, "character": col},
        })

        if not result or "result" not in result:
            return f"Definition not found at {file_path}:{line}:{col}"

        defn = result["result"]
        if isinstance(defn, list):
            defn = defn[0] if defn else None
        if not defn:
            return f"Definition not found at {file_path}:{line}:{col}"

        ref_uri = defn.get("uri", "")
        ref_line = defn.get("range", {}).get("start", {}).get("line", 0) + 1
        ref_col = defn.get("range", {}).get("start", {}).get("character", 0) + 1
        ref_path = ref_uri.replace("file:///", "").replace("file://", "")
        return f"Definition: {ref_path}:{ref_line}:{ref_col}"

    def _format_diagnostics(self, file_path: str, items: list) -> str:
        """Format diagnostics into a readable string."""
        if not items:
            return ""

        errors = []
        warnings = []
        for d in items:
            severity = d.get("severity", 2)  # 1=error, 2=warning, 3=info, 4=hint
            line = d.get("range", {}).get("start", {}).get("line", 0) + 1
            col = d.get("range", {}).get("start", {}).get("character", 0) + 1
            msg = d.get("message", "unknown")
            code = d.get("code", "")
            entry = f"  L{line}:{col} [{code}] {msg}" if code else f"  L{line}:{col} {msg}"

            if severity == 1:
                errors.append(entry)
            elif severity == 2:
                warnings.append(entry)

        parts = []
        short_path = str(Path(file_path).name)
        if errors:
            parts.append(f"  {short_path} errors ({len(errors)}):")
            parts.extend(errors[:10])
        if warnings:
            parts.append(f"  {short_path} warnings ({len(warnings)}):")
            parts.extend(warnings[:5])

        return "\n".join(parts) if parts else ""


# ═══════════════════════════════════════════════════════════════════════════════
# Global client cache — one per language
# ═══════════════════════════════════════════════════════════════════════════════

_clients: dict[str, LspClient] = {}
_clients_lock = threading.Lock()

# Registry of files that have been changed and need diagnostics
_pending_diagnostics: dict[str, str] = {}  # path -> language_id


def _get_or_create_client(workspace_path: str, language_id: str) -> LspClient | None:
    """Get or create an LSP client for the given language."""
    with _clients_lock:
        if language_id in _clients:
            client = _clients[language_id]
            if client._initialized:
                return client
            # Reconnect if dead
            client.stop()

        client = LspClient(f"file:///{workspace_path}", language_id)
        if client.start(workspace_path):
            _clients[language_id] = client
            return client
        return None


def _detect_language(file_path: str) -> str | None:
    """Detect language ID from file extension."""
    ext_map = {
        ".py": "python",
        ".rs": "rust",
        ".ts": "typescript",
        ".tsx": "typescriptreact",
        ".js": "javascript",
        ".jsx": "javascriptreact",
        ".go": "go",
        ".css": "css",
        ".html": "html",
        ".json": "json",
        ".yaml": "yaml",
        ".yml": "yaml",
        ".md": "markdown",
    }
    ext = Path(file_path).suffix.lower()
    return ext_map.get(ext)


# ═══════════════════════════════════════════════════════════════════════════════
# Tool-accessible functions
# ═══════════════════════════════════════════════════════════════════════════════

def lsp_diagnostics(file_path: str) -> str:
    """Get LSP diagnostics (errors/warnings) for a file.
    Returns formatted diagnostics or 'No issues found'.

    If the LSP server is not available, returns a message indicating that.
    """
    file_path = str(Path(file_path).resolve())
    if not os.path.isfile(file_path):
        return f"File not found: {file_path}"

    lang = _detect_language(file_path)
    if not lang:
        return f"No language server available for: {Path(file_path).suffix}"

    workspace = str(Path(file_path).parent)
    client = _get_or_create_client(workspace, lang)
    if not client:
        return f"Language server ({lang}) not installed. Install it for LSP diagnostics."

    # Open the file first
    try:
        client.open_file(file_path)
    except Exception:
        pass

    result = client.get_diagnostics(file_path)
    return result if result else "No issues found"


def lsp_references(file_path: str, line: int, column: int = 1) -> str:
    """Find all references to the symbol at file_path:line:column.
    Line is 1-based. Column defaults to 1.

    Returns list of file:line:col locations.
    """
    file_path = str(Path(file_path).resolve())
    if not os.path.isfile(file_path):
        return f"File not found: {file_path}"

    lang = _detect_language(file_path)
    if not lang:
        return f"No language server available for: {Path(file_path).suffix}"

    workspace = str(Path(file_path).parent)
    client = _get_or_create_client(workspace, lang)
    if not client:
        return f"Language server ({lang}) not installed."

    client.open_file(file_path)
    return client.get_references(file_path, line, column)


def lsp_definition(file_path: str, line: int, column: int = 1) -> str:
    """Go to definition of the symbol at file_path:line:column.
    Returns the definition location as file:line:col.
    """
    file_path = str(Path(file_path).resolve())
    if not os.path.isfile(file_path):
        return f"File not found: {file_path}"

    lang = _detect_language(file_path)
    if not lang:
        return f"No language server available for: {Path(file_path).suffix}"

    workspace = str(Path(file_path).parent)
    client = _get_or_create_client(workspace, lang)
    if not client:
        return f"Language server ({lang}) not installed."

    client.open_file(file_path)
    return client.get_definition(file_path, line, column)


def auto_diagnose(file_path: str):
    """Called automatically after write_file/edit_file/apply_diff.
    Triggers background diagnostics check.
    """
    lang = _detect_language(file_path)
    if lang:
        _pending_diagnostics[file_path] = lang


def get_pending_diagnostics() -> str:
    """Flush pending diagnostics. Called at end of tool execution loop."""
    if not _pending_diagnostics:
        return ""

    results = []
    for path, lang in list(_pending_diagnostics.items()):
        workspace = str(Path(path).parent)
        client = _get_or_create_client(workspace, lang)
        if client:
            try:
                client.open_file(path)
                diag = client.get_diagnostics(path)
                if diag:
                    results.append(diag)
            except Exception:
                pass
        del _pending_diagnostics[path]

    return "\n".join(results)


def shutdown_all():
    """Shutdown all LSP clients. Called on program exit."""
    with _clients_lock:
        for client in _clients.values():
            try:
                client.stop()
            except Exception:
                pass
        _clients.clear()
