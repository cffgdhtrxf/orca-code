"""orca_code.providers.registry — Adapter registry for multi-provider support.

Inspired by Proma's @proma/core/providers/index.ts adapterRegistry Map pattern.
Central registry maps provider type strings to adapter instances.

Usage:
    from orca_code.providers.registry import get_adapter, register_adapter

    adapter = get_adapter("deepseek")
    register_adapter(MyCustomAdapter())
"""

from __future__ import annotations

from .base import ProviderAdapter

# Global adapter registry
_registry: dict[str, ProviderAdapter] = {}
_registry_lock = __import__('threading').Lock()


def register_adapter(adapter: ProviderAdapter) -> None:
    """Register a provider adapter.

    Args:
        adapter: A ProviderAdapter instance. Its provider_type is used as the key.

    Raises:
        ValueError: If provider_type is empty or already registered.
    """
    if not adapter.provider_type:
        raise ValueError(f"Adapter {adapter!r} has empty provider_type")

    with _registry_lock:
        if adapter.provider_type in _registry:
            raise ValueError(
                f"Provider '{adapter.provider_type}' already registered: "
                f"{_registry[adapter.provider_type]!r}"
            )
        _registry[adapter.provider_type] = adapter


def get_adapter(provider_type: str) -> ProviderAdapter:
    """Get a provider adapter by type string.

    Args:
        provider_type: e.g., "deepseek", "openai", "anthropic", "local".

    Returns:
        The registered ProviderAdapter instance.

    Raises:
        KeyError: If the provider type is not registered.
    """
    with _registry_lock:
        if provider_type not in _registry:
            available = ", ".join(sorted(_registry.keys()))
            raise KeyError(
                f"Unknown provider: '{provider_type}'. "
                f"Available: {available or '(none registered)'}"
            )
        return _registry[provider_type]


def list_providers() -> list[dict[str, str]]:
    """Return a list of all registered providers with metadata.

    Returns:
        List of dicts with keys: type, label, thinking, multimodal, default_model.
    """
    with _registry_lock:
        return [
            {
                "type": a.provider_type,
                "label": a.provider_label,
                "thinking": a.supports_thinking(),
                "multimodal": a.supports_multimodal(),
                "default_model": a.get_default_model(),
            }
            for a in _registry.values()
        ]


def autodetect_provider(base_url: str, model_name: str) -> str | None:
    """Auto-detect the provider type from base_url and model_name.

    Used when config does not explicitly declare a provider_type.

    Args:
        base_url: The API base URL from config.
        model_name: The model name from config.

    Returns:
        Provider type string, or None if cannot be determined.
    """
    url_lower = base_url.lower()
    model_lower = model_name.lower()

    # Known host patterns
    if "deepseek.com" in url_lower or "deepseek" in url_lower:
        return "deepseek"
    if "openai.com" in url_lower or "openai" in url_lower:
        return "openai"
    if "anthropic.com" in url_lower or "api.anthropic" in url_lower:
        return "anthropic"
    if any(h in url_lower for h in ("localhost", "127.0.0.1", "ollama")):
        return "local"

    # Model name patterns
    if "deepseek" in model_lower:
        return "deepseek"
    if any(m in model_lower for m in ("gpt-", "o1", "o3", "o4")):
        return "openai"
    if "claude" in model_lower:
        return "anthropic"

    # Default: assume OpenAI-compatible
    return "openai_compat"
