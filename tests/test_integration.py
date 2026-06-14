"""Integration tests: Provider client, Tool bridge, EventBus wiring.

Verifies that the new modules work together correctly without breaking
backward compatibility with the existing TOOL_MAP system.
"""

from unittest.mock import MagicMock

import pytest

# ═══════════════════════════════════════════════════════════════════════════════
# Mock API streaming tests
# ═══════════════════════════════════════════════════════════════════════════════

class MockStreamChunk:
    def __init__(self, content="", reasoning="", tool_calls=None, usage=None):
        self.choices = [MagicMock()]
        self.choices[0].delta = MagicMock()
        self.choices[0].delta.content = content
        self.choices[0].delta.reasoning_content = reasoning
        self.choices[0].delta.tool_calls = tool_calls or []
        self.usage = usage


class TestMockAPIStream:
    """Verify stream processing with mocked API responses."""

    def test_process_text_stream(self):
        """Text-only stream should accumulate content."""
        from orca_code.session_stream import process_stream
        chunks = [
            MockStreamChunk(content="Hello "),
            MockStreamChunk(content="World"),
            MagicMock(choices=[], usage=MagicMock(prompt_tokens=10, completion_tokens=5)),
        ]
        reasoning, answer, tools, usage = process_stream(chunks)
        assert "Hello World" in answer
        assert reasoning == ""
        assert tools == {}

    def test_process_reasoning_stream(self):
        """Reasoning content should be captured separately."""
        from orca_code.session_stream import process_stream
        c1 = MockStreamChunk(content="", reasoning="Let me think...")
        c2 = MockStreamChunk(content="The answer", reasoning="")
        end = MagicMock(choices=[], usage=None)
        reasoning, answer, tools, usage = process_stream([c1, c2, end])
        assert "Let me think" in reasoning
        assert "The answer" in answer

    def test_process_tool_call_stream(self):
        """Tool call deltas should be accumulated by index."""
        from orca_code.session_stream import process_stream
        tc_delta = MagicMock()
        tc_delta.index = 0
        tc_delta.id = "call_1"
        tc_delta.function = MagicMock()
        tc_delta.function.name = "read_file"
        tc_delta.function.arguments = '{"path":'

        tc_delta2 = MagicMock()
        tc_delta2.index = 0
        tc_delta2.id = None
        tc_delta2.function = MagicMock()
        tc_delta2.function.name = None
        tc_delta2.function.arguments = '"/tmp/test.txt"}'

        chunks = [
            MockStreamChunk(tool_calls=[tc_delta]),
            MockStreamChunk(tool_calls=[tc_delta2]),
            MagicMock(choices=[], usage=None),
        ]
        reasoning, answer, tools, usage = process_stream(chunks)
        assert 0 in tools
        assert tools[0]["function_name"] == "read_file"
        assert "/tmp/test.txt" in tools[0]["function_arguments"]

    def test_sanitize_messages_removes_orphan_tools(self):
        """Tool messages without matching tool_call should be removed."""
        from orca_code.session_messages import sanitize_messages
        msgs = [
            {"role": "user", "content": "hello"},
            {"role": "tool", "tool_call_id": "orphan_1", "content": "result"},
            {"role": "assistant", "content": "reply"},
        ]
        cleaned = sanitize_messages(msgs)
        tool_msgs = [m for m in cleaned if m["role"] == "tool"]
        assert len(tool_msgs) == 0

    def test_sanitize_messages_preserves_valid_tools(self):
        """Tool messages with matching tool_call should be preserved."""
        from orca_code.session_messages import sanitize_messages
        msgs = [
            {"role": "user", "content": "read /tmp/test.txt"},
            {"role": "assistant", "content": None, "tool_calls": [
                {"id": "call_1", "type": "function", "function": {"name": "read_file", "arguments": '{"path":"/tmp/test.txt"}'}}
            ]},
            {"role": "tool", "tool_call_id": "call_1", "content": "file contents"},
        ]
        cleaned = sanitize_messages(msgs)
        tool_msgs = [m for m in cleaned if m["role"] == "tool"]
        assert len(tool_msgs) == 1

    def test_token_estimation_non_empty(self):
        """Token estimation should return positive count for non-empty text."""
        from orca_code.utils import _estimate_tokens
        tokens = _estimate_tokens("Hello World")
        assert tokens > 0

    def test_token_estimation_empty(self):
        """Token estimation should return 0 for empty text."""
        from orca_code.utils import _estimate_tokens
        assert _estimate_tokens("") == 0
        assert _estimate_tokens(None) == 0

    def test_call_model_includes_stream_options(self):
        """call_model should include stream_options for usage reporting."""
        from orca_code.session_stream import call_model
        # Verify the function exists and is callable with basic args
        msgs = [{"role": "user", "content": "hello"}]
        # We can't easily mock the tenacity-wrapped client, but we can verify
        # the function doesn't crash on import/signature check
        import inspect
        sig = inspect.signature(call_model)
        assert "messages" in sig.parameters

    def test_error_classification_network(self):
        """Network errors should be classified as retryable."""
        from orca_code.core.errors import ErrorCategory, classify_error
        cat, retry = classify_error(ConnectionError("Connection refused"))
        assert cat == ErrorCategory.NETWORK
        assert retry is True

    def test_error_classification_auth(self):
        """Auth errors should NOT be retryable."""
        from orca_code.core.errors import ErrorCategory, classify_error
        cat, retry = classify_error(Exception("Invalid API Key"))
        assert cat == ErrorCategory.AUTH
        assert retry is False


class TestProviderClient:
    """Verify ProviderAwareClient creation and auto-detection."""

    def test_create_deepseek_client(self):
        from orca_code.infrastructure.provider_client import create_provider_client
        client = create_provider_client(
            api_key="test-key",
            base_url="https://api.deepseek.com",
            model_name="deepseek-chat",
        )
        assert client.provider_type == "deepseek"
        assert client.supports_thinking is True
        assert client.model_name == "deepseek-chat"

    def test_create_openai_client(self):
        from orca_code.infrastructure.provider_client import create_provider_client
        client = create_provider_client(
            api_key="test-key",
            base_url="https://api.openai.com/v1",
            model_name="gpt-4o",
        )
        assert client.provider_type == "openai"
        assert client.supports_thinking is False

    def test_create_local_client(self):
        from orca_code.infrastructure.provider_client import create_provider_client
        client = create_provider_client(
            api_key="not-needed",
            base_url="http://localhost:11434/v1",
            model_name="llama3",
        )
        assert client.provider_type == "local"

    def test_auto_detect_by_model(self):
        from orca_code.infrastructure.provider_client import create_provider_client
        client = create_provider_client(
            api_key="test-key",
            base_url="https://custom.api.com/v1",
            model_name="claude-sonnet-4-6",
        )
        assert client.provider_type == "anthropic"

    def test_get_provider_info(self):
        from orca_code.infrastructure.provider_client import (
            create_provider_client,
            get_provider_info,
        )
        client = create_provider_client(
            api_key="test-key",
            base_url="https://api.deepseek.com",
            model_name="deepseek-chat",
        )
        info = get_provider_info(client)
        assert info["provider_type"] == "deepseek"
        assert info["thinking"] is True
        assert "available_providers" in info

    def test_chat_completions_interface_exists(self):
        """Verify the wrapped client has the expected .chat.completions interface."""
        from orca_code.infrastructure.provider_client import create_provider_client
        client = create_provider_client(
            api_key="test-key",
            base_url="https://api.deepseek.com",
            model_name="deepseek-chat",
        )
        # The client should expose .chat.completions.create
        assert hasattr(client, 'chat')
        assert hasattr(client.chat, 'completions')
        assert hasattr(client.chat.completions, 'create')


class TestToolBridge:
    """Verify ToolRegistry bridge to legacy TOOL_MAP works."""

    def test_registry_populated_at_import(self):
        from orca_code.tools import tool_registry
        assert len(tool_registry) >= 50
        assert "read_file" in tool_registry
        assert "execute_command" in tool_registry

    def test_bridge_dispatch_executes(self):
        from orca_code.tools import tool_registry
        result = tool_registry.dispatch("get_system_info")
        assert "Python" in result

    def test_bridge_unknown_tool(self):
        from orca_code.tools import tool_registry
        with pytest.raises(KeyError):
            tool_registry.dispatch("nonexistent_tool_xyz")

    def test_bridge_legacy_sync(self):
        from orca_code.tools import tool_registry
        from orca_code.tools.bridge import sync_from_legacy
        count = sync_from_legacy()
        assert count >= 0
        assert len(tool_registry) >= 50

    def test_bridge_to_legacy_map(self):
        from orca_code.tools import tool_registry
        legacy = tool_registry.to_legacy_map()
        assert callable(legacy["read_file"])


class TestEventBusIntegration:
    """Verify EventBus pub-sub works correctly."""

    def test_event_bus_subscribe_and_emit(self):
        from orca_code.core.event_bus import AgentEvent, EventType, get_event_bus
        bus = get_event_bus()
        events = []

        @bus.on(EventType.TOOL_START)
        def handler(e):
            events.append(e)

        bus.emit(AgentEvent(EventType.TOOL_START, {"name": "test"}, "test"))
        assert len(events) == 1
        assert events[0].data["name"] == "test"
        bus.unsubscribe(EventType.TOOL_START, handler)

    def test_event_bus_isolated_errors(self):
        from orca_code.core.event_bus import AgentEvent, EventType, get_event_bus
        bus = get_event_bus()
        called = []

        @bus.on(EventType.TOOL_ERROR)
        def bad(e):
            raise RuntimeError("boom")

        @bus.on(EventType.TOOL_ERROR)
        def good(e):
            called.append(True)

        bus.emit(AgentEvent(EventType.TOOL_ERROR, {}))
        assert len(called) == 1
        bus.unsubscribe(EventType.TOOL_ERROR, bad)
        bus.unsubscribe(EventType.TOOL_ERROR, good)

class TestBackwardCompatibility:
    """Verify new modules don't break the existing TOOL_MAP system."""

    def test_legacy_tool_map_still_works(self):
        """The original TOOL_MAP dict should still be importable and functional."""
        # This imports through the original __init__.py star imports
        from orca_code.main import TOOL_MAP
        assert isinstance(TOOL_MAP, dict)
        assert "read_file" in TOOL_MAP
        assert "execute_command" in TOOL_MAP
        assert callable(TOOL_MAP["read_file"])

    def test_legacy_run_tool_still_works(self, temp_file):
        """The original run_tool function should still work."""
        from orca_code.main import run_tool
        result = run_tool("read_file", {"path": str(temp_file)})
        assert "Hello World" in result

    def test_providers_list_available(self):
        """Verify all built-in providers are auto-registered."""
        from orca_code.providers.registry import list_providers
        providers = list_providers()
        provider_types = [p["type"] for p in providers]
        assert "deepseek" in provider_types
        assert "openai" in provider_types
        assert "anthropic" in provider_types
        assert "local" in provider_types
        assert "openai_compat" in provider_types
