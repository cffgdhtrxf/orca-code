"""Pytest configuration and shared fixtures for Orca Code tests.

Fixture catalog:
- temp_dir / temp_file — basic file I/O tests
- mock_config — minimal config dict
- no_env_deps (autouse) — tests run without env var dependencies
- mock_openai_client — returns mock streaming chunks
- mock_http_server — local HTTP server for web_fetch tests
- sample_messages — standard OpenAI-format message list

Orca Code 设计哲学：开箱即用，不依赖环境变量。
填好 config.json 即可启动，测试也不应依赖外部环境。
"""

import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest

_PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))


# ── Basic fixtures ────────────────────────────────────────────────────────────


@pytest.fixture
def temp_dir():
    """Create a temporary directory. Auto-cleaned."""
    with tempfile.TemporaryDirectory() as d:
        yield Path(d)


@pytest.fixture
def temp_file(temp_dir):
    """Create a temporary file with test content. Returns Path."""
    f = temp_dir / "test.txt"
    f.write_text("Hello World\nLine 2\nLine 3\n", encoding="utf-8")
    return f


@pytest.fixture
def mock_config():
    """Return a minimal config dict for tests.

    Use with mock.patch.dict(os.environ, {"CI": "1"}, ...)
    to bypass the plaintext-key guard at import time.
    """
    return {
        "api_key": "test-key-1234567890",
        "base_url": "https://api.deepseek.com",
        "model_name": "deepseek-chat",
        "max_output_tokens": 8192,
        "enable_think_mode": True,
        "context_max_tokens": 100000,
        "max_workers": 5,
        "keep_last_rounds": 20,
        "cmd_timeout": 120,
        "permission_mode": "auto",
        "permission_rules": {},
    }


# ── Environment fixture ───────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def no_env_deps():
    """Ensure tests run without requiring any env vars or extras.

    Orca Code 设计为开箱即用，测试也不应依赖环境变量。
    """
    yield


# ── Mock LLM streaming client ────────────────────────────────────────────────


@pytest.fixture
def mock_openai_client():
    """Return a MagicMock OpenAI client that yields stream chunks.

    Usage:
        client = mock_openai_client()
        stream = client.chat.completions.create.return_value
        for chunk in stream:
            ...
    """
    from openai import OpenAI

    def _make_chunk(content="", reasoning="", tool_calls=None, finish_reason=None):
        """Build a mock stream chunk resembling OpenAI's API."""
        choice = MagicMock()
        choice.delta.content = content
        choice.delta.reasoning_content = reasoning
        choice.delta.tool_calls = tool_calls
        choice.finish_reason = finish_reason
        choice.index = 0

        chunk = MagicMock()
        chunk.choices = [choice]
        chunk.usage = None
        chunk.model = "test-model"
        return chunk

    def _stream_gen():
        yield _make_chunk(content="Hello ")
        yield _make_chunk(content="world")
        yield _make_chunk(content="", finish_reason="stop")

    client = MagicMock(spec=OpenAI)
    client.chat.completions.create.return_value = _stream_gen()
    return client


@pytest.fixture
def sample_messages():
    """A standard list of OpenAI-format messages."""
    return [
        {"role": "system", "content": "You are a helpful assistant."},
        {"role": "user", "content": "Hello"},
        {"role": "assistant", "content": "Hi there!"},
        {"role": "user", "content": "What is 2+2?"},
        {"role": "assistant", "content": "4", "tool_calls": [
            {"id": "call_1", "type": "function",
             "function": {"name": "calculator", "arguments": '{"expr":"2+2"}'}}
        ]},
        {"role": "tool", "tool_call_id": "call_1", "content": "4"},
        {"role": "assistant", "content": "The answer is 4."},
    ]


# ── Mock HTTP server ─────────────────────────────────────────────────────────


@pytest.fixture
def mock_http_server():
    """Context manager that starts a local HTTP server for web_fetch tests.

    Usage:
        with mock_http_server() as server:
            url = f"http://127.0.0.1:{server.port}/test"
            # use url with web_fetch
    """
    import threading
    from http.server import HTTPServer, SimpleHTTPRequestHandler

    class _TestHandler(SimpleHTTPRequestHandler):
        def do_GET(self):
            body = json.dumps({"status": "ok", "path": self.path}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, fmt, *args):
            pass  # suppress stderr output during testing

    server = HTTPServer(("127.0.0.1", 0), _TestHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
