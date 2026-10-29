"""Signal compare: the device types you choose, side by side (deterministic, no model).

HACKATHON-BUILT — Meta Global AI Developer Hackathon (Oct 26 – Nov 4, 2026).

Every number comes from the same detector run the "What changed" page uses
(``maudesignal.monitor.deterioration``) plus the stored openFDA report source,
so the gate can recompute any of them. The user picks the product codes; the
tool never decides which devices are "similar".
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date
from typing import Any

from maudesignal.monitor.deterioration import detect_from_database
from maudesignal.monitor.digest import CHANGE_LABELS
from maudesignal.monitor.sources import source_counts, sourced_reports
from maudesignal.storage.database import Database


@dataclass(frozen=True)
class CompareRow:
    """One device type's numbers for the current window."""

    product_code: str
    change: str
    this_week: int
    baseline_weekly_mean: float
    ratio_to_baseline: float | None
    injury_death_this_week: int
    injury_death_share_pct: float | None
    injury_death_share_baseline_pct: float | None
    not_by_manufacturer_this_week: int
    stored_total: int


@dataclass(frozen=True)
class Comparison:
    """A comparison over one window."""

    as_of: date
    window_from: date
    window_to: date
    rows: tuple[CompareRow, ...]
    unknown_codes: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        """JSON-serialisable view (used by the copilot tool)."""
        return {
            "as_of": self.as_of.strftime("%Y%m%d"),
            "window": {
                "date_from": self.window_from.strftime("%Y%m%d"),
                "date_to": self.window_to.strftime("%Y%m%d"),
            },
            "rows": [asdict(r) for r in self.rows],
            "unknown_codes": list(self.unknown_codes),
        }


def _pct(share: float | None) -> float | None:
    return None if share is None else round(share * 100, 1)


def compare_signals(
    db: Database, product_codes: list[str], as_of: date | None = None
) -> Comparison:
    """Side-by-side numbers for the chosen product codes (order kept, duplicates dropped)."""
    wanted = list(dict.fromkeys(c.strip().upper() for c in product_codes if c and c.strip()))
    result = detect_from_database(db, as_of)
    w = result.window
    by_code = {s.product_code: s for s in result.signals}
    reports = sourced_reports(db)
    week = source_counts(
        reports,
        date_from=w.current_start.strftime("%Y%m%d"),
        date_to=w.current_end.strftime("%Y%m%d"),
    )
    stored = source_counts(reports)
    rows = []
    for pc in wanted:
        s = by_code.get(pc)
        if s is None:
            continue
        wk = week.get(pc, {})
        rows.append(
            CompareRow(
                product_code=pc,
                change=CHANGE_LABELS[s.classification],
                this_week=s.current_count,
                baseline_weekly_mean=round(s.baseline_weekly_mean, 2),
                ratio_to_baseline=None if s.spike_ratio is None else round(s.spike_ratio, 2),
                injury_death_this_week=s.current_severe_count,
                injury_death_share_pct=_pct(s.current_severe_share),
                injury_death_share_baseline_pct=_pct(s.baseline_severe_share),
                not_by_manufacturer_this_week=sum(
                    n for k, n in wk.items() if k not in ("manufacturer", "unknown")
                ),
                stored_total=sum(stored.get(pc, {}).values()),
            )
        )
    unknown = tuple(pc for pc in wanted if pc not in by_code)
    return Comparison(w.as_of, w.current_start, w.current_end, tuple(rows), unknown)
