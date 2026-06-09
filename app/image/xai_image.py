"""xAI / Grok image backend.

Lets a fully Grok-powered pipeline (`LLM_PROVIDER=grok`) generate images too,
using only `XAI_API_KEY` — no OpenAI key required. Targets xAI's OpenAI-compatible
`/v1/images/generations` endpoint with the `grok-2-image` model.

Note: xAI's image API ignores `size`/`quality`/`style` (it returns a fixed-size
image), so we don't send a size; the assembler scales the key-frame to the run's
resolution downstream.
"""

from __future__ import annotations

from app.config import Settings
from app.image.openai_compat_image import OpenAICompatImageBackend


class XAIImageBackend(OpenAICompatImageBackend):
    def __init__(self, cfg: Settings) -> None:
        super().__init__(
            cfg,
            name="xai",
            base_url="https://api.x.ai/v1",
            api_key=cfg.xai_api_key,
            model=cfg.xai_image_model,
            send_size=False,   # xAI image API does not accept a size parameter
            request_b64=True,  # ask for inline base64 (xAI returns a URL otherwise)
        )
