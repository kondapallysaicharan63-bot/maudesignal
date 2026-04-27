"""Structured logging for MaudeSignal.

Per NFR-08 (Doc 3 §4.3): logs contain no API keys, no PHI, and no full
narrative text. Use structlog for consistent, structured JSON output.
"""

from __future__ import annotations

import logging
import sys

import structlog
from structlog.types import Processor


def configure_logging(level: str = "INFO") -> None:
    """Configure structlog to produce JSON logs to stderr.

    Call once at program start (e.g., in the CLI entry point).

    Args:
        level: Python logging level name (DEBUG, INFO, WARNING, ERROR, CRITICAL).
    """
    level_int = getattr(logging, level.upper(), logging.INFO)

    # Shared processors run for both structlog and stdlib-logging calls
    shared_processors: list[Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]

    structlog.configure(
        processors=[
            *shared_processors,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(level_int),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(file=sys.stderr),
        cache_logger_on_first_use=True,
    )

    # Also bring stdlib logging into line so library-emitted logs render nicely
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stderr,
        level=level_int,
    )


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    """Return a configured structlog logger for the given module.

    Args:
        name: Typically ``__name__`` of the calling module.

    Returns:
        A structlog BoundLogger. Call ``.info()``, ``.warning()``, etc.,
        passing key=value pairs for structured fields.
    """
    logger: structlog.stdlib.BoundLogger = structlog.get_logger(name)
    return logger


def truncate_for_log(text: str | None, max_chars: int = 100) -> str:
    """Return a short, log-safe preview of a longer string.

    Per NFR-08, we never log full narratives. Use this helper any time
    you include user/device text in a log event.

    Args:
        text: The string to truncate.
        max_chars: Maximum length of the returned preview.

    Returns:
        The first ``max_chars`` characters followed by "..." if truncated.
        Returns the literal "<empty>" for None/empty input.
    """
    if not text:
        return "<empty>"
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + "..."
