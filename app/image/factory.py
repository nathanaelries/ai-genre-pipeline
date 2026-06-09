"""Image backend factory — maps IMAGE_BACKEND to a concrete implementation."""

from __future__ import annotations

from app.config import ImageBackendKind, Settings
from app.image.base import ImageBackendBase


def get_image_backend(cfg: Settings) -> ImageBackendBase:
    if cfg.image_backend is ImageBackendKind.openai:
        from app.image.openai_image import OpenAIImageBackend

        return OpenAIImageBackend(cfg)

    if cfg.image_backend is ImageBackendKind.comfyui:
        from app.image.comfyui import ComfyUIImageBackend

        return ComfyUIImageBackend(cfg)

    raise ValueError(f"Unsupported image backend: {cfg.image_backend}")
