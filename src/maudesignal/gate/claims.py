"""Claim types the gate verifies.

HACKATHON-BUILT — Meta Global AI Developer Hackathon (Oct 26 – Nov 4, 2026).

The copilot asks the model to return its answer as sentences, each tagged with
the atomic claims it makes. Each claim is one of the types below. Anything the
model states that cannot be expressed as a checkable claim is not allowed to
carry a number, a quote, a device id or a regulation reference.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

ClaimKind = Literal["quote", "count", "share", "device", "record", "regulation"]


@dataclass(frozen=True)
class QuoteClaim:
    """A verbatim quote attributed to a specific MAUDE report."""

    quote: str
    report_id: str
    kind: ClaimKind = "quote"


@dataclass(frozen=True)
class CountClaim:
    """'N reports' for a product code, optionally filtered by event type / dates."""

    product_code: str
    value: int
    event_type: str | None = None
    date_from: str | None = None
    date_to: str | None = None
    kind: ClaimKind = "count"


@dataclass(frozen=True)
class ShareClaim:
    """'X% of reports for product P are <event_type>' (percent, 0–100)."""

    product_code: str
    event_type: str
    value_pct: float
    date_from: str | None = None
    date_to: str | None = None
    kind: ClaimKind = "share"


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


Claim = QuoteClaim | CountClaim | ShareClaim | DeviceClaim | RecordClaim | RegulationClaim


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
            return QuoteClaim(quote=str(d["quote"]), report_id=str(d["report_id"]))
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
    except (KeyError, TypeError, ValueError) as exc:
        raise ClaimParseError(f"malformed {kind!r} claim: {exc}") from exc
    raise ClaimParseError(f"unknown claim kind: {kind!r}")
