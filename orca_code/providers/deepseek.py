"""orca_code.providers.deepseek — DeepSeek API adapter.

DeepSeek uses an OpenAI-compatible API with extensions:
  - reasoning_content in delta for thinking mode
  - thinking.type = "enabled" in request body
  - reasoning_effort parameter (low/medium/high)
  - DeepSeek-specific cache hit reporting

This adapter extends OpenAICompatAdapter with DeepSeek-specific behaviors.
"""

from __future__ import annotations

import json
from typing import List

from .base import (
    ProviderAdapter, StreamRequestInput, ProviderRequest,
    StreamEvent, StreamEventType,
)
from .openai_compat import OpenAICompatAdapter


class DeepSeekAdapter(OpenAICompatAdapter):
    """Adapter for DeepSeek API (deepseek-chat, deepseek-reasoner, etc.).

    DeepSeek's API is OpenAI-compatible with these extensions:
      - thinking / reasoning_content for Chain-of-Thought
      - reasoning_effort parameter
      - cache_hit reporting in usage
    """

    provider_type = "deepseek"
    provider_label = "DeepSeek"

    def __init__(self):
        super().__init__(provider_type="deepseek", label="DeepSeek")

    def build_stream_request(self, input: StreamRequestInput) -> ProviderRequest:
        """Build a DeepSeek streaming request with thinking support."""
        req = super().build_stream_request(input)

        # Inject DeepSeek-specific extensions
        body = json.loads(req.body)

        # Thinking mode for DeepSeek
        if input.thinking_enabled and "deepseek-reasoner" not in input.model_id:
            body["thinking"] = {"type": "enabled"}

        # Reasoning effort for V3/R1 models
        if "reasoning_effort" in body.get("extra_body", {}):
            body["reasoning_effort"] = input.reasoning_effort

        # DeepSeek-specific: always include stream_options for usage
        body["stream_options"] = {"include_usage": True}

        req.body = json.dumps(body, ensure_ascii=False)
        return req

    def parse_stream_line(self, json_line: str) -> List[StreamEvent]:
        """Parse DeepSeek SSE line, handling reasoning_content extension."""
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

            # DeepSeek reasoning/thinking content
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

                if tc_id and tc_func.get("name"):
                    events.append(StreamEvent(
                        type=StreamEventType.TOOL_CALL_START,
                        tool_call_id=tc_id,
                        tool_name=tc_func["name"],
                    ))

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
        return True

    def supports_multimodal(self) -> bool:
        # DeepSeek-V3 supports images
        return True

    def get_default_model(self) -> str:
        return "deepseek-chat"
