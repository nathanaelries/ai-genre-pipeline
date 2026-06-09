"""Kling AI image-to-video backend.

Kling authenticates with a short-lived JWT (HS256) signed from your access/secret
key pair. We mint the token inline to avoid an extra dependency. Flow: submit an
image2video task, poll for completion, download the rendered clip.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from pathlib import Path

import httpx

from app.config import Settings
from app.logging_config import get_logger
from app.utils import api_retry, download_file, raise_for_retryable_status
from app.video.base import VideoBackendBase, VideoBackendError

log = get_logger(__name__)


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _mint_jwt(access_key: str, secret_key: str, ttl_s: int = 1800) -> str:
    """Sign a minimal HS256 JWT the way Kling's open platform expects."""
    now = int(time.time())
    header = {"alg": "HS256", "typ": "JWT"}
    payload = {"iss": access_key, "exp": now + ttl_s, "nbf": now - 5}
    segments = [
        _b64url(json.dumps(header, separators=(",", ":")).encode()),
        _b64url(json.dumps(payload, separators=(",", ":")).encode()),
    ]
    signing_input = ".".join(segments).encode()
    sig = hmac.new(secret_key.encode(), signing_input, hashlib.sha256).digest()
    segments.append(_b64url(sig))
    return ".".join(segments)


class KlingVideoBackend(VideoBackendBase):
    name = "kling"

    SUBMIT_PATH = "/v1/videos/image2video"
    POLL_INTERVAL_S = 8
    POLL_TIMEOUT_S = 900

    def __init__(self, cfg: Settings) -> None:
        super().__init__(cfg)
        cfg.require("kling_access_key", "kling_secret_key")
        self.base = cfg.kling_api_base.rstrip("/")
        self._client = httpx.Client(timeout=60.0)

    def _headers(self) -> dict:
        token = _mint_jwt(self.cfg.kling_access_key, self.cfg.kling_secret_key)
        return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

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
            raise VideoBackendError("Kling backend requires a scene key-frame image.")

        task_id = self._submit(prompt, image_path, duration)
        log.info("kling_submitted", task_id=task_id)
        url = self._poll(task_id)
        download_file(url, dest)
        log.info("kling_done", dest=str(dest))
        return dest

    @api_retry
    def _submit(self, prompt: str, image_path: Path, duration: float) -> str:
        image_b64 = base64.b64encode(image_path.read_bytes()).decode("ascii")
        # Kling accepts 5s or 10s clips; snap to the nearest supported length.
        kling_duration = "10" if duration > 7 else "5"
        body = {
            "model_name": self.cfg.kling_model,
            "image": image_b64,
            "prompt": prompt[:2500],
            "mode": "std",
            "duration": kling_duration,
            "cfg_scale": 0.5,
        }
        resp = self._client.post(
            f"{self.base}{self.SUBMIT_PATH}", headers=self._headers(), json=body
        )
        raise_for_retryable_status(resp)
        if resp.status_code >= 400:
            raise VideoBackendError(f"Kling submit {resp.status_code}: {resp.text[:300]}")
        return str(resp.json()["data"]["task_id"])

    def _poll(self, task_id: str) -> str:
        waited = 0
        while waited < self.POLL_TIMEOUT_S:
            url = self._check_once(task_id)
            if url:
                return url
            time.sleep(self.POLL_INTERVAL_S)
            waited += self.POLL_INTERVAL_S
        raise VideoBackendError(f"Kling task {task_id} timed out.")

    @api_retry
    def _check_once(self, task_id: str) -> str | None:
        resp = self._client.get(
            f"{self.base}{self.SUBMIT_PATH}/{task_id}", headers=self._headers()
        )
        raise_for_retryable_status(resp)
        if resp.status_code >= 400:
            raise VideoBackendError(f"Kling status {resp.status_code}: {resp.text[:300]}")
        data = resp.json().get("data", {})
        status = (data.get("task_status") or "").lower()
        if status == "succeed":
            videos = data.get("task_result", {}).get("videos", [])
            if videos:
                return videos[0]["url"]
            raise VideoBackendError(f"Kling succeeded but no video url: {data}")
        if status == "failed":
            raise VideoBackendError(f"Kling task failed: {data.get('task_status_msg')}")
        return None
