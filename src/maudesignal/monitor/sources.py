"""Who filed the stored reports (openFDA ``report_source_code``).

HACKATHON-BUILT — Meta Global AI Developer Hackathon (Oct 26 – Nov 4, 2026).

A manufacturer already knows the complaints it reports itself. What it cannot
see in its own complaint system is the reports about its device type filed by
someone else — a user facility (hospital), a voluntary reporter, a distributor.
This module counts reports by source and lists the ones not filed by a
manufacturer, straight from the stored records (no model involved).
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

from maudesignal.gate.evidence import normalize_source
from maudesignal.storage.database import Database


@dataclass(frozen=True)
class SourcedReport:
    """One stored report with who filed it."""

    report_id: str
    product_code: str
    date_received: str | None
    source: str  # normalized; "" when openFDA gave none
    brand_name: str | None


def sourced_reports(db: Database) -> list[SourcedReport]:
    """Every stored report with its normalized source, newest first.

    Args:
        db: The database.

    Returns:
        Reports sorted by ``date_received`` (descending), then id.
    """
    dates = db.date_received_lookup()
    rows = [
        SourcedReport(
            report_id=e.maude_report_id,
            product_code=e.product_code,
            date_received=dates.get(e.maude_report_id),
            source=normalize_source(e.report_source),
            brand_name=e.brand_name,
        )
        for e in db.list_normalized_events()
    ]
    return sorted(rows, key=lambda r: (r.date_received or "", r.report_id), reverse=True)


def source_counts(
    reports: list[SourcedReport],
    *,
    date_from: str | None = None,
    date_to: str | None = None,
) -> dict[str, dict[str, int]]:
    """``product_code -> {source: count}`` (``"unknown"`` for a missing source).

    Args:
        reports: Output of :func:`sourced_reports`.
        date_from: Optional inclusive lower bound (YYYYMMDD).
        date_to: Optional inclusive upper bound (YYYYMMDD).
    """
    out: dict[str, Counter[str]] = {}
    for r in reports:
        if date_from and (r.date_received or "") < date_from:
            continue
        if date_to and (r.date_received or "99999999") > date_to:
            continue
        out.setdefault(r.product_code, Counter())[r.source or "unknown"] += 1
    return {pc: dict(sorted(c.items())) for pc, c in sorted(out.items())}


def not_by_manufacturer(
    reports: list[SourcedReport],
    *,
    date_from: str | None = None,
    date_to: str | None = None,
) -> list[SourcedReport]:
    """Reports whose known source is not a manufacturer (unknown sources are excluded)."""
    return [
        r
        for r in reports
        if r.source
        and r.source != "manufacturer"
        and not (date_from and (r.date_received or "") < date_from)
        and not (date_to and (r.date_received or "99999999") > date_to)
    ]
