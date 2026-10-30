"""Check any device type on openFDA, live (deterministic, no model, nothing stored).

HACKATHON-BUILT — Meta Global AI Developer Hackathon (Oct 26 – Nov 4, 2026).

The demo database holds a few device types. This module lets anyone check *any*
FDA product code: it asks openFDA for counts only (no report text is downloaded)
and applies the same four rules as :mod:`maudesignal.monitor.deterioration` —
same windows (the 7 days ending on the latest ``date_received`` vs the 4 weeks
before), same thresholds, same exact arithmetic. ``tests/unit/test_live_check.py``
checks that both give the same answer on the same reports.

Every figure comes with the openFDA query that produced it, so a reader can open
the link and see the same number.

Requests per check (about 5): per-day counts for the last two years (finds the
latest date and the two windows), event-type counts for the current window, the
baseline and everything before, and the total before the current window.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, replace
from datetime import date, timedelta
from fractions import Fraction
from typing import Any
from urllib.parse import urlencode

from maudesignal.common.exceptions import MaudeSignalError
from maudesignal.ingestion.openfda_client import (
    OPENFDA_EVENT_ENDPOINT,
    OpenFDAClient,
    build_query,
    search_param,
)
from maudesignal.monitor.deterioration import (
    BASELINE_WEEKS,
    CLASSIFICATION_PRECEDENCE,
    SEVERE_EVENT_TYPES,
    SEVERITY_ESCALATION_PP,
    SEVERITY_MIN_REPORTS,
    SPIKE_MIN_REPORTS,
    SPIKE_MULTIPLIER,
    UNKNOWN_EVENT_TYPE,
    Classification,
    DetectionWindow,
    build_window,
    parse_yyyymmdd,
)
from maudesignal.monitor.digest import CHANGE_LABELS

PRODUCT_CODE_RE = re.compile(r"^[A-Z]{3}$")
#: How far back to look for the latest report (openFDA lags real time by weeks).
LOOKBACK_DAYS = 730
_EARLIEST = "19900101"


class LiveCheckError(MaudeSignalError):
    """Raised for an invalid product code (network errors surface as OpenFDAAPIError)."""


@dataclass(frozen=True)
class WindowCounts:
    """Report counts for one product code and one window.

    Attributes:
        current_total: Reports in the current 7-day window.
        baseline_total: Reports in the 4-week baseline.
        prior_total: All reports dated before the current window.
        current_types: ``(event_type, count)`` in the current window.
        baseline_types: ``(event_type, count)`` in the baseline.
        prior_types: ``(event_type, count)`` before the current window.
    """

    current_total: int
    baseline_total: int
    prior_total: int
    current_types: tuple[tuple[str, int], ...]
    baseline_types: tuple[tuple[str, int], ...]
    prior_types: tuple[tuple[str, int], ...]


@dataclass(frozen=True)
class LiveCheck:
    """One device type's result, with the queries behind every figure."""

    product_code: str
    as_of: date | None
    window: DetectionWindow | None
    classification: Classification
    triggers: tuple[Classification, ...]
    current_count: int
    current_severe_count: int
    current_severe_share: float | None
    baseline_count: int
    baseline_weekly_mean: float
    baseline_severe_count: int
    baseline_severe_share: float | None
    severe_share_delta_pp: float | None
    spike_ratio: float | None
    prior_report_count: int
    new_event_types: tuple[str, ...]
    current_event_type_counts: tuple[tuple[str, int], ...]
    queries: tuple[tuple[str, str], ...] = ()

    @property
    def change(self) -> str:
        """The plain-words label used everywhere in the app."""
        return CHANGE_LABELS[self.classification]

    @property
    def all_dates_total(self) -> int:
        """Reports on openFDA up to the latest date (before the window plus the window)."""
        return self.prior_report_count + self.current_count

    def to_dict(self) -> dict[str, Any]:
        """JSON-serialisable view (dates as YYYYMMDD)."""
        d = asdict(self)
        d["as_of"] = self.as_of.strftime("%Y%m%d") if self.as_of else None
        if self.window:
            d["window"] = {k: v.strftime("%Y%m%d") for k, v in asdict(self.window).items()}
        d["change"] = self.change
        return d


def _ymd(d: date) -> str:
    return d.strftime("%Y%m%d")


def _norm(rows: list[tuple[str, int]], total: int) -> tuple[tuple[str, int], ...]:
    """Lower-case event types as the detector does; reports with no type count as unknown."""
    merged: dict[str, int] = {}
    for term, n in rows:
        key = term.strip().lower() or UNKNOWN_EVENT_TYPE
        merged[key] = merged.get(key, 0) + n
    missing = total - sum(merged.values())
    if missing > 0:
        merged[UNKNOWN_EVENT_TYPE] = merged.get(UNKNOWN_EVENT_TYPE, 0) + missing
    return tuple(sorted((k, v) for k, v in merged.items() if v > 0))


def _severe(types: tuple[tuple[str, int], ...]) -> int:
    return sum(n for t, n in types if t in SEVERE_EVENT_TYPES)


def _round(value: Fraction | None, digits: int = 4) -> float | None:
    return None if value is None else round(float(value), digits)


def skipped_for_few_reports(cur: int, cur_severe: int, base: int, base_severe: int) -> bool:
    """True when the severity rule's share jump is there but this week has too few reports.

    Such a code is *not* flagged ("flags need at least 3 reports this week"); this lets a
    page say how many codes were skipped for that reason.
    """
    if not cur or not base or cur >= SEVERITY_MIN_REPORTS:
        return False
    delta = (Fraction(cur_severe, cur) - Fraction(base_severe, base)) * 100
    return delta >= SEVERITY_ESCALATION_PP


def count_skipped(rows: list[dict[str, Any]]) -> int:
    """How many stored sweep rows were skipped for having too few reports this week."""
    return sum(
        skipped_for_few_reports(
            r.get("current_count", 0),
            r.get("current_severe_count", 0),
            r.get("baseline_count", 0),
            r.get("baseline_severe_count", 0),
        )
        for r in rows
    )


def classify_counts(product_code: str, counts: WindowCounts, window: DetectionWindow) -> LiveCheck:
    """Apply the detector's four rules to counts (mirrors ``_classify_product_code``)."""
    cur, base, prior = counts.current_total, counts.baseline_total, counts.prior_total
    cur_sev, base_sev = _severe(counts.current_types), _severe(counts.baseline_types)
    prior_kinds = {t for t, n in counts.prior_types if n > 0}
    cur_kinds = {t for t, n in counts.current_types if n > 0}
    new_types = sorted(cur_kinds - prior_kinds) if prior else []

    triggers: list[Classification] = []
    if cur and (not prior or new_types):
        triggers.append("new_signal")
    cur_share = Fraction(cur_sev, cur) if cur else None
    base_share = Fraction(base_sev, base) if base else None
    delta: Fraction | None = None
    if cur_share is not None and base_share is not None:
        delta = (cur_share - base_share) * 100
        if delta >= SEVERITY_ESCALATION_PP and cur >= SEVERITY_MIN_REPORTS:
            triggers.append("severity_escalation")
    mean = Fraction(base, BASELINE_WEEKS)
    if cur >= SPIKE_MIN_REPORTS and cur >= SPIKE_MULTIPLIER * mean:
        triggers.append("spike")
    ordered = tuple(c for c in CLASSIFICATION_PRECEDENCE if c in triggers)
    return LiveCheck(
        product_code=product_code,
        as_of=window.as_of,
        window=window,
        classification=ordered[0] if ordered else "stable",
        triggers=ordered,
        current_count=cur,
        current_severe_count=cur_sev,
        current_severe_share=_round(cur_share),
        baseline_count=base,
        baseline_weekly_mean=float(mean),
        baseline_severe_count=base_sev,
        baseline_severe_share=_round(base_share),
        severe_share_delta_pp=_round(delta, 2),
        spike_ratio=_round(Fraction(cur) / mean if mean else None, 2),
        prior_report_count=prior,
        new_event_types=tuple(new_types),
        current_event_type_counts=counts.current_types,
    )


def verify_url(
    product_code: str, start: str | None, end: str | None, count: str | None = None
) -> str:
    """The public openFDA URL a reader can open to see a figure (no key in it)."""
    params: dict[str, str | int] = {"search": search_param(build_query(product_code, start, end))}
    params.update({"count": count} if count else {"limit": 1})
    return f"{OPENFDA_EVENT_ENDPOINT}?{urlencode(params)}"


def normalize_code(text: str) -> str:
    """Upper-case and validate a product code.

    Raises:
        LiveCheckError: If it is not three letters.
    """
    code = text.strip().upper()
    if not PRODUCT_CODE_RE.match(code):
        raise LiveCheckError("A product code is three letters, for example LLZ or QIH.")
    return code


def check_product_code(
    client: OpenFDAClient, product_code: str, today: date, as_of: date | None = None
) -> LiveCheck:
    """Check one product code on openFDA as of its latest report (or a given date).

    Args:
        client: openFDA client (an API key raises the rate limit; none is needed).
        product_code: Three-letter FDA product code.
        today: Wall-clock date, used only to bound the search for the latest report.
        as_of: Last day of the current window. Defaults to the code's latest report;
            a sweep passes one date so every code compares the same week.

    Returns:
        The classification, its figures, and the queries behind them. When the code
        has no report in the last two years, ``as_of`` is None and the result is stable.

    Raises:
        LiveCheckError: For an invalid code.
        OpenFDAAPIError: When openFDA cannot be reached.
    """
    code = normalize_code(product_code)
    look_from = _ymd(today - timedelta(days=LOOKBACK_DAYS))
    days = [(d, n) for d, n in client.count_field(code, "date_received", look_from, _ymd(today))]
    days = [(d, n) for d, n in days if n > 0 and (as_of is None or parse_yyyymmdd(d) <= as_of)]
    if not days and as_of is None:
        prior_all = client.total(code)
        return LiveCheck(
            product_code=code,
            as_of=None,
            window=None,
            classification="stable",
            triggers=(),
            current_count=0,
            current_severe_count=0,
            current_severe_share=None,
            baseline_count=0,
            baseline_weekly_mean=0.0,
            baseline_severe_count=0,
            baseline_severe_share=None,
            severe_share_delta_pp=None,
            spike_ratio=None,
            prior_report_count=prior_all,
            new_event_types=(),
            current_event_type_counts=(),
            queries=(("Reports, all dates", verify_url(code, None, None)),),
        )
    w = build_window(as_of or max(parse_yyyymmdd(d) for d, _ in days))
    cs, ce = _ymd(w.current_start), _ymd(w.current_end)
    bs, be = _ymd(w.baseline_start), _ymd(w.baseline_end)
    before = _ymd(w.current_start - timedelta(days=1))

    def in_range(a: date, b: date) -> int:
        return sum(n for d, n in days if a <= parse_yyyymmdd(d) <= b)

    if w.baseline_start >= today - timedelta(days=LOOKBACK_DAYS):
        cur_total = in_range(w.current_start, w.current_end)
        base_total = in_range(w.baseline_start, w.baseline_end)
    else:  # the windows reach past the per-day lookback
        cur_total, base_total = client.total(code, cs, ce), client.total(code, bs, be)
    prior_total = client.total(code, _EARLIEST, before)

    # Event-type counts are only needed where there are reports (the rules ignore them
    # otherwise), which keeps a sweep of quiet codes cheap.
    def types(a: str, b: str, total: int, needed: bool) -> tuple[tuple[str, int], ...]:
        if not (needed and total):
            return ()
        return _norm(client.count_field(code, "event_type.exact", a, b), total)

    counts = WindowCounts(
        current_total=cur_total,
        baseline_total=base_total,
        prior_total=prior_total,
        current_types=types(cs, ce, cur_total, True),
        baseline_types=types(bs, be, base_total, True),
        prior_types=types(_EARLIEST, before, prior_total, cur_total > 0),
    )
    result = classify_counts(code, counts, w)
    queries = (
        (
            "Reports per day (latest date, both windows)",
            verify_url(code, look_from, _ymd(today), "date_received"),
        ),
        ("This week, by event type", verify_url(code, cs, ce, "event_type.exact")),
        ("4 weeks before, by event type", verify_url(code, bs, be, "event_type.exact")),
        ("Everything before this week", verify_url(code, _EARLIEST, before)),
        (
            "Everything before this week, by event type",
            verify_url(code, _EARLIEST, before, "event_type.exact"),
        ),
    )
    return replace(result, queries=queries)
