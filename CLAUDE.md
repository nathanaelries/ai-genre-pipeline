# CLAUDE.md — agent guide for `ai-genre-pipeline`

Onboarding notes for an AI agent (or a future me) working on this repo. The
[README](README.md) is the user-facing manual; **this file is the developer/agent
manual** — how to verify changes here, the conventions, and the gotchas we already hit
so you don't re-learn them. Read this first.

## What this is

A config-driven, Dockerized pipeline: a single `.env` (genre, theme, character,
backends, keys) becomes an **AI song + a cohesive music video with a consistent
character**, with optional **24/7 multi-platform RTMP live streaming**. Public repo:
`github.com/nathanaelries/ai-genre-pipeline`. The #1 design goal is "spin up a new genre
by editing `.env` only."

## Where it runs (two very different machines)

- **Authoring / this dev box (Windows):** has **no** project Python deps and **no**
  ffmpeg installed. Do **not** try to run the full pipeline here — it can't.
- **Production: a homelab Linux NUC**, via Docker, using cloud backends (no GPU).
  Generated output persists in a **named Docker volume** `agp_outputs` (not on the host
  by default). Deploy cycle on the NUC: `git pull` → `docker compose build` →
  `docker compose run --rm orchestrator <cmd>`.

## How to verify changes (READ before "testing")

The code is structured so you can validate almost everything **without** the heavy deps
or ffmpeg, because **nothing heavy is imported at module load** — it shells out to ffmpeg
via `subprocess` and talks to all providers with raw `httpx` (the `moviepy` /
`ffmpeg-python` / `Pillow` / `anthropic` / `openai` deps are NOT imported anywhere).

1. **Syntax:** `python -m py_compile $(find app -name '*.py')`
2. **Imports / CLI / logic:** a throwaway venv with only the lightweight import deps:
   ```bash
   python -m venv .venv-check
   ./.venv-check/Scripts/python.exe -m pip install -q \
       pydantic pydantic-settings typer httpx structlog rich tenacity
   ./.venv-check/Scripts/python.exe -m app.main --help
   # then `rm -rf .venv-check` when done
   ```
3. **Logic tests** (no Docker): build a `Settings(_env_file=None, FIELD=...)` and an
   `Orchestrator` against a tempfile `OUTPUT_DIR`, then drive it directly — e.g. mark
   state and assert `invalidate()` clears the right keys, or check
   `cfg.stream_url_for(...)`, the character resolver, audio detection, etc. (Git history
   has several of these inline `python -c` snippets.)
4. **Real media / ffmpeg / live API behavior** is only verifiable on the NUC. Provider
   request shapes (Suno relay, Kling, Runway) are coded to docs but not live-tested.

## Architecture (1-minute version; full tree in the README)

- **Config:** `app/config.py` — pydantic-settings, the entire `.env`. `Settings` is
  **mutable**; CLI overrides (`--run`, `--theme`, `--character`, `--stream`) assign onto
  `cfg` before the `Orchestrator` is built.
- **Backends** are each `abstract base + factory + enum-in-config`:
  - `app/llm/` → claude · openai · grok (openai+grok share `openai_compat.py`)
  - `app/music/` → suno_thirdparty · local · prompt_only
  - `app/image/` → openai · xai · comfyui (openai+xai share `openai_compat_image.py`)
  - `app/video/` → kling · runway · comfyui
  - `app/assembly/` → ffmpeg final cut · `app/streaming/` → RTMP tee fan-out + feeder
- **Orchestrator** (`app/orchestrator.py`) drives the stages; **RunState**
  (`app/state.py`, `state.json`) makes runs resumable. Stage keys:
  `bible`, `ref:i`, `concept:t`, `scenes:t`, `image:t:s`, `video:t:s`, `audio:t`, `final:t`.
- **Adding a backend:** subclass the base → add the enum value in `config.py` → wire the
  factory → add any keys to `Settings` + `.env.example` + the `doctor` required-keys map.

### Model defaults (override via `.env`)
LLM: claude `claude-opus-4-8`, openai `gpt-4o`, grok `grok-3`. Image: openai `gpt-image-1`,
xai `grok-2-image`. Video: kling `kling-v1`, runway `gen3a_turbo`.

## Conventions

- **Commit trailer:** end messages with
  `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`.
- **Push email (GH007):** this personal repo rejects pushes that expose a private email.
  Commit author must be the GitHub noreply:
  `nathanaelries <1423199+nathanaelries@users.noreply.github.com>` (set as local
  `user.email`). The `dev/personal/` dir already selects the personal git identity (see
  the parent `dev/CLAUDE.md`).
- **Public repo, no secrets:** `.env` is gitignored (only `.env.*.example` with empty
  keys are committed). `mcps/` and `inbox/*` are gitignored.
- **Style:** match the surrounding code — raw `httpx` (not provider SDKs), `subprocess`
  to ffmpeg, generous but purposeful comments.
- `gh` CLI exists on the **dev box** (`C:\Program Files\GitHub CLI\gh.exe`); the NUC uses
  plain git over HTTPS. Pushes in this project were made from the dev box.

## Gotchas (already paid for — don't repeat)

1. **The image bakes `app/` at build time.** `git pull` alone does NOT change what the
   container runs — you must `docker compose build` after pulling. (Optional
   `./app:/app/app:ro` mount in compose avoids rebuilds for code-only changes.)
2. **Outputs live in the `agp_outputs` named volume**, not on the host. To get files in/out:
   `add-audio` + the `./inbox` mount, a `docker run -v ...volume... alpine cp` one-liner,
   or switch to the `./outputs` bind mount — **but** that orphans existing volume data
   (migrate it first).
3. **ffmpeg concat needs absolute paths.** The concat demuxer resolves relative entries
   against the list-file's directory, which doubles paths. See `assembly/ffmpeg_assembler.concat`.
4. **Lyric overlay needs ffmpeg built with libass.** If absent, `burn_subtitles` raises,
   is caught, and the overlay is **silently skipped** (run still completes). The container
   image may lack libass — TODO in `todo.md`.
5. **Lyrics & copyright:** the songwriting prompt forces original wording (no NIV/ESV-style
   verbatim) so Suno's filter doesn't flag it — **not a legal guarantee**.
6. **Video resilience:** missing video-backend keys → automatic Ken-Burns still fallback;
   a single scene failure never kills the run (by design).
7. **`prompt_only` music = silent video.** The user renders in Suno, then `add-audio
   <file> --track N` (or drops `03_music/track_NN.<ext>` and runs `run --redo final`).
   Detection sits at the top of `_music_for_track` and overrides the cached empty marker.

## Iteration flags worth knowing

- `run --redo <stages>` — regenerate only some stages (e.g. `concept,music,final` to fix
  flagged lyrics) keeping the rest cached. Stages map to the state-key prefixes above.
- `run --character <run|path>` (+`--run`/`--theme`) — reuse a character across runs to
  build a **series** without re-paying for the Visual Bible + reference images.
- `add-audio`, `stream`, `doctor`, `config` — see README CLI table.

Keep this file and [todo.md](todo.md) current as you change things.
