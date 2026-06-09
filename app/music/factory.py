"""Music backend factory — maps MUSIC_BACKEND to a concrete implementation."""

from __future__ import annotations

from app.config import MusicBackendKind, Settings
from app.music.base import MusicBackendBase


def get_music_backend(cfg: Settings) -> MusicBackendBase:
    if cfg.music_backend is MusicBackendKind.suno_thirdparty:
        from app.music.suno_thirdparty import SunoThirdPartyBackend

        return SunoThirdPartyBackend(cfg)

    if cfg.music_backend is MusicBackendKind.local:
        from app.music.local import LocalBackend

        return LocalBackend(cfg)

    if cfg.music_backend is MusicBackendKind.prompt_only:
        from app.music.prompt_only import PromptOnlyBackend

        return PromptOnlyBackend(cfg)

    raise ValueError(f"Unsupported music backend: {cfg.music_backend}")
