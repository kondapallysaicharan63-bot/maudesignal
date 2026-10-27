"""Evidence store the claim-level gate verifies against.

HACKATHON-BUILT — Meta Global AI Developer Hackathon (Oct 26 – Nov 4, 2026).

The gate never trusts a model's memory. Every claim is checked against an
``EvidenceStore`` built from records MaudeSignal already holds: openFDA MAUDE
events, the 510(k) device catalog, and the scattered sources fetched next to
them — openFDA device recalls, openFDA 510(k) clearance records, and PubMed
abstracts. The store is a plain in-memory object so
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
    """One cleared device: from the 510(k) catalog or a stored openFDA 510(k) record."""

    k_number: str
    product_code: str
    device_name: str
    company_name: str | None = None
    decision_date: str | None = None  # YYYY-MM-DD as openFDA 510(k) returns it
    decision_code: str | None = None
    statement_or_summary: str | None = None


@dataclass(frozen=True)
class RecallRef:
    """One openFDA device recall (product-level row of ``device/recall.json``)."""

    recall_number: str  # product_res_number, e.g. "Z-0186-2027"
    product_code: str
    event_number: str | None = None  # res_event_number (one event, many products)
    recalling_firm: str | None = None
    product_description: str = ""
    reason_for_recall: str = ""
    recall_status: str | None = None
    date_initiated: str | None = None  # YYYYMMDD
    k_numbers: tuple[str, ...] = ()

    @property
    def text(self) -> str:
        """Quotable text: product description + reason for recall."""
        return f"{self.product_description} {self.reason_for_recall}".strip()


@dataclass(frozen=True)
class LiteratureRef:
    """One stored PubMed article."""

    pmid: str
    title: str
    abstract: str = ""
    year: int | None = None
    journal: str | None = None
    product_code: str | None = None  # product code the fetch query was run for

    @property
    def text(self) -> str:
        """Quotable text: title + abstract."""
        return f"{self.title} {self.abstract}".strip()


@dataclass
class EvidenceStore:
    """In-memory index over evidence records, devices, recalls and literature.

    ``devices`` is the curated AI/ML 510(k) catalog; ``clearances`` holds
    510(k) records fetched one by one from openFDA (``device/510k.json``) and is
    consulted only when the catalog lacks a K-number.
    """

    records: list[EvidenceRecord] = field(default_factory=list)
    devices: list[DeviceRef] = field(default_factory=list)
    recalls: list[RecallRef] = field(default_factory=list)
    clearances: list[DeviceRef] = field(default_factory=list)
    literature: list[LiteratureRef] = field(default_factory=list)

    def __post_init__(self) -> None:
        """Build lookup indexes."""
        self._by_id = {r.report_id: r for r in self.records}
        self._by_k = {d.k_number.upper(): d for d in self.devices}
        self._by_k_510k = {d.k_number.upper(): d for d in self.clearances}
        self._by_pmid = {a.pmid: a for a in self.literature}
        self._recall_norm = {id(r): normalize_text(r.text) for r in self.recalls}
        self._lit_norm = {a.pmid: normalize_text(a.text) for a in self.literature}

    @classmethod
    def from_iterables(
        cls,
        records: Iterable[EvidenceRecord],
        devices: Iterable[DeviceRef] = (),
        *,
        recalls: Iterable[RecallRef] = (),
        clearances: Iterable[DeviceRef] = (),
        literature: Iterable[LiteratureRef] = (),
    ) -> EvidenceStore:
        """Build a store from any iterables."""
        return cls(
            records=list(records),
            devices=list(devices),
            recalls=list(recalls),
            clearances=list(clearances),
            literature=list(literature),
        )

    def record(self, report_id: str) -> EvidenceRecord | None:
        """Return the record with this MAUDE report id, if present."""
        return self._by_id.get(report_id)

    def device(self, k_number: str) -> DeviceRef | None:
        """Return the catalog device with this 510(k) number, if present."""
        return self._by_k.get(k_number.upper())

    def clearance(self, k_number: str) -> DeviceRef | None:
        """Return the stored openFDA 510(k) record for this K-number, if present."""
        return self._by_k_510k.get(k_number.strip().upper())

    def recalls_by_number(self, number: str) -> list[RecallRef]:
        """Recalls whose recall number or recall event number equals ``number``."""
        n = number.strip().upper()
        if not n:
            return []
        return [r for r in self.recalls if r.recall_number.upper() == n or r.event_number == n]

    def select_recalls(
        self,
        *,
        product_code: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
    ) -> list[RecallRef]:
        """Recalls matching every given filter (inclusive event_date_initiated bounds)."""
        out: list[RecallRef] = []
        for r in self.recalls:
            if product_code and r.product_code.upper() != product_code.upper():
                continue
            if date_from and (r.date_initiated or "") < date_from:
                continue
            if date_to and (r.date_initiated or "99999999") > date_to:
                continue
            out.append(r)
        return out

    def article(self, pmid: str) -> LiteratureRef | None:
        """Return the stored PubMed article with this PMID, if present."""
        return self._by_pmid.get(pmid.strip())

    def source_text(self, source_id: str) -> tuple[str, str] | None:
        """Return ``(normalized_text, label)`` for a stored literature or recall source.

        ``source_id`` is a PMID (optionally prefixed ``PMID:``) or a recall /
        recall event number.
        """
        sid = source_id.strip()
        pmid = sid[4:].lstrip(" :") if sid.lower().startswith("pmid") else sid
        if pmid in self._lit_norm:
            return self._lit_norm[pmid], f"PMID {pmid}"
        matches = self.recalls_by_number(sid)
        if matches:
            text = " ".join(self._recall_norm[id(r)] for r in matches)
            return text, f"recall {sid}"
        return None

    def find_quote_in_sources(self, quote: str) -> list[str]:
        """Labels of every stored literature / recall source containing the quote."""
        q = normalize_text(quote)
        if not q:
            return []
        out = [f"PMID {p}" for p, t in self._lit_norm.items() if q in t]
        out += [f"recall {r.recall_number}" for r in self.recalls if q in self._recall_norm[id(r)]]
        return out

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
