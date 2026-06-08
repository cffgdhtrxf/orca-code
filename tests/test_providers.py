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
