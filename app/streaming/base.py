"""Stream target resolution.

Turns the `.env` platform selection + keys into concrete, validated RTMP/RTMPS
ingest endpoints, with key-masking for safe logging.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.config import Settings, StreamPlatform
from app.logging_config import get_logger

log = get_logger(__name__)


@dataclass(frozen=True)
class StreamTarget:
    """One resolved publish destination."""

    platform: StreamPlatform
    url: str  # full RTMP/RTMPS ingest URL including the stream key

    @property
    def safe_url(self) -> str:
        """URL with the trailing key/secret masked, for logs and display."""
        # Mask everything after the last path segment (the key) and any query.
        masked = re.sub(r"([^/]{2})[^/]{2,}$", r"\1••••", self.url)
        return masked


def build_targets(cfg: Settings) -> list[StreamTarget]:
    """Resolve every selected platform to a usable ingest URL.

    Platforms that are selected but missing a key/URL are skipped with a warning
    rather than aborting — you can stream to the ones that are configured.
    """
    targets: list[StreamTarget] = []
    for platform in cfg.stream_targets:
        url = cfg.stream_url_for(platform)
        if not url:
            log.warning("stream_target_skipped", platform=platform.value, reason="no key/url")
            continue
        if not url.startswith(("rtmp://", "rtmps://")):
            log.warning("stream_target_skipped", platform=platform.value, reason="not an rtmp url")
            continue
        targets.append(StreamTarget(platform=platform, url=url))
    return targets
