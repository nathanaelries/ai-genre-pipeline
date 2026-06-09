"""Music generation backends (Suno third-party / local / prompt-only)."""

from app.music.factory import get_music_backend

__all__ = ["get_music_backend"]
