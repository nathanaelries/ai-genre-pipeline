"""RTMP broadcaster — one persistent encoder, fan-out to many platforms.

Design for *seamless, never-stopping* playback:

  * A single long-running ffmpeg reads MPEG-TS segment bytes from its stdin
    (``-re`` paces it at realtime, which back-pressures our feeder), re-encodes
    to one clean continuous H.264/AAC timeline, and pushes to every configured
    platform at once through the ``tee`` muxer (``onfail=ignore`` so one platform
    dropping never kills the rest).
  * A feeder thread writes the next queued segment into stdin. When the queue is
    empty it loops the already-streamed library (or a standby card), so the wire
    is never starved and the stream never goes black.
  * If the encoder dies (e.g. transient RTMP hiccup) the feeder respawns it and
    keeps going.

Segments must share identical codec params (the StreamManager guarantees this),
so re-encoding across boundaries stays glitch-free.
"""

from __future__ import annotations

import queue
import re
import subprocess
import threading
import time
from pathlib import Path

from app.logging_config import get_logger
from app.streaming.base import StreamTarget

log = get_logger(__name__)

_CHUNK = 1 << 16  # 64 KiB writes into the encoder stdin


def _double_rate(rate: str) -> str:
    """'4500k' -> '9000k' (used for the rate-control buffer size)."""
    m = re.fullmatch(r"(\d+)([kKmM]?)", rate.strip())
    if not m:
        return rate
    return f"{int(m.group(1)) * 2}{m.group(2)}"


class RTMPBroadcaster:
    def __init__(
        self,
        *,
        width: int,
        height: int,
        fps: int,
        targets: list[StreamTarget],
        video_bitrate: str = "4500k",
        audio_bitrate: str = "128k",
        preset: str = "veryfast",
        loop_when_idle: bool = True,
        standby: Path | None = None,
        log_file: Path | None = None,
        max_restarts: int = 20,
    ) -> None:
        if not targets:
            raise ValueError("RTMPBroadcaster needs at least one stream target.")
        self.width = width
        self.height = height
        self.fps = fps
        self.targets = targets
        self.video_bitrate = video_bitrate
        self.audio_bitrate = audio_bitrate
        self.preset = preset
        self.loop_when_idle = loop_when_idle
        self.standby = standby
        self.log_file = log_file
        self.max_restarts = max_restarts

        self._pending: "queue.Queue[Path]" = queue.Queue()
        self._library: list[Path] = []
        self._lib_idx = 0
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._proc: subprocess.Popen | None = None
        self._feeder: threading.Thread | None = None
        self._log_fh = None
        self._restarts = 0

    # ------------------------------------------------------------------ #
    # Lifecycle
    # ------------------------------------------------------------------ #
    def start(self) -> None:
        if self.log_file:
            self.log_file.parent.mkdir(parents=True, exist_ok=True)
            self._log_fh = self.log_file.open("ab")
        self._spawn_encoder()
        self._feeder = threading.Thread(target=self._feed_loop, name="rtmp-feeder", daemon=True)
        self._feeder.start()
        log.info(
            "stream_started",
            targets=[t.safe_url for t in self.targets],
            loop_when_idle=self.loop_when_idle,
        )

    def enqueue(self, segment: Path) -> None:
        """Queue a fresh segment to play at the next segment boundary."""
        self._pending.put(segment)
        log.info("stream_enqueued", segment=segment.name, pending=self._pending.qsize())

    def stop(self, drain: bool = False) -> None:
        """Stop streaming. If drain, wait for the pending queue to empty first."""
        if drain:
            while not self._pending.empty() and self._encoder_alive():
                time.sleep(0.5)
        self._stop.set()
        if self._feeder:
            self._feeder.join(timeout=10)
        self._kill_encoder()
        if self._log_fh:
            self._log_fh.close()
        log.info("stream_stopped")

    @property
    def has_content(self) -> bool:
        with self._lock:
            return bool(self._library) or not self._pending.empty() or self.standby is not None

    # ------------------------------------------------------------------ #
    # Encoder process
    # ------------------------------------------------------------------ #
    def _build_cmd(self) -> list[str]:
        gop = max(self.fps * 2, 2)
        outputs = "|".join(f"[f=flv:onfail=ignore]{t.url}" for t in self.targets)
        return [
            "ffmpeg", "-hide_banner", "-loglevel", "warning",
            "-re",
            "-fflags", "+genpts+igndts",
            "-f", "mpegts", "-i", "pipe:0",
            "-c:v", "libx264", "-preset", self.preset, "-tune", "zerolatency",
            "-pix_fmt", "yuv420p",
            "-g", str(gop), "-keyint_min", str(self.fps), "-sc_threshold", "0",
            "-b:v", self.video_bitrate,
            "-maxrate", self.video_bitrate,
            "-bufsize", _double_rate(self.video_bitrate),
            "-c:a", "aac", "-ar", "44100", "-b:a", self.audio_bitrate,
            "-f", "tee", "-map", "0:v:0", "-map", "0:a:0",
            outputs,
        ]

    def _spawn_encoder(self) -> None:
        self._proc = subprocess.Popen(
            self._build_cmd(),
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=self._log_fh or subprocess.DEVNULL,
        )

    def _encoder_alive(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def _kill_encoder(self) -> None:
        if not self._proc:
            return
        try:
            if self._proc.stdin:
                self._proc.stdin.close()
        except OSError:
            pass
        try:
            self._proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._proc.kill()

    # ------------------------------------------------------------------ #
    # Feeder
    # ------------------------------------------------------------------ #
    def _next_segment(self) -> Path | None:
        # Fresh clips take priority; record them so they re-loop later.
        try:
            seg = self._pending.get_nowait()
            with self._lock:
                self._library.append(seg)
            return seg
        except queue.Empty:
            pass

        if self.loop_when_idle:
            with self._lock:
                if self._library:
                    seg = self._library[self._lib_idx % len(self._library)]
                    self._lib_idx += 1
                    return seg

        return self.standby  # may be None -> caller idles briefly

    def _feed_loop(self) -> None:
        while not self._stop.is_set():
            # Respawn the encoder if it died unexpectedly.
            if not self._encoder_alive():
                if self._restarts >= self.max_restarts:
                    log.error("stream_encoder_gave_up", restarts=self._restarts)
                    return
                self._restarts += 1
                log.warning("stream_encoder_restart", attempt=self._restarts)
                self._spawn_encoder()
                time.sleep(2)
                continue

            seg = self._next_segment()
            if seg is None:
                time.sleep(0.2)  # nothing to play yet; wait for the first clip
                continue
            self._write_segment(seg)

    def _write_segment(self, seg: Path) -> None:
        if not seg.exists():
            log.warning("stream_segment_missing", segment=str(seg))
            return
        try:
            with seg.open("rb") as fh:
                while not self._stop.is_set():
                    chunk = fh.read(_CHUNK)
                    if not chunk:
                        break
                    assert self._proc and self._proc.stdin
                    self._proc.stdin.write(chunk)
            if self._proc and self._proc.stdin:
                self._proc.stdin.flush()
        except (BrokenPipeError, ValueError, OSError) as exc:
            # Encoder went away mid-write; the feed loop will respawn it.
            log.warning("stream_write_failed", error=str(exc)[:160])
