"""End-to-end 510(k) summary flow shared by the dashboard and the recording script.

HACKATHON-BUILT — Meta Global AI Developer Hackathon (Oct 26 – Nov 4, 2026).

K-number → cached PDF → page images + text layer → two independent Muse Spark
reads → accuracy check against each other, openFDA and the text layer.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from maudesignal.vision.fda_pdf import DEFAULT_CACHE_DIR, DEFAULT_MAX_PAGES, load_summary
from maudesignal.vision.images import thumbnail_data_url
from maudesignal.vision.openfda510k import OpenFda510k
from maudesignal.vision.reader import read_twice
from maudesignal.vision.spark import DEFAULT_VISION_MODEL
from maudesignal.vision.verify import VerifiedSummary, verify_readings

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEMO_VISION_DIR = PROJECT_ROOT / "demo" / "vision"


def read_and_verify_510k(
    k_number: str,
    *,
    client: Any,
    openfda: OpenFda510k | None,
    cache_dir: Path = DEFAULT_CACHE_DIR,
    max_pages: int = DEFAULT_MAX_PAGES,
    model: str = DEFAULT_VISION_MODEL,
    browser_fallback: bool = False,
) -> VerifiedSummary:
    """Read one 510(k) summary twice and check every field.

    ``browser_fallback`` lets the PDF download fall back to a headless browser
    (see :func:`~maudesignal.vision.fda_pdf.fetch_510k_pdf`).

    Raises:
        PdfUnavailableError: The PDF could not be obtained (nothing was read).
        FdaPdfError: The PDF could not be rasterized.
        VisionModelError: A Muse Spark read failed.
        OpenFdaError: openFDA failed (the reading is not checked without it).
    """
    doc = load_summary(k_number, cache_dir, max_pages=max_pages, browser_fallback=browser_fallback)
    read_a, read_b = read_twice(client, doc.pages, model=model)
    record = openfda.get(doc.k_number) if openfda else None

    def predicates_exist(ks: list[str]) -> set[str]:
        return set(openfda.get_many(ks)) if openfda else set()

    summary = verify_readings(
        read_a,
        read_b,
        k_number=doc.k_number,
        openfda=record,
        text_pages=doc.text_pages if doc.has_text_layer else None,
        predicate_lookup=predicates_exist if openfda else None,
        page_count=doc.page_count,
        pdf_url=doc.url,
    )
    summary.thumbnails = [thumbnail_data_url(p.png) for p in doc.pages]
    return summary


def summary_path(out_dir: Path, k_number: str) -> Path:
    """``demo/vision/510k-<K>.json``."""
    return out_dir / f"510k-{k_number.upper()}.json"


def save_summary(summary: VerifiedSummary, out_dir: Path = DEMO_VISION_DIR) -> Path:
    """Write a checked reading as pretty JSON."""
    out_dir.mkdir(parents=True, exist_ok=True)
    path = summary_path(out_dir, summary.k_number)
    path.write_text(json.dumps(summary.to_dict(), indent=2) + "\n", encoding="utf-8")
    return path


def load_recorded_summaries(directory: Path = DEMO_VISION_DIR) -> list[VerifiedSummary]:
    """Recorded readings (``510k-*.json``), sorted by K-number; unreadable files skipped."""
    out: list[VerifiedSummary] = []
    for p in sorted(directory.glob("510k-*.json")):
        try:
            out.append(VerifiedSummary.from_dict(json.loads(p.read_text(encoding="utf-8"))))
        except (ValueError, KeyError, TypeError):
            continue
    return out


def load_recorded_labels(directory: Path = DEMO_VISION_DIR) -> list[dict[str, Any]]:
    """Recorded label runs (``label-*.json``) as dicts; unreadable files skipped."""
    out: list[dict[str, Any]] = []
    for p in sorted(directory.glob("label-*.json")):
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except ValueError:
            continue
        if isinstance(data, dict):
            data.setdefault("_file", p.name)
            out.append(data)
    return out
