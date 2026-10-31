"""HACKATHON-BUILT — Meta Global AI Developer Hackathon (Oct 26 – Nov 4, 2026).

Per-product-code deterioration detector over stored MAUDE events.

For every product code the detector compares a **current window** (the 7
days ending on, and including, the *as-of* date) with a **baseline** (the
4 weeks immediately before the current window) and assigns one primary
classification:

``new_signal``
    The product code has reports in the current window but none ever
    before it, or the current window contains an event type never seen
    for that product code before.
``severity_escalation``
    The share of Injury/Death reports in the current window exceeds the
    baseline share by at least 15 percentage points (baseline must be
    non-empty, and the current window needs at least 3 reports).
``spike``
    Current-window count is at least 2x the baseline weekly mean **and** at
    least 3 reports.
``stable``
    None of the above fired.

Several rules can fire at once; all of them are listed in
:attr:`ProductCodeSignal.triggers`, and the primary classification follows
the precedence ``new_signal > severity_escalation > spike``.

Windows are anchored on openFDA ``date_received`` (a ``YYYYMMDD`` string)
and the *as-of* date defaults to the latest ``date_received`` in the data —
never wall-clock today, because openFDA lags real time by weeks.

Every number used in a decision is returned verbatim (counts, means,
shares, report ids) so a downstream citation gate can recompute it from
the stored records. Threshold decisions use exact integer/fraction
arithmetic; the float fields are for display only.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from fractions import Fraction
from typing import Literal

from maudesignal.storage.database import Database

Classification = Literal["new_signal", "severity_escalation", "spike", "stable"]

#: Precedence used to pick the primary classification when several fire.
CLASSIFICATION_PRECEDENCE: tuple[Classification, ...] = (
    "new_signal",
    "severity_escalation",
    "spike",
)

CURRENT_WINDOW_DAYS = 7
BASELINE_WEEKS = 4
SPIKE_MULTIPLIER = 2
SPIKE_MIN_REPORTS = 3
# Same floor for the severity rule (Charan, Oct 30): a share built on 1 or 2 reports is noise.
SEVERITY_MIN_REPORTS = SPIKE_MIN_REPORTS
SEVERITY_ESCALATION_PP = 15
SEVERE_EVENT_TYPES: frozenset[str] = frozenset({"injury", "death"})
UNKNOWN_EVENT_TYPE = "unknown"


# ----------------------------------------------------------------------
# Data types
# ----------------------------------------------------------------------


@dataclass(frozen=True)
class EventFact:
    """The minimal facts about one MAUDE report the detector needs.

    Attributes:
        report_id: MAUDE report identifier (``mdr_report_key``).
        product_code: FDA 3-letter product code.
        date_received: openFDA ``date_received`` as a date.
        event_type: Lower-cased openFDA event type (``"malfunction"``,
            ``"injury"``, ``"death"``, ``"other"``, ...) or ``"unknown"``.
    """

    report_id: str
    product_code: str
    date_received: date
    event_type: str


@dataclass(frozen=True)
class DetectionWindow:
    """The inclusive date ranges a detection run compared.

    Attributes:
        as_of: Last day of the current window.
        current_start: First day of the current window (as_of - 6 days).
        current_end: Same as ``as_of``.
        baseline_start: First day of the baseline (current_start - 28 days).
        baseline_end: Last day of the baseline (current_start - 1 day).
    """

    as_of: date
    current_start: date
    current_end: date
    baseline_start: date
    baseline_end: date


@dataclass(frozen=True)
class ProductCodeSignal:
    """Classification and the exact evidence for one product code.

    Attributes:
        product_code: FDA product code.
        classification: Primary classification (see module docstring).
        triggers: Every rule that fired, in precedence order (empty if stable).
        current_count: Reports in the current window.
        current_report_ids: Their report ids (sorted).
        current_severe_count: Injury/Death reports in the current window.
        current_severe_report_ids: Their report ids (sorted).
        current_severe_share: ``current_severe_count / current_count`` or None.
        baseline_count: Reports in the 4-week baseline.
        baseline_report_ids: Their report ids (sorted).
        baseline_weekly_mean: ``baseline_count / 4``.
        baseline_severe_count: Injury/Death reports in the baseline.
        baseline_severe_report_ids: Their report ids (sorted).
        baseline_severe_share: ``baseline_severe_count / baseline_count`` or None.
        severe_share_delta_pp: Current minus baseline share, in percentage
            points, or None when either share is undefined.
        spike_ratio: ``current_count / baseline_weekly_mean`` or None when the
            baseline mean is zero.
        prior_report_count: All reports dated before the current window.
        new_event_types: Event types in the current window never seen before it.
        new_event_type_report_ids: Current-window reports carrying a new type.
        current_event_type_counts: ``(event_type, count)`` pairs, sorted.
    """

    product_code: str
    classification: Classification
    triggers: tuple[Classification, ...]
    current_count: int
    current_report_ids: tuple[str, ...]
    current_severe_count: int
    current_severe_report_ids: tuple[str, ...]
    current_severe_share: float | None
    baseline_count: int
    baseline_report_ids: tuple[str, ...]
    baseline_weekly_mean: float
    baseline_severe_count: int
    baseline_severe_report_ids: tuple[str, ...]
    baseline_severe_share: float | None
    severe_share_delta_pp: float | None
    spike_ratio: float | None
    prior_report_count: int
    new_event_types: tuple[str, ...]
    new_event_type_report_ids: tuple[str, ...]
    current_event_type_counts: tuple[tuple[str, int], ...]

    @property
    def is_stable(self) -> bool:
        """True when no rule fired."""
        return self.classification == "stable"


@dataclass(frozen=True)
class DetectionResult:
    """Output of one detection run.

    Attributes:
        window: The compared date ranges.
        signals: One entry per product code, sorted by product code.
        events_considered: Events with a valid date on or before ``as_of``.
        events_after_as_of: Events ignored because they post-date ``as_of``.
        events_skipped_missing_date: Rows dropped for a missing/invalid date.
    """

    window: DetectionWindow
    signals: tuple[ProductCodeSignal, ...]
    events_considered: int
    events_after_as_of: int
    events_skipped_missing_date: int

    def non_stable(self) -> tuple[ProductCodeSignal, ...]:
        """Return the signals whose classification is not ``stable``."""
        return tuple(s for s in self.signals if not s.is_stable)


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------


def parse_yyyymmdd(value: str) -> date:
    """Parse an openFDA ``YYYYMMDD`` (or ISO ``YYYY-MM-DD``) date string.

    Args:
        value: Date string.

    Returns:
        The parsed date.

    Raises:
        ValueError: If the string is not a valid date in either format.
    """
    text = value.strip()
    fmt = "%Y-%m-%d" if "-" in text else "%Y%m%d"
    return datetime.strptime(text, fmt).date()


def facts_from_rows(
    rows: Iterable[tuple[str, str, str | None, str | None]],
) -> tuple[list[EventFact], int]:
    """Convert database rows into :class:`EventFact` objects.

    Args:
        rows: ``(report_id, product_code, date_received, event_type)`` tuples,
            as returned by :meth:`Database.list_event_facts`.

    Returns:
        ``(facts, skipped)`` where ``skipped`` counts rows without a usable
        ``date_received``.
    """
    facts: list[EventFact] = []
    skipped = 0
    for report_id, product_code, date_received, event_type in rows:
        if not date_received:
            skipped += 1
            continue
        try:
            received = parse_yyyymmdd(date_received)
        except ValueError:
            skipped += 1
            continue
        facts.append(
            EventFact(
                report_id=report_id,
                product_code=product_code,
                date_received=received,
                event_type=(event_type or UNKNOWN_EVENT_TYPE).strip().lower() or UNKNOWN_EVENT_TYPE,
            )
        )
    return facts, skipped


def default_as_of(facts: Sequence[EventFact]) -> date:
    """Return the latest ``date_received`` among ``facts``.

    Args:
        facts: Events to inspect.

    Returns:
        The maximum ``date_received``.

    Raises:
        ValueError: If ``facts`` is empty.
    """
    if not facts:
        raise ValueError("cannot derive an as-of date from zero events")
    return max(f.date_received for f in facts)


def build_window(as_of: date) -> DetectionWindow:
    """Build the current (7-day) and baseline (4-week) windows for ``as_of``.

    Args:
        as_of: Last day of the current window (inclusive).

    Returns:
        The inclusive window boundaries.
    """
    current_start = as_of - timedelta(days=CURRENT_WINDOW_DAYS - 1)
    baseline_end = current_start - timedelta(days=1)
    baseline_start = current_start - timedelta(weeks=BASELINE_WEEKS)
    return DetectionWindow(
        as_of=as_of,
        current_start=current_start,
        current_end=as_of,
        baseline_start=baseline_start,
        baseline_end=baseline_end,
    )


def _share(numerator: int, denominator: int) -> Fraction | None:
    return Fraction(numerator, denominator) if denominator else None


def _round(value: Fraction | None, digits: int = 4) -> float | None:
    return None if value is None else round(float(value), digits)


# ----------------------------------------------------------------------
# Core
# ----------------------------------------------------------------------


def _classify_product_code(
    product_code: str,
    events: Sequence[EventFact],
    window: DetectionWindow,
) -> ProductCodeSignal:
    """Classify one product code given all of its events up to ``as_of``."""
    current = sorted(
        (e for e in events if window.current_start <= e.date_received <= window.current_end),
        key=lambda e: e.report_id,
    )
    baseline = sorted(
        (e for e in events if window.baseline_start <= e.date_received <= window.baseline_end),
        key=lambda e: e.report_id,
    )
    prior = [e for e in events if e.date_received < window.current_start]

    current_severe = [e for e in current if e.event_type in SEVERE_EVENT_TYPES]
    baseline_severe = [e for e in baseline if e.event_type in SEVERE_EVENT_TYPES]

    prior_types = {e.event_type for e in prior}
    new_types = sorted({e.event_type for e in current} - prior_types) if prior else []
    new_type_ids = tuple(e.report_id for e in current if e.event_type in set(new_types))

    triggers: list[Classification] = []

    # new_signal: first-ever reports for the code, or a never-seen event type.
    if current and (not prior or new_types):
        triggers.append("new_signal")

    # severity_escalation: >= 15 pp rise in Injury/Death share (exact arithmetic), and
    # at least SEVERITY_MIN_REPORTS reports this window.
    cur_share = _share(len(current_severe), len(current))
    base_share = _share(len(baseline_severe), len(baseline))
    delta: Fraction | None = None
    if cur_share is not None and base_share is not None:
        delta = (cur_share - base_share) * 100
        if delta >= SEVERITY_ESCALATION_PP and len(current) >= SEVERITY_MIN_REPORTS:
            triggers.append("severity_escalation")

    # spike: current >= 2 x (baseline / 4) and current >= 3.
    baseline_mean = Fraction(len(baseline), BASELINE_WEEKS)
    if len(current) >= SPIKE_MIN_REPORTS and len(current) >= SPIKE_MULTIPLIER * baseline_mean:
        triggers.append("spike")

    ordered = tuple(c for c in CLASSIFICATION_PRECEDENCE if c in triggers)
    classification: Classification = ordered[0] if ordered else "stable"

    type_counts = Counter(e.event_type for e in current)
    return ProductCodeSignal(
        product_code=product_code,
        classification=classification,
        triggers=ordered,
        current_count=len(current),
        current_report_ids=tuple(e.report_id for e in current),
        current_severe_count=len(current_severe),
        current_severe_report_ids=tuple(e.report_id for e in current_severe),
        current_severe_share=_round(cur_share),
        baseline_count=len(baseline),
        baseline_report_ids=tuple(e.report_id for e in baseline),
        baseline_weekly_mean=float(baseline_mean),
        baseline_severe_count=len(baseline_severe),
        baseline_severe_report_ids=tuple(e.report_id for e in baseline_severe),
        baseline_severe_share=_round(base_share),
        severe_share_delta_pp=_round(delta, 2),
        spike_ratio=_round(Fraction(len(current)) / baseline_mean if baseline_mean else None, 2),
        prior_report_count=len(prior),
        new_event_types=tuple(new_types),
        new_event_type_report_ids=new_type_ids,
        current_event_type_counts=tuple(sorted(type_counts.items())),
    )


def detect_deterioration(
    facts: Sequence[EventFact],
    as_of: date | None = None,
    *,
    skipped_missing_date: int = 0,
) -> DetectionResult:
    """Classify every product code in ``facts`` as of a given date.

    Args:
        facts: All stored events (any date). Events after ``as_of`` are ignored.
        as_of: Last day of the current window. Defaults to the latest
            ``date_received`` in ``facts`` (never wall-clock today).
        skipped_missing_date: Count of upstream rows dropped for a missing
            date, carried through for transparency.

    Returns:
        A :class:`DetectionResult` with one signal per product code.

    Raises:
        ValueError: If ``as_of`` is None and ``facts`` is empty.
    """
    effective_as_of = as_of if as_of is not None else default_as_of(facts)
    window = build_window(effective_as_of)

    in_scope = [f for f in facts if f.date_received <= effective_as_of]
    by_code: dict[str, list[EventFact]] = {}
    for fact in in_scope:
        by_code.setdefault(fact.product_code, []).append(fact)
    # Codes whose only reports post-date as_of still appear (as stable, zero counts).
    for fact in facts:
        by_code.setdefault(fact.product_code, [])

    signals = tuple(_classify_product_code(code, by_code[code], window) for code in sorted(by_code))
    return DetectionResult(
        window=window,
        signals=signals,
        events_considered=len(in_scope),
        events_after_as_of=len(facts) - len(in_scope),
        events_skipped_missing_date=skipped_missing_date,
    )


def detect_from_database(db: Database, as_of: date | None = None) -> DetectionResult:
    """Load events from ``db`` and run :func:`detect_deterioration`.

    Args:
        db: The MaudeSignal database facade.
        as_of: Optional as-of date; defaults to the latest stored ``date_received``.

    Returns:
        The detection result.

    Raises:
        ValueError: If the database holds no dated events and ``as_of`` is None.
    """
    facts, skipped = facts_from_rows(db.list_event_facts())
    return detect_deterioration(facts, as_of, skipped_missing_date=skipped)
