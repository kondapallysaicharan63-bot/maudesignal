"""Today's date, the stored data window, and the date-range guard for copilot tools.

HACKATHON-BUILT — Meta Global AI Developer Hackathon (Oct 26 – Nov 4, 2026).

On the live site, "Why did reports for LLZ jump in the last week of August?" made the
model query 2025-08-25..2025-08-31 (its own guess of the year) and answer "0 reports",
although the stored LLZ reports run 2026-07-01..2026-08-31. Two deterministic fixes live
here:

* :func:`render_date_context` fills the date-context block of the ``safety-copilot`` Skill
  with today's date (UTC) and the stored data window, so the model resolves relative dates
  against the data instead of guessing;
* :func:`check_range` is the tool-layer guard: a requested report-date range that lies
  entirely outside the stored reports of that product code is moved to the same dates in
  the data's year when that lands inside the data, and otherwise flagged as "no stored data
  for that range" with the dates the data covers, so the model never reads it as zero.

The instructions to the model live in ``skills/safety-copilot``; the notes below are the
deterministic facts a tool result carries.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any

from maudesignal.gate.evidence import EvidenceStore

#: Most product codes listed one by one in the date context (the rest are counted).
MAX_CONTEXT_CODES = 25


def utc_today() -> date:
    """Today's date in UTC."""
    return datetime.now(UTC).date()


def _parse(ymd: str) -> date | None:
    try:
        return datetime.strptime(ymd.strip()[:8], "%Y%m%d").date()
    except (ValueError, AttributeError):
        return None


def _ymd(d: date) -> str:
    return d.strftime("%Y%m%d")


def _iso(ymd: str) -> str:
    d = _parse(ymd)
    return d.isoformat() if d else ymd


@dataclass(frozen=True)
class Window:
    """Earliest and latest stored report date (``YYYYMMDD``) and how many reports."""

    earliest: str
    latest: str
    reports: int


def stored_window(store: EvidenceStore, product_code: str | None = None) -> Window | None:
    """Stored report-date window, for one product code or the whole store (None: no dates)."""
    code = product_code.strip().upper() if product_code else None
    dates = [
        r.date_received
        for r in store.records
        if r.date_received and (code is None or (r.product_code or "").upper() == code)
    ]
    if not dates:
        return None
    return Window(min(dates), max(dates), len(dates))


def code_windows(store: EvidenceStore) -> dict[str, Window]:
    """Stored window per product code, most reports first."""
    by: dict[str, list[str]] = {}
    for r in store.records:
        if r.product_code and r.date_received:
            by.setdefault(r.product_code.upper(), []).append(r.date_received)
    out = {c: Window(min(d), max(d), len(d)) for c, d in by.items()}
    return dict(sorted(out.items(), key=lambda kv: (-kv[1].reports, kv[0])))


@dataclass(frozen=True)
class RangeCheck:
    """Outcome of :func:`check_range` for one tool call."""

    date_from: str | None
    date_to: str | None
    adjusted: bool = False
    no_data: bool = False
    window: Window | None = None
    requested_from: str | None = None
    requested_to: str | None = None
    note: str | None = None

    def fields(self) -> dict[str, Any]:
        """Keys a tool adds to its result (empty when the range was used as asked)."""
        if not (self.adjusted or self.no_data) or self.window is None:
            return {}
        out: dict[str, Any] = {
            "requested_date_from": self.requested_from,
            "requested_date_to": self.requested_to,
            "data_covers": {"date_from": self.window.earliest, "date_to": self.window.latest},
            "date_note": self.note,
        }
        if self.adjusted:
            out["date_adjusted"] = True
        if self.no_data:
            out["no_data_for_range"] = True
        return out


def _shift_year(d: date, year: int) -> date:
    try:
        return d.replace(year=year)
    except ValueError:  # 29 February in a non-leap year
        return d.replace(year=year, day=28)


def check_range(
    store: EvidenceStore,
    product_code: str | None,
    date_from: str | None,
    date_to: str | None,
) -> RangeCheck:
    """Guard a report-date range against the stored data window.

    * No dates, or a range that overlaps the stored reports of the product code (of the
      whole store when no code is given or the code has no reports): used as asked.
    * Both bounds given, entirely outside the window, and the same month/day in the year of
      the latest stored report (or the year before) overlaps the window: moved there
      (``adjusted``), with a note the model must repeat
      (e.g. 20250825..20250831 -> 20260825..20260831 for LLZ).
    * Otherwise entirely outside: ``no_data`` with the dates the data covers, so the tool
      says "no stored data for that range" instead of returning a count of 0.
    """
    plain = RangeCheck(date_from, date_to)
    if not date_from and not date_to:
        return plain
    window = stored_window(store, product_code) or stored_window(store)
    if window is None:
        return plain
    lo, hi = window.earliest, window.latest
    start = date_from or "00000000"
    end = date_to or "99999999"
    if start <= hi and end >= lo:
        return plain  # overlaps the stored data
    covers = f"{_iso(lo)} to {_iso(hi)}"
    who = f"stored {product_code} reports" if product_code else "stored reports"
    asked = f"{_iso(date_from) if date_from else '...'} to {_iso(date_to) if date_to else '...'}"
    d_from = _parse(date_from) if date_from else None
    d_to = _parse(date_to) if date_to else None
    hi_d = _parse(hi)
    if d_from and d_to and hi_d and d_from <= d_to:
        span = d_to.year - d_from.year
        for year in (hi_d.year, hi_d.year - 1):
            if d_to.year == year:
                continue
            nf = _ymd(_shift_year(d_from, year - span))
            nt = _ymd(_shift_year(d_to, year))
            if nf <= hi and nt >= lo:
                return RangeCheck(
                    nf,
                    nt,
                    adjusted=True,
                    window=window,
                    requested_from=date_from,
                    requested_to=date_to,
                    note=(
                        f"No {who} fall in {asked}; the {who} cover {covers}. "
                        f"This result is for the same dates in {year}: "
                        f"{_iso(nf)} to {_iso(nt)}. Say which dates were used."
                    ),
                )
    return RangeCheck(
        date_from,
        date_to,
        no_data=True,
        window=window,
        requested_from=date_from,
        requested_to=date_to,
        note=(
            f"No stored data for {asked}: the {who} cover {covers}. "
            "Say that the stored data does not cover that range; do not report it as 0 reports."
        ),
    )


def render_date_context(
    template: str,
    store: EvidenceStore,
    *,
    today: date,
    sweep_window: dict[str, str] | None = None,
) -> str:
    """Fill the Skill's date-context block with today's date and the stored data window."""
    overall = stored_window(store)
    windows = code_windows(store)
    listed = list(windows.items())[:MAX_CONTEXT_CODES]
    per_code = "; ".join(
        f"{c} {_iso(w.earliest)} to {_iso(w.latest)} ({w.reports} reports)" for c, w in listed
    )
    if len(windows) > len(listed):
        per_code += f"; and {len(windows) - len(listed)} more product codes"
    sweep = "none stored"
    if sweep_window and sweep_window.get("current_start") and sweep_window.get("current_end"):
        sweep = f"openFDA week {sweep_window['current_start']} to {sweep_window['current_end']}"
        if sweep_window.get("run_date"):
            sweep += f", run on {sweep_window['run_date']}"
    values = {
        "{today}": today.isoformat(),
        "{data_from}": _iso(overall.earliest) if overall else "none stored",
        "{data_to}": _iso(overall.latest) if overall else "none stored",
        "{data_year}": overall.latest[:4] if overall else "none stored",
        "{code_windows}": per_code or "none stored",
        "{sweep}": sweep,
    }
    out = template
    for key, value in values.items():
        out = out.replace(key, value)
    return out.strip()
