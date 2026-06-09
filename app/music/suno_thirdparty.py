"""suno_thirdparty backend.

Suno has no official public API, so this targets the common third-party relay
shape (sunoapi.org / EvoLink / 302.ai style): submit a generation task, poll for
completion, download the rendered audio.

Endpoint paths vary slightly between providers — they're centralised as class
attributes so adapting to a different relay is a one-line change.
"""

from __future__ import annotations

import time
from pathlib import Path

import httpx

from app.config import Settings
from app.logging_config import get_logger
from app.models import SongConcept
from app.music.base import MusicBackendBase, MusicBackendError, MusicResult
from app.utils import api_retry, download_file, raise_for_retryable_status

log = get_logger(__name__)


class SunoThirdPartyBackend(MusicBackendBase):
    name = "suno_thirdparty"

    # --- provider-specific paths (override per relay if needed) ---
    SUBMIT_PATH = "/api/v1/generate"
    STATUS_PATH = "/api/v1/generate/record-info"
    MODEL = "V4"

    POLL_INTERVAL_S = 8
    POLL_TIMEOUT_S = 600  # generation can take several minutes

    def __init__(self, cfg: Settings) -> None:
        super().__init__(cfg)
        cfg.require("suno_api_key", "suno_api_base")
        self.base = cfg.suno_api_base.rstrip("/")
        self._client = httpx.Client(
            timeout=60.0,
            headers={
                "Authorization": f"Bearer {cfg.suno_api_key}",
                "Content-Type": "application/json",
            },
        )

    def generate(
        self,
        concept: SongConcept,
        out_dir: Path,
        track_index: int,
        target_seconds: float,
    ) -> MusicResult:
        lyrics_path, suno_prompt_path = self._write_briefs(concept, out_dir, track_index)

        task_id = self._submit(concept)
        log.info("suno_submitted", track=track_index + 1, task_id=task_id)

        audio_url = self._poll(task_id)
        stem = f"track_{track_index + 1:02d}"
        audio_path = download_file(audio_url, out_dir / f"{stem}.mp3")
        log.info("suno_done", track=track_index + 1, audio=str(audio_path))

        return MusicResult(
            lyrics_path=lyrics_path,
            suno_prompt_path=suno_prompt_path,
            audio_path=audio_path,
            note=f"Generated via third-party Suno relay ({self.base}).",
        )

    # ------------------------------------------------------------------ #
    @api_retry
    def _submit(self, concept: SongConcept) -> str:
        body = {
            # customMode lets us supply our own lyrics + style explicitly.
            "customMode": True,
            "instrumental": False,
            "model": self.MODEL,
            "title": concept.title[:80],
            "style": concept.suno_style_prompt[:200],
            "prompt": concept.lyrics,  # 'prompt' carries the lyrics in customMode
        }
        resp = self._client.post(f"{self.base}{self.SUBMIT_PATH}", json=body)
        raise_for_retryable_status(resp)
        if resp.status_code >= 400:
            raise MusicBackendError(f"Suno submit failed {resp.status_code}: {resp.text[:300]}")

        data = resp.json()
        # Relays nest the task id differently; probe the common spots.
        task_id = (
            data.get("data", {}).get("taskId")
            or data.get("data", {}).get("task_id")
            or data.get("taskId")
            or data.get("id")
        )
        if not task_id:
            raise MusicBackendError(f"No task id in Suno response: {data}")
        return str(task_id)

    def _poll(self, task_id: str) -> str:
        deadline = self.POLL_TIMEOUT_S
        waited = 0
        while waited < deadline:
            audio_url = self._check_once(task_id)
            if audio_url:
                return audio_url
            time.sleep(self.POLL_INTERVAL_S)
            waited += self.POLL_INTERVAL_S
        raise MusicBackendError(
            f"Suno generation timed out after {deadline}s (task {task_id})."
        )

    @api_retry
    def _check_once(self, task_id: str) -> str | None:
        resp = self._client.get(
            f"{self.base}{self.STATUS_PATH}", params={"taskId": task_id}
        )
        raise_for_retryable_status(resp)
        if resp.status_code >= 400:
            raise MusicBackendError(f"Suno status failed {resp.status_code}: {resp.text[:300]}")

        data = resp.json().get("data", {})
        status = (data.get("status") or "").upper()
        if status in {"SUCCESS", "COMPLETE", "FINISHED"}:
            # The finished payload contains one or more tracks; take the first.
            items = (
                data.get("response", {}).get("sunoData")
                or data.get("sunoData")
                or data.get("items")
                or []
            )
            for item in items:
                url = item.get("audioUrl") or item.get("audio_url") or item.get("url")
                if url:
                    return url
            raise MusicBackendError(f"Suno reported success but no audio url: {data}")
        if status in {"FAILED", "ERROR"}:
            raise MusicBackendError(f"Suno generation failed: {data}")
        return None  # still pending
