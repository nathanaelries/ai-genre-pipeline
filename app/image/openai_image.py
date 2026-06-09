"""OpenAI image backend (Images API over httpx).

Consistency strategy: OpenAI image models don't take IP-Adapter-style reference
images, so character coherence relies entirely on the deterministic character
description that the orchestrator injects into every prompt. Returns PNG.
"""

from __future__ import annotations

import base64
from pathlib import Path

import httpx

from app.config import Settings
from app.image.base import ImageBackendBase, ImageBackendError
from app.logging_config import get_logger
from app.utils import api_retry, download_file, raise_for_retryable_status

log = get_logger(__name__)

API_URL = "https://api.openai.com/v1/images/generations"


def _closest_supported_size(width: int, height: int) -> str:
    """Map an arbitrary WxH to the nearest size gpt-image-1 accepts."""
    ratio = width / height
    if ratio > 1.2:
        return "1536x1024"  # landscape
    if ratio < 0.83:
        return "1024x1536"  # portrait
    return "1024x1024"  # square-ish


class OpenAIImageBackend(ImageBackendBase):
    name = "openai"

    def __init__(self, cfg: Settings) -> None:
        super().__init__(cfg)
        cfg.require("openai_api_key")
        self.model = cfg.openai_image_model
        self._client = httpx.Client(timeout=180.0)

    @api_retry
    def generate(
        self,
        prompt: str,
        dest: Path,
        *,
        negative: str = "",
        reference_images: list[Path] | None = None,
        seed: int | None = None,
    ) -> Path:
        # OpenAI has no negative-prompt field; fold it into the prompt as guidance.
        full_prompt = prompt
        if negative:
            full_prompt += f"\n\nAvoid: {negative}"

        headers = {
            "Authorization": f"Bearer {self.cfg.openai_api_key}",
            "Content-Type": "application/json",
        }
        body = {
            "model": self.model,
            "prompt": full_prompt[:4000],
            "n": 1,
            "size": _closest_supported_size(self.cfg.width, self.cfg.height),
        }
        resp = self._client.post(API_URL, headers=headers, json=body)
        raise_for_retryable_status(resp)
        if resp.status_code >= 400:
            raise ImageBackendError(
                f"OpenAI image error {resp.status_code}: {resp.text[:300]}"
            )

        item = resp.json()["data"][0]
        dest.parent.mkdir(parents=True, exist_ok=True)
        if item.get("b64_json"):
            dest.write_bytes(base64.b64decode(item["b64_json"]))
        elif item.get("url"):
            download_file(item["url"], dest)
        else:  # pragma: no cover - defensive
            raise ImageBackendError(f"No image payload in response: {item}")

        log.debug("openai_image", dest=str(dest))
        return dest
