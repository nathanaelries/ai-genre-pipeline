"""ComfyUI image backend.

Two modes:
  * Default (no custom workflow): a built-in text-to-image graph
    (checkpoint -> CLIP -> KSampler -> VAE -> SaveImage). Character consistency
    comes from the deterministic prompt + a fixed seed.
  * Custom workflow (COMFYUI_IMAGE_WORKFLOW=path): your exported API-format graph
    with placeholder tokens that we substitute. This is where you wire IP-Adapter
    / ControlNet using the uploaded reference images for true face/outfit locking.

Supported placeholder tokens in a custom workflow JSON:
  %POSITIVE%  %NEGATIVE%  %SEED%  %WIDTH%  %HEIGHT%  %CKPT%  %REF_IMAGE%
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

from app.comfyui_client import ComfyUIClient
from app.config import Settings
from app.image.base import ImageBackendBase, ImageBackendError
from app.logging_config import get_logger

log = get_logger(__name__)


def _default_workflow(
    positive: str, negative: str, seed: int, width: int, height: int, ckpt: str
) -> dict:
    """A minimal, dependency-light text-to-image graph in ComfyUI API format."""
    return {
        "3": {
            "class_type": "KSampler",
            "inputs": {
                "seed": seed,
                "steps": 28,
                "cfg": 7.0,
                "sampler_name": "dpmpp_2m",
                "scheduler": "karras",
                "denoise": 1.0,
                "model": ["4", 0],
                "positive": ["6", 0],
                "negative": ["7", 0],
                "latent_image": ["5", 0],
            },
        },
        "4": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": ckpt}},
        "5": {
            "class_type": "EmptyLatentImage",
            "inputs": {"width": width, "height": height, "batch_size": 1},
        },
        "6": {"class_type": "CLIPTextEncode", "inputs": {"text": positive, "clip": ["4", 1]}},
        "7": {"class_type": "CLIPTextEncode", "inputs": {"text": negative, "clip": ["4", 1]}},
        "8": {"class_type": "VAEDecode", "inputs": {"samples": ["3", 0], "vae": ["4", 2]}},
        "9": {
            "class_type": "SaveImage",
            "inputs": {"filename_prefix": "agp_img", "images": ["8", 0]},
        },
    }


class ComfyUIImageBackend(ImageBackendBase):
    name = "comfyui"

    def __init__(self, cfg: Settings) -> None:
        super().__init__(cfg)
        self.client = ComfyUIClient(cfg.comfyui_url)
        self._template_path = cfg.comfyui_image_workflow.strip()

    @property
    def supports_reference_images(self) -> bool:
        # Only meaningful when a custom workflow wires the %REF_IMAGE% into an
        # IP-Adapter/ControlNet node. The default text2img graph ignores refs.
        return bool(self._template_path)

    def generate(
        self,
        prompt: str,
        dest: Path,
        *,
        negative: str = "",
        reference_images: list[Path] | None = None,
        seed: int | None = None,
    ) -> Path:
        seed = self.cfg.seed if seed is None else seed

        # Upload the first reference (if any) so a custom workflow can consume it.
        ref_name = ""
        if reference_images and self._template_path:
            ref_name = self.client.upload_image(reference_images[0])

        workflow = self._build_workflow(prompt, negative, seed, ref_name)
        prompt_id = self.client.queue_prompt(workflow)
        outputs = self.client.wait_outputs(prompt_id)

        art = self.client.first_output(outputs, keys=("images",))
        if not art:
            raise ImageBackendError(f"No image output from ComfyUI ({prompt_id})")
        self.client.download_view(
            art["filename"], art.get("subfolder", ""), art.get("type", "output"), dest
        )
        log.debug("comfyui_image", dest=str(dest), seed=seed)
        return dest

    def _build_workflow(self, positive: str, negative: str, seed: int, ref_name: str) -> dict:
        if self._template_path:
            raw = Path(self._template_path).read_text(encoding="utf-8")
            raw = (
                raw.replace("%POSITIVE%", json.dumps(positive)[1:-1])
                .replace("%NEGATIVE%", json.dumps(negative)[1:-1])
                .replace("%SEED%", str(seed))
                .replace("%WIDTH%", str(self.cfg.width))
                .replace("%HEIGHT%", str(self.cfg.height))
                .replace("%CKPT%", self.cfg.comfyui_ckpt)
                .replace("%REF_IMAGE%", ref_name)
            )
            return json.loads(raw)

        return copy.deepcopy(
            _default_workflow(
                positive, negative, seed, self.cfg.width, self.cfg.height, self.cfg.comfyui_ckpt
            )
        )
