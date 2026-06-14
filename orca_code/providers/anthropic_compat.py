"""orca_code.providers.anthropic_compat — Anthropic Messages API adapter.

Handles the Anthropic Messages API protocol. Many Chinese providers now support
Anthropic-compatible endpoints (Kimi Coding, DeepSeek Anthropic mode, Zhipu Coding).

Key differences from OpenAI-compatible:
  - Endpoint: /v1/messages (not /chat/completions)
  - Auth header: x-api-key (not Bearer)
  - Messages format: content blocks instead of plain text
  - Tool use: content block type "tool_use" instead of "tool_calls"
  - Thinking: extended_thinking with budget_tokens
  - SSE format: server-sent events with different event types
"""

from __future__ import annotations

import json

from .base import (
    ProviderAdapter,
    ProviderRequest,
    StreamEvent,
    StreamEventType,
    StreamRequestInput,
)


class AnthropicCompatAdapter(ProviderAdapter):
    """Adapter for Anthropic-compatible Messages API.

    Handles: Anthropic, Kimi Coding, DeepSeek Anthropic mode, Zhipu Coding.
    """

    provider_type = "anthropic_compat"
    provider_label = "Anthropic Compatible"

    ANTHROPIC_VERSION = "2023-06-01"

    def __init__(self, provider_type: str = "anthropic_compat", label: str = "Anthropic Compatible"):
        self.provider_type = provider_type
        self.provider_label = label

    def build_stream_request(self, input: StreamRequestInput) -> ProviderRequest:
        """Build an Anthropic Messages API streaming request."""
        url = f"{input.base_url.rstrip('/')}/v1/messages"

        headers = {
            "Content-Type": "application/json",
            "x-api-key": input.api_key,
            "anthropic-version": self.ANTHROPIC_VERSION,
        }

        # Convert OpenAI-format messages to Anthropic format
        system_msg = ""
        anthropic_messages = []
        for msg in input.messages:
            role = msg.get("role", "")
            if role == "system":
                system_msg = msg.get("content", "")
                continue

            content = msg.get("content", "")
            anthropic_msg: dict = {"role": role}

            # Handle multimodal content arrays
            if isinstance(content, list):
                anthropic_msg["content"] = content
            else:
                anthropic_msg["content"] = str(content) if content else ""

            anthropic_messages.append(anthropic_msg)

        body: dict = {
            "model": input.model_id,
            "messages": anthropic_messages,
            "max_tokens": input.max_output_tokens,
            "stream": True,
        }

        if system_msg:
            body["system"] = system_msg

        # Tools → Anthropic tool format
        if input.tools:
            body["tools"] = [
                {
                    "name": t.name,
                    "description": t.description,
                    "input_schema": t.parameters,
                }
                for t in input.tools
            ]

        # Extended thinking
        if input.thinking_enabled:
            body["thinking"] = {
                "type": "enabled",
                "budget_tokens": min(input.max_output_tokens // 2, 4096),
            }

        # Extra body overrides
        if input.extra_body:
            body.update(input.extra_body)

        return ProviderRequest(
            url=url,
            headers=headers,
            body=json.dumps(body, ensure_ascii=False),
        )

    def parse_stream_line(self, json_line: str) -> list[StreamEvent]:
        """Parse Anthropic SSE line into StreamEvents.

        Anthropic SSE event types:
          - message_start: metadata
          - content_block_start: new content block (text or tool_use)
          - content_block_delta: text_delta or input_json_delta
          - content_block_stop: end of a content block
          - message_delta: stop_reason, usage
          - message_stop: stream complete
          - ping: keepalive
        """
        if not json_line or not json_line.strip():
            return []

        try:
            data = json.loads(json_line)
        except json.JSONDecodeError:
            return []

        event_type = data.get("type", "")
        events: list[StreamEvent] = []

        if event_type == "content_block_start":
            block = data.get("content_block", {})
            if block.get("type") == "tool_use":
                events.append(StreamEvent(
                    type=StreamEventType.TOOL_CALL_START,
                    tool_call_id=block.get("id", ""),
                    tool_name=block.get("name", ""),
                ))
            elif block.get("type") == "thinking":
                events.append(StreamEvent(type=StreamEventType.REASONING))

        elif event_type == "content_block_delta":
            delta = data.get("delta", {})
            if delta.get("type") == "text_delta":
                events.append(StreamEvent(
                    type=StreamEventType.CHUNK,
                    delta=delta.get("text", ""),
                ))
            elif delta.get("type") == "thinking_delta":
                events.append(StreamEvent(
                    type=StreamEventType.REASONING,
                    delta=delta.get("thinking", ""),
                ))
            elif delta.get("type") == "signature_delta":
                events.append(StreamEvent(
                    type=StreamEventType.REASONING_SIGNATURE,
                    signature=delta.get("signature", ""),
                ))
            elif delta.get("type") == "input_json_delta":
                events.append(StreamEvent(
                    type=StreamEventType.TOOL_CALL_DELTA,
                    arguments_delta=delta.get("partial_json", ""),
                ))

        elif event_type == "message_delta":
            stop_reason = data.get("delta", {}).get("stop_reason", "")
            events.append(StreamEvent(
                type=StreamEventType.DONE,
                stop_reason=stop_reason,
            ))

        elif event_type == "message_stop":
            events.append(StreamEvent(type=StreamEventType.DONE))

        elif event_type == "error":
            events.append(StreamEvent(
                type=StreamEventType.ERROR,
                error=data.get("error", {}).get("message", "Unknown Anthropic error"),
            ))

        return events

    def supports_thinking(self) -> bool:
        return True  # Anthropic supports extended_thinking

    def supports_multimodal(self) -> bool:
        return True  # Claude models support images

    def get_default_model(self) -> str:
        return "claude-sonnet-4-6"
