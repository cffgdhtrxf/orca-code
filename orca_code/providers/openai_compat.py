"""orca_code.providers.openai_compat — OpenAI-compatible API adapter.

This adapter handles the standard OpenAI chat completions API protocol,
used by OpenAI, many Chinese providers (Zhipu, Qwen, Doubao, MiniMax),
and custom OpenAI-compatible endpoints.

It wraps the existing openai SDK client pattern used throughout Orca Code.
"""

from __future__ import annotations

import json
from typing import List

from .base import (
    ProviderAdapter, StreamRequestInput, ProviderRequest,
    StreamEvent, StreamEventType, ToolDefinition,
)


class OpenAICompatAdapter(ProviderAdapter):
    """Adapter for OpenAI-compatible chat completions API.

    Handles: OpenAI, Zhipu, Qwen, Doubao, MiniMax, custom endpoints.
    """

    provider_type = "openai_compat"
    provider_label = "OpenAI Compatible"

    def __init__(self, provider_type: str = "openai_compat", label: str = "OpenAI Compatible"):
        self.provider_type = provider_type
        self.provider_label = label

    def build_stream_request(self, input: StreamRequestInput) -> ProviderRequest:
        """Build an OpenAI-compatible streaming chat completions request."""
        url = f"{input.base_url.rstrip('/')}/chat/completions"

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {input.api_key}",
        }

        body: dict = {
            "model": input.model_id,
            "messages": input.messages,
            "stream": True,
            "max_tokens": input.max_output_tokens,
            "temperature": input.temperature,
        }

        # Tools → OpenAI function calling format
        if input.tools:
            body["tools"] = [
                {
                    "type": "function",
                    "function": {
                        "name": t.name,
                        "description": t.description,
                        "parameters": t.parameters,
                    },
                }
                for t in input.tools
            ]

        # Thinking/reasoning — DeepSeek extension, ignored by strict OpenAI
        if input.thinking_enabled and "deepseek" in self.provider_type:
            body["thinking"] = {"type": "enabled"}

        # Extra body overrides (for provider-specific params)
        if input.extra_body:
            body.update(input.extra_body)

        return ProviderRequest(
            url=url,
            headers=headers,
            body=json.dumps(body, ensure_ascii=False),
        )

    def parse_stream_line(self, json_line: str) -> List[StreamEvent]:
        """Parse one SSE data line into StreamEvents."""
        if not json_line or json_line.strip() == "[DONE]":
            return [StreamEvent(type=StreamEventType.DONE)]

        try:
            data = json.loads(json_line)
        except json.JSONDecodeError:
            return []

        events: List[StreamEvent] = []
        choices = data.get("choices", [])

        for choice in choices:
            delta = choice.get("delta", {})

            # Text content
            content = delta.get("content", "")
            if content:
                events.append(StreamEvent(
                    type=StreamEventType.CHUNK,
                    delta=content,
                ))

            # Reasoning content (DeepSeek extension)
            reasoning = delta.get("reasoning_content", "")
            if reasoning:
                events.append(StreamEvent(
                    type=StreamEventType.REASONING,
                    delta=reasoning,
                ))

            # Tool calls
            tool_calls = delta.get("tool_calls", [])
            for tc in tool_calls:
                tc_id = tc.get("id", "")
                tc_func = tc.get("function", {})

                # Tool call start (first chunk with id and name)
                if tc_id and tc_func.get("name"):
                    events.append(StreamEvent(
                        type=StreamEventType.TOOL_CALL_START,
                        tool_call_id=tc_id,
                        tool_name=tc_func["name"],
                    ))

                # Tool call delta (arguments streaming)
                if tc_func.get("arguments"):
                    events.append(StreamEvent(
                        type=StreamEventType.TOOL_CALL_DELTA,
                        tool_call_id=tc_id or "unknown",
                        arguments_delta=tc_func["arguments"],
                    ))

            # Finish reason
            finish = choice.get("finish_reason", "")
            if finish:
                events.append(StreamEvent(
                    type=StreamEventType.DONE,
                    stop_reason=finish,
                ))

        return events

    def supports_thinking(self) -> bool:
        return "deepseek" in self.provider_type

    def get_default_model(self) -> str:
        return "gpt-4o"
