"""HACKATHON-BUILT — Meta Global AI Developer Hackathon (Oct 26 – Nov 4, 2026).

Deterministic daily monitor for MAUDE adverse-event reports: reports suddenly
increased, more serious than usual, or a new kind of problem.

* :mod:`maudesignal.monitor.deterioration` — classifies each product code's
  last 7 days against a trailing 4-week baseline (pure functions, no I/O
  beyond an optional :class:`~maudesignal.storage.database.Database` read).
* :mod:`maudesignal.monitor.digest` — turns a detection result into a
  Markdown + JSON digest with a fixed advisory footer. No LLM is involved.
"""

from __future__ import annotations

from maudesignal.monitor.deterioration import (
    DetectionResult,
    DetectionWindow,
    EventFact,
    ProductCodeSignal,
    build_window,
    default_as_of,
    detect_deterioration,
    detect_from_database,
    facts_from_rows,
    parse_yyyymmdd,
)
from maudesignal.monitor.digest import (
    DIGEST_FOOTER,
    Digest,
    build_digest,
    digest_to_dict,
    render_json,
    render_markdown,
)

__all__ = [
    "DIGEST_FOOTER",
    "DetectionResult",
    "DetectionWindow",
    "Digest",
    "EventFact",
    "ProductCodeSignal",
    "build_digest",
    "build_window",
    "default_as_of",
    "detect_deterioration",
    "detect_from_database",
    "digest_to_dict",
    "facts_from_rows",
    "parse_yyyymmdd",
    "render_json",
    "render_markdown",
]
