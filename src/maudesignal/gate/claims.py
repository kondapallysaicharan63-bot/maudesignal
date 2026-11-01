"""Claim types the gate verifies.

HACKATHON-BUILT — Meta Global AI Developer Hackathon (Oct 26 – Nov 4, 2026).

The copilot asks the model to return its answer as sentences, each tagged with
the atomic claims it makes. Each claim is one of the types below. Anything the
model states that cannot be expressed as a checkable claim is not allowed to
carry a number, a quote, a device id or a regulation reference.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Literal

ClaimKind = Literal[
    "quote",
    "count",
    "share",
    "device",
    "record",
    "regulation",
    "recall",
    "recall_count",
    "literature",
    "source_count",
    "group_count",
]


_ISO_DAY = re.compile(r"^(\d{4})-(\d{1,2})-(\d{1,2})$")


def normalize_ymd(value: str | None) -> str | None:
    """``YYYYMMDD`` from ``YYYYMMDD``, ``YYYY-MM-DD`` or unpadded ``YYYY-M-D``.

    Anything else is returned unchanged (the claim then fails to match, as before).
    """
    if value is None:
        return None
    text = str(value).strip()
    m = _ISO_DAY.match(text)
    if m:
        return f"{m.group(1)}{int(m.group(2)):02d}{int(m.group(3)):02d}"
    return text


def _normalize_dates(claim: object) -> None:
    """Rewrite a frozen claim's ``date_from`` / ``date_to`` as ``YYYYMMDD`` (at construction)."""
    for name in ("date_from", "date_to"):
        object.__setattr__(claim, name, normalize_ymd(getattr(claim, name)))


@dataclass(frozen=True)
class QuoteClaim:
    """A verbatim quote attributed to one stored source.

    Exactly one attribution is used: ``source_id`` (a stored PubMed PMID or FDA
    recall number) when given, otherwise ``report_id`` (a MAUDE report id).
    """

    quote: str
    report_id: str | None = None
    source_id: str | None = None
    kind: ClaimKind = "quote"

    @property
    def attributed_to(self) -> str:
        """The id this quote is pinned to."""
        return self.source_id or self.report_id or ""


@dataclass(frozen=True)
class CountClaim:
    """'N reports' for a product code, optionally filtered by event type / dates."""

    product_code: str
    value: int
    event_type: str | None = None
    date_from: str | None = None
    date_to: str | None = None
    kind: ClaimKind = "count"

    def __post_init__(self) -> None:
        """Normalise the dates."""
        _normalize_dates(self)


@dataclass(frozen=True)
class ShareClaim:
    """'X% of reports for product P are <event_type>' (percent, 0–100)."""

    product_code: str
    event_type: str
    value_pct: float
    date_from: str | None = None
    date_to: str | None = None
    kind: ClaimKind = "share"

    def __post_init__(self) -> None:
        """Normalise the dates."""
        _normalize_dates(self)


@dataclass(frozen=True)
class DeviceClaim:
    """A 510(k) number asserted to belong to a product code (and optionally a name)."""

    k_number: str
    product_code: str | None = None
    device_name: str | None = None
    kind: ClaimKind = "device"


@dataclass(frozen=True)
class RecordClaim:
    """A MAUDE report id asserted to exist (optionally for a product code)."""

    report_id: str
    product_code: str | None = None
    kind: ClaimKind = "record"


@dataclass(frozen=True)
class RegulationClaim:
    """A 21 CFR section citation, e.g. '803.50'."""

    section: str
    kind: ClaimKind = "regulation"


@dataclass(frozen=True)
class RecallClaim:
    """An FDA recall asserted to exist (optionally for a product code).

    ``recall_number`` is the product-level recall number (e.g. ``Z-0186-2027``)
    or the recall event number (``res_event_number``) from openFDA.
    """

    recall_number: str
    product_code: str | None = None
    kind: ClaimKind = "recall"


@dataclass(frozen=True)
class RecallCountClaim:
    """'N recalls' for a product code, optionally by event_date_initiated window."""

    product_code: str
    value: int
    date_from: str | None = None
    date_to: str | None = None
    kind: ClaimKind = "recall_count"

    def __post_init__(self) -> None:
        """Normalise the dates."""
        _normalize_dates(self)


@dataclass(frozen=True)
class LiteratureClaim:
    """A PubMed article (PMID) asserted to exist in stored sources (optionally its year)."""

    pmid: str
    year: int | None = None
    kind: ClaimKind = "literature"


@dataclass(frozen=True)
class SourceCountClaim:
    """'N reports from <source>' for a product code, optionally within dates.

    ``source`` is a report source ("manufacturer", "user facility", "voluntary",
    "distributor") or "non-manufacturer" (every known source except manufacturer).
    """

    product_code: str
    source: str
    value: int
    date_from: str | None = None
    date_to: str | None = None
    kind: ClaimKind = "source_count"

    def __post_init__(self) -> None:
        """Normalise the dates."""
        _normalize_dates(self)


@dataclass(frozen=True)
class GroupCountClaim:
    """'N reports describe <label>', with the report ids that make up the group.

    The gate recomputes ``value`` as the number of distinct listed ids and checks
    that every id is a stored report of ``product_code`` (and inside the dates, when
    given), so a group label can never carry a count the listed reports do not back.
    """

    product_code: str
    label: str
    report_ids: tuple[str, ...]
    value: int
    date_from: str | None = None
    date_to: str | None = None
    kind: ClaimKind = "group_count"

    def __post_init__(self) -> None:
        """Normalise the dates."""
        _normalize_dates(self)


Claim = (
    QuoteClaim
    | CountClaim
    | ShareClaim
    | DeviceClaim
    | RecordClaim
    | RegulationClaim
    | RecallClaim
    | RecallCountClaim
    | LiteratureClaim
    | SourceCountClaim
    | GroupCountClaim
)


def _opt_str(v: Any) -> str | None:
    """None / empty stays None; anything else becomes a stripped string."""
    if v is None:
        return None
    s = str(v).strip()
    return s or None


def normalize_pmid(pmid: str) -> str:
    """'PMID: 123' / 'pmid123' -> '123'."""
    p = pmid.strip()
    if p.lower().startswith("pmid"):
        p = p[4:].lstrip(" :")
    return p


class ClaimParseError(ValueError):
    """Raised when a claim dict is malformed."""


def claim_from_dict(d: dict[str, Any]) -> Claim:
    """Build a typed claim from a JSON-like dict (model output or fixture).

    Raises:
        ClaimParseError: unknown kind or missing / ill-typed fields.
    """
    kind = d.get("kind")
    try:
        if kind == "quote":
            report_id, source_id = _opt_str(d.get("report_id")), _opt_str(d.get("source_id"))
            if not report_id and not source_id:
                raise KeyError("report_id or source_id")
            return QuoteClaim(quote=str(d["quote"]), report_id=report_id, source_id=source_id)
        if kind == "count":
            return CountClaim(
                product_code=str(d["product_code"]),
                value=int(d["value"]),
                event_type=d.get("event_type"),
                date_from=d.get("date_from"),
                date_to=d.get("date_to"),
            )
        if kind == "share":
            return ShareClaim(
                product_code=str(d["product_code"]),
                event_type=str(d["event_type"]),
                value_pct=float(d["value_pct"]),
                date_from=d.get("date_from"),
                date_to=d.get("date_to"),
            )
        if kind == "device":
            return DeviceClaim(
                k_number=str(d["k_number"]),
                product_code=d.get("product_code"),
                device_name=d.get("device_name"),
            )
        if kind == "record":
            return RecordClaim(report_id=str(d["report_id"]), product_code=d.get("product_code"))
        if kind == "regulation":
            return RegulationClaim(section=str(d["section"]).replace("21 CFR", "").strip())
        if kind == "recall":
            return RecallClaim(
                recall_number=str(d["recall_number"]).strip(),
                product_code=_opt_str(d.get("product_code")),
            )
        if kind == "recall_count":
            return RecallCountClaim(
                product_code=str(d["product_code"]),
                value=int(d["value"]),
                date_from=_opt_str(d.get("date_from")),
                date_to=_opt_str(d.get("date_to")),
            )
        if kind == "source_count":
            return SourceCountClaim(
                product_code=str(d["product_code"]),
                source=str(d["source"]),
                value=int(d["value"]),
                date_from=_opt_str(d.get("date_from")),
                date_to=_opt_str(d.get("date_to")),
            )
        if kind == "group_count":
            ids = d["report_ids"]
            if not isinstance(ids, list | tuple):
                raise TypeError("report_ids must be a list")
            return GroupCountClaim(
                product_code=str(d["product_code"]),
                label=str(d["label"]).strip(),
                report_ids=tuple(str(i).strip() for i in ids),
                value=int(d["value"]),
                date_from=_opt_str(d.get("date_from")),
                date_to=_opt_str(d.get("date_to")),
            )
        if kind == "literature":
            year = d.get("year")
            return LiteratureClaim(
                pmid=normalize_pmid(str(d["pmid"])),
                year=None if year is None else int(year),
            )
    except (KeyError, TypeError, ValueError) as exc:
        raise ClaimParseError(f"malformed {kind!r} claim: {exc}") from exc
    raise ClaimParseError(f"unknown claim kind: {kind!r}")
