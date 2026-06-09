"""FFmpeg-based final assembly.

Responsibilities:
  * normalise each scene clip to identical geometry/fps/codec,
  * turn a still into a Ken-Burns clip (fallback when video gen is unavailable),
  * concatenate scenes in order,
  * mux the song audio with gentle fades (synced to the music),
  * optionally burn a karaoke-style lyric overlay.

All operations shell out to ffmpeg/ffprobe (must be on PATH; the Docker image
installs them). Each step is a small, independently-testable function.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from app.logging_config import get_logger

log = get_logger(__name__)


class AssemblyError(RuntimeError):
    pass


def _run(cmd: list[str], cwd: Path | None = None) -> None:
    log.debug("ffmpeg", cmd=" ".join(cmd))
    proc = subprocess.run(
        cmd, capture_output=True, text=True, cwd=str(cwd) if cwd else None
    )
    if proc.returncode != 0:
        raise AssemblyError(
            f"ffmpeg failed ({proc.returncode}):\n{proc.stderr[-1200:]}"
        )


class FFmpegAssembler:
    def __init__(self, width: int, height: int, fps: int) -> None:
        self.w = width
        self.h = height
        self.fps = fps

    # ------------------------------------------------------------------ #
    # Probing
    # ------------------------------------------------------------------ #
    @staticmethod
    def probe_duration(path: Path) -> float:
        proc = subprocess.run(
            [
                "ffprobe", "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                str(path),
            ],
            capture_output=True, text=True,
        )
        try:
            return float(proc.stdout.strip())
        except ValueError:
            return 0.0

    # ------------------------------------------------------------------ #
    # Clip production
    # ------------------------------------------------------------------ #
    def still_to_clip(self, image: Path, dest: Path, duration: float) -> Path:
        """Animate a single still with a slow Ken-Burns zoom (motion fallback)."""
        frames = max(int(round(duration * self.fps)), 1)
        # Upscale first so the zoompan motion stays smooth, then crop to frame.
        vf = (
            f"scale={self.w * 2}:{self.h * 2}:force_original_aspect_ratio=increase,"
            f"crop={self.w * 2}:{self.h * 2},"
            f"zoompan=z='min(zoom+0.0009,1.15)':d={frames}:"
            f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':"
            f"s={self.w}x{self.h}:fps={self.fps},setsar=1"
        )
        _run([
            "ffmpeg", "-y", "-loop", "1", "-i", str(image),
            "-t", f"{duration:.3f}", "-vf", vf,
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-r", str(self.fps),
            str(dest),
        ])
        return dest

    def normalize_clip(self, src: Path, dest: Path, duration: float) -> Path:
        """Conform a generated clip to exact geometry/fps and pad/trim duration."""
        vf = (
            f"scale={self.w}:{self.h}:force_original_aspect_ratio=decrease,"
            f"pad={self.w}:{self.h}:(ow-iw)/2:(oh-ih)/2:color=black,"
            f"setsar=1,fps={self.fps},"
            # Clone the last frame if the source is shorter than the slot.
            f"tpad=stop_mode=clone:stop_duration={duration:.3f}"
        )
        _run([
            "ffmpeg", "-y", "-i", str(src),
            "-an", "-vf", vf, "-t", f"{duration:.3f}",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-r", str(self.fps),
            str(dest),
        ])
        return dest

    # ------------------------------------------------------------------ #
    # Concatenation + audio
    # ------------------------------------------------------------------ #
    def concat(self, clips: list[Path], dest: Path) -> Path:
        """Concatenate normalised clips (re-encode for safety)."""
        if not clips:
            raise AssemblyError("No clips to concatenate.")
        listing = dest.parent / "_concat_list.txt"
        # ffmpeg concat demuxer needs forward slashes + escaped quotes.
        listing.write_text(
            "".join(f"file '{c.as_posix()}'\n" for c in clips), encoding="utf-8"
        )
        _run([
            "ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(listing),
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-r", str(self.fps),
            str(dest),
        ])
        listing.unlink(missing_ok=True)
        return dest

    def mux_audio(self, video: Path, audio: Path, dest: Path) -> Path:
        """Mux audio under video with fade-in/out, trimmed to the shorter track."""
        v_dur = self.probe_duration(video)
        a_dur = self.probe_duration(audio)
        end = max(min(v_dur, a_dur), 0.1)
        fade_out_start = max(end - 2.0, 0.0)
        afade = f"afade=t=in:st=0:d=1.5,afade=t=out:st={fade_out_start:.2f}:d=2.0"
        _run([
            "ffmpeg", "-y", "-i", str(video), "-i", str(audio),
            "-filter:a", afade,
            "-map", "0:v:0", "-map", "1:a:0",
            "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
            "-shortest", str(dest),
        ])
        return dest

    # ------------------------------------------------------------------ #
    # Lyric overlay (best-effort; requires ffmpeg built with libass)
    # ------------------------------------------------------------------ #
    def burn_subtitles(self, video: Path, srt: Path, dest: Path) -> Path:
        """Burn an .srt onto the video. Run from the srt's dir to dodge the
        Windows drive-letter colon that breaks the subtitles filter path."""
        style = "FontSize=20,PrimaryColour=&H00FFFFFF,OutlineColour=&H80000000,BorderStyle=1,Outline=2,Shadow=0,Alignment=2,MarginV=40"
        vf = f"subtitles={srt.name}:force_style='{style}'"
        _run(
            [
                "ffmpeg", "-y", "-i", str(video.resolve()),
                "-vf", vf, "-c:a", "copy", str(dest.resolve()),
            ],
            cwd=srt.parent,
        )
        return dest

    @staticmethod
    def write_lyrics_srt(lyrics: str, duration: float, dest: Path) -> Path:
        """Distribute lyric lines evenly across the track as subtitles.

        Section tags like [Chorus] and blank lines are dropped. This is a simple
        even split — good enough for ambient lyric videos; swap in forced
        alignment later if you need word-level sync.
        """
        lines = [
            ln.strip()
            for ln in lyrics.splitlines()
            if ln.strip() and not (ln.strip().startswith("[") and ln.strip().endswith("]"))
        ]
        if not lines:
            raise AssemblyError("No lyric lines to render.")

        per = duration / len(lines)

        def ts(seconds: float) -> str:
            h = int(seconds // 3600)
            m = int((seconds % 3600) // 60)
            s = int(seconds % 60)
            ms = int((seconds - int(seconds)) * 1000)
            return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"

        blocks: list[str] = []
        for i, line in enumerate(lines):
            start = i * per
            end = (i + 1) * per - 0.05
            blocks.append(f"{i + 1}\n{ts(start)} --> {ts(end)}\n{line}\n")

        dest.write_text("\n".join(blocks), encoding="utf-8")
        return dest
