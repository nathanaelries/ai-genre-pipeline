"""OpenAI image backend (Images API).

Thin wrapper over the shared OpenAI-compatible image backend, pinned to OpenAI's
endpoint + `gpt-image-1` (which accepts a `size` and returns base64 by default).
"""

from __future__ import annotations

from app.config import Settings
from app.image.openai_compat_image import OpenAICompatImageBackend


class OpenAIImageBackend(OpenAICompatImageBackend):
    def __init__(self, cfg: Settings) -> None:
        super().__init__(
            cfg,
            name="openai",
            base_url="https://api.openai.com/v1",
            api_key=cfg.openai_api_key,
            model=cfg.openai_image_model,
            send_size=True,
            request_b64=False,
        )
