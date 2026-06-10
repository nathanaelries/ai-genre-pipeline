"""OpenAI-compatible image backend, shared by OpenAI and xAI/Grok.

Both providers expose the same `/v1/images/generations` contract, so a single
implementation parameterised by (base_url, api_key, model) serves both — mirroring
how `app/llm/openai_compat.py` backs both chat providers.

Provider quirks handled via flags:
  * `send_size`   — OpenAI's gpt-image-1 accepts a `size`; xAI's image API does not.
  * `request_b64` — ask for base64 inline (xAI defaults to returning a URL).

Neither provider supports IP-Adapter-style reference images, so character coherence
relies on the deterministic character description the orchestrator bakes into every
prompt. (`supports_reference_images` stays False, inherited from the base.)
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


def closest_supported_size(width: int, height: int) -> str:
    """Map an arbitrary WxH to the nearest size the image API accepts."""
    ratio = width / height
    if ratio > 1.2:
        return "1536x1024"  # landscape
    if ratio < 0.83:
        return "1024x1536"  # portrait
    return "1024x1024"  # square-ish


class OpenAICompatImageBackend(ImageBackendBase):
    """Image backend for any OpenAI-compatible `/images/generations` endpoint."""

    def __init__(
        self,
        cfg: Settings,
        *,
        name: str,
        base_url: str,
        api_key: str,
        model: str,
        send_size: bool = True,
        request_b64: bool = False,
        quality: str | None = None,
    ) -> None:
        super().__init__(cfg)
        if not api_key.strip():
            raise ImageBackendError(f"{name}: API key is empty (check your .env).")
        self.name = name
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.send_size = send_size
        self.request_b64 = request_b64
        # Cost lever (OpenAI gpt-image-1: low|medium|high — ~10-15x price spread).
        self.quality = quality
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
        # These APIs have no negative-prompt field; fold it in as guidance.
        full_prompt = prompt
        if negative:
            full_prompt += f"\n\nAvoid: {negative}"

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        body: dict = {"model": self.model, "prompt": full_prompt[:4000], "n": 1}
        if self.send_size:
            body["size"] = closest_supported_size(self.cfg.width, self.cfg.height)
        if self.request_b64:
            body["response_format"] = "b64_json"
        if self.quality:
            body["quality"] = self.quality

        resp = self._client.post(
            f"{self.base_url}/images/generations", headers=headers, json=body
        )
        raise_for_retryable_status(resp)
        if resp.status_code >= 400:
            raise ImageBackendError(
                f"{self.name} image error {resp.status_code}: {resp.text[:300]}"
            )

        item = resp.json()["data"][0]
        dest.parent.mkdir(parents=True, exist_ok=True)
        if item.get("b64_json"):
            dest.write_bytes(base64.b64decode(item["b64_json"]))
        elif item.get("url"):
            download_file(item["url"], dest)
        else:  # pragma: no cover - defensive
            raise ImageBackendError(f"No image payload in response: {item}")

        log.debug("image_generated", backend=self.name, dest=str(dest))
        return dest
