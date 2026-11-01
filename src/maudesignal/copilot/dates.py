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

from maudesignal.gate.claims import normalize_ymd
from maudesignal.gate.evidence import EvidenceStore
from maudesignal.gate.gate import DateShift

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


def recall_window(store: EvidenceStore, product_code: str | None) -> Window | None:
    """Stored recall-date (``date_initiated``) window for one product code (None: no dates)."""
    code = product_code.strip().upper() if product_code else None
    dates = [
        r.date_initiated
        for r in store.recalls
        if r.date_initiated and (code is None or r.product_code.upper() == code)
    ]
    if not dates:
        return None
    return Window(min(dates), max(dates), len(dates))


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

    def shift(self) -> DateShift | None:
        """The moved range, for the claim gate (None unless the range was moved)."""
        if not (self.adjusted and self.date_from and self.date_to):
            return None
        return DateShift(
            self.requested_from or "", self.requested_to or "", self.date_from, self.date_to
        )


def _shift_year(d: date, year: int) -> date:
    try:
        return d.replace(year=year)
    except ValueError:  # 29 February in a non-leap year
        return d.replace(year=year, day=28)


def _check(
    window: Window | None,
    who: str,
    date_from: str | None,
    date_to: str | None,
    *,
    may_shift: bool = True,
) -> RangeCheck:
    """Core of the range guards (``who`` names the data in the plural: "stored LLZ reports")."""
    date_from, date_to = normalize_ymd(date_from), normalize_ymd(date_to)
    plain = RangeCheck(date_from, date_to)
    if (not date_from and not date_to) or window is None:
        return plain
    lo, hi = window.earliest, window.latest
    if (date_from or "00000000") <= hi and (date_to or "99999999") >= lo:
        return plain  # overlaps the stored data
    asked = f"{_iso(date_from) if date_from else '...'} to {_iso(date_to) if date_to else '...'}"
    covers = f"{_iso(lo)} to {_iso(hi)}"
    d_from = _parse(date_from) if date_from else None
    d_to = _parse(date_to) if date_to else None
    lo_year, hi_year = int(lo[:4]), int(hi[:4])
    # The one correction made is the model's usual slip: the year before the data's latest
    # year. A range is moved forward by exactly one year, and only when the moved range lies
    # fully inside the stored window and neither requested year is a year the data covers.
    # Anything else (a later year, an older one, two or more years off) is answered "no stored
    # report in that range".
    if (
        may_shift
        and d_from is not None
        and d_to is not None
        and d_from <= d_to
        and not (lo_year <= d_from.year <= hi_year)
        and not (lo_year <= d_to.year <= hi_year)
        and d_from.year + 1 == hi_year
        and d_to.year + 1 == hi_year
    ):
        nf = _ymd(_shift_year(d_from, d_from.year + 1))
        nt = _ymd(_shift_year(d_to, d_to.year + 1))
        if lo <= nf <= nt <= hi:
            return RangeCheck(
                nf,
                nt,
                adjusted=True,
                window=window,
                requested_from=date_from,
                requested_to=date_to,
                note=(
                    f"No {who.removesuffix('s')} is dated in {asked}; the {who} run {covers}. "
                    f"This result is for {_iso(nf)} to {_iso(nt)}, the same dates one year "
                    "later. Say which dates were used."
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
            f"No {who.removesuffix('s')} is dated in {asked}; the {who} run {covers}. "
            "Say exactly that; do not report it as 0 reports."
        ),
    )


def check_range(
    store: EvidenceStore,
    product_code: str | None,
    date_from: str | None,
    date_to: str | None,
) -> RangeCheck:
    """Guard a report-date range against the stored data window.

    * No dates, or a range that overlaps the stored reports of the product code (of the
      whole store when the code has none): used as asked. ISO dates are normalised.
    * Both bounds given, entirely outside the window, and neither bound's year is within the
      years the data covers: moved to the same dates in the latest stored year when that
      overlaps the data (``adjusted``), e.g. LLZ 20250825..20250831 -> 20260825..20260831.
    * Otherwise entirely outside (including any range in a year the data covers): ``no_data``,
      a truthful "no stored report is dated in that range; they run X to Y", never a count.
    """
    scoped = stored_window(store, product_code) if product_code else None
    window = scoped or stored_window(store)
    who = f"stored {product_code} reports" if scoped and product_code else "stored reports"
    return _check(window, who, date_from, date_to, may_shift=scoped is not None)


def check_recall_range(
    store: EvidenceStore,
    product_code: str | None,
    date_from: str | None,
    date_to: str | None,
) -> RangeCheck:
    """The same guard for recall dates (``date_initiated``); only a code with stored recalls.

    Recall dates legitimately go back many years, so a range is flagged only when it lies
    entirely outside the stored recall dates of that code, and it is never moved to another
    year (a recall of 2015 is not an answer about 2026).
    """
    window = recall_window(store, product_code) if product_code else None
    who = f"stored {product_code} recalls"
    return _check(window, who, date_from, date_to, may_shift=False)


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
