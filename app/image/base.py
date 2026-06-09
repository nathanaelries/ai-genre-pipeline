"""Abstract image backend.

Used for two jobs:
  1. character reference images (the consistency anchors), and
  2. per-scene key-frame images that seed the video stage.

`reference_images` is how consistency propagates: scene generation passes the
character references so backends that support it (ComfyUI IP-Adapter) can lock
the character's appearance. Text-only backends ignore them and rely on the
deterministic character description baked into the prompt.
"""

from __future__ import annotations

import abc
from pathlib import Path

from app.config import Settings


class ImageBackendError(RuntimeError):
    pass


class ImageBackendBase(abc.ABC):
    name: str = "image"

    def __init__(self, cfg: Settings) -> None:
        self.cfg = cfg

    @abc.abstractmethod
    def generate(
        self,
        prompt: str,
        dest: Path,
        *,
        negative: str = "",
        reference_images: list[Path] | None = None,
        seed: int | None = None,
    ) -> Path:
        """Generate one image to `dest` and return its path."""

    @property
    def supports_reference_images(self) -> bool:
        """Whether this backend can use reference images for consistency."""
        return False
