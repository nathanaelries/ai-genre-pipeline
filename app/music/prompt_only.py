"""prompt_only backend.

The most portable option: generate perfect lyrics + a paste-ready Suno brief and
stop there. The creator generates the song in the Suno web UI, drops the audio
into the track's music folder, and re-runs the pipeline to assemble the video.

Produces no audio, so it needs no API keys at all.
"""

from __future__ import annotations

from pathlib import Path

from app.logging_config import get_logger
from app.models import SongConcept
from app.music.base import MusicBackendBase, MusicResult

log = get_logger(__name__)


class PromptOnlyBackend(MusicBackendBase):
    name = "prompt_only"

    def generate(
        self,
        concept: SongConcept,
        out_dir: Path,
        track_index: int,
        target_seconds: float,
    ) -> MusicResult:
        lyrics_path, suno_prompt_path = self._write_briefs(concept, out_dir, track_index)
        log.info(
            "music_prompt_only",
            track=track_index + 1,
            suno_prompt=str(suno_prompt_path),
        )
        return MusicResult(
            lyrics_path=lyrics_path,
            suno_prompt_path=suno_prompt_path,
            audio_path=None,
            note=(
                "No audio generated (prompt_only). Paste the Suno brief into "
                "suno.com, then drop the rendered audio next to this file and "
                "re-run to assemble the video."
            ),
        )
