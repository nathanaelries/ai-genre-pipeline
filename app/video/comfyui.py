"""ComfyUI image-to-video backend.

Video graphs are model-specific (SVD, AnimateDiff, CogVideo, WAN, ...), so rather
than ship a default that assumes particular models are installed, this backend
requires you to export an API-format workflow and point COMFYUI_VIDEO_WORKFLOW at
it. We upload the scene key-frame, substitute placeholder tokens, run the graph,
and download the resulting clip.

Supported placeholder tokens:
  %PROMPT%  %NEGATIVE%  %SEED%  %WIDTH%  %HEIGHT%  %FRAMES%  %FPS%  %REF_IMAGE%
"""

from __future__ import annotations

import json
from pathlib import Path

from app.comfyui_client import ComfyUIClient
from app.config import Settings
from app.logging_config import get_logger
from app.video.base import VideoBackendBase, VideoBackendError

log = get_logger(__name__)


class ComfyUIVideoBackend(VideoBackendBase):
    name = "comfyui"

    def __init__(self, cfg: Settings) -> None:
        super().__init__(cfg)
        self.client = ComfyUIClient(cfg.comfyui_url)
        self._template_path = cfg.comfyui_video_workflow.strip()
        if not self._template_path:
            raise VideoBackendError(
                "VIDEO_BACKEND=comfyui requires COMFYUI_VIDEO_WORKFLOW to point at "
                "an exported API-format workflow (e.g. an SVD or AnimateDiff graph)."
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
        seed = self.cfg.seed if seed is None else seed
        ref_name = self.client.upload_image(image_path) if image_path else ""
        frames = max(int(round(duration * self.cfg.fps)), 1)

        raw = Path(self._template_path).read_text(encoding="utf-8")
        raw = (
            raw.replace("%PROMPT%", json.dumps(prompt)[1:-1])
            .replace("%NEGATIVE%", "")
            .replace("%SEED%", str(seed))
            .replace("%WIDTH%", str(self.cfg.width))
            .replace("%HEIGHT%", str(self.cfg.height))
            .replace("%FRAMES%", str(frames))
            .replace("%FPS%", str(self.cfg.fps))
            .replace("%REF_IMAGE%", ref_name)
        )
        workflow = json.loads(raw)

        prompt_id = self.client.queue_prompt(workflow)
        outputs = self.client.wait_outputs(prompt_id)
        art = self.client.first_output(outputs, keys=("gifs", "videos", "images"))
        if not art:
            raise VideoBackendError(f"No video output from ComfyUI ({prompt_id})")
        self.client.download_view(
            art["filename"], art.get("subfolder", ""), art.get("type", "output"), dest
        )
        log.info("comfyui_video_done", dest=str(dest), frames=frames)
        return dest
