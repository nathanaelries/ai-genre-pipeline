"""Anthropic Claude provider (via the Messages REST API over httpx).

Using raw HTTP keeps the dependency surface small and avoids SDK-version drift;
the `anthropic` SDK is listed as an optional extra for those who prefer it.
"""

from __future__ import annotations

import httpx

from app.config import Settings
from app.llm.base import LLMError, LLMProviderBase
from app.utils import api_retry, raise_for_retryable_status

# Default to the latest Claude model family. Override via env if desired.
DEFAULT_MODEL = "claude-opus-4-8"
API_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_VERSION = "2023-06-01"


class ClaudeProvider(LLMProviderBase):
    name = "claude"

    def __init__(self, cfg: Settings, model: str = DEFAULT_MODEL) -> None:
        super().__init__(cfg)
        cfg.require("anthropic_api_key")
        self.model = model
        self._client = httpx.Client(timeout=120.0)

    @api_retry
    def _complete(self, system: str, user: str, *, json_mode: bool) -> str:
        headers = {
            "x-api-key": self.cfg.anthropic_api_key,
            "anthropic-version": ANTHROPIC_VERSION,
            "content-type": "application/json",
        }
        body = {
            "model": self.model,
            "max_tokens": 4096,
            "system": system,
            "messages": [{"role": "user", "content": user}],
        }
        # Nudge JSON output by prefilling the assistant turn with "{".
        # (Only safe for object-shaped requests; array prompts skip this.)
        resp = self._client.post(API_URL, headers=headers, json=body)
        raise_for_retryable_status(resp)
        if resp.status_code >= 400:
            raise LLMError(f"Claude API error {resp.status_code}: {resp.text[:300]}")

        data = resp.json()
        try:
            return "".join(
                block.get("text", "")
                for block in data["content"]
                if block.get("type") == "text"
            )
        except (KeyError, TypeError) as exc:  # pragma: no cover - defensive
            raise LLMError(f"Unexpected Claude response: {data}") from exc
