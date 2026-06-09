"""Video generation backends (Kling / Runway / local ComfyUI)."""

from app.video.factory import get_video_backend

__all__ = ["get_video_backend"]
