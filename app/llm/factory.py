"""LLM provider factory — maps LLM_PROVIDER to a concrete implementation."""

from __future__ import annotations

from app.config import LLMProvider, Settings
from app.llm.base import LLMProviderBase


def get_llm(cfg: Settings) -> LLMProviderBase:
    """Construct the LLM provider selected by `LLM_PROVIDER` in .env."""
    if cfg.llm_provider is LLMProvider.claude:
        from app.llm.claude import ClaudeProvider

        return ClaudeProvider(cfg)

    if cfg.llm_provider is LLMProvider.openai:
        from app.llm.openai_compat import OpenAICompatProvider

        return OpenAICompatProvider(
            cfg,
            name="openai",
            base_url="https://api.openai.com/v1",
            api_key=cfg.openai_api_key,
            model="gpt-4o",
        )

    if cfg.llm_provider is LLMProvider.grok:
        from app.llm.openai_compat import OpenAICompatProvider

        # xAI exposes an OpenAI-compatible endpoint.
        return OpenAICompatProvider(
            cfg,
            name="grok",
            base_url="https://api.x.ai/v1",
            api_key=cfg.xai_api_key,
            model="grok-3",
        )

    raise ValueError(f"Unsupported LLM provider: {cfg.llm_provider}")
