"""Evidence store the claim-level gate verifies against.

HACKATHON-BUILT — Meta Global AI Developer Hackathon (Oct 26 – Nov 4, 2026).

The gate never trusts a model's memory. Every claim is checked against an
``EvidenceStore`` built from records MaudeSignal already holds (openFDA MAUDE
events + the 510(k) device catalog). The store is a plain in-memory object so
the gate is deterministic and unit-testable without a database.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass, field

_WS = re.compile(r"\s+")
_NON_WORD_EDGE = re.compile(r"^[^\w]+|[^\w]+$")


def normalize_text(text: str) -> str:
    """Normalize text for verbatim-quote matching.

    Lower-cases, collapses whitespace, unifies curly quotes/dashes, and strips
    leading/trailing punctuation. It does NOT stem, paraphrase or drop words:
    a quote that changes any word still fails.
    """
    t = (
        text.replace("’", "'")
        .replace("‘", "'")
        .replace("“", '"')
        .replace("”", '"')
        .replace("–", "-")
        .replace("—", "-")
    )
    t = _WS.sub(" ", t).strip().lower()
    return _NON_WORD_EDGE.sub("", t)


@dataclass(frozen=True)
class EvidenceRecord:
    """One adverse-event record (a MAUDE report) usable as evidence."""

    report_id: str
    product_code: str
    event_type: str | None = None
    date_received: str | None = None  # YYYYMMDD, as openFDA returns it
    text: str = ""  # narrative + manufacturer narrative
    manufacturer: str | None = None
    brand_name: str | None = None

    @property
    def normalized_text(self) -> str:
        """Normalized narrative used for quote matching."""
        return normalize_text(self.text)


@dataclass(frozen=True)
class DeviceRef:
    """One cleared device from the 510(k) catalog."""

    k_number: str
    product_code: str
    device_name: str
    company_name: str | None = None


@dataclass
class EvidenceStore:
    """In-memory index over evidence records and catalog devices."""

    records: list[EvidenceRecord] = field(default_factory=list)
    devices: list[DeviceRef] = field(default_factory=list)

    def __post_init__(self) -> None:
        """Build lookup indexes."""
        self._by_id = {r.report_id: r for r in self.records}
        self._by_k = {d.k_number.upper(): d for d in self.devices}

    @classmethod
    def from_iterables(
        cls, records: Iterable[EvidenceRecord], devices: Iterable[DeviceRef] = ()
    ) -> EvidenceStore:
        """Build a store from any iterables."""
        return cls(records=list(records), devices=list(devices))

    def record(self, report_id: str) -> EvidenceRecord | None:
        """Return the record with this MAUDE report id, if present."""
        return self._by_id.get(report_id)

    def device(self, k_number: str) -> DeviceRef | None:
        """Return the catalog device with this 510(k) number, if present."""
        return self._by_k.get(k_number.upper())

    def select(
        self,
        *,
        product_code: str | None = None,
        event_type: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
    ) -> list[EvidenceRecord]:
        """Return records matching every given filter (inclusive date bounds)."""
        out: list[EvidenceRecord] = []
        for r in self.records:
            if product_code and r.product_code != product_code:
                continue
            if event_type and (r.event_type or "").lower() != event_type.lower():
                continue
            if date_from and (r.date_received or "") < date_from:
                continue
            if date_to and (r.date_received or "99999999") > date_to:
                continue
            out.append(r)
        return out

    def find_quote(self, quote: str) -> list[str]:
        """Return ids of every record whose narrative contains the quote verbatim."""
        q = normalize_text(quote)
        if not q:
            return []
        return [r.report_id for r in self.records if q in r.normalized_text]
