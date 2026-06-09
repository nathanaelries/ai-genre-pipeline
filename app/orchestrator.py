"""The orchestrator — reads config, drives every stage, assembles the result.

High-level flow (per the project spec):

    1. resolve run folder + load/restore state
    2. LLM -> Visual Bible (consistency contract)
    3. image backend -> character reference images
    4. for each track:
         a. LLM -> song concept + lyrics
         b. music backend -> audio (or paste-ready Suno brief)
         c. LLM -> timed scene list
         d. per scene: key-frame image -> video clip (Ken-Burns fallback)
         e. FFmpeg -> normalise, concat, mux audio, optional lyric overlay
    5. write manifest.json

Every expensive step is guarded by `RunState`, so an interrupted run resumes
and only redoes unfinished work.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from pydantic import ValidationError

from app import prompts
from app.assembly import FFmpegAssembler
from app.config import Settings
from app.image import get_image_backend
from app.llm import get_llm
from app.logging_config import get_logger
from app.models import RunManifest, Scene, SongConcept, Track, VisualBible
from app.music import get_music_backend
from app.state import RunState
from app.utils import RunPaths, read_json, write_json
from app.video import get_video_backend

log = get_logger(__name__)

# Secret-bearing config fields excluded from the manifest snapshot.
_SECRET_FIELDS = {
    "anthropic_api_key", "openai_api_key", "xai_api_key", "suno_api_key",
    "kling_access_key", "kling_secret_key", "runway_api_key",
}

# Named stages -> the state-key prefix(es) they own. Used by `--redo` to
# regenerate one stage (e.g. re-write copyright-flagged lyrics) while keeping
# every other expensive step (images, videos) cached.
_STAGE_KEY_PREFIXES: dict[str, tuple[str, ...]] = {
    "bible": ("bible",),
    "refs": ("ref:",),
    "concept": ("concept:",),   # song concept + lyrics
    "scenes": ("scenes:",),
    "images": ("image:",),
    "videos": ("video:",),
    "music": ("audio:",),       # song audio + Suno brief
    "final": ("final:",),       # final assembly (incl. burned lyric overlay)
}


class Orchestrator:
    def __init__(self, cfg: Settings) -> None:
        self.cfg = cfg
        self.paths = RunPaths(cfg.output_dir / cfg.slug).ensure()
        self.state = RunState(self.paths.state_file)
        self.assembler = FFmpegAssembler(cfg.width, cfg.height, cfg.fps)

        # Backends are built lazily so a dry run (or a stage that isn't used)
        # never requires that backend's API keys.
        self._llm = None
        self._image = None
        self._music = None
        self._video = None

        self.manifest = self._load_or_init_manifest()

    # ------------------------------------------------------------------ #
    # Lazy backend accessors
    # ------------------------------------------------------------------ #
    @property
    def llm(self):
        if self._llm is None:
            self._llm = get_llm(self.cfg)
        return self._llm

    @property
    def image(self):
        if self._image is None:
            self._image = get_image_backend(self.cfg)
        return self._image

    @property
    def music(self):
        if self._music is None:
            self._music = get_music_backend(self.cfg)
        return self._music

    @property
    def video(self):
        if self._video is None:
            self._video = get_video_backend(self.cfg)
        return self._video

    # ------------------------------------------------------------------ #
    # Public entrypoint
    # ------------------------------------------------------------------ #
    def run(
        self,
        force: bool = False,
        dry_run: bool = False,
        on_track_complete: "Callable[[Path], None] | None" = None,
    ) -> RunManifest:
        """Run the pipeline.

        `on_track_complete` is invoked with the absolute path of each finished
        track video as soon as it is assembled — the live-streaming hook uses
        this to enqueue clips while later tracks are still generating.
        """
        if force:
            log.warning("force_rerun", note="discarding saved progress")
            self.state.reset()

        log.info(
            "run_start",
            run=self.paths.root.name,
            genre=self.cfg.genre,
            tracks=self.cfg.num_tracks,
            scenes_per_track=self.cfg.scenes_per_track,
            dry_run=dry_run,
        )

        bible = self._visual_bible()
        self.manifest.visual_bible = bible
        self._save_manifest()

        refs: list[Path] = []
        if not dry_run:
            refs = self._reference_images(bible)
            self.manifest.character_reference_images = [self.paths.rel(p) for p in refs]
            self._save_manifest()

        self.manifest.tracks = []
        for t in range(self.cfg.num_tracks):
            track = self._produce_track(t, bible, refs, dry_run=dry_run)
            self.manifest.tracks.append(track)
            self._save_manifest()

            # Stream the freshly-finished track immediately (live mode).
            if on_track_complete and track.final_video_path:
                try:
                    on_track_complete(self.paths.root / track.final_video_path)
                except Exception as exc:  # noqa: BLE001 - never let streaming break generation
                    log.warning("on_track_complete_failed", track=t + 1, error=str(exc)[:200])

        log.info("run_complete", run=self.paths.root.name, manifest=str(self.paths.manifest_file))
        return self.manifest

    # ------------------------------------------------------------------ #
    # Targeted regeneration
    # ------------------------------------------------------------------ #
    @staticmethod
    def valid_stages() -> list[str]:
        return list(_STAGE_KEY_PREFIXES)

    def invalidate(self, stages: list[str]) -> int:
        """Clear saved progress for the named stages so the next run redoes only
        those (and leaves everything else cached). Returns markers cleared.

        Example: invalidate(['concept','music','final']) re-writes the lyrics +
        Suno brief and re-burns the lyric overlay, but keeps all generated images
        and video clips.
        """
        unknown = [s for s in stages if s not in _STAGE_KEY_PREFIXES]
        if unknown:
            raise ValueError(
                f"Unknown stage(s): {', '.join(unknown)}. "
                f"Valid stages: {', '.join(_STAGE_KEY_PREFIXES)}"
            )
        prefixes = tuple(p for s in stages for p in _STAGE_KEY_PREFIXES[s])

        def matches(key: str) -> bool:
            return any(key == p or key.startswith(p) for p in prefixes)

        cleared = self.state.clear(matches)
        log.info("invalidate", stages=stages, cleared=cleared)
        return cleared

    # ------------------------------------------------------------------ #
    # Stage 2: Visual Bible
    # ------------------------------------------------------------------ #
    def _visual_bible(self) -> VisualBible:
        bible_file = self.paths.bible / "bible.json"
        if self.state.is_done("bible") and bible_file.exists():
            log.info("bible_cached")
            return VisualBible.model_validate(read_json(bible_file))

        log.info("bible_generate", provider=self.cfg.llm_provider.value)
        system, user = prompts.visual_bible_prompt(self.cfg)
        data = self.llm.generate_json(system, user)
        bible = self._coerce(VisualBible, data, "Visual Bible")

        # Guarantee the creator's exact character text is never lost.
        if self.cfg.character_description.strip() and not bible.character_description.strip():
            bible.character_description = self.cfg.character_description

        write_json(bible_file, bible.model_dump())
        self.state.mark("bible")
        return bible

    # ------------------------------------------------------------------ #
    # Stage 3: character reference images
    # ------------------------------------------------------------------ #
    def _reference_images(self, bible: VisualBible, count: int = 4) -> list[Path]:
        out: list[Path] = []
        ref_prompts = prompts.reference_image_prompts(bible, count)
        negative = bible.negative_suffix()

        for i, prompt in enumerate(ref_prompts):
            dest = self.paths.reference_images / f"character_ref_{i + 1:02d}.png"
            key = f"ref:{i}"
            if self.state.is_done(key) and dest.exists():
                out.append(dest)
                continue
            log.info("reference_image", index=i + 1, of=count)
            # Feed already-made references back in so later angles stay on-model.
            self.image.generate(
                prompt, dest, negative=negative,
                reference_images=out or None, seed=self.cfg.seed + i,
            )
            out.append(dest)
            self.state.mark(key)
        return out

    # ------------------------------------------------------------------ #
    # Per-track production
    # ------------------------------------------------------------------ #
    def _produce_track(
        self, t: int, bible: VisualBible, refs: list[Path], *, dry_run: bool
    ) -> Track:
        concept = self._song_concept(t)
        track = Track(index=t, name=concept.title, concept=concept)

        scenes = self._scene_list(bible, concept, t)
        track.scenes = scenes

        if dry_run:
            log.info("dry_run_skip_media", track=t + 1)
            self._save_scene_metadata(t, scenes)
            return track

        # (b) music — always writes the Suno brief; audio is backend-dependent.
        target_seconds = self.cfg.scenes_per_track * self.cfg.seconds_per_scene
        audio_path = self._music_for_track(concept, t, target_seconds)
        track.audio_path = self.paths.rel(audio_path) if audio_path else None

        # (d) per-scene image + video
        for scene in scenes:
            self._produce_scene(t, scene, bible, refs)
        self._save_scene_metadata(t, scenes)

        # (e) assemble
        final = self._assemble_track(t, track, audio_path)
        track.final_video_path = self.paths.rel(final) if final else None
        return track

    def _song_concept(self, t: int) -> SongConcept:
        concept_file = self.paths.concept / f"track_{t + 1:02d}_concept.json"
        if self.state.is_done(f"concept:{t}") and concept_file.exists():
            return SongConcept.model_validate(read_json(concept_file))

        log.info("concept_generate", track=t + 1)
        system, user = prompts.song_concept_prompt(self.cfg, t)
        data = self.llm.generate_json(system, user)
        concept = self._coerce(SongConcept, data, "Song concept")
        write_json(concept_file, concept.model_dump())
        self.state.mark(f"concept:{t}")
        return concept

    def _scene_list(self, bible: VisualBible, concept: SongConcept, t: int) -> list[Scene]:
        scenes_file = self.paths.concept / f"track_{t + 1:02d}_scenes.json"
        if self.state.is_done(f"scenes:{t}") and scenes_file.exists():
            return [Scene.model_validate(s) for s in read_json(scenes_file)]

        log.info("scenes_generate", track=t + 1, count=self.cfg.scenes_per_track)
        system, user = prompts.scene_list_prompt(
            self.cfg, bible, concept.concept, self.cfg.scenes_per_track
        )
        data = self.llm.generate_json(system, user)
        if not isinstance(data, list):
            data = data.get("scenes", []) if isinstance(data, dict) else []

        scenes = self._build_scenes(data, bible)
        write_json(scenes_file, [s.model_dump() for s in scenes])
        self.state.mark(f"scenes:{t}")
        return scenes

    def _build_scenes(self, data: list, bible: VisualBible) -> list[Scene]:
        """Validate raw scene dicts and compute sequential start times + prompts."""
        scenes: list[Scene] = []
        start = 0.0
        for i, raw in enumerate(data[: self.cfg.scenes_per_track]):
            duration = float(raw.get("duration") or self.cfg.seconds_per_scene)
            scene = Scene(
                index=i,
                title=raw.get("title", f"Scene {i + 1}"),
                start_time=round(start, 2),
                duration=duration,
                mood=raw.get("mood", ""),
                camera_movement=raw.get("camera_movement", ""),
                description=raw.get("description", ""),
                image_prompt=self._compose_image_prompt(raw.get("image_prompt", ""), bible),
                video_prompt=raw.get("video_prompt", raw.get("description", "")),
            )
            scenes.append(scene)
            start += duration
        return scenes

    def _compose_image_prompt(self, seed_prompt: str, bible: VisualBible) -> str:
        """Bake the consistent character + style into every scene prompt."""
        return (
            f"{seed_prompt}. "
            f"Featuring this exact character: {bible.character_description}. "
            f"{bible.style_suffix()}"
        ).strip()

    # ------------------------------------------------------------------ #
    # Scene media
    # ------------------------------------------------------------------ #
    def _produce_scene(
        self, t: int, scene: Scene, bible: VisualBible, refs: list[Path]
    ) -> None:
        # --- key-frame image ---
        img_dest = self.paths.scenes / f"track{t + 1:02d}_scene{scene.index:02d}.png"
        img_key = RunState.scene_image(t, scene.index)
        if self.state.is_done(img_key) and img_dest.exists():
            scene.image_path = self.paths.rel(img_dest)
        else:
            log.info("scene_image", track=t + 1, scene=scene.index)
            self.image.generate(
                scene.image_prompt,
                img_dest,
                negative=bible.negative_suffix(),
                reference_images=refs if self.image.supports_reference_images else None,
                seed=self.cfg.seed + scene.index,
            )
            scene.image_path = self.paths.rel(img_dest)
            self.state.mark(img_key)

        # --- video clip (with Ken-Burns fallback) ---
        vid_dest = self.paths.scenes / f"track{t + 1:02d}_scene{scene.index:02d}.mp4"
        vid_key = RunState.scene_video(t, scene.index)
        if self.state.is_done(vid_key) and vid_dest.exists():
            scene.video_path = self.paths.rel(vid_dest)
            return

        try:
            log.info("scene_video", track=t + 1, scene=scene.index, backend=self.cfg.video_backend.value)
            self.video.generate(
                scene.video_prompt,
                vid_dest,
                image_path=img_dest,
                duration=scene.duration,
                seed=self.cfg.seed + scene.index,
            )
        except Exception as exc:  # noqa: BLE001 - resilience: any backend failure
            # Never let one scene kill the run: fall back to an animated still.
            log.warning(
                "scene_video_fallback",
                track=t + 1, scene=scene.index, error=str(exc)[:200],
            )
            self.assembler.still_to_clip(img_dest, vid_dest, scene.duration)

        scene.video_path = self.paths.rel(vid_dest)
        self.state.mark(vid_key)

    # ------------------------------------------------------------------ #
    # Music
    # ------------------------------------------------------------------ #
    def _music_for_track(self, concept: SongConcept, t: int, target_seconds: float) -> Path | None:
        audio_marker = self.paths.music / f"track_{t + 1:02d}.audio_path.txt"
        if self.state.is_done(RunState.track_audio(t)) and audio_marker.exists():
            saved = audio_marker.read_text(encoding="utf-8").strip()
            return Path(saved) if saved else None

        result = self.music.generate(concept, self.paths.music, t, target_seconds)
        if result.note:
            log.info("music_note", track=t + 1, note=result.note)

        # Persist where the audio landed (or empty for prompt-only) for resume.
        audio_marker.write_text(
            str(result.audio_path) if result.audio_path else "", encoding="utf-8"
        )
        self.state.mark(RunState.track_audio(t))
        return result.audio_path

    # ------------------------------------------------------------------ #
    # Assembly
    # ------------------------------------------------------------------ #
    def _assemble_track(self, t: int, track: Track, audio_path: Path | None) -> Path | None:
        final_key = RunState.track_final(t)
        final_dest = self.paths.final_videos / f"track_{t + 1:02d}_{self._safe(track.name)}.mp4"
        if self.state.is_done(final_key) and final_dest.exists():
            return final_dest

        # Normalise each scene clip to identical params, then concat.
        normalized: list[Path] = []
        for scene in track.scenes:
            if not scene.video_path:
                continue
            src = self.paths.root / scene.video_path
            norm = self.paths.scenes / f"norm_track{t + 1:02d}_scene{scene.index:02d}.mp4"
            self.assembler.normalize_clip(src, norm, scene.duration)
            normalized.append(norm)

        if not normalized:
            log.warning("assemble_no_clips", track=t + 1)
            return None

        silent = self.paths.final_videos / f"_track_{t + 1:02d}_silent.mp4"
        self.assembler.concat(normalized, silent)

        # Mux audio if we have it; otherwise the silent cut is the base.
        base = silent
        if audio_path and audio_path.exists():
            with_audio = self.paths.final_videos / f"_track_{t + 1:02d}_audio.mp4"
            self.assembler.mux_audio(silent, audio_path, with_audio)
            base = with_audio

        # Optional lyric overlay (best-effort).
        if self.cfg.lyrics_overlay and track.concept and track.concept.lyrics.strip():
            base = self._overlay_lyrics(t, track, base, final_dest) or base

        if base != final_dest:
            # Move/rename the finished cut to its canonical name.
            if final_dest.exists():
                final_dest.unlink()
            base.replace(final_dest)

        # Tidy intermediates.
        for tmp in (silent,):
            tmp.unlink(missing_ok=True)

        self.state.mark(final_key)
        log.info("track_final", track=t + 1, path=str(final_dest))
        return final_dest

    def _overlay_lyrics(self, t: int, track: Track, base: Path, final_dest: Path) -> Path | None:
        try:
            total = self.assembler.probe_duration(base)
            srt = self.paths.final_videos / f"track_{t + 1:02d}_lyrics.srt"
            self.assembler.write_lyrics_srt(track.concept.lyrics, total, srt)
            out = self.paths.final_videos / f"_track_{t + 1:02d}_subbed.mp4"
            self.assembler.burn_subtitles(base, srt, out)
            return out
        except Exception as exc:  # noqa: BLE001 - best-effort overlay, never fatal
            log.warning("lyrics_overlay_skipped", track=t + 1, error=str(exc)[:200])
            return None

    # ------------------------------------------------------------------ #
    # Helpers
    # ------------------------------------------------------------------ #
    def _coerce(self, model, data, what: str):
        try:
            return model.model_validate(data)
        except ValidationError as exc:
            raise RuntimeError(
                f"{what} from the LLM did not match the expected schema:\n{exc}"
            ) from exc

    def _save_scene_metadata(self, t: int, scenes: list[Scene]) -> None:
        write_json(
            self.paths.concept / f"track_{t + 1:02d}_scenes.json",
            [s.model_dump() for s in scenes],
        )

    def _save_manifest(self) -> None:
        write_json(self.paths.manifest_file, self.manifest.model_dump())

    def _load_or_init_manifest(self) -> RunManifest:
        if self.paths.manifest_file.exists():
            try:
                return RunManifest.model_validate(read_json(self.paths.manifest_file))
            except (ValidationError, ValueError):
                log.warning("manifest_reset", note="existing manifest unreadable")
        snapshot = {
            k: v for k, v in self.cfg.model_dump(mode="json").items() if k not in _SECRET_FIELDS
        }
        return RunManifest(
            run_name=self.paths.root.name,
            genre=self.cfg.genre,
            theme=self.cfg.theme,
            config_snapshot=snapshot,
        )

    @staticmethod
    def _safe(name: str) -> str:
        import re

        return re.sub(r"[^a-zA-Z0-9]+", "_", name).strip("_").lower()[:40] or "track"
