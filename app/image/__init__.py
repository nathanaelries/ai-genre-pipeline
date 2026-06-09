"""Image generation backends (OpenAI images / local ComfyUI)."""

from app.image.factory import get_image_backend

__all__ = ["get_image_backend"]
