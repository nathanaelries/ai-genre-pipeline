# TODO / Backlog — ai-genre-pipeline

Working backlog for agents and the maintainer. See [CLAUDE.md](CLAUDE.md) for how to work
on the repo, and `git log` for the detail behind "Done".

## Known limitations

- [ ] **Lip-sync** (`LIPSYNC` env flag) is a stub/no-op. Needs a Wav2Lip / LatentSync
      ComfyUI workflow wired into the video stage (only meaningful with `VIDEO_BACKEND=comfyui`).
- [ ] **Burned lyrics are off by default** (`LYRICS_OVERLAY=false`) because the even-split
      timing can't match the song's vocals. To make them usable, add **forced alignment**
      (e.g. whisperX against the rendered audio) and only then re-enable the overlay.
- [ ] **Lyric overlay needs ffmpeg+libass.** If the container's ffmpeg lacks it,
      `burn_subtitles` fails and the overlay is silently skipped. Add a `doctor` check for
      libass and/or a `drawtext`-based fallback overlay.
- [ ] **ComfyUI video** has no bundled workflow — requires a user-supplied API-format graph
      (`COMFYUI_VIDEO_WORKFLOW`) because video graphs are model-specific.
- [ ] **Provider request shapes not live-tested.** The Suno relay, Kling, and Runway
      request/response formats are coded to docs; the first real call may need field tweaks.
      Endpoints are isolated as class constants for easy adaptation.
- [ ] **No beat-synced scene cuts** (would need audio onset/beat detection).
- [ ] **Base image CVEs:** `python:3.11-slim` is flagged with high vulnerabilities by image
      scanners. Consider pinning a patched digest or bumping the base.

## Operational (maintainer / deployment)

- [ ] Set `KLING_*` or `RUNWAY_API_KEY` if you want real motion video; otherwise scenes use
      the free Ken-Burns still fallback (fine for ambient channels).
- [ ] Decide outputs storage: named volume `agp_outputs` (default, durable, less accessible)
      vs `./outputs` bind mount (host access — migrate existing volume data first).
- [ ] Remember: after any `git pull`, run `docker compose build` before running (the image
      bakes `app/` at build time).

## Nice-to-have features

- [ ] `run --redo concept --show-lyrics` (or a flag) to print regenerated lyrics to the
      console for a quick copyright eyeball before generating audio.
- [ ] A `new-video` / `series` convenience wrapper around
      `run --character ... --run ... --theme ...`.
- [ ] Per-track distinct themes (currently `THEME` is per-run; multi-track repeats the theme).
- [ ] **pytest suite** codifying the ad-hoc checks: `RunState` invalidate/clear, stream URL
      building + target parsing, character resolver, audio detection, `--redo` stage mapping,
      aspect-preset resolution. (All validated by hand via throwaway-venv snippets so far.)
- [ ] **CI:** GitHub Actions running `python -m py_compile` on every push (and pytest once it
      exists).

## Done (recent — newest first; see `git log` for detail)

- grok-3 as the Grok LLM model (was grok-2-latest).
- Suno audio ingest: `add-audio` command + `./inbox` host mount; auto-detect
  `03_music/track_NN.<ext>` and mux into the final video.
- Character reuse across runs (`--character` / `CHARACTER_DIR`) for building a series.
- Original-lyrics prompt hardening (copyright) + `run --redo <stages>` targeted regen.
- xAI/Grok image backend (`IMAGE_BACKEND=xai`) — a fully Grok pipeline needs no OpenAI key.
- Named Docker data volume for outputs (+ Dockerfile chown so the volume is writable);
  "rebuild after pull" docs + optional source bind mount.
- 24/7 live streaming: RTMP/RTMPS `tee` fan-out to YouTube/TikTok/Facebook/Rumble, seamless
  MPEG-TS segment feeder with loop-when-idle and encoder auto-restart; `stream` command.
- Provider sign-up / buying guide in the README.
- Fixed ffmpeg concat to use absolute paths (path-doubling bug).
- Initial pipeline: LLM (claude/openai/grok) → Visual Bible → reference images → song
  (suno/local/prompt_only) → scenes → key-frame images → video (kling/runway/comfyui,
  Ken-Burns fallback) → ffmpeg assembly; Docker + compose; 3 example genres; resumable state.
