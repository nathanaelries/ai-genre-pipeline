"""CLI entrypoint (Typer).

    python -m app.main run                 # full pipeline from .env
    python -m app.main run --dry-run       # creative artifacts only (cheap)
    python -m app.main run --force         # ignore saved progress, start fresh
    python -m app.main config              # show the resolved (sanitised) config
    python -m app.main doctor              # check ffmpeg + required API keys
"""

from __future__ import annotations

import shutil
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from app import __version__
from app.config import Settings, get_settings
from app.logging_config import configure_logging, get_logger

app = typer.Typer(
    add_completion=False,
    help="ai-genre-pipeline — turn a .env genre into AI songs + music videos.",
    no_args_is_help=True,
)
console = Console()
log = get_logger("cli")


def _load_settings(env_file: str | None) -> Settings:
    if env_file:
        if not Path(env_file).exists():
            console.print(f"[red]Env file not found:[/red] {env_file}")
            raise typer.Exit(2)
        return Settings(_env_file=env_file)  # type: ignore[call-arg]
    return get_settings()


# Maps each backend choice to the config fields it needs.
_REQUIRED: dict[tuple[str, str], list[str]] = {
    ("llm_provider", "claude"): ["anthropic_api_key"],
    ("llm_provider", "openai"): ["openai_api_key"],
    ("llm_provider", "grok"): ["xai_api_key"],
    ("music_backend", "suno_thirdparty"): ["suno_api_key", "suno_api_base"],
    ("image_backend", "openai"): ["openai_api_key"],
    ("image_backend", "xai"): ["xai_api_key"],
    ("video_backend", "kling"): ["kling_access_key", "kling_secret_key"],
    ("video_backend", "runway"): ["runway_api_key"],
}


@app.command()
def run(
    env_file: str = typer.Option(None, "--env-file", "-e", help="Path to a .env (default: ./.env)."),
    force: bool = typer.Option(False, "--force", "-f", help="Ignore saved progress and start fresh."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Generate creative artifacts only; skip media."),
    stream: bool | None = typer.Option(
        None, "--stream/--no-stream",
        help="Override STREAM_ENABLED for this run.",
    ),
    redo: str = typer.Option(
        None, "--redo",
        help="Regenerate only these comma-separated stages, keeping the rest "
        "cached: concept,music,scenes,images,videos,final,bible,refs. "
        "E.g. --redo concept,music,final to rewrite lyrics without redoing images.",
    ),
    run_name: str = typer.Option(
        None, "--run", help="Override RUN_NAME (the output folder) for this run."
    ),
    theme: str = typer.Option(
        None, "--theme", help="Override THEME for this run (e.g. a new verse)."
    ),
    character: str = typer.Option(
        None, "--character",
        help="Reuse an existing character: a prior run name or path to its "
        "02_character_bible. Skips regenerating the Visual Bible + reference images.",
    ),
) -> None:
    """Run the full generation pipeline (optionally live-streaming as it goes)."""
    cfg = _load_settings(env_file)
    configure_logging(cfg.log_level, cfg.log_pretty)

    # Per-invocation overrides — handy for spinning up the next video in a series
    # (new verse + folder) that reuses the same character.
    if run_name:
        cfg.run_name = run_name
    if theme:
        cfg.theme = theme
    if character:
        cfg.character_dir = character

    # Import here so `config`/`doctor` work even if a heavy dep is missing.
    from app.config import StreamMode
    from app.orchestrator import Orchestrator

    orch = Orchestrator(cfg)

    # Targeted regeneration: clear just the requested stages before running.
    if redo:
        stages = [s.strip() for s in redo.split(",") if s.strip()]
        try:
            cleared = orch.invalidate(stages)
        except ValueError as exc:
            console.print(f"[red]{exc}[/red]")
            raise typer.Exit(2)
        console.print(f"[yellow]Redo:[/yellow] cleared {cleared} cached step(s) for: {', '.join(stages)}")

    streaming = (cfg.stream_enabled if stream is None else stream) and not dry_run
    stream_mgr = _build_stream_manager(cfg, orch.paths) if streaming else None
    streaming = stream_mgr is not None  # may have been disabled (no targets)

    # In `live` mode we start the broadcaster up-front (standby plays until the
    # first clip lands) and enqueue each track the moment it finishes.
    hook = None
    if stream_mgr and cfg.stream_mode is StreamMode.live:
        stream_mgr.start(with_standby=True)
        hook = stream_mgr.add_video

    try:
        manifest = orch.run(force=force, dry_run=dry_run, on_track_complete=hook)
    except Exception as exc:  # noqa: BLE001 - surface a clean message to the user
        if stream_mgr:
            stream_mgr.stop()
        log.error("run_failed", error=str(exc))
        console.print(f"\n[red bold]Run failed:[/red bold] {exc}")
        raise typer.Exit(1)

    finals = [t.final_video_path for t in manifest.tracks if t.final_video_path]
    console.print("\n[green bold]Done.[/green bold]")
    console.print(f"Run folder: [cyan]{cfg.output_dir / cfg.slug}[/cyan]")
    if finals:
        console.print("Final videos:")
        for f in finals:
            console.print(f"  • {f}")
    elif dry_run:
        console.print("Dry run complete — see 01_lyrics_and_concept/ and 02_character_bible/.")

    # Hand off to the live stream and block until the operator stops it.
    if stream_mgr:
        abs_finals = [orch.paths.root / f for f in finals]
        if cfg.stream_mode is StreamMode.after:
            if not abs_finals:
                console.print("[yellow]Nothing to stream.[/yellow]")
                return
            stream_mgr.start(with_standby=False)
            stream_mgr.add_existing(abs_finals)
        _serve_stream(stream_mgr)


def _build_stream_manager(cfg, paths):
    """Construct a StreamManager, or warn + return None if it can't stream."""
    from app.streaming import StreamManager
    from app.streaming.manager import StreamError

    try:
        return StreamManager(cfg, paths)
    except StreamError as exc:
        console.print(f"[yellow]Streaming disabled:[/yellow] {exc}")
        return None


def _serve_stream(stream_mgr) -> None:
    platforms = ", ".join(t.platform.value for t in stream_mgr.targets)
    console.print(f"\n[magenta bold]● LIVE[/magenta bold] streaming to: {platforms}")
    console.print("[dim]Looping the library so it never stops. Press Ctrl-C to end.[/dim]")
    try:
        stream_mgr.wait()
    finally:
        stream_mgr.stop()
        console.print("\n[green]Stream stopped.[/green]")


@app.command()
def config(
    env_file: str = typer.Option(None, "--env-file", "-e", help="Path to a .env (default: ./.env)."),
) -> None:
    """Print the resolved configuration (secrets masked)."""
    cfg = _load_settings(env_file)
    table = Table(title="Resolved configuration", show_lines=False)
    table.add_column("Setting", style="cyan", no_wrap=True)
    table.add_column("Value", style="white")

    secret_like = ("key", "secret", "token")
    for name, value in cfg.model_dump(mode="json").items():
        shown = value
        if any(s in name for s in secret_like) and value:
            shown = "•" * 8 + " (set)"
        elif any(s in name for s in secret_like):
            shown = "[dim](unset)[/dim]"
        table.add_row(name, str(shown))
    console.print(table)
    console.print(f"\nRun folder would be: [cyan]{cfg.output_dir / cfg.slug}[/cyan]")


@app.command()
def doctor(
    env_file: str = typer.Option(None, "--env-file", "-e", help="Path to a .env (default: ./.env)."),
) -> None:
    """Check ffmpeg availability and that selected backends have their keys."""
    cfg = _load_settings(env_file)
    ok = True

    # 1. ffmpeg / ffprobe
    for tool in ("ffmpeg", "ffprobe"):
        if shutil.which(tool):
            console.print(f"[green]✓[/green] {tool} found")
        else:
            ok = False
            console.print(f"[red]✗[/red] {tool} NOT found on PATH (required for assembly)")

    # 2. backend keys
    selections = {
        "llm_provider": cfg.llm_provider.value,
        "music_backend": cfg.music_backend.value,
        "image_backend": cfg.image_backend.value,
        "video_backend": cfg.video_backend.value,
    }
    for field, choice in selections.items():
        needed = _REQUIRED.get((field, choice), [])
        missing = [n for n in needed if not str(getattr(cfg, n, "")).strip()]
        label = f"{field}={choice}"
        if missing:
            ok = False
            console.print(f"[red]✗[/red] {label} missing: {', '.join(m.upper() for m in missing)}")
        else:
            console.print(f"[green]✓[/green] {label} configured")

    if cfg.video_backend.value == "comfyui" and not cfg.comfyui_video_workflow.strip():
        console.print("[yellow]![/yellow] VIDEO_BACKEND=comfyui needs COMFYUI_VIDEO_WORKFLOW set")

    # 3. live streaming
    if cfg.stream_enabled:
        selected = cfg.stream_targets
        usable = [p for p in selected if cfg.stream_url_for(p)]
        if usable:
            console.print(
                f"[green]✓[/green] streaming -> {', '.join(p.value for p in usable)} "
                f"(mode={cfg.stream_mode.value})"
            )
            for p in selected:
                if p not in usable:
                    console.print(f"[yellow]![/yellow] stream target '{p.value}' selected but has no key/URL")
        else:
            ok = False
            console.print("[red]✗[/red] STREAM_ENABLED but no platform has a key/URL set")

    console.print(
        "\n[green bold]All checks passed.[/green bold]" if ok
        else "\n[red bold]Some checks failed — see above.[/red bold]"
    )
    raise typer.Exit(0 if ok else 1)


@app.command("add-audio")
def add_audio(
    file: str = typer.Argument(
        ...,
        help="Audio file to ingest (a path the CONTAINER can see — e.g. "
        "inbox/track_01.mp3 when you drop it in the ./inbox folder).",
    ),
    env_file: str = typer.Option(None, "--env-file", "-e", help="Path to a .env (default: ./.env)."),
    run_name: str = typer.Option(None, "--run", help="Target run folder (default: from .env)."),
    track: int = typer.Option(1, "--track", help="Track number (1-based)."),
    reassemble: bool = typer.Option(
        True, "--reassemble/--no-reassemble",
        help="Re-mux the final video now (default), or just place the file.",
    ),
) -> None:
    """Add a downloaded song (e.g. a Suno render) to a run and re-mux the video.

    Drops the file into the run's 03_music/ as track_NN.<ext> and re-assembles
    that track's final video with the audio + lyric overlay. Everything else
    (concept, scenes, images, clips) stays cached.
    """
    import shutil as _shutil

    cfg = _load_settings(env_file)
    configure_logging(cfg.log_level, cfg.log_pretty)
    if run_name:
        cfg.run_name = run_name

    src = Path(file)
    # `exists()` re-raises EACCES (it only swallows not-found errors), so guard it:
    # the container runs as uid 1000 and may not be able to read a host file that
    # was created root-owned or with restrictive permissions.
    try:
        present = src.exists()
    except OSError as exc:
        console.print(
            f"[red]Can't access[/red] {file}: {exc}\n"
            f"[yellow]Hint:[/yellow] the container runs as uid 1000. Make it readable "
            f"on the host, e.g. [cyan]chmod -R a+rX inbox[/cyan], then retry."
        )
        raise typer.Exit(1)
    if not present:
        console.print(f"[red]Audio file not found:[/red] {file}")
        raise typer.Exit(1)

    from app.orchestrator import _AUDIO_EXTS, Orchestrator

    if src.suffix.lower() not in _AUDIO_EXTS:
        console.print(
            f"[yellow]Note:[/yellow] '{src.suffix}' isn't a typical audio extension "
            f"({', '.join(_AUDIO_EXTS)}); proceeding anyway."
        )

    orch = Orchestrator(cfg)
    # add-audio only makes sense for a run that has ALREADY been generated — it
    # re-muxes audio into an existing video. Guard against an empty/fresh run
    # folder (e.g. a brand-new or wrong outputs volume), which would otherwise
    # fall through to a full, paid, different-character regeneration.
    t0 = track - 1
    generated = orch.state.is_done(f"final:{t0}") or orch.state.is_done(f"video:{t0}:0")
    if not generated:
        console.print(
            f"[red]Run '{orch.paths.root.name}' (track {track}) has no generated video to "
            f"add audio to.[/red]\n"
            f"[yellow]Likely cause:[/yellow] you're pointing at an empty/wrong outputs volume "
            f"(a freshly-created volume looks like this). Generate it first with `run`, or "
            f"check your docker-compose volume mount. Refusing to regenerate from scratch."
        )
        raise typer.Exit(1)

    dest = orch.paths.music / f"track_{track:02d}{src.suffix.lower()}"
    try:
        _shutil.copy2(src, dest)
    except OSError as exc:
        console.print(
            f"[red]Could not copy the audio file:[/red] {exc}\n"
            f"[yellow]Hint:[/yellow] make it readable by the container (uid 1000), "
            f"e.g. [cyan]chmod -R a+rX inbox[/cyan], then retry."
        )
        raise typer.Exit(1)
    console.print(f"Added audio → [cyan]{orch.paths.rel(dest)}[/cyan]")

    if not reassemble:
        console.print("Now run: [cyan]run --redo final[/cyan] to mux it into the video.")
        return

    # Clear only this track's final checkpoint, then re-assemble (all else cached).
    orch.state.clear(lambda k: k == f"final:{track - 1}")
    console.print("Re-assembling the final video with your audio…")
    try:
        manifest = orch.run()
    except Exception as exc:  # noqa: BLE001
        console.print(f"\n[red bold]Re-assembly failed:[/red bold] {exc}")
        raise typer.Exit(1)

    finals = [t.final_video_path for t in manifest.tracks if t.final_video_path]
    console.print("\n[green bold]Done.[/green bold]")
    for f in finals:
        console.print(f"  • {f}")


@app.command()
def stream(
    env_file: str = typer.Option(None, "--env-file", "-e", help="Path to a .env (default: ./.env)."),
    run_name: str = typer.Option(None, "--run", help="Stream a run folder by name (under OUTPUT_DIR)."),
    directory: str = typer.Option(None, "--dir", help="Stream every *.mp4 in this folder."),
) -> None:
    """Live-stream an already-generated library (no generation).

    Loops the videos forever so the channel never goes dark. With no --run/--dir
    it streams the run folder implied by the current .env.
    """
    cfg = _load_settings(env_file)
    configure_logging(cfg.log_level, cfg.log_pretty)

    from app.streaming import StreamManager
    from app.streaming.manager import StreamError
    from app.utils import RunPaths

    if directory:
        root = Path(directory)
        videos = sorted(root.glob("*.mp4"))
    else:
        root = cfg.output_dir / (run_name or cfg.slug)
        videos = sorted((root / "05_final_videos").glob("*.mp4"))

    if not videos:
        console.print(f"[red]No .mp4 videos found to stream[/red] (looked in {root}).")
        raise typer.Exit(1)

    try:
        mgr = StreamManager(cfg, RunPaths(root).ensure())
    except StreamError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1)

    console.print(f"Streaming [cyan]{len(videos)}[/cyan] video(s) from [cyan]{root}[/cyan].")
    mgr.start(with_standby=False)
    mgr.add_existing(videos)
    _serve_stream(mgr)


@app.command()
def version() -> None:
    """Print the pipeline version."""
    console.print(f"ai-genre-pipeline {__version__}")


if __name__ == "__main__":
    app()
