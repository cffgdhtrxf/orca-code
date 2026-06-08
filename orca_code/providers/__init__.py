"""orca_code.providers — Multi-LLM provider adapter layer.

Inspired by Proma's ProviderAdapter pattern (@proma/core/providers/).
Each provider adapter encapsulates protocol differences, allowing seamless
switching between DeepSeek, OpenAI, Anthropic, and local models.

Usage:
    from orca_code.providers import get_adapter, list_providers

    adapter = get_adapter("deepseek")
    request = adapter.build_request(input)
"""

from .base import ProviderAdapter, StreamRequestInput, ProviderRequest, StreamEvent
from .registry import get_adapter, register_adapter, list_providers

# Auto-register built-in adapters on first import
def _init():
    from .deepseek import DeepSeekAdapter
    from .openai_compat import OpenAICompatAdapter
    from .anthropic_compat import AnthropicCompatAdapter
    from .local import LocalAdapter
    for adapter in [
        DeepSeekAdapter(),
        OpenAICompatAdapter(),
        OpenAICompatAdapter(provider_type="openai", label="OpenAI"),
        AnthropicCompatAdapter(),
        AnthropicCompatAdapter(provider_type="anthropic", label="Anthropic"),
        LocalAdapter(),
    ]:
        try:
            register_adapter(adapter)
        except ValueError:
            pass  # already registered

_init()

__all__ = [
    "ProviderAdapter",
    "StreamRequestInput",
    "ProviderRequest",
    "StreamEvent",
    "get_adapter",
    "register_adapter",
    "list_providers",
]
