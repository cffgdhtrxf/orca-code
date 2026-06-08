"""Tests for providers layer — adapter registry and adapters."""

import json
import pytest
from orca_code.providers.base import (
    StreamRequestInput, StreamEvent, StreamEventType, ToolDefinition,
)
from orca_code.providers.registry import (
    get_adapter, register_adapter, list_providers, autodetect_provider,
)
from orca_code.providers.openai_compat import OpenAICompatAdapter
from orca_code.providers.deepseek import DeepSeekAdapter
from orca_code.providers.local import LocalAdapter


class TestAdapterRegistration:
    """Verify adapter registration and lookup."""

    def test_register_and_get(self):
        adapter = OpenAICompatAdapter(provider_type="test_openai")
        register_adapter(adapter)
        assert get_adapter("test_openai") is adapter

    def test_get_unknown_raises(self):
        with pytest.raises(KeyError, match="Unknown provider"):
            get_adapter("nonexistent_provider_xyz")

    def test_list_providers(self):
        adapter = OpenAICompatAdapter(provider_type="list_test")
        register_adapter(adapter)
        providers = list_providers()
        types = [p["type"] for p in providers]
        assert "list_test" in types


class TestOpenAICompatAdapter:
    """Verify OpenAI-compatible adapter builds correct requests."""

    def test_build_basic_request(self):
        adapter = OpenAICompatAdapter()
        input_data = StreamRequestInput(
            base_url="https://api.openai.com/v1",
            api_key="test-key",
            model_id="gpt-4o",
            messages=[{"role": "user", "content": "Hello"}],
        )
        req = adapter.build_stream_request(input_data)
        assert req.url == "https://api.openai.com/v1/chat/completions"
        assert req.headers["Authorization"] == "Bearer test-key"

        body = json.loads(req.body)
        assert body["model"] == "gpt-4o"
        assert body["stream"] is True
        assert body["messages"][0]["content"] == "Hello"

    def test_build_request_with_tools(self):
        adapter = OpenAICompatAdapter()
        input_data = StreamRequestInput(
            base_url="https://api.openai.com/v1",
            api_key="test-key",
            model_id="gpt-4o",
            messages=[{"role": "user", "content": "Read /tmp/test.txt"}],
            tools=[
                ToolDefinition(
                    name="read_file",
                    description="Read a file",
                    parameters={
                        "type": "object",
                        "properties": {"path": {"type": "string"}},
                        "required": ["path"],
                    },
                )
            ],
        )
        req = adapter.build_stream_request(input_data)
        body = json.loads(req.body)
        assert "tools" in body
        assert body["tools"][0]["function"]["name"] == "read_file"

    def test_parse_chunk(self):
        adapter = OpenAICompatAdapter()
        events = adapter.parse_stream_line(
            '{"choices":[{"delta":{"content":"Hello"},"index":0}]}'
        )
        assert len(events) == 1
        assert events[0].type == StreamEventType.CHUNK
        assert events[0].delta == "Hello"

    def test_parse_done(self):
        adapter = OpenAICompatAdapter()
        events = adapter.parse_stream_line("[DONE]")
        assert len(events) == 1
        assert events[0].type == StreamEventType.DONE

    def test_supports_thinking(self):
        adapter = OpenAICompatAdapter()
        assert adapter.supports_thinking() is False

        adapter_ds = OpenAICompatAdapter(provider_type="deepseek")
        assert adapter_ds.supports_thinking() is True


class TestDeepSeekAdapter:
    """Verify DeepSeek-specific adapter behaviors."""

    def test_deepseek_always_has_thinking(self):
        adapter = DeepSeekAdapter()
        assert adapter.supports_thinking() is True
        assert adapter.supports_multimodal() is True

    def test_deepseek_default_model(self):
        adapter = DeepSeekAdapter()
        assert adapter.get_default_model() == "deepseek-chat"


class TestLocalAdapter:
    """Verify local model adapter."""

    def test_local_defaults(self):
        adapter = LocalAdapter()
        assert adapter.provider_type == "local"
        assert adapter.supports_thinking() is False
        assert adapter.supports_multimodal() is True
        assert adapter.get_default_model() == "llama3"


class TestAutoDetect:
    """Verify provider auto-detection."""

    def test_detect_deepseek_by_url(self):
        result = autodetect_provider("https://api.deepseek.com", "some-model")
        assert result == "deepseek"

    def test_detect_openai_by_url(self):
        result = autodetect_provider("https://api.openai.com/v1", "gpt-4o")
        assert result == "openai"

    def test_detect_local_by_host(self):
        result = autodetect_provider("http://localhost:11434", "llama3")
        assert result == "local"

    def test_detect_by_model_name(self):
        result = autodetect_provider("https://custom.api.com", "claude-sonnet-4-6")
        assert result == "anthropic"

    def test_detect_default(self):
        result = autodetect_provider("https://unknown.api.com", "unknown-model")
        assert result == "openai_compat"


class TestDeepSeekThinkingMode:
    """Verify DeepSeek thinking mode request building."""

    def test_thinking_enabled_injects_extra_body(self):
        adapter = DeepSeekAdapter()
        input_data = StreamRequestInput(
            base_url="https://api.deepseek.com",
            api_key="sk-test",
            model_id="deepseek-chat",
            messages=[{"role": "user", "content": "Hello"}],
            thinking_enabled=True,
            reasoning_effort="high",
        )
        req = adapter.build_stream_request(input_data)
        body = json.loads(req.body)
        assert "thinking" in body
        assert body["thinking"]["type"] == "enabled"
        assert "stream_options" in body
        assert body["stream_options"]["include_usage"] is True

    def test_thinking_skipped_for_reasoner_model(self):
        adapter = DeepSeekAdapter()
        input_data = StreamRequestInput(
            base_url="https://api.deepseek.com",
            api_key="sk-test",
            model_id="deepseek-reasoner",
            messages=[{"role": "user", "content": "Hello"}],
            thinking_enabled=True,
        )
        req = adapter.build_stream_request(input_data)
        body = json.loads(req.body)
        # reasoner model always has thinking, don't inject "thinking" key
        assert "thinking" not in body

    def test_parse_reasoning_content(self):
        adapter = DeepSeekAdapter()
        events = adapter.parse_stream_line(
            '{"choices":[{"delta":{"reasoning_content":"Let me think..."},"index":0}]}'
        )
        assert len(events) == 1
        assert events[0].type == StreamEventType.REASONING
        assert events[0].delta == "Let me think..."


class TestStreamEventTypes:
    """Verify all stream event type values."""

    def test_all_event_types(self):
        types = {e.value for e in StreamEventType}
        expected = {"chunk", "reasoning", "reasoning_signature",
                    "tool_call_start", "tool_call_delta", "error", "done"}
        assert types == expected

    def test_stream_event_creation(self):
        evt = StreamEvent(
            type=StreamEventType.TOOL_CALL_START,
            tool_call_id="call_123",
            tool_name="read_file",
        )
        assert evt.tool_name == "read_file"
        assert "tool_call_start" in repr(evt)


class TestToolDefinition:
    """Verify ToolDefinition dataclass."""

    def test_tool_definition_fields(self):
        td = ToolDefinition(
            name="search",
            description="Search the web",
            parameters={"type": "object", "properties": {"q": {"type": "string"}}},
        )
        assert td.name == "search"
        assert "q" in td.parameters["properties"]


class TestStreamRequestInput:
    """Verify StreamRequestInput dataclass defaults."""

    def test_default_values(self):
        inp = StreamRequestInput(
            base_url="https://api.test.com",
            api_key="k",
            model_id="m",
            messages=[{"role": "user", "content": "hi"}],
        )
        assert inp.max_output_tokens == 8192
        assert inp.temperature == 0.7
        assert inp.thinking_enabled is False
        assert inp.reasoning_effort == "high"
        assert inp.tools is None


class TestNonStreamRequest:
    """Verify non-streaming request building."""

    def test_build_non_stream_request(self):
        adapter = OpenAICompatAdapter()
        input_data = StreamRequestInput(
            base_url="https://api.openai.com/v1",
            api_key="sk-test",
            model_id="gpt-4o",
            messages=[{"role": "user", "content": "Hello"}],
        )
        req = adapter.build_non_stream_request(input_data)
        body = json.loads(req.body)
        assert body["stream"] is False
