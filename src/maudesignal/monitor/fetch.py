"""HACKATHON-BUILT — Meta Global AI Developer Hackathon (Oct 26 – Nov 4, 2026).

Capped, gap-free incremental fetch for the overnight monitor.

For each product code already in the database, the monitor asks openFDA
for per-day counts *after* the latest stored ``date_received`` (one cheap
``count=`` request), then ingests only **whole days** that fit inside the
remaining ``max_new`` budget, via the existing
:func:`maudesignal.ingestion.pipeline.ingest_product_code`. Fetching whole
days means a capped run never leaves a partially-fetched day that a later
run (starting the day after the stored maximum) would skip.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import timedelta

from maudesignal.common.exceptions import MaudeSignalError
from maudesignal.common.logging import get_logger
from maudesignal.ingestion.openfda_client import OpenFDAClient
from maudesignal.ingestion.pipeline import ingest_product_code
from maudesignal.monitor.deterioration import parse_yyyymmdd
from maudesignal.storage.database import Database

logger = get_logger(__name__)


@dataclass(frozen=True)
class CodeFetch:
    """What the incremental fetch did for one product code.

    Attributes:
        product_code: FDA product code.
        start_date: First ``date_received`` requested (YYYYMMDD) or None.
        end_date: Last whole day fetched (YYYYMMDD) or None if nothing fetched.
        planned: Records the per-day counts said the fetched days contain.
        fetched: Records returned by openFDA.
        new: Records newly stored (not already in the database).
    """

    product_code: str
    start_date: str | None
    end_date: str | None
    planned: int
    fetched: int
    new: int


@dataclass(frozen=True)
class FetchReport:
    """Summary of one capped incremental fetch.

    Attributes:
        items: Per-product-code outcomes, in processing order.
        notes: Human-readable warnings (budget exhausted, API errors, ...).
    """

    items: tuple[CodeFetch, ...]
    notes: tuple[str, ...]

    @property
    def total_fetched(self) -> int:
        """Total records returned by openFDA across all product codes."""
        return sum(i.fetched for i in self.items)

    @property
    def new_by_code(self) -> dict[str, int]:
        """``product_code -> newly stored records`` (only codes with new records)."""
        return {i.product_code: i.new for i in self.items if i.new}


def plan_whole_days(day_counts: Sequence[tuple[str, int]], budget: int) -> tuple[str | None, int]:
    """Choose the longest prefix of days whose total fits in ``budget``.

    Args:
        day_counts: ``(YYYYMMDD, count)`` pairs sorted by date.
        budget: Maximum records allowed.

    Returns:
        ``(last_day_included, total_records)``; ``(None, 0)`` when even the
        first day exceeds the budget or there are no days.
    """
    last_day: str | None = None
    total = 0
    for day, count in day_counts:
        if total + count > budget:
            break
        last_day = day
        total += count
    return last_day, total


def _day_after(yyyymmdd: str) -> str:
    return (parse_yyyymmdd(yyyymmdd) + timedelta(days=1)).strftime("%Y%m%d")


def incremental_fetch(
    *,
    db: Database,
    client: OpenFDAClient,
    max_new: int,
    product_codes: Sequence[str] | None = None,
) -> FetchReport:
    """Fetch up to ``max_new`` records newer than what is stored, whole days only.

    Args:
        db: Database to read the latest stored date from and ingest into.
        client: openFDA client (keyless works; key only raises rate limits).
        max_new: Cap on records fetched across all product codes this run.
        product_codes: Codes to update; defaults to every code in the database.

    Returns:
        A :class:`FetchReport`. openFDA errors are recorded as notes, never raised,
        so a scheduled run still produces a digest from what is stored.
    """
    codes = list(product_codes) if product_codes is not None else db.list_product_codes()
    remaining = max(max_new, 0)
    items: list[CodeFetch] = []
    notes: list[str] = []

    for code in codes:
        if remaining <= 0:
            notes.append(f"{code}: not checked — --max-new budget exhausted")
            continue
        latest = db.max_date_received(code)
        start = _day_after(latest) if latest else None
        try:
            day_counts = client.count_by_date_received(code, start_date=start)
            end, planned = plan_whole_days(day_counts, remaining)
            if not day_counts:
                items.append(CodeFetch(code, start, None, 0, 0, 0))
                continue
            if end is None:
                first_day, first_count = day_counts[0]
                notes.append(
                    f"{code}: {first_day} has {first_count} reports, more than the "
                    f"remaining budget of {remaining}; skipped (raise --max-new)"
                )
                items.append(CodeFetch(code, start, None, 0, 0, 0))
                continue
            result = ingest_product_code(
                client=client,
                db=db,
                product_code=code,
                start_date=start or day_counts[0][0],
                end_date=end,
                limit=planned,
            )
        except MaudeSignalError as exc:
            logger.warning("monitor_fetch_failed", product_code=code, error=str(exc))
            notes.append(f"{code}: openFDA fetch failed ({exc}); used stored data only")
            continue
        remaining -= result.records_fetched
        items.append(
            CodeFetch(code, start, end, planned, result.records_fetched, result.records_new)
        )

    return FetchReport(items=tuple(items), notes=tuple(notes))
