# ai-genre-pipeline

Turn a single `.env` file into an AI-generated **song + cohesive music video** with a
**consistent character** across every scene — in the style of ambient/cinematic music
channels (FeelTheDeepLiveTheCalm / Thungdor).

Spinning up a brand-new genre is the #1 design goal: **copy an `.env`, edit the creative
block, run.** No code changes.

```
.env  ─▶  LLM (concept · lyrics · Visual Bible · scenes)
      ─▶  reference images  ─▶  per-scene key-frames  ─▶  video clips
      ─▶  music (Suno brief / API / local)
      ─▶  FFmpeg final cut (timed, audio-synced, optional lyric overlay)
      ─▶  (optional) 24/7 live stream to YouTube / TikTok / Facebook / Rumble
```

---

## Why this produces *consistent* characters

Consistency is engineered, not hoped for:

1. **Visual Bible** — generated once per run, it locks a single, physically-specific
   `character_description`, color palette, lighting and negative prompts.
2. **That exact description is injected into every image and video prompt** verbatim.
3. **Character reference images** are generated once and (with the ComfyUI backend +
   an IP-Adapter workflow) fed into every scene to lock face/wardrobe.
4. **Image-to-video**: the video stage animates the scene *still* (which already encodes
   the character) instead of generating from scratch — the model only adds motion.
5. **Deterministic seeds** keep results stable across re-runs.

---

## Quick start (Docker — recommended)

```bash
# 1. Pick a genre and create your .env
cp .env.example .env            # deep house / ocean
#   or: cp .env.cyberpunk.example .env
#   or: cp .env.country-trance.example .env

# 2. Put your API keys in .env (only for the backends you enabled)

# 3. Sanity-check config + ffmpeg + keys
docker compose run --rm orchestrator doctor

# 4. Generate everything
docker compose run --rm orchestrator run
```

Every run's output is written to a **persistent Docker data volume** (`agp_outputs`),
so generated content survives `docker compose down`, image rebuilds, and container
recreation — see [Persisting & retrieving content](#persisting--retrieving-generated-content).

### Updating after a `git pull` (rebuild the image!)

The image bakes `app/` in at build time, so **pulling new code does not change what
the container runs until you rebuild**:

```bash
git pull
docker compose build                       # <-- required after code changes
docker compose run --rm orchestrator run
# (or do both at once:)  docker compose run --build orchestrator run
```

Tip for a "pull and run" homelab setup: uncomment `- ./app:/app/app:ro` in
[docker-compose.yml](docker-compose.yml) to mount the source, so future pulls take effect
without rebuilding (you still rebuild when `requirements.txt` changes).

### With local ComfyUI (highest consistency, needs an NVIDIA GPU)

```bash
# set IMAGE_BACKEND=comfyui (and/or VIDEO_BACKEND=comfyui) + COMFYUI_URL in .env
docker compose --profile local up -d comfyui
docker compose run --rm orchestrator run
```

## Quick start (local Python)

```bash
python -m venv .venv && source .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -r requirements.txt
# Requires ffmpeg + ffprobe on PATH (https://ffmpeg.org/download.html)

cp .env.example .env            # then edit
python -m app.main doctor
python -m app.main run
```

---

## CLI

| Command | What it does |
|---|---|
| `run` | Run the full pipeline from `.env`. |
| `run --dry-run` | Generate only the **creative** artifacts (Visual Bible, lyrics, scene list). Cheap; great for tuning prompts. |
| `run --force` | Ignore saved progress and regenerate from scratch. |
| `run --redo <stages>` | Regenerate only certain stages, keeping the rest cached (see below). |
| `run --character <run>` | Reuse an existing character (Visual Bible + refs) for a new video. `--run`/`--theme` set the new folder + verse. |
| `run --stream` / `--no-stream` | Force live streaming on/off for this run (overrides `STREAM_ENABLED`). |
| `run -e path/to/.env` | Use an alternate env file. |
| `add-audio <file>` | Add a downloaded song (e.g. a Suno render) to a run and re-mux the final video. `--run`, `--track`. |
| `stream` | Live-stream an already-generated library on a loop (no generation). `--run <name>` or `--dir <folder>`. |
| `config` | Print the resolved configuration (secrets masked). |
| `doctor` | Verify `ffmpeg`/`ffprobe` are present and the selected backends + stream targets are configured. |
| `version` | Print the version. |

Runs are **resumable**: progress is saved to `state.json` after every expensive step, so
re-running continues where it stopped. Use `--force` to start over.

### Regenerating a single stage (`--redo`)

Sometimes you want to redo *one* step without paying to regenerate everything — the classic
case is **a music service flagging your lyrics as copyrighted** and needing fresh lyrics while
keeping all the (expensive) images and video clips you already made.

```bash
# Rewrite the lyrics + Suno brief and re-burn the lyric overlay, keep all visuals:
docker compose run --rm orchestrator run --redo concept,music,final
```

Valid stages: `bible`, `refs`, `concept` (lyrics), `scenes`, `images`, `videos`,
`music` (audio + Suno brief), `final` (assembly + lyric overlay). Each clears only its own
cached checkpoints; the next `run` regenerates exactly those and reuses the rest.

> **Lyrics & copyright:** the songwriting prompt instructs the LLM to write *original* lyrics
> and never reproduce a copyrighted translation/text verbatim (e.g. NIV/ESV), so output clears
> automated filters like Suno's. If a song still gets flagged, `--redo concept,music,final`
> regenerates it with fresh wording.

### Making a series — reuse one character across videos

To build a channel of videos that all star the **same character** (e.g. one narrator across
many psalms), generate the character once, then point every new video at it. The Visual Bible
and reference images are imported and marked cached, so each new run only pays for the
verse-specific stages (concept, scenes, scene images, video, final) — **not** the character.

```bash
# First video establishes the character (full run):
docker compose run --rm orchestrator run            # -> outputs/scripture-meditations/

# Next video: new folder + new verse, SAME character (no bible/ref regen):
docker compose run --rm orchestrator run \
    --run psalm-91-refuge \
    --theme "Psalm 91 — dwelling in the shelter of the Most High" \
    --character scripture-meditations
```

`--character` takes a prior run name (under `OUTPUT_DIR`) or a path to its
`02_character_bible/` folder; the equivalent `.env` setting is `CHARACTER_DIR`. New scene
images are still generated — they're fresh shots **of the same character**, kept on-model by
the imported reference images. Because each video is its own run folder, the previous ones are
never overwritten, so they all stack up as a library (ready for the 24/7 stream).

**Batching a whole series** — list your verses (`cp verses.example.txt verses.txt`, then edit
`<run-name> | <theme>` per line) and use the bash helpers. A plain loop is the right tool here:
the pipeline is deterministic, so there's nothing for an LLM agent to decide.

```bash
sudo bash scripts/batch-generate.sh           # generate every verse's silent video + Suno brief
# ...render each Suno brief, drop the mp3 at outputs/<run>/03_music/track_01.mp3...
sudo bash scripts/batch-finish.sh             # mux audio into every verse that has a song
```

Both scripts are re-runnable and skip finished work. The Suno render in the middle is manual
with `prompt_only`; switch `MUSIC_BACKEND=suno_thirdparty` (+ a relay key) to make it a single
unattended loop end-to-end.

### Adding your Suno song

With `MUSIC_BACKEND=prompt_only`, the pipeline writes a paste-ready brief to
`03_music/track_NN_suno_prompt.txt` and produces a **silent** video. Once you've rendered the
song in Suno and downloaded the `.mp3`/`.wav`, feed it back in:

```bash
# Drop the download into ./inbox on the host (it's mounted into the container),
# then ingest + re-mux the final video in one command:
docker compose run --rm orchestrator add-audio inbox/my-song.mp3 --run scripture-meditations --track 1
```

`add-audio` copies the file into the run as `03_music/track_NN.<ext>` and re-assembles **only**
that track's final video (audio muxed in with fades + the lyric overlay) — everything else stays
cached. Multi-track run? Use `--track 2`, etc.

> **Permission denied?** The container runs as uid 1000, so a file dropped in `./inbox` must be
> readable by it. On an **SELinux** host (openSUSE/Fedora/RHEL — check with `getenforce`), the
> compose file already tags the mount `:z` to relabel it; if you still hit it, run
> `sudo chcon -Rt container_file_t inbox`. On non-SELinux hosts a plain
> `sudo chmod -R a+rX inbox` is enough.

Prefer to place the file yourself? Put it at `03_music/track_01.mp3` (or `.wav`) and run
`run --redo final`; the assembler auto-detects `track_NN.<ext>` and muxes it. (Your `03_music/`
lives in the `agp_outputs` volume, which is why the `./inbox` drop-folder + `add-audio` is the
easy path — no digging into the volume.)

---

## Configuration (`.env`)

Everything lives in `.env`. The creative block is all you change between genres:

| Variable | Purpose |
|---|---|
| `GENRE`, `SUB_STYLE`, `THEME`, `MOOD` | The creative brief. |
| `CHARACTER_DESCRIPTION` | **The consistency anchor.** Be physically specific. |
| `STYLE_GUIDE` | Global art direction applied to every shot. |
| `NUM_TRACKS`, `SCENES_PER_TRACK`, `SECONDS_PER_SCENE` | How much to make. |
| `RESOLUTION`, `FPS`, `ASPECT` | Output geometry (`ASPECT` preset overrides `RESOLUTION`). |
| `LLM_PROVIDER` | `claude` \| `openai` \| `grok` |
| `MUSIC_BACKEND` | `suno_thirdparty` \| `local` \| `prompt_only` |
| `IMAGE_BACKEND` | `openai` \| `xai` \| `comfyui` |
| `VIDEO_BACKEND` | `kling` \| `runway` \| `comfyui` |
| `LYRICS_OVERLAY`, `LIPSYNC` | Final-cut extras. |
| `*_API_KEY`, `COMFYUI_URL`, ... | Credentials / endpoints. |
| `SEED`, `OUTPUT_DIR`, `RUN_NAME`, `LOG_LEVEL`, `LOG_PRETTY` | Runtime. |

See [.env.example](.env.example) for the fully-commented reference.

### Backend notes / honest limitations

- **Suno has no official public API.** `MUSIC_BACKEND=prompt_only` (the default) writes
  perfect lyrics + a paste-ready Suno brief to `03_music/` — you render in the Suno web UI,
  then [add the downloaded song](#adding-your-suno-song) and re-assemble. `suno_thirdparty`
  targets common relay providers (sunoapi.org / EvoLink / 302.ai); endpoint paths are
  centralised in [app/music/suno_thirdparty.py](app/music/suno_thirdparty.py) for easy adaptation.
- **No video backend configured / a scene fails?** The pipeline never dies — it falls back
  to an animated **Ken-Burns** clip of the scene still, so a run always produces a complete,
  correctly-timed video.
- **`MUSIC_BACKEND=local`** ships a correctly-timed *silent* bed so fully-offline runs still
  assemble; swap in your own local model in [app/music/local.py](app/music/local.py).
- **ComfyUI video** requires you to export an API-format workflow and set
  `COMFYUI_VIDEO_WORKFLOW` (video graphs are model-specific). Placeholder tokens
  (`%PROMPT%`, `%REF_IMAGE%`, `%SEED%`, `%FRAMES%`, ...) are substituted at runtime.

---

## Provider guide — which services to sign up for

> **Create your own first-party accounts** directly with each provider below and load
> credits/subscriptions onto them. **Do not buy pre-made, "aged", or resold accounts** —
> for the streaming platforms in particular, account reselling violates their Terms of
> Service and risks permanent bans and payment-fraud chargebacks; for the AI APIs, shared
> or resold keys get revoked and leak your billing. First-party accounts are cheaper,
> safer, and the only ones these APIs are designed for.

You only need accounts for the backends you actually enable in `.env`. Each stage maps to
one engine. Pricing models below are the *shape* of the cost (pay-as-you-go credits vs flat
subscription) — always check the provider's current pricing page, as rates change.

### 1. Text / LLM — concept, lyrics, Visual Bible, scenes  *(cheapest stage — pennies/run)*

| Provider | Where to sign up | Billing model | Pick it when |
|---|---|---|---|
| **Anthropic Claude** *(default)* | console.anthropic.com | Pre-paid API credits, pay-as-you-go | You want the richest creative writing + reliable structured JSON. |
| **OpenAI** | platform.openai.com | Pre-paid API credits | You also want images from the same account/key (`IMAGE_BACKEND=openai`). |
| **xAI Grok** | console.x.ai | Pre-paid API credits | You're already in the X/Grok ecosystem. |

A whole run's text is a few cents — don't optimize here. Create an account, add a small
credit balance, generate an **API key**, paste into `.env`. **Recommended:** Claude or OpenAI.

### 2. Music — song + lyrics

| Option | Where | Billing | Notes |
|---|---|---|---|
| **Suno subscription** *(recommended)* | suno.com | Monthly (Pro/Premier) | Gives commercial-use rights + downloads. Use `MUSIC_BACKEND=prompt_only`: the pipeline writes the brief, you paste it into Suno, drop the audio back in. Most reliable + clean rights. |
| **Third-party Suno relay** | sunoapi.org, 302.AI, EvoLink | Per-credit API key | Enables full automation (`MUSIC_BACKEND=suno_thirdparty`), but it's **unofficial**, ToS-gray, and can break without notice. Check the relay's licensing before commercial use. |
| **Local model** | self-host | Free (your GPU) | `MUSIC_BACKEND=local` is a silent placeholder today; wire in MusicGen/AudioCraft yourself. |

**Recommended:** a Suno subscription + `prompt_only` for rights clarity and reliability;
only use a relay if hands-off automation is worth the fragility.

### 3. Images — character references + scene key-frames

| Option | Where | Billing | Notes |
|---|---|---|---|
| **OpenAI images** | platform.openai.com | Per-image credits | Easiest cloud path; same key as the LLM. Good consistency via the locked character prompt. |
| **xAI / Grok images** | console.x.ai | Per-image credits | `IMAGE_BACKEND=xai` (model `grok-2-image`). Lets a fully Grok pipeline run on **only `XAI_API_KEY`** — no OpenAI account needed. |
| **ComfyUI (local)** *(best consistency)* | github.com/comfyanonymous/ComfyUI | Free software + a GPU | IP-Adapter/ControlNet give true face/wardrobe locking and the lowest per-image cost at volume. Needs an NVIDIA GPU (≥12–16 GB VRAM; RTX 3090/4090 ideal) **or** a rented cloud GPU (below). |

**Recommended:** start on OpenAI (or xAI if you're already all-in on Grok) for simplicity;
move to ComfyUI once you care about tight character consistency or are generating at volume.

### 4. Video — scene clips  *(by far the most expensive stage — budget here)*

| Option | Where | Billing | Notes |
|---|---|---|---|
| **Runway** | runwayml.com → dev.runwayml.com | Subscription + API credits | Easiest **official** image-to-video API (Gen-3/Gen-4). Most reliable to automate. |
| **Kling** | klingai.com (API via the Kling/Kuaishou open platform) | Credit packs | Strong, cost-effective image-to-video; API access may require an application. |
| **ComfyUI (local)** | self-host (SVD / AnimateDiff / WAN) | Free software + GPU | Cheapest at scale; needs a capable GPU and a workflow you export yourself. |
| **None / free** | — | $0 | Leave video unset and rely on the **Ken-Burns** still-motion fallback — perfectly fine for calm ambient channels. |

**Recommended:** Runway for the smoothest official API; Kling to cut cost; ComfyUI if you
have the GPU and want volume. Generate short test clips first — video credits burn fast.

### 5. GPU rental (only if you self-host ComfyUI without your own card)

Rent by the hour and point `COMFYUI_URL` at it: **RunPod** (runpod.io), **Vast.ai**
(vast.ai), or **Lambda** (lambdalabs.com). Cheaper than a cloud API once you're producing
a lot, but you manage the box.

### 6. Streaming platforms (free accounts — but each has eligibility rules)

All are **free to create** — you're not buying anything, just enabling live + grabbing a
stream key. Use your own account; see the warning at the top of this section.

| Platform | Get the RTMP key from | Gotchas |
|---|---|---|
| **YouTube Live** | YouTube Studio → Go Live | Verify your account; first-time live enable can take ~24 h. Monetization needs YPP thresholds. |
| **Facebook / Instagram** | Facebook Live Producer (a Page) | Instagram Live uses the same Facebook Live API ingest. |
| **TikTok Live** | TikTok LIVE Studio | Needs LIVE access (often ~1,000 followers) before you get an RTMP key. |
| **Rumble** | Rumble → stream settings | Copy the full RTMP URL (+ key) it shows you. |

### Recommended starter stacks

| Goal | LLM | Music | Image | Video | ~Monthly cost shape |
|---|---|---|---|---|---|
| **Cheapest, clean rights** | Claude (PAYG) | Suno sub + `prompt_only` | OpenAI | Ken-Burns fallback ($0) | Suno sub + a few $ of API credits |
| **Balanced cloud** | OpenAI | Suno sub | OpenAI | Runway | Subs + moderate video credits |
| **Max quality / volume** | Claude | Suno sub | ComfyUI (owned/rented GPU) | Kling or ComfyUI | GPU + video credits |

**Budget reality:** text ≈ pennies, music ≈ a flat subscription, images ≈ cheap, **video
dominates** — a single multi-scene track can cost more in video credits than everything
else combined. Prototype with `--dry-run` (creative only, no media spend) and the free
Ken-Burns fallback before turning on a paid video backend.

---

## Live streaming (24/7, never stops)

Push generated videos to **YouTube Live, TikTok Live, Facebook/Instagram Live, and Rumble**
— all at once — as a single continuous stream that loops the library so the channel
never goes dark.

```bash
# 1. In .env: enable streaming + paste at least one platform key
STREAM_ENABLED=true
STREAM_TARGETS="youtube,facebook,rumble"
YOUTUBE_STREAM_KEY="xxxx-xxxx-xxxx-xxxx"
# FACEBOOK_STREAM_KEY=... / TIKTOK_INGEST_URL=... / RUMBLE_INGEST_URL=...

docker compose run --rm orchestrator doctor      # confirm targets resolve
docker compose run --rm orchestrator run         # generate + go live

# Or stream a library you already generated, on a loop:
docker compose run --rm orchestrator stream --run <run-folder-name>
docker compose run --rm orchestrator stream --dir ./outputs/<run>/05_final_videos
```

**Modes** (`STREAM_MODE`):
- `live` — the stream starts immediately (a standby card plays), and each track joins the
  stream the instant it finishes generating. Best for "generate forever" channels.
- `after` — generate the whole library first, then stream it on an endless loop.

**How it stays seamless and never stops:**
- Every finished video is transcoded once into an **MPEG-TS segment** with identical codec
  params (resolution, fps, GOP, 44.1 kHz audio).
- A **single persistent ffmpeg encoder** consumes those segments from a pipe (`-re` paces it
  in realtime), producing one clean continuous timeline, and **fans out to every platform
  simultaneously** via the `tee` muxer (`onfail=ignore` — one platform dropping doesn't take
  down the others).
- A feeder thread keeps the encoder fed; when the queue is empty it **re-loops the existing
  library** (`STREAM_LOOP_WHEN_IDLE=true`), so the wire is never starved. If the encoder
  hiccups it is automatically respawned.

**Platform reality check:**
- **YouTube** & **Facebook/Instagram** have stable RTMP/RTMPS ingest — paste the stream key
  and go. (Instagram uses the same Facebook Live API ingest.)
- **TikTok** requires LIVE access / TikTok Live Studio; when granted it gives you an RTMP
  server URL + key — put them in `TIKTOK_INGEST_URL` / `TIKTOK_STREAM_KEY`.
- **Rumble** gives a full RTMP URL (and key) in your stream settings — paste into
  `RUMBLE_INGEST_URL` / `RUMBLE_STREAM_KEY`.
- `custom` accepts any RTMP/RTMPS endpoint (Twitch, a self-hosted nginx-rtmp relay, etc.).

`ffmpeg` push output is logged to `<run>/logs/stream.log`. Stop a stream with `Ctrl-C`.

---

## Output structure (per run)

```
outputs/<run-name>/
├── 01_lyrics_and_concept/      # song concept + lyrics + timed scene list (JSON)
├── 02_character_bible/
│   ├── bible.json              # the consistency contract
│   └── reference_images/       # character reference set
├── 03_music/                   # lyrics + Suno brief (+ audio if generated)
├── 04_scenes/                  # per-scene key-frames + raw/normalised clips
├── 05_final_videos/            # the finished music video(s) + .srt
├── 06_stream/segments/         # MPEG-TS segments fed to the live stream
├── logs/                       # incl. stream.log (ffmpeg push output)
├── manifest.json               # full machine-readable record of the run
└── state.json                  # resume checkpoints
```

---

## Persisting & retrieving generated content

All output is stored in a **named Docker volume, `agp_outputs`** (mounted at
`/app/outputs` in the container), declared in [docker-compose.yml](docker-compose.yml).
It is managed by Docker and **persists across `docker compose down`, image rebuilds, and
container recreation** — it is only deleted by an explicit `docker compose down -v` or
`docker volume rm`. (The Dockerfile pre-creates the mount point owned by the non-root
runtime user, so the volume is writable on first run.)

```bash
# Inspect the volume (real name is <project>_agp_outputs)
docker volume ls
docker volume inspect ai-genre-pipeline_agp_outputs

# Copy everything out to ./exported on the host
docker run --rm \
  -v ai-genre-pipeline_agp_outputs:/data \
  -v "$(pwd)/exported:/out" \
  alpine sh -c "cp -a /data/. /out/"

# Back up the whole volume to a tarball
docker run --rm -v ai-genre-pipeline_agp_outputs:/data -v "$(pwd):/backup" \
  alpine tar czf /backup/outputs-backup.tgz -C /data .
```

**Pin it to a specific disk** (e.g. a large drive on a homelab box): uncomment the
`driver_opts` block under `volumes: agp_outputs:` in `docker-compose.yml` and set
`device: /srv/ai-genre-pipeline/outputs`.

**Prefer files directly on the host** (handiest for grabbing finished videos to upload):
swap the volume for a bind mount — comment `- agp_outputs:/app/outputs` and uncomment
`- ./outputs:/app/outputs` in the `orchestrator` service. On Linux, make the host folder
writable by the container user (uid 1000), e.g. `mkdir -p outputs && sudo chown 1000:1000 outputs`.

> Running the pipeline **without Docker** (local Python) already writes straight to
> `./outputs/` on your machine, so nothing extra is needed there.

---

## Architecture

```
app/
├── main.py            # Typer CLI (run / config / doctor / version)
├── orchestrator.py    # the brain — drives every stage, handles resume
├── config.py          # pydantic-settings: the whole .env, typed + validated
├── models.py          # SongConcept · VisualBible · Scene · Track · RunManifest
├── prompts.py         # LLM prompt templates (concept, bible, scenes, refs)
├── state.py           # progress checkpoints (resume)
├── utils.py           # run-folder layout, JSON/HTTP helpers, retry policy
├── comfyui_client.py  # shared ComfyUI HTTP client
├── llm/               # LLMProviderBase  -> claude · openai · grok
├── music/             # MusicBackendBase -> suno_thirdparty · local · prompt_only
├── image/             # ImageBackendBase -> openai · comfyui
├── video/             # VideoBackendBase -> kling · runway · comfyui
├── assembly/          # FFmpeg final cut (normalise · concat · audio · subtitles)
└── streaming/         # RTMP/RTMPS live streaming (seamless, multi-platform)
```

Each media stage is an **abstract backend + a factory** that reads the `.env` choice.
All backends use a shared `httpx` retry policy (exponential backoff on 5xx/429/network).

---

## Extending the pipeline

### Add a new video provider (e.g. Pika)

1. Create `app/video/pika.py` subclassing `VideoBackendBase` and implement
   `generate(prompt, dest, *, image_path, duration, seed) -> Path`.
2. Add `pika = "pika"` to `VideoBackendKind` in [app/config.py](app/config.py).
3. Wire it into [app/video/factory.py](app/video/factory.py).
4. Add any keys to `Settings` + `.env.example`. Done — select with `VIDEO_BACKEND=pika`.

The same three-step pattern (subclass → enum → factory) adds an LLM, music, or image
provider. Because consistency data flows through the shared models, a new backend
automatically receives the character description, references, and seeds.

### Add a new genre

Copy any `.env.*.example`, edit the creative block (`GENRE` … `CHARACTER_DESCRIPTION` …
`STYLE_GUIDE`), and run. That's the whole workflow.

---

## Roadmap / optional extras

- **Lip-sync** (`LIPSYNC=true`) is wired as a flag; plug a Wav2Lip / LatentSync ComfyUI
  workflow into the video stage to enable it.
- Word-level lyric timing via forced alignment (currently an even split).
- Beat-synced scene cuts driven by audio onset detection.
