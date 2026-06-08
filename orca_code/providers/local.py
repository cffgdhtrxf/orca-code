"""orca_code.providers.local — Local model adapter (Ollama, LM Studio, vLLM).

Local models use OpenAI-compatible /v1/chat/completions endpoints but:
  - No authentication needed (localhost)
  - May not support all features (thinking, tools vary by model)
  - Often have lower context windows
"""

from __future__ import annotations

from .openai_compat import OpenAICompatAdapter


class LocalAdapter(OpenAICompatAdapter):
    """Adapter for locally-hosted models via Ollama / LM Studio / vLLM.

    These typically expose OpenAI-compatible endpoints at localhost.
    No API key required.
    """

    provider_type = "local"
    provider_label = "Local Model (Ollama/LM Studio/vLLM)"

    def __init__(self):
        super().__init__(provider_type="local", label="Local Model (Ollama/LM Studio/vLLM)")

    def supports_thinking(self) -> bool:
        # Most local models don't support extended thinking
        # Override if using a model that does (like local DeepSeek-R1)
        return False

    def supports_multimodal(self) -> bool:
        # Ollama supports multimodal with llava/minicpm/etc
        return True

    def supports_tools(self) -> bool:
        # Tool support depends on the model — assume yes for modern ones
        return True

    def get_default_model(self) -> str:
        return "llama3"
