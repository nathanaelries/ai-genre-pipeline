"""Prompt construction for the LLM stages.

Each function returns a `(system, user)` tuple. The user prompt asks for STRICT
JSON matching a known shape so the orchestrator can validate it into a pydantic
model. Keeping prompts here (not inline) makes tuning creative output easy.
"""

from __future__ import annotations

import json

from app.config import Settings
from app.models import VisualBible


def _creative_context(cfg: Settings) -> str:
    """Shared creative brief injected into every LLM stage."""
    return (
        f"GENRE: {cfg.genre}\n"
        f"SUB-STYLE: {cfg.sub_style}\n"
        f"THEME: {cfg.theme}\n"
        f"MOOD: {cfg.mood}\n"
        f"CHARACTER: {cfg.character_description}\n"
        f"STYLE GUIDE: {cfg.style_guide}\n"
    )


# --------------------------------------------------------------------------- #
# 1. Song concept + lyrics
# --------------------------------------------------------------------------- #
def song_concept_prompt(cfg: Settings, track_index: int) -> tuple[str, str]:
    system = (
        "You are an award-winning songwriter and music supervisor. You write "
        "emotionally resonant, singable lyrics and precise production briefs. "
        "You always respond with a single valid JSON object and nothing else."
    )
    shape = {
        "title": "string",
        "concept": "2-4 sentence creative summary",
        "lyrics": "full lyrics using [Intro]/[Verse 1]/[Chorus]/[Bridge]/[Outro] tags",
        "structure": ["Intro", "Verse 1", "Chorus", "..."],
        "suno_style_prompt": "Suno 'Style of Music' line: genre, mood, "
        "instrumentation, BPM, vocal style, production notes. NO lyrics here.",
        "bpm": "integer BPM",
    }
    user = (
        f"{_creative_context(cfg)}\n"
        f"This is track #{track_index + 1} of {cfg.num_tracks}.\n\n"
        "Write a complete song that fits the genre, theme and mood. The lyrics "
        "should be evocative and connect to the recurring character's journey.\n\n"
        "Respond with JSON exactly matching this shape:\n"
        f"{json.dumps(shape, indent=2)}"
    )
    return system, user


# --------------------------------------------------------------------------- #
# 2. Visual Bible — the consistency contract
# --------------------------------------------------------------------------- #
def visual_bible_prompt(cfg: Settings) -> tuple[str, str]:
    system = (
        "You are a film director and art director defining a strict visual "
        "style guide ('Visual Bible') for a music video. Consistency across "
        "every shot is the top priority. Respond with one valid JSON object only."
    )
    shape = {
        "character_description": "ONE canonical, physically specific paragraph. "
        "Lock hair, age, wardrobe, colors, distinguishing features. This text "
        "is pasted verbatim into every image/video prompt, so be deterministic.",
        "style_rules": ["concrete art-direction rule", "..."],
        "color_palette": ["named color or #hex", "..."],
        "recurring_elements": ["motif/prop/location that reappears", "..."],
        "lighting_rules": ["lighting direction", "..."],
        "negative_prompts": ["thing to exclude (extra fingers, text, watermark)", "..."],
    }
    user = (
        f"{_creative_context(cfg)}\n"
        "Expand the brief above into a detailed, deterministic Visual Bible. "
        "The character_description MUST preserve every concrete detail from the "
        "CHARACTER field and may enrich it, but must never contradict it.\n\n"
        "Respond with JSON exactly matching this shape:\n"
        f"{json.dumps(shape, indent=2)}"
    )
    return system, user


# --------------------------------------------------------------------------- #
# 3. Character reference-image prompts
# --------------------------------------------------------------------------- #
def reference_image_prompts(bible: VisualBible, count: int) -> list[str]:
    """Deterministic, varied angles of the SAME character for IP-Adapter/refs.

    These don't need the LLM — we template them from the bible so the character
    description is identical across every reference, only the framing changes.
    """
    angles = [
        "front-facing portrait, neutral expression, eye-level",
        "3/4 left profile portrait, soft smile",
        "full-body shot, relaxed standing pose",
        "side profile, looking into the distance",
        "medium close-up, dramatic key light",
        "back-three-quarter view showing hair and wardrobe",
    ]
    style = bible.style_suffix()
    out: list[str] = []
    for i in range(count):
        angle = angles[i % len(angles)]
        out.append(
            f"Character reference sheet, {angle}. {bible.character_description} "
            f"Plain neutral studio background, consistent character design. {style}"
        )
    return out


# --------------------------------------------------------------------------- #
# 4. Scene list with timing + per-shot prompts
# --------------------------------------------------------------------------- #
def scene_list_prompt(
    cfg: Settings, bible: VisualBible, concept_summary: str, num_scenes: int
) -> tuple[str, str]:
    system = (
        "You are a music-video director and storyboard artist. You break a song "
        "into a sequence of cinematic shots featuring a single consistent "
        "character. Respond with one valid JSON array only."
    )
    total = round(num_scenes * cfg.seconds_per_scene, 2)
    shape = [
        {
            "index": 0,
            "title": "short shot title",
            "duration": cfg.seconds_per_scene,
            "mood": "shot mood",
            "camera_movement": "e.g. slow dolly-in, static wide, orbit left",
            "description": "what literally happens in the shot",
            "image_prompt": "vivid key-frame prompt. Include the character and "
            "setting; the pipeline appends style + character automatically, so "
            "focus on composition, action and environment.",
            "video_prompt": "how the shot animates over its duration (motion, "
            "camera, subject action).",
        }
    ]
    user = (
        f"{_creative_context(cfg)}\n"
        f"SONG CONCEPT: {concept_summary}\n"
        f"RECURRING ELEMENTS: {', '.join(bible.recurring_elements) or 'n/a'}\n\n"
        f"Create EXACTLY {num_scenes} sequential shots that together tell a "
        f"cohesive visual story (~{total}s total, ~{cfg.seconds_per_scene}s each). "
        "Vary camera and composition; keep the character and world consistent. "
        "Do not include start_time (the pipeline computes it).\n\n"
        f"Respond with a JSON array of {num_scenes} objects matching this shape "
        "(index 0..N-1):\n"
        f"{json.dumps(shape, indent=2)}"
    )
    return system, user
