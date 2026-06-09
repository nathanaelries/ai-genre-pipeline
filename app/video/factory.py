"""Video backend factory — maps VIDEO_BACKEND to a concrete implementation."""

from __future__ import annotations

from app.config import Settings, VideoBackendKind
from app.video.base import VideoBackendBase


def get_video_backend(cfg: Settings) -> VideoBackendBase:
    if cfg.video_backend is VideoBackendKind.kling:
        from app.video.kling import KlingVideoBackend

        return KlingVideoBackend(cfg)

    if cfg.video_backend is VideoBackendKind.runway:
        from app.video.runway import RunwayVideoBackend

        return RunwayVideoBackend(cfg)

    if cfg.video_backend is VideoBackendKind.comfyui:
        from app.video.comfyui import ComfyUIVideoBackend

        return ComfyUIVideoBackend(cfg)

    raise ValueError(f"Unsupported video backend: {cfg.video_backend}")
