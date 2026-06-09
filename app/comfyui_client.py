"""Minimal ComfyUI HTTP client shared by the image and video backends.

ComfyUI's API is: POST a workflow graph (the "API format" JSON exported from the
UI) to ``/prompt``, poll ``/history/{id}`` until the node outputs appear, then
download artifacts from ``/view``. Reference images are uploaded via
``/upload/image`` and referenced by filename inside the graph.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import httpx

from app.logging_config import get_logger
from app.utils import api_retry, raise_for_retryable_status

log = get_logger(__name__)


class ComfyUIError(RuntimeError):
    pass


class ComfyUIClient:
    def __init__(self, base_url: str, poll_interval_s: int = 3, timeout_s: int = 900):
        self.base = base_url.rstrip("/")
        self.poll_interval_s = poll_interval_s
        self.timeout_s = timeout_s
        self._client = httpx.Client(timeout=60.0)

    # ------------------------------------------------------------------ #
    @api_retry
    def upload_image(self, path: Path, overwrite: bool = True) -> str:
        """Upload a reference image to ComfyUI's input folder; return its name."""
        with path.open("rb") as fh:
            files = {"image": (path.name, fh, "image/png")}
            data = {"overwrite": "true" if overwrite else "false"}
            resp = self._client.post(f"{self.base}/upload/image", files=files, data=data)
        raise_for_retryable_status(resp)
        if resp.status_code >= 400:
            raise ComfyUIError(f"upload failed {resp.status_code}: {resp.text[:200]}")
        return resp.json()["name"]

    @api_retry
    def queue_prompt(self, workflow: dict) -> str:
        resp = self._client.post(f"{self.base}/prompt", json={"prompt": workflow})
        raise_for_retryable_status(resp)
        if resp.status_code >= 400:
            raise ComfyUIError(f"queue failed {resp.status_code}: {resp.text[:300]}")
        return resp.json()["prompt_id"]

    def wait_outputs(self, prompt_id: str) -> dict:
        """Block until the prompt finishes; return its `outputs` dict."""
        waited = 0
        while waited < self.timeout_s:
            history = self._history(prompt_id)
            entry = history.get(prompt_id)
            if entry and entry.get("outputs"):
                return entry["outputs"]
            time.sleep(self.poll_interval_s)
            waited += self.poll_interval_s
        raise ComfyUIError(f"ComfyUI prompt {prompt_id} timed out after {self.timeout_s}s")

    @api_retry
    def _history(self, prompt_id: str) -> dict:
        resp = self._client.get(f"{self.base}/history/{prompt_id}")
        raise_for_retryable_status(resp)
        return resp.json() if resp.status_code < 400 else {}

    @api_retry
    def download_view(self, filename: str, subfolder: str, type_: str, dest: Path) -> Path:
        params = {"filename": filename, "subfolder": subfolder, "type": type_}
        resp = self._client.get(f"{self.base}/view", params=params)
        raise_for_retryable_status(resp)
        if resp.status_code >= 400:
            raise ComfyUIError(f"view failed {resp.status_code}: {resp.text[:200]}")
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(resp.content)
        return dest

    # ------------------------------------------------------------------ #
    @staticmethod
    def first_output(outputs: dict, keys: tuple[str, ...] = ("images", "gifs", "videos")):
        """Return the first artifact descriptor across known output key types."""
        for node in outputs.values():
            for key in keys:
                if node.get(key):
                    return node[key][0]
        return None

    @staticmethod
    def load_workflow_template(path: str) -> dict:
        return json.loads(Path(path).read_text(encoding="utf-8"))
