"""local backend.

Intended for a self-hosted music model (e.g. a MusicGen server). Since no
specific local model is mandated, this implementation does the dependable thing:
it writes the briefs AND renders a correctly-timed *silent* audio bed with
ffmpeg, so a fully offline run still produces a complete, properly-paced video.

To wire in a real local model, replace `_render_silent_bed` with a call to your
inference server and return the produced file.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from app.logging_config import get_logger
from app.models import SongConcept
from app.music.base import MusicBackendBase, MusicBackendError, MusicResult

log = get_logger(__name__)


class LocalBackend(MusicBackendBase):
    name = "local"

    def generate(
        self,
        concept: SongConcept,
        out_dir: Path,
        track_index: int,
        target_seconds: float,
    ) -> MusicResult:
        lyrics_path, suno_prompt_path = self._write_briefs(concept, out_dir, track_index)

        stem = f"track_{track_index + 1:02d}"
        audio_path = self._render_silent_bed(out_dir / f"{stem}.wav", target_seconds)
        log.warning(
            "music_local_placeholder",
            track=track_index + 1,
            seconds=target_seconds,
            note="silent stand-in; wire a local model into LocalBackend to replace",
        )
        return MusicResult(
            lyrics_path=lyrics_path,
            suno_prompt_path=suno_prompt_path,
            audio_path=audio_path,
            note="Offline silent bed (placeholder). Replace with a local model.",
        )

    @staticmethod
    def _render_silent_bed(dest: Path, seconds: float) -> Path:
        dest.parent.mkdir(parents=True, exist_ok=True)
        cmd = [
            "ffmpeg", "-y",
            "-f", "lavfi",
            "-i", "anullsrc=channel_layout=stereo:sample_rate=44100",
            "-t", f"{max(seconds, 1):.2f}",
            "-c:a", "pcm_s16le",
            str(dest),
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode != 0:
            raise MusicBackendError(f"ffmpeg silent-bed failed: {proc.stderr[:300]}")
        return dest
