"""Data-as-of + reporting-delay banner text (PRD-23).

HACKATHON-BUILT — Meta Global AI Developer Hackathon (Oct 26 – Nov 4, 2026), 2026-11-03.

The same words as ``web/src/pms/DataAsOf.tsx``. Every date is read from stored data or
from the live answer; "today" is never used as a data date.
"""

from __future__ import annotations

from dataclasses import dataclass

from maudesignal.storage.database import Database

DELAY_SENTENCE = (
    "OpenFDA republishes weekly and reports arrive with delay — recent months may show few "
    "or no reports because of reporting delay, not because risk is zero."
)


def iso_day(raw: str | None) -> str | None:
    """``20260831`` / ``2026-08-31`` / a timestamp → ``2026-08-31`` (None stays None)."""
    if not raw:
        return None
    digits = raw.replace("-", "")[:8]
    if len(digits) == 8 and digits.isdigit():
        return f"{digits[:4]}-{digits[4:6]}-{digits[6:8]}"
    return raw


@dataclass(frozen=True)
class AsOf:
    """The three dates of the banner.

    Attributes:
        latest: Latest report date behind the figures (ISO day), or None.
        snapshot: The stored snapshot window in words, or None.
        live: When a live openFDA query was made, or None when nothing live was asked.
    """

    latest: str | None
    snapshot: str | None
    live: str | None = None


def as_of_text(a: AsOf) -> str:
    """The banner as one paragraph (exports print exactly this)."""
    return " ".join(
        [
            f"Data as of: {a.latest or 'not stated'}.",
            DELAY_SENTENCE,
            f"Stored snapshot: {a.snapshot or 'not stated'}.",
            f"Live check: {a.live or 'none on this page'}.",
        ]
    )


def stored_as_of(db: Database, product_code: str | None = None, live: str | None = None) -> AsOf:
    """The banner dates for the stored reports (optionally one product code).

    Args:
        db: The database the figures were computed from.
        product_code: Restrict the window to one code.
        live: When a live openFDA check was made for this page, if any.

    Returns:
        The latest stored ``date_received`` and the stored window in words.
    """
    rows = db.list_event_facts(product_code)
    dates = sorted(d for _rid, _code, d, _et in rows if d)
    if not dates:
        return AsOf(latest=None, snapshot="no stored reports", live=live)
    lo, hi = iso_day(dates[0]), iso_day(dates[-1])
    who = f" for {product_code}" if product_code else ""
    return AsOf(
        latest=hi,
        snapshot=f"{lo} to {hi} ({len(dates)} stored MAUDE reports{who})",
        live=live,
    )
