"""Runway Gen-3 image-to-video backend (dev API over httpx).

Flow: POST /v1/image_to_video with the scene key-frame (as a data URI) + motion
prompt, then poll /v1/tasks/{id} until SUCCEEDED and download the output.
"""

from __future__ import annotations

import time
from pathlib import Path

import httpx

from app.config import Settings
from app.logging_config import get_logger
from app.utils import api_retry, download_file, image_to_data_uri, raise_for_retryable_status
from app.video.base import VideoBackendBase, VideoBackendError

log = get_logger(__name__)

RUNWAY_VERSION = "2024-11-06"


def _nearest_ratio(width: int, height: int) -> str:
    """Map output geometry to a Runway-supported aspect ratio token."""
    ratio = width / height
    if ratio > 1.2:
        return "1280:768"
    if ratio < 0.83:
        return "768:1280"
    return "1024:1024"


class RunwayVideoBackend(VideoBackendBase):
    name = "runway"

    POLL_INTERVAL_S = 6
    POLL_TIMEOUT_S = 900

    def __init__(self, cfg: Settings) -> None:
        super().__init__(cfg)
        cfg.require("runway_api_key")
        self.base = cfg.runway_api_base.rstrip("/")
        self._client = httpx.Client(
            timeout=60.0,
            headers={
                "Authorization": f"Bearer {cfg.runway_api_key}",
                "X-Runway-Version": RUNWAY_VERSION,
                "Content-Type": "application/json",
            },
        )

    def generate(
        self,
        prompt: str,
        dest: Path,
        *,
        image_path: Path | None = None,
        duration: float = 5.0,
        seed: int | None = None,
    ) -> Path:
        if image_path is None:
            raise VideoBackendError("Runway backend requires a scene key-frame image.")

        task_id = self._submit(prompt, image_path, duration, seed)
        log.info("runway_submitted", task_id=task_id)
        url = self._poll(task_id)
        download_file(url, dest)
        log.info("runway_done", dest=str(dest))
        return dest

    @api_retry
    def _submit(self, prompt: str, image_path: Path, duration: float, seed: int | None) -> str:
        body = {
            "model": self.cfg.runway_model,
            "promptImage": image_to_data_uri(image_path),
            "promptText": prompt[:1000],
            # Runway Gen-3 supports 5s or 10s durations.
            "duration": 10 if duration > 7 else 5,
            "ratio": _nearest_ratio(self.cfg.width, self.cfg.height),
        }
        if seed is not None:
            body["seed"] = seed % 4294967295
        resp = self._client.post(f"{self.base}/v1/image_to_video", json=body)
        raise_for_retryable_status(resp)
        if resp.status_code >= 400:
            raise VideoBackendError(f"Runway submit {resp.status_code}: {resp.text[:300]}")
        return resp.json()["id"]

    def _poll(self, task_id: str) -> str:
        waited = 0
        while waited < self.POLL_TIMEOUT_S:
            url = self._check_once(task_id)
            if url:
                return url
            time.sleep(self.POLL_INTERVAL_S)
            waited += self.POLL_INTERVAL_S
        raise VideoBackendError(f"Runway task {task_id} timed out.")

    @api_retry
    def _check_once(self, task_id: str) -> str | None:
        resp = self._client.get(f"{self.base}/v1/tasks/{task_id}")
        raise_for_retryable_status(resp)
        if resp.status_code >= 400:
            raise VideoBackendError(f"Runway status {resp.status_code}: {resp.text[:300]}")
        data = resp.json()
        status = (data.get("status") or "").upper()
        if status == "SUCCEEDED":
            output = data.get("output") or []
            if output:
                return output[0]
            raise VideoBackendError(f"Runway succeeded but no output: {data}")
        if status in {"FAILED", "CANCELLED"}:
            raise VideoBackendError(f"Runway task {status}: {data.get('failure', '')}")
        return None
