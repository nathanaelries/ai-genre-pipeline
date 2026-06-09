"""OpenAI-compatible chat provider.

Both OpenAI and xAI/Grok expose the same `/v1/chat/completions` contract, so a
single implementation parameterised by (base_url, api_key, model) serves both.
"""

from __future__ import annotations

import httpx

from app.config import Settings
from app.llm.base import LLMError, LLMProviderBase
from app.utils import api_retry, raise_for_retryable_status


class OpenAICompatProvider(LLMProviderBase):
    """Chat-completions provider shared by OpenAI and Grok."""

    def __init__(
        self,
        cfg: Settings,
        *,
        name: str,
        base_url: str,
        api_key: str,
        model: str,
    ) -> None:
        super().__init__(cfg)
        if not api_key.strip():
            raise LLMError(f"{name}: API key is empty (check your .env).")
        self.name = name
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self._client = httpx.Client(timeout=120.0)

    @api_retry
    def _complete(self, system: str, user: str, *, json_mode: bool) -> str:
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        body: dict = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": 0.9,
        }
        resp = self._client.post(
            f"{self.base_url}/chat/completions", headers=headers, json=body
        )
        raise_for_retryable_status(resp)
        if resp.status_code >= 400:
            raise LLMError(f"{self.name} API error {resp.status_code}: {resp.text[:300]}")

        data = resp.json()
        try:
            return data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:  # pragma: no cover
            raise LLMError(f"Unexpected {self.name} response: {data}") from exc
