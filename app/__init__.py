"""ai-genre-pipeline.

A config-driven pipeline that turns a `.env` genre definition into AI-generated
songs and cohesive music videos with consistent characters.

The package is organised around swappable backends:

    app.llm     -> text generation (concept, lyrics, Visual Bible, scenes)
    app.music   -> song generation (Suno third-party / local / prompt-only)
    app.image   -> character reference + scene key-frame images
    app.video   -> scene video clips
    app.assembly-> FFmpeg/moviepy final cut

`app.orchestrator.Orchestrator` wires them together; `app.main` is the CLI.
"""

__version__ = "0.1.0"
