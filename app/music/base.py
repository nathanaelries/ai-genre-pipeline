"""Abstract music backend.

Every backend writes the lyrics + a ready-to-paste Suno style prompt to disk
(so manual generation is always possible), and *optionally* returns a produced
audio file. Backends that can't produce audio return ``audio_path=None`` and the
assembler renders a correctly-timed silent video instead.
"""

from __future__ import annotations

import abc
from dataclasses import dataclass
from pathlib import Path

from app.config import Settings
from app.models import SongConcept


@dataclass
class MusicResult:
    """Outcome of a music-generation attempt for one track."""

    lyrics_path: Path
    suno_prompt_path: Path
    audio_path: Path | None = None
    note: str = ""


class MusicBackendError(RuntimeError):
    pass


class MusicBackendBase(abc.ABC):
    name: str = "music"

    def __init__(self, cfg: Settings) -> None:
        self.cfg = cfg

    def _write_briefs(
        self, concept: SongConcept, out_dir: Path, track_index: int
    ) -> tuple[Path, Path]:
        """Persist lyrics + Suno style prompt; shared by all backends."""
        out_dir.mkdir(parents=True, exist_ok=True)
        stem = f"track_{track_index + 1:02d}"

        lyrics_path = out_dir / f"{stem}_lyrics.txt"
        lyrics_path.write_text(concept.lyrics, encoding="utf-8")

        # A rich, paste-ready Suno brief: style line + structure + lyrics.
        suno_prompt_path = out_dir / f"{stem}_suno_prompt.txt"
        suno_prompt_path.write_text(
            self._format_suno_brief(concept), encoding="utf-8"
        )
        return lyrics_path, suno_prompt_path

    @staticmethod
    def _format_suno_brief(concept: SongConcept) -> str:
        structure = " -> ".join(concept.structure) if concept.structure else "n/a"
        bpm = f"{concept.bpm} BPM" if concept.bpm else "BPM: pick to taste"
        return (
            f"TITLE: {concept.title}\n\n"
            f"--- STYLE OF MUSIC (paste into Suno 'Style' field) ---\n"
            f"{concept.suno_style_prompt}\n"
            f"{bpm}\n\n"
            f"--- SONG STRUCTURE ---\n{structure}\n\n"
            f"--- LYRICS (paste into Suno 'Lyrics' field) ---\n{concept.lyrics}\n"
        )

    @abc.abstractmethod
    def generate(
        self,
        concept: SongConcept,
        out_dir: Path,
        track_index: int,
        target_seconds: float,
    ) -> MusicResult:
        """Produce briefs (always) and audio (if the backend supports it)."""
