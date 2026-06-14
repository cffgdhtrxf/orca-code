"""orca_code.providers.base — Provider adapter abstract base class.

Inspired by Proma's ProviderAdapter interface (packages/core/src/providers/types.ts).
Defines the contract all LLM provider adapters must implement.

Each adapter is responsible for:
  1. Converting unified StreamRequestInput → provider-specific HTTP request
  2. Parsing provider-specific SSE stream events → unified StreamEvent list
  3. Declaring provider capabilities (thinking, multimodal, etc.)
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

# ─── Stream event types ──────────────────────────────────────────────────────

class StreamEventType(Enum):
    """Unified stream event types across all providers."""
    CHUNK = "chunk"                      # Text delta
    REASONING = "reasoning"              # Thinking/reasoning delta
    REASONING_SIGNATURE = "reasoning_signature"  # Anthropic thinking signature
    TOOL_CALL_START = "tool_call_start"  # Tool call begins
    TOOL_CALL_DELTA = "tool_call_delta"  # Tool call argument delta
    ERROR = "error"                      # Stream error
    DONE = "done"                        # Stream complete


@dataclass
class StreamEvent:
    """A single event from an LLM stream, provider-agnostic."""
    type: StreamEventType
    delta: str = ""
    tool_call_id: str = ""
    tool_name: str = ""
    arguments_delta: str = ""
    signature: str = ""
    stop_reason: str = ""
    error: str = ""

    def __repr__(self) -> str:
        return f"StreamEvent({self.type.value}, delta='{self.delta[:30]}...')" if self.delta else f"StreamEvent({self.type.value})"


# ─── Request input ───────────────────────────────────────────────────────────

@dataclass
class ToolDefinition:
    """Provider-agnostic tool definition (JSON Schema)."""
    name: str
    description: str
    parameters: dict[str, Any] = field(default_factory=dict)


@dataclass
class StreamRequestInput:
    """Unified input for a streaming LLM request.

    Each adapter converts this to its provider-specific HTTP request format.
    """
    base_url: str
    api_key: str
    model_id: str
    messages: list[dict[str, Any]]         # OpenAI-format message history
    system_prompt: str = ""
    tools: list[ToolDefinition] | None = None
    max_output_tokens: int = 8192
    temperature: float = 0.7
    thinking_enabled: bool = False
    reasoning_effort: str = "high"          # "low" | "medium" | "high" (DeepSeek)
    extra_body: dict[str, Any] | None = None  # Provider-specific overrides


@dataclass
class ProviderRequest:
    """Built HTTP request ready for fetch/requests."""
    url: str
    headers: dict[str, str]
    body: str  # JSON-encoded request body


# ─── Adapter interface ───────────────────────────────────────────────────────

class ProviderAdapter(ABC):
    """Abstract base class for LLM provider adapters.

    Each provider (DeepSeek, OpenAI, Anthropic, Ollama, etc.) implements
    this interface. Adapters are stateless pure-logic objects — they build
    HTTP requests and parse responses but never execute HTTP calls themselves.
    """

    # Subclasses must set these
    provider_type: str = ""          # "deepseek" | "openai" | "anthropic" | "local"
    provider_label: str = ""         # Human-readable label for UI

    @abstractmethod
    def build_stream_request(self, input: StreamRequestInput) -> ProviderRequest:
        """Convert unified input into a provider-specific streaming HTTP request.

        Args:
            input: Unified request input (messages, tools, config).

        Returns:
            A ProviderRequest with URL, headers, and JSON body.
        """
        ...

    @abstractmethod
    def parse_stream_line(self, json_line: str) -> list[StreamEvent]:
        """Parse a single SSE data line into zero or more StreamEvents.

        Args:
            json_line: The JSON string from an SSE "data:" line.

        Returns:
            List of StreamEvents (may be empty for no-op lines like [DONE]).
        """
        ...

    def build_non_stream_request(self, input: StreamRequestInput) -> ProviderRequest:
        """Build a non-streaming request. Default: same as streaming with stream=False."""
        req = self.build_stream_request(input)
        import json
        body = json.loads(req.body)
        body["stream"] = False
        req.body = json.dumps(body, ensure_ascii=False)
        return req

    def supports_thinking(self) -> bool:
        """Whether this provider supports extended thinking/reasoning."""
        return False

    def supports_multimodal(self) -> bool:
        """Whether this provider supports image inputs."""
        return False

    def supports_tools(self) -> bool:
        """Whether this provider supports function calling / tool use."""
        return True

    def get_default_model(self) -> str:
        """Return the default model for this provider."""
        return ""

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__}({self.provider_type})>"
