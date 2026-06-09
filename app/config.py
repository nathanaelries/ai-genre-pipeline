"""Configuration layer.

Everything that makes a run unique lives in `.env` and is loaded here via
pydantic-settings. The rest of the codebase reads a single immutable `Settings`
object, so spinning up a new genre never requires touching code.
"""

from __future__ import annotations

import re
from enum import Enum
from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


# --------------------------------------------------------------------------- #
# Enums — keep backend selection typo-proof and self-documenting.
# --------------------------------------------------------------------------- #
class LLMProvider(str, Enum):
    claude = "claude"
    openai = "openai"
    grok = "grok"


class MusicBackendKind(str, Enum):
    suno_thirdparty = "suno_thirdparty"
    local = "local"
    prompt_only = "prompt_only"


class ImageBackendKind(str, Enum):
    openai = "openai"
    xai = "xai"          # xAI / Grok image model (grok-2-image)
    comfyui = "comfyui"


class VideoBackendKind(str, Enum):
    kling = "kling"
    runway = "runway"
    comfyui = "comfyui"


class StreamPlatform(str, Enum):
    youtube = "youtube"
    tiktok = "tiktok"
    facebook = "facebook"   # also covers Instagram (same Live API ingest)
    rumble = "rumble"
    custom = "custom"       # any other RTMP/RTMPS ingest


class StreamMode(str, Enum):
    after = "after"   # generate everything first, then stream the library in a loop
    live = "live"     # start streaming immediately; enqueue clips as they finish


# Convenience presets so a creator can say "vertical" instead of memorising
# pixel dimensions. RESOLUTION still wins if ASPECT is left as "custom".
_ASPECT_PRESETS = {
    "horizontal": (1920, 1080),
    "vertical": (1080, 1920),
    "square": (1080, 1080),
}


class Settings(BaseSettings):
    """Typed, validated view of `.env`."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ---------------------------- creative ---------------------------------- #
    genre: str = Field(default="Deep House", alias="GENRE")
    sub_style: str = Field(default="", alias="SUB_STYLE")
    theme: str = Field(default="", alias="THEME")
    mood: str = Field(default="", alias="MOOD")
    character_description: str = Field(default="", alias="CHARACTER_DESCRIPTION")
    style_guide: str = Field(default="", alias="STYLE_GUIDE")

    num_tracks: int = Field(default=1, ge=1, le=50, alias="NUM_TRACKS")
    scenes_per_track: int = Field(default=8, ge=1, le=100, alias="SCENES_PER_TRACK")
    seconds_per_scene: float = Field(default=8.0, gt=0, le=60, alias="SECONDS_PER_SCENE")

    resolution: str = Field(default="1920x1080", alias="RESOLUTION")
    fps: int = Field(default=24, ge=1, le=120, alias="FPS")
    aspect: str = Field(default="horizontal", alias="ASPECT")

    # ---------------------------- backends ---------------------------------- #
    llm_provider: LLMProvider = Field(default=LLMProvider.claude, alias="LLM_PROVIDER")
    music_backend: MusicBackendKind = Field(
        default=MusicBackendKind.prompt_only, alias="MUSIC_BACKEND"
    )
    image_backend: ImageBackendKind = Field(
        default=ImageBackendKind.openai, alias="IMAGE_BACKEND"
    )
    video_backend: VideoBackendKind = Field(
        default=VideoBackendKind.kling, alias="VIDEO_BACKEND"
    )

    lyrics_overlay: bool = Field(default=True, alias="LYRICS_OVERLAY")
    lipsync: bool = Field(default=False, alias="LIPSYNC")

    # ---------------------------- api keys ---------------------------------- #
    anthropic_api_key: str = Field(default="", alias="ANTHROPIC_API_KEY")
    openai_api_key: str = Field(default="", alias="OPENAI_API_KEY")
    xai_api_key: str = Field(default="", alias="XAI_API_KEY")

    suno_api_base: str = Field(default="https://api.sunoapi.org", alias="SUNO_API_BASE")
    suno_api_key: str = Field(default="", alias="SUNO_API_KEY")

    kling_access_key: str = Field(default="", alias="KLING_ACCESS_KEY")
    kling_secret_key: str = Field(default="", alias="KLING_SECRET_KEY")
    kling_api_base: str = Field(default="https://api.klingai.com", alias="KLING_API_BASE")
    runway_api_key: str = Field(default="", alias="RUNWAY_API_KEY")
    runway_api_base: str = Field(
        default="https://api.dev.runwayml.com", alias="RUNWAY_API_BASE"
    )

    comfyui_url: str = Field(default="http://localhost:8188", alias="COMFYUI_URL")
    # Checkpoint + optional custom workflow templates (ComfyUI "API format" JSON).
    comfyui_ckpt: str = Field(
        default="sd_xl_base_1.0.safetensors", alias="COMFYUI_CKPT"
    )
    comfyui_image_workflow: str = Field(default="", alias="COMFYUI_IMAGE_WORKFLOW")
    comfyui_video_workflow: str = Field(default="", alias="COMFYUI_VIDEO_WORKFLOW")
    # Image / video model identifiers (overridable per run).
    openai_image_model: str = Field(default="gpt-image-1", alias="OPENAI_IMAGE_MODEL")
    xai_image_model: str = Field(default="grok-2-image", alias="XAI_IMAGE_MODEL")
    runway_model: str = Field(default="gen3a_turbo", alias="RUNWAY_MODEL")
    kling_model: str = Field(default="kling-v1", alias="KLING_MODEL")

    # ---------------------------- runtime ----------------------------------- #
    output_dir: Path = Field(default=Path("outputs"), alias="OUTPUT_DIR")
    run_name: str = Field(default="", alias="RUN_NAME")
    # Reuse an existing character instead of generating a new one. Point at a
    # prior run (by name or path) or its 02_character_bible folder; the Visual
    # Bible + reference images are imported and marked cached, so a new
    # theme/verse reuses the exact same character. Empty = generate fresh.
    character_dir: str = Field(default="", alias="CHARACTER_DIR")
    seed: int = Field(default=42, alias="SEED")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    log_pretty: bool = Field(default=True, alias="LOG_PRETTY")

    # ----------------------------- streaming -------------------------------- #
    # 24/7 live streaming: as videos are generated they are queued and pushed
    # to one or more platforms via RTMP/RTMPS, so playback never stops.
    stream_enabled: bool = Field(default=False, alias="STREAM_ENABLED")
    # Comma-separated platforms: youtube,tiktok,facebook,rumble,custom
    stream_targets_raw: str = Field(default="youtube", alias="STREAM_TARGETS")
    stream_mode: StreamMode = Field(default=StreamMode.after, alias="STREAM_MODE")
    # Re-loop the already-generated library whenever the queue is empty so the
    # stream never goes black (the "never stops" guarantee).
    stream_loop_when_idle: bool = Field(default=True, alias="STREAM_LOOP_WHEN_IDLE")
    stream_video_bitrate: str = Field(default="4500k", alias="STREAM_VIDEO_BITRATE")
    stream_audio_bitrate: str = Field(default="128k", alias="STREAM_AUDIO_BITRATE")
    stream_preset: str = Field(default="veryfast", alias="STREAM_PRESET")

    # Per-platform ingest. For YouTube/Facebook we ship the stable server base
    # and append your key. For TikTok/Rumble paste the full URL (and/or key)
    # from their live studio. `custom` is any RTMP/RTMPS URL.
    youtube_ingest_url: str = Field(
        default="rtmp://a.rtmp.youtube.com/live2", alias="YOUTUBE_INGEST_URL"
    )
    youtube_stream_key: str = Field(default="", alias="YOUTUBE_STREAM_KEY")
    facebook_ingest_url: str = Field(
        default="rtmps://live-api-s.facebook.com:443/rtmp", alias="FACEBOOK_INGEST_URL"
    )
    facebook_stream_key: str = Field(default="", alias="FACEBOOK_STREAM_KEY")
    tiktok_ingest_url: str = Field(default="", alias="TIKTOK_INGEST_URL")
    tiktok_stream_key: str = Field(default="", alias="TIKTOK_STREAM_KEY")
    rumble_ingest_url: str = Field(default="", alias="RUMBLE_INGEST_URL")
    rumble_stream_key: str = Field(default="", alias="RUMBLE_STREAM_KEY")
    custom_ingest_url: str = Field(default="", alias="CUSTOM_INGEST_URL")

    # ------------------------------------------------------------------ #
    # Derived helpers
    # ------------------------------------------------------------------ #
    @field_validator("resolution")
    @classmethod
    def _validate_resolution(cls, v: str) -> str:
        if not re.fullmatch(r"\d{2,5}x\d{2,5}", v.strip()):
            raise ValueError("RESOLUTION must look like '1920x1080'")
        return v.strip()

    @model_validator(mode="after")
    def _apply_aspect_preset(self) -> "Settings":
        """If ASPECT names a known preset, let it define resolution."""
        preset = _ASPECT_PRESETS.get(self.aspect.strip().lower())
        if preset:
            object.__setattr__(self, "resolution", f"{preset[0]}x{preset[1]}")
        return self

    @property
    def width(self) -> int:
        return int(self.resolution.split("x")[0])

    @property
    def height(self) -> int:
        return int(self.resolution.split("x")[1])

    @property
    def slug(self) -> str:
        """Filesystem-safe run name derived from genre + theme when unset."""
        if self.run_name.strip():
            base = self.run_name
        else:
            base = f"{self.genre}-{self.theme}"
        base = base.lower()
        base = re.sub(r"[^a-z0-9]+", "-", base).strip("-")
        return base[:60] or "run"

    def require(self, *fields: str) -> None:
        """Raise a clear error if a required secret/setting is empty.

        Backends call this at construction time so misconfiguration fails fast
        with an actionable message instead of an opaque 401 deep in a request.
        """
        missing = [f for f in fields if not str(getattr(self, f, "")).strip()]
        if missing:
            env_names = ", ".join(f.upper() for f in missing)
            raise ConfigError(
                f"Missing required configuration: {env_names}. "
                f"Set it in your .env file."
            )

    # ------------------------------------------------------------------ #
    # Streaming helpers
    # ------------------------------------------------------------------ #
    @property
    def stream_targets(self) -> list[StreamPlatform]:
        """Parse STREAM_TARGETS into a deduped list of known platforms."""
        out: list[StreamPlatform] = []
        for token in self.stream_targets_raw.split(","):
            token = token.strip().lower()
            if not token:
                continue
            try:
                platform = StreamPlatform(token)
            except ValueError:
                continue  # ignore unknown tokens rather than crash a run
            if platform not in out:
                out.append(platform)
        return out

    def stream_url_for(self, platform: StreamPlatform) -> str | None:
        """Build the full RTMP/RTMPS ingest URL for a platform, or None.

        Convention: when a stream key is provided it is appended to the ingest
        base; when only the ingest URL is given it is assumed to already include
        the key (how TikTok/Rumble studios hand it out).
        """
        base, key = {
            StreamPlatform.youtube: (self.youtube_ingest_url, self.youtube_stream_key),
            StreamPlatform.facebook: (self.facebook_ingest_url, self.facebook_stream_key),
            StreamPlatform.tiktok: (self.tiktok_ingest_url, self.tiktok_stream_key),
            StreamPlatform.rumble: (self.rumble_ingest_url, self.rumble_stream_key),
            StreamPlatform.custom: (self.custom_ingest_url, ""),
        }[platform]

        base = base.strip()
        key = key.strip()
        if not base and not key:
            return None
        if key:
            return f"{base.rstrip('/')}/{key}" if base else None
        return base or None


class ConfigError(RuntimeError):
    """Raised when required configuration is absent or invalid."""


@lru_cache
def get_settings() -> Settings:
    """Return the process-wide Settings singleton (cached)."""
    return Settings()  # type: ignore[call-arg]
