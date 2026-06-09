"""Pydantic data models — the structured artifacts the pipeline passes around.

These double as:
  * the JSON schema we ask the LLM to fill (concept, bible, scenes), and
  * the on-disk format written into each run folder.

Keeping them strongly typed means a malformed LLM response fails loudly at the
boundary instead of corrupting a downstream stage.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class SongConcept(BaseModel):
    """High-level creative concept + full lyrics for a single track."""

    title: str
    concept: str = Field(description="2-4 sentence creative summary of the song.")
    lyrics: str = Field(description="Full lyrics with [Verse]/[Chorus] section tags.")
    structure: list[str] = Field(
        default_factory=list,
        description="Ordered section list, e.g. ['Intro','Verse 1','Chorus',...].",
    )
    suno_style_prompt: str = Field(
        default="",
        description="Ready-to-paste Suno 'Style of Music' prompt (genre, mood, "
        "instrumentation, BPM, production notes). No lyrics here.",
    )
    bpm: int | None = Field(default=None, ge=40, le=220)


class VisualBible(BaseModel):
    """The consistency contract. Generated once per run, reused everywhere."""

    character_description: str = Field(
        description="Canonical, physically specific description of the recurring "
        "character. This exact text is injected into every prompt."
    )
    style_rules: list[str] = Field(
        default_factory=list,
        description="Art-direction rules every scene must obey.",
    )
    color_palette: list[str] = Field(
        default_factory=list,
        description="Named colors or hex codes that define the grade.",
    )
    recurring_elements: list[str] = Field(
        default_factory=list,
        description="Motifs/props/locations that should reappear across scenes.",
    )
    lighting_rules: list[str] = Field(
        default_factory=list,
        description="Lighting direction (e.g. 'golden-hour backlight, soft fill').",
    )
    negative_prompts: list[str] = Field(
        default_factory=list,
        description="Things to actively exclude (extra fingers, text, watermarks).",
    )

    def style_suffix(self) -> str:
        """Compact one-line style block appended to image/video prompts."""
        parts: list[str] = []
        if self.style_rules:
            parts.append(", ".join(self.style_rules))
        if self.color_palette:
            parts.append("color palette: " + ", ".join(self.color_palette))
        if self.lighting_rules:
            parts.append("lighting: " + ", ".join(self.lighting_rules))
        return ". ".join(parts)

    def negative_suffix(self) -> str:
        return ", ".join(self.negative_prompts)


class Scene(BaseModel):
    """A single shot in a track."""

    index: int
    title: str
    start_time: float = Field(description="Seconds from the start of the track.")
    duration: float = Field(gt=0, description="Shot length in seconds.")
    mood: str = ""
    camera_movement: str = Field(
        default="", description="e.g. 'slow dolly-in', 'static wide', 'orbit left'."
    )
    description: str = Field(description="What literally happens in the shot.")
    image_prompt: str = Field(
        default="", description="Prompt seed for the scene key-frame image."
    )
    video_prompt: str = Field(
        default="", description="Prompt seed for animating the shot."
    )

    # Populated as the pipeline produces artifacts (relative paths within run dir).
    image_path: str | None = None
    video_path: str | None = None


class Track(BaseModel):
    """One song + its visual scene list + produced media paths."""

    index: int
    name: str
    concept: SongConcept | None = None
    scenes: list[Scene] = Field(default_factory=list)

    # Artifact paths (relative to the run folder), filled in as we go.
    audio_path: str | None = None
    final_video_path: str | None = None


class RunManifest(BaseModel):
    """Top-level record of a run. Serialised to `manifest.json`."""

    run_name: str
    genre: str
    theme: str
    config_snapshot: dict = Field(default_factory=dict)
    visual_bible: VisualBible | None = None
    character_reference_images: list[str] = Field(default_factory=list)
    tracks: list[Track] = Field(default_factory=list)
