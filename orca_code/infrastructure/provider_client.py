"""orca_code.infrastructure.provider_client — Provider-aware LLM client factory.

Bridges the existing session.py call_model() with the new ProviderAdapter system.
Provides:
  - Auto-detection of provider type from config (base_url + model_name)
  - Provider-aware client creation (uses appropriate adapter)
  - Error classification wrapping for all API calls
  - Backward-compatible drop-in replacement for the openai.OpenAI client

Usage in session.py:
    from orca_code.infrastructure.provider_client import get_provider_client
    client = get_provider_client()
    stream = client.chat.completions.create(**kwargs)  # same API as before
"""

from __future__ import annotations

import logging
from typing import Any

from openai import OpenAI

from orca_code.core.errors import classify_error
from orca_code.providers.base import (
    ProviderAdapter,
)
from orca_code.providers.registry import autodetect_provider, get_adapter, list_providers

logger = logging.getLogger(__name__)


class ProviderAwareClient:
    """Wraps an OpenAI-compatible client with provider awareness.

    Behaves identically to openai.OpenAI for chat.completions.create(),
    but is configured based on the detected provider type.

    Key features:
      - Auto-detects provider from base_url / model_name
      - Applies provider-specific defaults (e.g., thinking mode for DeepSeek)
      - Classifies API errors for intelligent retry
      - Supports provider hot-switching via /config
    """

    def __init__(
        self,
        api_key: str,
        base_url: str,
        model_name: str,
        provider_type: str | None = None,
    ):
        self.api_key = api_key
        self.base_url = base_url
        self.model_name = model_name
        self.provider_type = provider_type or autodetect_provider(base_url, model_name)

        # Get the adapter for this provider
        self._adapter: ProviderAdapter | None = None
        try:
            self._adapter = get_adapter(self.provider_type)
        except KeyError:
            logger.warning(
                "No adapter registered for provider '%s', using raw OpenAI client",
                self.provider_type,
            )

        # Create the underlying OpenAI client
        self._client = OpenAI(api_key=api_key, base_url=base_url)

    @property
    def chat(self):
        """Return a chat completions interface that wraps API calls with error classification."""
        return _ProviderChatWrapper(self)

    @property
    def adapter(self) -> ProviderAdapter | None:
        return self._adapter

    @property
    def supports_thinking(self) -> bool:
        if self._adapter:
            return self._adapter.supports_thinking()
        return False

    @property
    def supports_multimodal(self) -> bool:
        if self._adapter:
            return self._adapter.supports_multimodal()
        return False


class _ProviderChatWrapper:
    """Wraps the chat.completions interface with provider awareness."""

    def __init__(self, parent: ProviderAwareClient):
        self._parent = parent

    @property
    def completions(self):
        return _ProviderCompletionsWrapper(self._parent)


class _ProviderCompletionsWrapper:
    """Wraps chat.completions.create() with error classification.

    Usage is identical to openai.OpenAI().chat.completions.create(**kwargs).
    """

    def __init__(self, parent: ProviderAwareClient):
        self._parent = parent

    def create(self, **kwargs) -> Any:
        """Create a chat completion. Identical API to openai.OpenAI().chat.completions.create().

        Adds:
          - Provider-specific defaults (thinking, reasoning_effort, etc.)
          - Error classification on failure
        """
        # Inject provider-specific optimizations
        adapter = self._parent.adapter

        # For DeepSeek: add stream_options for cache hit reporting
        if adapter and adapter.provider_type == "deepseek" and kwargs.get("stream"):
            if "stream_options" not in kwargs:
                kwargs["stream_options"] = {"include_usage": True}

        try:
            return self._parent._client.chat.completions.create(**kwargs)
        except Exception as e:
            category, retryable = classify_error(e)
            logger.warning(
                "API error [%s, retryable=%s]: %s",
                category.value, retryable, str(e)[:300],
            )
            raise


def create_provider_client(
    api_key: str = "",
    base_url: str = "https://api.deepseek.com",
    model_name: str = "deepseek-chat",
    provider_type: str | None = None,
) -> ProviderAwareClient:
    """Factory function: create a provider-aware LLM client.

    Args:
        api_key: API key for the provider.
        base_url: API base URL.
        model_name: Model name/ID.
        provider_type: Explicit provider type, or None for auto-detection.

    Returns:
        A ProviderAwareClient wrapping an OpenAI-compatible client.
    """
    return ProviderAwareClient(
        api_key=api_key,
        base_url=base_url,
        model_name=model_name,
        provider_type=provider_type,
    )


def get_provider_info(client: ProviderAwareClient) -> dict[str, Any]:
    """Get diagnostic information about the current provider.

    Returns:
        Dict with keys: provider_type, model, base_url, thinking, multimodal,
        adapter_name.
    """
    info: dict[str, Any] = {
        "provider_type": client.provider_type,
        "model": client.model_name,
        "base_url": client.base_url,
        "thinking": client.supports_thinking,
        "multimodal": client.supports_multimodal,
        "adapter_name": type(client.adapter).__name__ if client.adapter else None,
    }

    # List all available providers
    info["available_providers"] = [
        p["type"] for p in list_providers()
    ]

    return info


# ── Auto-initialization: register adapters on import ─────────────────────

def _init_providers():
    """Register all built-in provider adapters. Called once on first import."""
    from orca_code.providers.anthropic_compat import AnthropicCompatAdapter
    from orca_code.providers.deepseek import DeepSeekAdapter
    from orca_code.providers.local import LocalAdapter
    from orca_code.providers.openai_compat import OpenAICompatAdapter
    from orca_code.providers.registry import register_adapter

    try:
        register_adapter(DeepSeekAdapter())
        register_adapter(OpenAICompatAdapter())
        register_adapter(OpenAICompatAdapter(provider_type="openai", label="OpenAI"))
        register_adapter(AnthropicCompatAdapter())
        register_adapter(AnthropicCompatAdapter(
            provider_type="anthropic", label="Anthropic"
        ))
        register_adapter(LocalAdapter())
    except ValueError:
        # Already registered (imported multiple times)
        pass


# Register on import
_init_providers()
