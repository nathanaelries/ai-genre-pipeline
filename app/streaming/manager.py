"""StreamManager — public entry point for live streaming.

Responsibilities:
  * resolve platform targets from config,
  * transcode each finished video into a gapless MPEG-TS segment with codec
    params identical to the broadcaster's encoder (so joins are seamless),
  * generate a standby card so a `live` stream has something to show before the
    first clip is ready,
  * own the RTMPBroadcaster lifecycle.

Typical use:

    mgr = StreamManager(cfg, paths)
    mgr.start()                 # begins pushing (standby until clips arrive)
    mgr.add_video(final_mp4)    # call as each track finishes
    mgr.wait()                  # block (Ctrl-C) — keeps looping the library
    mgr.stop()
"""

from __future__ import annotations

import subprocess
import time
from pathlib import Path

from app.config import Settings
from app.logging_config import get_logger
from app.streaming.base import build_targets
from app.streaming.broadcaster import RTMPBroadcaster
from app.utils import RunPaths

log = get_logger(__name__)


class StreamError(RuntimeError):
    pass


class StreamManager:
    def __init__(self, cfg: Settings, paths: RunPaths) -> None:
        self.cfg = cfg
        self.paths = paths
        self.targets = build_targets(cfg)
        if not self.targets:
            raise StreamError(
                "Streaming is enabled but no platform is configured. Set a stream "
                "key/URL for at least one of STREAM_TARGETS (e.g. YOUTUBE_STREAM_KEY)."
            )
        self._seg_counter = 0
        self._broadcaster: RTMPBroadcaster | None = None

    # ------------------------------------------------------------------ #
    # Lifecycle
    # ------------------------------------------------------------------ #
    def start(self, with_standby: bool = True) -> None:
        standby = self._make_standby() if with_standby else None
        self._broadcaster = RTMPBroadcaster(
            width=self.cfg.width,
            height=self.cfg.height,
            fps=self.cfg.fps,
            targets=self.targets,
            video_bitrate=self.cfg.stream_video_bitrate,
            audio_bitrate=self.cfg.stream_audio_bitrate,
            preset=self.cfg.stream_preset,
            loop_when_idle=self.cfg.stream_loop_when_idle,
            standby=standby,
            log_file=self.paths.logs / "stream.log",
        )
        self._broadcaster.start()
        log.info("stream_manager_started", platforms=[t.platform.value for t in self.targets])

    def add_video(self, video: Path) -> None:
        """Transcode a finished video to a segment and queue it for playback."""
        if not self._broadcaster:
            raise StreamError("StreamManager.start() must be called before add_video().")
        segment = self._prepare_segment(video)
        self._broadcaster.enqueue(segment)

    def add_existing(self, videos: list[Path]) -> None:
        for v in videos:
            self.add_video(v)

    def wait(self) -> None:
        """Block while the stream runs; returns on Ctrl-C or encoder give-up."""
        log.info("stream_serving", note="streaming live — press Ctrl-C to stop")
        try:
            while self._broadcaster and self._broadcaster.has_content:
                time.sleep(1)
        except KeyboardInterrupt:
            log.info("stream_interrupted")

    def stop(self, drain: bool = False) -> None:
        if self._broadcaster:
            self._broadcaster.stop(drain=drain)

    # ------------------------------------------------------------------ #
    # Segment + standby production
    # ------------------------------------------------------------------ #
    def _prepare_segment(self, video: Path) -> Path:
        """Conform `video` to the canonical stream codec params as MPEG-TS."""
        self._seg_counter += 1
        dest = self.paths.stream_segments / f"seg_{self._seg_counter:04d}.ts"
        w, h, fps = self.cfg.width, self.cfg.height, self.cfg.fps
        vf = (
            f"scale={w}:{h}:force_original_aspect_ratio=decrease,"
            f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2,setsar=1,fps={fps},format=yuv420p"
        )
        cmd = [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-i", str(video),
            "-vf", vf,
            "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p",
            "-g", str(fps * 2), "-keyint_min", str(fps), "-sc_threshold", "0",
            "-c:a", "aac", "-ar", "44100", "-ac", "2",
            "-b:a", self.cfg.stream_audio_bitrate,
            "-af", "aresample=async=1:first_pts=0",
            "-muxpreload", "0", "-muxdelay", "0",
            "-f", "mpegts", str(dest),
        ]
        self._run(cmd, what="segment")
        log.info("stream_segment_ready", source=video.name, segment=dest.name)
        return dest

    def _make_standby(self, seconds: int = 6) -> Path | None:
        """A black + silent loop shown until the first real clip arrives."""
        dest = self.paths.stream_segments / "standby.ts"
        w, h, fps = self.cfg.width, self.cfg.height, self.cfg.fps
        cmd = [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i", f"color=c=black:s={w}x{h}:r={fps}",
            "-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=44100",
            "-t", str(seconds),
            "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p",
            "-g", str(fps * 2), "-keyint_min", str(fps), "-sc_threshold", "0",
            "-c:a", "aac", "-ar", "44100", "-b:a", self.cfg.stream_audio_bitrate,
            "-muxpreload", "0", "-muxdelay", "0",
            "-f", "mpegts", str(dest),
        ]
        try:
            self._run(cmd, what="standby")
            return dest
        except StreamError as exc:
            log.warning("stream_standby_failed", error=str(exc)[:160])
            return None

    @staticmethod
    def _run(cmd: list[str], what: str) -> None:
        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode != 0:
            raise StreamError(f"ffmpeg {what} failed: {proc.stderr[-600:]}")
