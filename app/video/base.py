"""Abstract video backend.

Every backend is image-to-video: it animates a scene key-frame (which already
encodes the consistent character) using a motion prompt. Passing the key-frame
is the central consistency mechanism — the character is "locked" in the still,
and the video model only adds motion.
"""

from __future__ import annotations

import abc
from pathlib import Path

from app.config import Settings


class VideoBackendError(RuntimeError):
    pass


class VideoBackendBase(abc.ABC):
    name: str = "video"

    def __init__(self, cfg: Settings) -> None:
        self.cfg = cfg

    @abc.abstractmethod
    def generate(
        self,
        prompt: str,
        dest: Path,
        *,
        image_path: Path | None = None,
        duration: float = 5.0,
        seed: int | None = None,
    ) -> Path:
        """Generate a video clip to `dest` and return its path."""
