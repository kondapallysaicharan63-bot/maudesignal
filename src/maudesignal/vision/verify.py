"""Accuracy check for 510(k) summary readings. Deterministic, no model calls.

HACKATHON-BUILT — Meta Global AI Developer Hackathon (Oct 26 – Nov 4, 2026).

Every field ends in exactly one state:

* ``VERIFIED`` — the two independent reads agree AND every available independent
  source agrees (openFDA 510(k) record; the PDF's own text layer for verbatim
  fields; openFDA existence for predicate K-numbers). When no independent source
  covers a field, two clear agreeing reads are the basis, and the verdict says so.
* ``CONFLICT`` — the reads disagree, or they agree with each other but not with
  an independent source. Both values are shown and the field is flagged
  "low clarity — human check". Nothing is silently resolved.
* ``UNVERIFIABLE`` — a read marked the field illegible, neither read found it,
  or it is only partly legible with no independent source to confirm it.

The two reads are never merged, and the model is never asked to break a tie.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from difflib import SequenceMatcher
from typing import Any, Literal

from maudesignal.common.device_ids import (  # noqa: F401  (re-exported)
    norm_company as norm_company,
)
from maudesignal.common.device_ids import (
    norm_text as norm_text,
)
from maudesignal.common.device_ids import (
    normalize_k_number,
)
from maudesignal.vision.fda_pdf import find_k_numbers, is_k_number
from maudesignal.vision.openfda510k import Fda510kRecord
from maudesignal.vision.reader import (
    LIST_FIELDS,
    READ_FIELDS,
    VERBATIM_FIELDS,
    FieldReading,
    Reading,
)

Status = Literal["VERIFIED", "CONFLICT", "UNVERIFIABLE"]
Outcome = Literal["pass", "fail", "n/a"]
HUMAN_CHECK = "low clarity — human check"
SOURCE_TYPE = "510k_summary_reading"

# Fields openFDA can confirm, and the record attribute that holds the value.
OPENFDA_FIELDS: dict[str, str] = {
    "k_number": "k_number",
    "applicant": "applicant",
    "device_name": "device_name",
    "product_code": "product_code",
    "decision_date": "decision_date",
    "regulation_number": "regulation_number",
}
VERBATIM_AGREE = 0.95  # SequenceMatcher ratio between reads, after normalization
SUMMARY_AGREE = 0.5  # token Jaccard for the (condensed) technology summary
NAME_AGREE = 0.9
TEXT_LAYER_MATCH = 0.9  # share of the read's 4-word shingles found in the text layer

_MONTHS = {
    m: i
    for i, names in enumerate(
        [
            ("jan", "january"),
            ("feb", "february"),
            ("mar", "march"),
            ("apr", "april"),
            ("may",),
            ("jun", "june"),
            ("jul", "july"),
            ("aug", "august"),
            ("sep", "sept", "september"),
            ("oct", "october"),
            ("nov", "november"),
            ("dec", "december"),
        ],
        start=1,
    )
    for m in names
}


# ---------------------------------------------------------------------------
# Normalization
# ---------------------------------------------------------------------------


def norm_date(value: str) -> str:
    """ISO ``YYYY-MM-DD`` from common printed formats; ``""`` when not a date."""
    v = (value or "").strip()
    if not v:
        return ""
    m = re.fullmatch(r"(\d{4})-(\d{1,2})-(\d{1,2})", v) or re.fullmatch(r"(\d{4})(\d{2})(\d{2})", v)
    if m:
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
    else:
        m = re.fullmatch(r"(\d{1,2})[/.\-](\d{1,2})[/.\-](\d{2,4})", v)
        if m:
            mo, d, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
            y = y + 2000 if y < 70 else (y + 1900 if y < 100 else y)
        else:
            m = re.fullmatch(r"([A-Za-z]+)\.?\s+(\d{1,2}),?\s+(\d{4})", v) or None
            if m and m.group(1).casefold() in _MONTHS:
                mo, d, y = _MONTHS[m.group(1).casefold()], int(m.group(2)), int(m.group(3))
            else:
                m = re.fullmatch(r"(\d{1,2})\s+([A-Za-z]+)\.?,?\s+(\d{4})", v)
                if not m or m.group(2).casefold() not in _MONTHS:
                    return ""
                d, mo, y = int(m.group(1)), _MONTHS[m.group(2).casefold()], int(m.group(3))
    try:
        return date(y, mo, d).isoformat()
    except ValueError:
        return ""


def norm_regulation(value: str) -> str:
    """``892.2050`` from ``21 CFR 892.2050`` / ``§ 892.2050``."""
    m = re.search(r"(\d{3,4}\.\d{2,4})", value or "")
    return m.group(1) if m else norm_text(value)


def norm_k(value: str) -> str:
    """Normalized K-number, or the cleaned text when it is not one."""
    try:
        return normalize_k_number(value)
    except ValueError:
        return norm_text(value)


def norm_predicates(values: list[str]) -> list[str]:
    """Predicate K-numbers when printed, else normalized names; sorted, unique."""
    out: set[str] = set()
    for v in values:
        ks = find_k_numbers(v)
        if ks:
            out.update(ks)
        elif norm_text(v):
            out.add(norm_text(v))
    return sorted(out)


def _shingles(text: str, n: int = 4) -> set[tuple[str, ...]]:
    words = norm_text(text).split()
    if len(words) < n:
        return {tuple(words)} if words else set()
    return {tuple(words[i : i + n]) for i in range(len(words) - n + 1)}


def _jaccard(a: str, b: str) -> float:
    sa, sb = set(norm_text(a).split()), set(norm_text(b).split())
    if not sa and not sb:
        return 1.0
    return len(sa & sb) / len(sa | sb)


def _ratio(a: str, b: str) -> float:
    return SequenceMatcher(None, a, b, autojunk=False).ratio()


# ---------------------------------------------------------------------------
# Comparison
# ---------------------------------------------------------------------------


def compare_values(name: str, a: str | list[str], b: str | list[str]) -> tuple[bool, float]:
    """Do two values of field ``name`` agree? Returns (agree, similarity 0..1)."""
    if name in LIST_FIELDS:
        la = norm_predicates(a if isinstance(a, list) else [a])
        lb = norm_predicates(b if isinstance(b, list) else [b])
        if not la and not lb:
            return True, 1.0
        sim = len(set(la) & set(lb)) / len(set(la) | set(lb))
        return la == lb, round(sim, 3)
    sa = a if isinstance(a, str) else "; ".join(a)
    sb = b if isinstance(b, str) else "; ".join(b)
    if name == "k_number":
        na, nb = norm_k(sa), norm_k(sb)
    elif name == "product_code":
        na, nb = norm_text(sa).upper(), norm_text(sb).upper()
    elif name == "decision_date":
        na, nb = norm_date(sa) or norm_text(sa), norm_date(sb) or norm_text(sb)
    elif name == "regulation_number":
        na, nb = norm_regulation(sa), norm_regulation(sb)
    elif name == "applicant":
        na, nb = norm_company(sa), norm_company(sb)
    else:
        na, nb = norm_text(sa), norm_text(sb)
    if name == "technology_summary":
        sim = _jaccard(sa, sb)
        return sim >= SUMMARY_AGREE, round(sim, 3)
    sim = 1.0 if na == nb else _ratio(na, nb)
    if name in VERBATIM_FIELDS:
        return sim >= VERBATIM_AGREE, round(sim, 3)
    if name in ("device_name", "applicant"):
        return sim >= NAME_AGREE, round(sim, 3)
    return na == nb, round(sim, 3)


def matches_openfda(name: str, value: str, rec: Fda510kRecord) -> tuple[bool, str]:
    """Compare a read value with the openFDA record. Returns (match, openFDA value)."""
    ref = str(getattr(rec, OPENFDA_FIELDS[name]))
    if name == "applicant":
        na, nb = norm_company(value), norm_company(ref)
        ok = na == nb or (bool(na) and bool(nb) and (na in nb or nb in na))
        return ok or _ratio(na, nb) >= NAME_AGREE, ref
    if name == "device_name":
        na, nb = norm_text(value), norm_text(ref)
        ok = na == nb or (bool(na) and bool(nb) and (na in nb or nb in na))
        return ok or _ratio(na, nb) >= NAME_AGREE, ref
    agree, _ = compare_values(name, value, ref)
    return agree, ref


def in_text_layer(value: str, text_pages: list[str]) -> float:
    """Share of the value's 4-word shingles present in the PDF text layer (0..1)."""
    want = _shingles(value)
    if not want:
        return 0.0
    have = _shingles(" ".join(text_pages))
    return round(len(want & have) / len(want), 3)


# ---------------------------------------------------------------------------
# Verdicts
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Check:
    """One independent check of a field."""

    source: str  # "two_reads" | "openfda" | "text_layer" | "openfda_predicates"
    outcome: Outcome
    detail: str

    def to_dict(self) -> dict[str, str]:
        """JSON form."""
        return {"source": self.source, "outcome": self.outcome, "detail": self.detail}


@dataclass
class FieldVerdict:
    """Final state of one field."""

    name: str
    status: Status
    value: str | list[str] | None  # the agreed value; None when not VERIFIED
    read_a: FieldReading
    read_b: FieldReading
    reads_agree: bool | None
    similarity: float
    checks: list[Check] = field(default_factory=list)
    note: str = ""

    @property
    def basis(self) -> str:
        """Plain-English summary of what supports a VERIFIED field."""
        passed = [c.source for c in self.checks if c.outcome == "pass"]
        return " + ".join(passed) if passed else "-"

    def to_dict(self) -> dict[str, Any]:
        """JSON form."""
        return {
            "name": self.name,
            "status": self.status,
            "value": self.value,
            "read_a": self.read_a.to_dict(),
            "read_b": self.read_b.to_dict(),
            "reads_agree": self.reads_agree,
            "similarity": self.similarity,
            "checks": [c.to_dict() for c in self.checks],
            "note": self.note,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> FieldVerdict:
        """Inverse of :meth:`to_dict`."""
        status = str(d.get("status"))
        if status not in ("VERIFIED", "CONFLICT", "UNVERIFIABLE"):
            status = "UNVERIFIABLE"
        return cls(
            name=str(d["name"]),
            status=status,  # type: ignore[arg-type]
            value=d.get("value"),
            read_a=FieldReading.from_dict(d.get("read_a") or {}),
            read_b=FieldReading.from_dict(d.get("read_b") or {}),
            reads_agree=d.get("reads_agree"),
            similarity=float(d.get("similarity") or 0.0),
            checks=[
                Check(str(c["source"]), c["outcome"], str(c.get("detail") or ""))
                for c in d.get("checks") or []
            ],
            note=str(d.get("note") or ""),
        )


@dataclass
class VerifiedSummary:
    """A 510(k) summary reading after the accuracy check."""

    k_number: str
    fields: list[FieldVerdict]
    reads: tuple[Reading, Reading]
    openfda: Fda510kRecord | None
    has_text_layer: bool
    pages_read: int
    page_count: int
    pdf_url: str = ""
    created_at: str = field(
        default_factory=lambda: datetime.now(UTC).replace(microsecond=0).isoformat()
    )
    thumbnails: list[str] = field(default_factory=list)

    @property
    def compared(self) -> list[FieldVerdict]:
        """Fields where at least one read found something (agreement denominator)."""
        return [f for f in self.fields if f.reads_agree is not None]

    @property
    def agreement_pct(self) -> float:
        """Share of compared fields on which the two reads agree, in percent."""
        comp = self.compared
        if not comp:
            return 0.0
        return round(100.0 * sum(1 for f in comp if f.reads_agree) / len(comp), 1)

    def count(self, status: Status) -> int:
        """Number of fields in ``status``."""
        return sum(1 for f in self.fields if f.status == status)

    @property
    def cost_usd(self) -> float:
        """Muse Spark cost of both reads."""
        return round(sum(r.cost_usd for r in self.reads), 6)

    @property
    def product_code(self) -> str | None:
        """Verified product code, else openFDA's, else None."""
        for f in self.fields:
            if f.name == "product_code" and f.status == "VERIFIED" and isinstance(f.value, str):
                return f.value.upper()
        return self.openfda.product_code if self.openfda else None

    def field(self, name: str) -> FieldVerdict:
        """Verdict for one field."""
        for f in self.fields:
            if f.name == name:
                return f
        raise KeyError(name)

    def to_dict(self) -> dict[str, Any]:
        """JSON form (``demo/vision/510k-<K>.json``)."""
        return {
            "kind": SOURCE_TYPE,
            "k_number": self.k_number,
            "created_at": self.created_at,
            "pdf_url": self.pdf_url,
            "page_count": self.page_count,
            "pages_read": self.pages_read,
            "has_text_layer": self.has_text_layer,
            "agreement_pct": self.agreement_pct,
            "counts": {s: self.count(s) for s in ("VERIFIED", "CONFLICT", "UNVERIFIABLE")},
            "cost_usd": self.cost_usd,
            "openfda": self.openfda.to_dict() if self.openfda else None,
            "fields": [f.to_dict() for f in self.fields],
            "reads": [r.to_dict() for r in self.reads],
            "thumbnails": self.thumbnails,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> VerifiedSummary:
        """Inverse of :meth:`to_dict`."""
        reads = [Reading.from_dict(r) for r in d.get("reads") or []]
        while len(reads) < 2:
            reads.append(Reading(label="?", fields={}, page_order=[], max_side=0))
        ofda = d.get("openfda")
        return cls(
            k_number=str(d.get("k_number") or ""),
            fields=[FieldVerdict.from_dict(f) for f in d.get("fields") or []],
            reads=(reads[0], reads[1]),
            openfda=Fda510kRecord.from_dict(ofda) if isinstance(ofda, dict) else None,
            has_text_layer=bool(d.get("has_text_layer")),
            pages_read=int(d.get("pages_read") or 0),
            page_count=int(d.get("page_count") or 0),
            pdf_url=str(d.get("pdf_url") or ""),
            created_at=str(d.get("created_at") or ""),
            thumbnails=[str(t) for t in d.get("thumbnails") or []],
        )


PredicateLookup = Callable[[list[str]], set[str]]


def _verdict_for(
    name: str,
    a: FieldReading,
    b: FieldReading,
    *,
    openfda: Fda510kRecord | None,
    text_pages: list[str] | None,
    predicate_lookup: PredicateLookup | None,
) -> FieldVerdict:
    # 1. Illegible / absent: nothing to verify.
    if not a.present and not b.present:
        note = "not found on the pages read"
        if "illegible" in (a.legibility, b.legibility):
            note = "illegible on the pages read"
        checks = []
        if openfda is not None and name in OPENFDA_FIELDS:
            ref = str(getattr(openfda, OPENFDA_FIELDS[name]))
            checks.append(Check("openfda", "n/a", f"openFDA has {ref!r} (reference only)"))
        return FieldVerdict(name, "UNVERIFIABLE", None, a, b, None, 0.0, checks, note)
    if "illegible" in (a.legibility, b.legibility):
        agree, sim = compare_values(name, a.value, b.value)
        return FieldVerdict(
            name, "UNVERIFIABLE", None, a, b, agree, sim, [], f"illegible in a read; {HUMAN_CHECK}"
        )

    # 2. Two independent reads.
    agree, sim = compare_values(name, a.value, b.value)
    checks = [Check("two_reads", "pass" if agree else "fail", f"similarity {sim:.2f}")]
    if not agree:
        return FieldVerdict(
            name, "CONFLICT", None, a, b, False, sim, checks, f"reads disagree; {HUMAN_CHECK}"
        )
    value = a.value

    # 3. Independent sources.
    conflict = ""
    if openfda is not None and name in OPENFDA_FIELDS and isinstance(value, str):
        ok, ref = matches_openfda(name, value, openfda)
        if ref:
            checks.append(Check("openfda", "pass" if ok else "fail", f"openFDA: {ref!r}"))
            if not ok:
                conflict = f"reads agree but openFDA has {ref!r}; {HUMAN_CHECK}"
    if name in VERBATIM_FIELDS and isinstance(value, str):
        if text_pages is not None:
            share = in_text_layer(value, text_pages)
            ok = share >= TEXT_LAYER_MATCH
            checks.append(
                Check("text_layer", "pass" if ok else "fail", f"{share:.0%} found in text layer")
            )
            if not ok and not conflict:
                conflict = f"not found verbatim in the PDF text layer; {HUMAN_CHECK}"
        else:
            checks.append(Check("text_layer", "n/a", "PDF has no text layer (scanned)"))
    if name in LIST_FIELDS and predicate_lookup is not None and isinstance(value, list):
        ks = [k for k in norm_predicates(value) if is_k_number(k)]
        if ks:
            found = predicate_lookup(ks)
            missing = [k for k in ks if k not in found]
            checks.append(
                Check(
                    "openfda_predicates",
                    "fail" if missing else "pass",
                    (
                        f"missing in openFDA: {', '.join(missing)}"
                        if missing
                        else f"{len(ks)} predicate K-number(s) exist in openFDA"
                    ),
                )
            )
            if missing and not conflict:
                conflict = f"predicate not in openFDA: {', '.join(missing)}; {HUMAN_CHECK}"
    if conflict:
        return FieldVerdict(name, "CONFLICT", None, a, b, True, sim, checks, conflict)

    independent = [c for c in checks if c.source != "two_reads" and c.outcome == "pass"]
    partly = "partly_legible" in (a.legibility, b.legibility)
    if partly and not independent:
        return FieldVerdict(
            name,
            "UNVERIFIABLE",
            None,
            a,
            b,
            True,
            sim,
            checks,
            f"partly legible and no independent source; {HUMAN_CHECK}",
        )
    note = "" if independent else "two independent reads agree (no other source covers it)"
    return FieldVerdict(name, "VERIFIED", value, a, b, True, sim, checks, note)


def verify_readings(
    read_a: Reading,
    read_b: Reading,
    *,
    k_number: str,
    openfda: Fda510kRecord | None,
    text_pages: list[str] | None,
    predicate_lookup: PredicateLookup | None = None,
    page_count: int = 0,
    pdf_url: str = "",
) -> VerifiedSummary:
    """Run the accuracy check over two independent reads.

    Args:
        read_a: First read.
        read_b: Second, independent read.
        k_number: The K-number the PDF was fetched for.
        openfda: The openFDA 510(k) record for ``k_number`` (None if unavailable).
        text_pages: The PDF text layer per page, or None when it has none (scanned).
        predicate_lookup: Returns which of the given K-numbers exist in openFDA.
        page_count: Total pages in the PDF.
        pdf_url: Source URL.

    Returns:
        Per-field verdicts plus agreement statistics.
    """
    verdicts = [
        _verdict_for(
            name,
            read_a.fields.get(name, FieldReading("", 0, "not_present")),
            read_b.fields.get(name, FieldReading("", 0, "not_present")),
            openfda=openfda,
            text_pages=text_pages,
            predicate_lookup=predicate_lookup,
        )
        for name in READ_FIELDS
    ]
    return VerifiedSummary(
        k_number=normalize_k_number(k_number),
        fields=verdicts,
        reads=(read_a, read_b),
        openfda=openfda,
        has_text_layer=text_pages is not None,
        pages_read=len(read_a.page_order),
        page_count=page_count,
        pdf_url=pdf_url,
    )


def store_summary(db: Any, summary: VerifiedSummary) -> str:
    """Persist a checked reading as an ``ExternalSourceRecord`` (idempotent per K-number).

    Only VERIFIED values appear in the searchable columns; every verdict (with both
    reads for conflicts) is kept in ``raw_json``.

    Returns:
        The record id.
    """
    record_id = f"{SOURCE_TYPE}:{summary.k_number}"

    def verified(name: str) -> str | None:
        f = summary.field(name)
        return f.value if f.status == "VERIFIED" and isinstance(f.value, str) else None

    db.upsert_external_source(
        record_id=record_id,
        source_type=SOURCE_TYPE,
        source_id=summary.k_number,
        product_code=summary.product_code,
        title=verified("device_name"),
        authors=verified("applicant"),
        publication_date=verified("decision_date"),
        abstract=verified("indications_for_use"),
        url=summary.pdf_url or None,
        raw_payload={k: v for k, v in summary.to_dict().items() if k != "thumbnails"},
    )
    return record_id
