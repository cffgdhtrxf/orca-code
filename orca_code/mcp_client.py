"""orca_code.mcp_client — Model Context Protocol (MCP) client implementation (P2-13).

Inspired by Claude-Code-main's src/services/mcp/ patterns.
Supports MCP servers via:
  - stdio transport (subprocess-based)
  - sse transport (HTTP Server-Sent Events)

Provides:
  - McpClient: connect, list_tools, call_tool, disconnect
  - McpConfig: server configuration from config.json
  - McpRegistry: manage multiple MCP server connections

Spec: https://modelcontextprotocol.io/
"""

from __future__ import annotations

import json
import logging
import subprocess
import sys
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════════════════════
# Data types
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class McpTool:
    """An MCP tool discovered from a server."""
    name: str
    description: str = ""
    parameters: dict = field(default_factory=dict)
    server_name: str = ""
    server_id: str = ""


@dataclass
class McpServerConfig:
    """Configuration for a single MCP server."""
    name: str
    command: str | None = None      # for stdio transport
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    url: str | None = None          # for sse transport
    headers: dict[str, str] = field(default_factory=dict)
    enabled: bool = True
    timeout_seconds: float = 30.0


# ═══════════════════════════════════════════════════════════════════════════════
# JSON-RPC helpers
# ═══════════════════════════════════════════════════════════════════════════════

class McpError(Exception):
    """MCP protocol error."""
    def __init__(self, code: int, message: str, data: Any = None):
        self.code = code
        self.message = message
        self.data = data
        super().__init__(f"MCP Error [{code}]: {message}")


def _make_request(method: str, params: dict | None = None) -> dict:
    """Build a JSON-RPC 2.0 request."""
    return {
        "jsonrpc": "2.0",
        "id": 1,
        "method": method,
        "params": params or {},
    }


def _parse_response(raw: str) -> dict:
    """Parse a JSON-RPC response, raising McpError on failure."""
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        raise McpError(-32700, f"Parse error: {e}")

    if "error" in data:
        err = data["error"]
        raise McpError(err.get("code", -1), err.get("message", "Unknown"), err.get("data"))

    if "result" not in data:
        raise McpError(-32603, "Invalid response: missing result")

    return data["result"]


# ═══════════════════════════════════════════════════════════════════════════════
# Stdio transport
# ═══════════════════════════════════════════════════════════════════════════════

class StdioMcpTransport:
    """MCP transport over subprocess stdio.

    Spawns the server as a child process and communicates via stdin/stdout.
    Each message is a JSON-RPC line followed by a newline (ndjson).
    """

    def __init__(self, command: str, args: list[str] | None = None,
                 env: dict[str, str] | None = None, timeout: float = 30.0):
        self.command = command
        self.args = args or []
        self.env = env or {}
        self.timeout = timeout
        self._process: subprocess.Popen | None = None
        self._request_id = 0

    def start(self):
        """Launch the MCP server subprocess."""
        full_env = {**dict(sys.modules.get('os', __import__('os')).environ), **self.env}
        try:
            self._process = subprocess.Popen(
                [self.command] + self.args,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=full_env,
                text=True,
                bufsize=1,
            )
        except FileNotFoundError:
            raise McpError(-32000, f"MCP server command not found: {self.command}")
        except Exception as e:
            raise McpError(-32000, f"Failed to start MCP server: {e}")

    def stop(self):
        """Terminate the MCP server subprocess."""
        if self._process:
            try:
                self._process.stdin.close()
                self._process.stdout.close()
                self._process.terminate()
                self._process.wait(timeout=5)
            except Exception:
                self._process.kill()
            finally:
                self._process = None

    def send_request(self, method: str, params: dict | None = None) -> dict:
        """Send a JSON-RPC request and return the result."""
        if not self._process or self._process.poll() is not None:
            raise McpError(-32000, "MCP server not running")

        self._request_id += 1
        request = {
            "jsonrpc": "2.0",
            "id": self._request_id,
            "method": method,
            "params": params or {},
        }
        request_line = json.dumps(request, ensure_ascii=False) + "\n"

        try:
            self._process.stdin.write(request_line)
            self._process.stdin.flush()
        except (BrokenPipeError, OSError, UnicodeEncodeError) as e:
            raise McpError(-32000, f"Failed to write to MCP server: {e}")

        try:
            response_line = self._process.stdout.readline()
            if not response_line:
                raise McpError(-32000, "MCP server closed connection")
            return _parse_response(response_line.strip())
        except OSError as e:
            raise McpError(-32000, f"Failed to read from MCP server: {e}")

    def is_running(self) -> bool:
        return self._process is not None and self._process.poll() is None


# ═══════════════════════════════════════════════════════════════════════════════
# MCP Client
# ═══════════════════════════════════════════════════════════════════════════════

class McpClient:
    """MCP client wrapping a transport.

    Usage:
        config = McpServerConfig(name="my-server", command="python", args=["-m", "my_mcp_server"])
        client = McpClient(config)
        client.connect()
        tools = client.list_tools()
        result = client.call_tool("my_tool", {"arg": "value"})
        client.disconnect()
    """

    def __init__(self, config: McpServerConfig):
        self.config = config
        self._transport: StdioMcpTransport | None = None
        self._tools: list[McpTool] = []
        self._connected = False

    def connect(self) -> bool:
        """Connect to the MCP server and initialize."""
        if self.config.command:
            self._transport = StdioMcpTransport(
                self.config.command,
                self.config.args,
                self.config.env,
                self.config.timeout_seconds,
            )
        elif self.config.url:
            # SSE transport not yet implemented — use command-based for now
            logger.warning("SSE transport not yet supported, skipping %s", self.config.name)
            return False
        else:
            logger.warning("No command or URL configured for MCP server %s", self.config.name)
            return False

        try:
            self._transport.start()

            # Initialize handshake
            init_result = self._transport.send_request("initialize", {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {
                    "name": "orca-code",
                    "version": "5.3.0",
                },
            })

            # Send initialized notification
            self._transport.send_request("notifications/initialized", {})

            server_info = init_result.get("serverInfo", {})
            logger.info("MCP connected to %s (%s v%s)",
                        self.config.name,
                        server_info.get("name", "unknown"),
                        server_info.get("version", "0.0.0"))

            # Discover tools
            self._discover_tools()
            self._connected = True
            return True

        except McpError as e:
            logger.error("MCP init failed for %s: %s", self.config.name, e)
            self._transport.stop()
            self._transport = None
            return False
        except Exception as e:
            logger.error("Unexpected MCP error for %s: %s", self.config.name, e)
            if self._transport:
                self._transport.stop()
                self._transport = None
            return False

    def _discover_tools(self):
        """Discover available tools from the MCP server."""
        if not self._transport:
            return
        try:
            result = self._transport.send_request("tools/list", {})
            tools_data = result.get("tools", [])
            self._tools = []
            for td in tools_data:
                tool = McpTool(
                    name=td.get("name", ""),
                    description=td.get("description", ""),
                    parameters=td.get("inputSchema", {}),
                    server_name=self.config.name,
                    server_id=self.config.name,
                )
                self._tools.append(tool)
            logger.info("MCP %s: discovered %d tools", self.config.name, len(self._tools))
        except McpError as e:
            logger.warning("Failed to discover tools for %s: %s", self.config.name, e)

    def list_tools(self) -> list[McpTool]:
        """Return discovered tools."""
        return list(self._tools)

    def call_tool(self, tool_name: str, arguments: dict) -> str:
        """Call a tool on the MCP server and return the result."""
        if not self._transport or not self._connected:
            return f"Error: MCP server {self.config.name} not connected"

        try:
            result = self._transport.send_request("tools/call", {
                "name": tool_name,
                "arguments": arguments,
            })

            # Extract text content from result
            content = result.get("content", [])
            if isinstance(content, list):
                texts = []
                for block in content:
                    if isinstance(block, dict):
                        if block.get("type") == "text":
                            texts.append(str(block.get("text", "")))
                        elif block.get("type") == "resource":
                            texts.append(f"[Resource: {block.get('resource', {})}]")
                return "\n".join(texts) if texts else json.dumps(result, ensure_ascii=False)
            return str(content)

        except McpError as e:
            return f"Error: MCP tool '{tool_name}' failed: {e.message}"
        except Exception as e:
            return f"Error: MCP tool '{tool_name}' unexpected error: {e}"

    def disconnect(self):
        """Disconnect from the MCP server."""
        self._connected = False
        if self._transport:
            try:
                self._transport.send_request("shutdown", {})
            except Exception:
                pass
            self._transport.stop()
            self._transport = None

    @property
    def is_connected(self) -> bool:
        return self._connected


# ═══════════════════════════════════════════════════════════════════════════════
# MCP Registry — manages multiple MCP server connections
# ═══════════════════════════════════════════════════════════════════════════════

class McpRegistry:
    """Registry of MCP server connections with lazy initialization.

    Usage:
        registry = McpRegistry()
        registry.add_server(McpServerConfig(name="filesystem", command="npx", args=["-y", "@modelcontextprotocol/server-filesystem", "."]))
        registry.connect_all()
        all_tools = registry.get_all_tools()
    """

    def __init__(self):
        self._servers: dict[str, McpServerConfig] = {}
        self._clients: dict[str, McpClient] = {}
        self._initialized = False

    def add_server(self, config: McpServerConfig):
        """Register an MCP server configuration."""
        self._servers[config.name] = config

    def remove_server(self, name: str):
        """Remove an MCP server configuration and disconnect if connected."""
        if name in self._clients:
            self._clients[name].disconnect()
            del self._clients[name]
        self._servers.pop(name, None)

    def connect_all(self) -> dict[str, bool]:
        """Connect to all enabled MCP servers. Returns {name: success}."""
        results: dict[str, bool] = {}
        for name, config in self._servers.items():
            if not config.enabled:
                continue
            if name in self._clients and self._clients[name].is_connected:
                results[name] = True
                continue
            client = McpClient(config)
            success = client.connect()
            if success:
                self._clients[name] = client
            results[name] = success
        self._initialized = True
        return results

    def get_all_tools(self) -> list[McpTool]:
        """Get all tools from all connected MCP servers."""
        tools: list[McpTool] = []
        for client in self._clients.values():
            if client.is_connected:
                tools.extend(client.list_tools())
        return tools

    def call_tool(self, server_name: str, tool_name: str, arguments: dict) -> str:
        """Call a tool on a specific MCP server."""
        client = self._clients.get(server_name)
        if not client or not client.is_connected:
            return f"Error: MCP server '{server_name}' not connected"
        return client.call_tool(tool_name, arguments)

    def disconnect_all(self):
        """Disconnect from all MCP servers."""
        for client in self._clients.values():
            client.disconnect()
        self._clients.clear()
        self._initialized = False

    @property
    def server_count(self) -> int:
        return len(self._servers)

    @property
    def connected_count(self) -> int:
        return sum(1 for c in self._clients.values() if c.is_connected)


# ═══════════════════════════════════════════════════════════════════════════════
# Config loading
# ═══════════════════════════════════════════════════════════════════════════════

def load_mcp_configs_from_dict(data: dict) -> list[McpServerConfig]:
    """Parse MCP server configs from a config dictionary.

    Expected format in config.json:
    {
      "mcp_servers": {
        "filesystem": {
          "command": "npx",
          "args": ["-y", "@modelcontextprotocol/server-filesystem", "."],
          "enabled": true
        },
        "github": {
          "command": "npx",
          "args": ["-y", "@modelcontextprotocol/server-github"],
          "env": {"GITHUB_PERSONAL_ACCESS_TOKEN": "..."},
          "enabled": false
        }
      }
    }
    """
    servers_data = data.get("mcp_servers", {})
    configs: list[McpServerConfig] = []
    for name, cfg in servers_data.items():
        if not isinstance(cfg, dict):
            continue
        configs.append(McpServerConfig(
            name=name,
            command=cfg.get("command"),
            args=cfg.get("args", []),
            env=cfg.get("env", {}),
            url=cfg.get("url"),
            headers=cfg.get("headers", {}),
            enabled=cfg.get("enabled", True),
            timeout_seconds=float(cfg.get("timeout", 30)),
        ))
    return configs


# ═══════════════════════════════════════════════════════════════════════════════
# Singleton
# ═══════════════════════════════════════════════════════════════════════════════

_mcp_registry: McpRegistry | None = None


def get_mcp_registry() -> McpRegistry:
    """Get or create the global MCP registry singleton."""
    global _mcp_registry
    if _mcp_registry is None:
        _mcp_registry = McpRegistry()
    return _mcp_registry
