"""Small shared helpers: run-folder layout, JSON parsing, HTTP retry policy."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

import httpx
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from app.logging_config import get_logger

log = get_logger(__name__)


# --------------------------------------------------------------------------- #
# Run-folder layout — the canonical output structure from the spec.
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class RunPaths:
    """Resolves and creates the standard per-run directory tree."""

    root: Path

    @property
    def concept(self) -> Path:
        return self.root / "01_lyrics_and_concept"

    @property
    def bible(self) -> Path:
        return self.root / "02_character_bible"

    @property
    def reference_images(self) -> Path:
        return self.bible / "reference_images"

    @property
    def music(self) -> Path:
        return self.root / "03_music"

    @property
    def scenes(self) -> Path:
        return self.root / "04_scenes"

    @property
    def final_videos(self) -> Path:
        return self.root / "05_final_videos"

    @property
    def stream(self) -> Path:
        return self.root / "06_stream"

    @property
    def stream_segments(self) -> Path:
        return self.stream / "segments"

    @property
    def logs(self) -> Path:
        return self.root / "logs"

    @property
    def manifest_file(self) -> Path:
        return self.root / "manifest.json"

    @property
    def state_file(self) -> Path:
        return self.root / "state.json"

    def ensure(self) -> "RunPaths":
        """Create every directory in the tree (idempotent)."""
        for p in (
            self.root,
            self.concept,
            self.bible,
            self.reference_images,
            self.music,
            self.scenes,
            self.final_videos,
            self.stream,
            self.stream_segments,
            self.logs,
        ):
            p.mkdir(parents=True, exist_ok=True)
        return self

    def rel(self, path: Path) -> str:
        """Express an absolute artifact path relative to the run root."""
        try:
            return str(path.relative_to(self.root)).replace("\\", "/")
        except ValueError:
            return str(path)


# --------------------------------------------------------------------------- #
# JSON helpers — LLMs love to wrap JSON in prose or ```json fences.
# --------------------------------------------------------------------------- #
def extract_json(text: str) -> dict | list:
    """Best-effort extraction of a JSON object/array from an LLM response."""
    text = text.strip()

    # Strip ```json ... ``` fences if present.
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if fence:
        text = fence.group(1).strip()

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Fall back to the first balanced {...} or [...] span.
    for opener, closer in (("{", "}"), ("[", "]")):
        start = text.find(opener)
        end = text.rfind(closer)
        if start != -1 and end != -1 and end > start:
            try:
                return json.loads(text[start : end + 1])
            except json.JSONDecodeError:
                continue

    raise ValueError(f"Could not parse JSON from model output:\n{text[:500]}")


def write_json(path: Path, data: dict | list) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def read_json(path: Path) -> dict | list:
    return json.loads(path.read_text(encoding="utf-8"))


def slugify(text: str, max_len: int = 40) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return s[:max_len] or "item"


def image_to_data_uri(path: Path) -> str:
    """Encode a local image as a base64 data URI (for image-to-video APIs)."""
    import base64
    import mimetypes

    mime = mimetypes.guess_type(str(path))[0] or "image/png"
    b64 = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{b64}"


# --------------------------------------------------------------------------- #
# HTTP — shared retry policy for all backends.
# --------------------------------------------------------------------------- #
# Retry on transient network errors and 5xx/429. tenacity gives exponential
# backoff with jitter; backends wrap their request calls with @api_retry.
_RETRYABLE = (httpx.TransportError, httpx.HTTPStatusError)

api_retry = retry(
    retry=retry_if_exception_type(_RETRYABLE),
    wait=wait_exponential(multiplier=1, min=2, max=30),
    stop=stop_after_attempt(5),
    reraise=True,
)


def raise_for_retryable_status(resp: httpx.Response) -> httpx.Response:
    """Raise HTTPStatusError only for statuses worth retrying (5xx/429).

    4xx (other than 429) are caller errors — surface them immediately rather
    than burning retries on a request that will never succeed.
    """
    if resp.status_code == 429 or resp.status_code >= 500:
        resp.raise_for_status()
    return resp


def download_file(url: str, dest: Path, timeout: float = 120.0) -> Path:
    """Stream a remote asset (audio/video/image) to disk."""
    dest.parent.mkdir(parents=True, exist_ok=True)

    @api_retry
    def _go() -> None:
        with httpx.stream("GET", url, timeout=timeout, follow_redirects=True) as r:
            raise_for_retryable_status(r)
            r.raise_for_status()
            with dest.open("wb") as fh:
                for chunk in r.iter_bytes():
                    fh.write(chunk)

    _go()
    log.debug("downloaded", url=url, dest=str(dest), bytes=dest.stat().st_size)
    return dest
