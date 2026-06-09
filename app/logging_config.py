"""Structured logging setup (structlog + rich).

`configure_logging()` is called once from the CLI. Everywhere else you just do:

    from app.logging_config import get_logger
    log = get_logger(__name__)
    log.info("generated_scene", scene=3, backend="kling")
"""

from __future__ import annotations

import logging

import structlog
from rich.logging import RichHandler


def configure_logging(level: str = "INFO", pretty: bool = True) -> None:
    """Wire stdlib logging + structlog.

    pretty=True  -> colourful, human-friendly console output (local dev).
    pretty=False -> JSON lines, ideal for log shipping / containers.
    """
    log_level = getattr(logging, level.upper(), logging.INFO)

    shared_processors: list = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
    ]

    if pretty:
        # Let Rich own the console; structlog renders key/values nicely.
        logging.basicConfig(
            level=log_level,
            format="%(message)s",
            handlers=[RichHandler(rich_tracebacks=True, show_path=False)],
        )
        renderer: structlog.types.Processor = structlog.dev.ConsoleRenderer()
    else:
        logging.basicConfig(level=log_level, format="%(message)s")
        renderer = structlog.processors.JSONRenderer()

    structlog.configure(
        processors=[*shared_processors, renderer],
        wrapper_class=structlog.make_filtering_bound_logger(log_level),
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    return structlog.get_logger(name)
