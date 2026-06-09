"""Progress tracking + resume.

The pipeline is a sequence of expensive, fallible steps (LLM calls, paid video
generation). We persist a tiny `state.json` after every completed step so an
interrupted run can be re-invoked and skip work that already succeeded.

Granularity is intentionally coarse-but-keyed: top-level stages plus per-item
keys like ``scene:0:1`` (track 0, scene 1) so a crash mid-track only re-does the
unfinished scenes.
"""

from __future__ import annotations

import json
from pathlib import Path

from app.logging_config import get_logger

log = get_logger(__name__)


class RunState:
    """A resumable set of completed-step markers backed by a JSON file."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._done: set[str] = set()
        self._load()

    def _load(self) -> None:
        if self._path.exists():
            try:
                data = json.loads(self._path.read_text(encoding="utf-8"))
                self._done = set(data.get("completed", []))
                log.info("state_loaded", completed=len(self._done), path=str(self._path))
            except (json.JSONDecodeError, OSError) as exc:
                log.warning("state_load_failed", error=str(exc))
                self._done = set()

    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(
            json.dumps({"completed": sorted(self._done)}, indent=2),
            encoding="utf-8",
        )

    def is_done(self, key: str) -> bool:
        return key in self._done

    def mark(self, key: str) -> None:
        """Record a step as complete and immediately persist."""
        self._done.add(key)
        self._save()
        log.debug("state_marked", key=key)

    def reset(self) -> None:
        """Forget all progress (used by `--force`)."""
        self._done.clear()
        self._save()

    # Stage-key helpers keep key naming consistent across the orchestrator.
    @staticmethod
    def scene_image(track: int, scene: int) -> str:
        return f"image:{track}:{scene}"

    @staticmethod
    def scene_video(track: int, scene: int) -> str:
        return f"video:{track}:{scene}"

    @staticmethod
    def track_audio(track: int) -> str:
        return f"audio:{track}"

    @staticmethod
    def track_final(track: int) -> str:
        return f"final:{track}"
