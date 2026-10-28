"""Claim-level citation gate.

HACKATHON-BUILT — Meta Global AI Developer Hackathon (Oct 26 – Nov 4, 2026).
The ``regulatory-citation-verifier`` Skill spec existed before the hackathon but
had zero call sites; this module is the enforcement, written during the event.

What it guarantees, for every sentence the copilot shows a user:

* every **number** is recomputed from stored records and must match exactly
  (counts) or within 0.5 percentage points (shares);
* every **quote** must appear verbatim in the narrative of the report — or the
  stored PubMed abstract / FDA recall text — it is attributed to (a real quote
  pinned to the wrong source is blocked);
* every **510(k) number** must exist in the catalog (or, failing that, in the
  stored openFDA 510(k) records) and belong to the stated product code / device;
* every **recall number** must exist in the stored openFDA recalls (and match
  the stated product code); every **recall count** is recomputed;
* every **PMID** must exist in the stored PubMed records (and match a stated year);
* every **MAUDE report id** must exist (and match the stated product code);
* every **21 CFR section** must be in the curated allowlist (superseded QS-reg
  sections are blocked with the reason);
* a sentence that mentions a K-number, CFR section, percentage, report or recall
  count, recall number or PMID *without* a matching structured claim is blocked
  as ungrounded.

The gate is deterministic and makes no model calls.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Literal

from maudesignal.gate.cfr import CFR_SECTIONS, SUPERSEDED_SECTIONS, find_cfr_citations
from maudesignal.gate.claims import (
    Claim,
    CountClaim,
    DeviceClaim,
    LiteratureClaim,
    QuoteClaim,
    RecallClaim,
    RecallCountClaim,
    RecordClaim,
    RegulationClaim,
    ShareClaim,
    SourceCountClaim,
    normalize_pmid,
)
from maudesignal.gate.evidence import (
    NON_MANUFACTURER,
    EvidenceStore,
    normalize_source,
    normalize_text,
)

Status = Literal["pass", "block"]

SHARE_TOLERANCE_PP = 0.5

_K_RE = re.compile(r"\b[KkDd][Ee]?N?\d{6}\b")
_PCT_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(?:%|percent\b)")
_COUNT_RE = re.compile(
    r"\b(\d[\d,]*)\s+(?:\w+\s+){0,2}?"
    r"(?:reports?|events?|deaths?|injur(?:y|ies)|malfunctions?|MDRs?|records?)\b",
    re.IGNORECASE,
)
_RECALL_COUNT_RE = re.compile(r"\b(\d[\d,]*)\s+(?:[\w-]+\s+){0,2}?recalls?\b", re.IGNORECASE)
_RECALL_NO_RE = re.compile(r"\b[A-Z]-\d{4}-\d{4}\b")
_PMID_RE = re.compile(r"\bPMID\s*:?\s*(\d{1,9})\b", re.IGNORECASE)


@dataclass(frozen=True)
class ClaimVerdict:
    """Outcome for one claim."""

    claim: Claim
    status: Status
    reason: str
    evidence_ids: tuple[str, ...] = ()
    recomputed: float | None = None


@dataclass(frozen=True)
class SentenceVerdict:
    """Outcome for one sentence of an answer."""

    text: str
    status: Status
    claim_verdicts: tuple[ClaimVerdict, ...]
    ungrounded: tuple[str, ...] = ()

    @property
    def reasons(self) -> list[str]:
        """Human-readable reasons this sentence was blocked (empty if it passed)."""
        out = [
            f"{cv.claim.kind}: {cv.reason}" for cv in self.claim_verdicts if cv.status == "block"
        ]
        out += [f"ungrounded: {u}" for u in self.ungrounded]
        return out


@dataclass
class GateReport:
    """Outcome for a whole answer."""

    sentences: list[SentenceVerdict] = field(default_factory=list)

    @property
    def passed(self) -> int:
        """Number of sentences shown to the user."""
        return sum(1 for s in self.sentences if s.status == "pass")

    @property
    def blocked(self) -> int:
        """Number of sentences withheld."""
        return sum(1 for s in self.sentences if s.status == "block")

    @property
    def claim_counts(self) -> dict[str, int]:
        """Pass/block totals across all claims (for the audit trail)."""
        counts = {"pass": 0, "block": 0}
        for s in self.sentences:
            for cv in s.claim_verdicts:
                counts[cv.status] += 1
        return counts

    def render(self, *, show_blocked_reason: bool = True) -> str:
        """Render the user-visible answer: passed sentences verbatim, blocked ones redacted."""
        parts: list[str] = []
        for s in self.sentences:
            if s.status == "pass":
                parts.append(s.text)
            elif show_blocked_reason:
                parts.append(f"[Withheld — could not verify: {'; '.join(s.reasons)}]")
            else:
                parts.append("[Withheld — could not verify]")
        return " ".join(parts)


# ---------------------------------------------------------------------------
# Per-claim verification
# ---------------------------------------------------------------------------


def verify_claim(claim: Claim, store: EvidenceStore) -> ClaimVerdict:
    """Verify one claim against the evidence store."""
    if isinstance(claim, QuoteClaim):
        return _verify_quote(claim, store)
    if isinstance(claim, CountClaim):
        return _verify_count(claim, store)
    if isinstance(claim, ShareClaim):
        return _verify_share(claim, store)
    if isinstance(claim, DeviceClaim):
        return _verify_device(claim, store)
    if isinstance(claim, RecordClaim):
        return _verify_record(claim, store)
    if isinstance(claim, RecallClaim):
        return _verify_recall(claim, store)
    if isinstance(claim, RecallCountClaim):
        return _verify_recall_count(claim, store)
    if isinstance(claim, LiteratureClaim):
        return _verify_literature(claim, store)
    if isinstance(claim, SourceCountClaim):
        return _verify_source_count(claim, store)
    return _verify_regulation(claim)


def _verify_quote(c: QuoteClaim, store: EvidenceStore) -> ClaimVerdict:
    q = normalize_text(c.quote)
    if len(q) < 8:
        return ClaimVerdict(c, "block", "quote too short to verify")
    if c.source_id:
        return _verify_source_quote(c, q, store)
    if not c.report_id:
        return ClaimVerdict(c, "block", "quote is not attributed to any source")
    rec = store.record(c.report_id)
    if rec is None:
        return ClaimVerdict(c, "block", f"report {c.report_id} not in evidence store")
    if q in rec.normalized_text:
        return ClaimVerdict(c, "pass", "verbatim match", (rec.report_id,))
    elsewhere = store.find_quote(c.quote) or store.find_quote_in_sources(c.quote)
    if elsewhere:
        return ClaimVerdict(
            c,
            "block",
            f"quote is real but belongs to {', '.join(elsewhere[:3])}, not {c.report_id}",
            tuple(elsewhere[:3]),
        )
    return ClaimVerdict(c, "block", f"quote not found verbatim in {c.report_id}")


def _verify_source_quote(c: QuoteClaim, q: str, store: EvidenceStore) -> ClaimVerdict:
    sid = c.source_id or ""
    found = store.source_text(sid)
    if found is None:
        return ClaimVerdict(c, "block", f"source {sid} not in stored literature or recalls")
    text, label = found
    if q in text:
        return ClaimVerdict(c, "pass", f"verbatim match in {label}", (label,))
    elsewhere = [x for x in store.find_quote_in_sources(c.quote) if x != label]
    elsewhere += store.find_quote(c.quote)
    if elsewhere:
        return ClaimVerdict(
            c,
            "block",
            f"quote is real but belongs to {', '.join(elsewhere[:3])}, not {label}",
            tuple(elsewhere[:3]),
        )
    return ClaimVerdict(c, "block", f"quote not found verbatim in {label}")


def _verify_count(c: CountClaim, store: EvidenceStore) -> ClaimVerdict:
    rows = store.select(
        product_code=c.product_code,
        event_type=c.event_type,
        date_from=c.date_from,
        date_to=c.date_to,
    )
    n = len(rows)
    ids = tuple(r.report_id for r in rows[:20])
    if n == c.value:
        return ClaimVerdict(c, "pass", f"recomputed {n}", ids, float(n))
    return ClaimVerdict(c, "block", f"claimed {c.value}, records show {n}", ids, float(n))


def _verify_source_count(c: SourceCountClaim, store: EvidenceStore) -> ClaimVerdict:
    want = normalize_source(c.source)
    if not want:
        return ClaimVerdict(c, "block", f"unknown report source {c.source!r}")
    rows = store.select(product_code=c.product_code, date_from=c.date_from, date_to=c.date_to)
    if want == NON_MANUFACTURER:
        # Reports whose source is unknown are not counted as "not filed by a manufacturer".
        hits = [r for r in rows if r.source and r.source != "manufacturer"]
    else:
        hits = [r for r in rows if r.source == want]
    n = len(hits)
    ids = tuple(r.report_id for r in hits[:20])
    label = f"{want} reports" if want != NON_MANUFACTURER else "reports not filed by a manufacturer"
    if n == c.value:
        return ClaimVerdict(c, "pass", f"recomputed {n} {label}", ids, float(n))
    return ClaimVerdict(c, "block", f"claimed {c.value}, records show {n} {label}", ids, float(n))


def _verify_share(c: ShareClaim, store: EvidenceStore) -> ClaimVerdict:
    if not 0.0 <= c.value_pct <= 100.0:
        return ClaimVerdict(c, "block", f"{c.value_pct}% is not a valid share")
    denom = store.select(product_code=c.product_code, date_from=c.date_from, date_to=c.date_to)
    if not denom:
        return ClaimVerdict(c, "block", f"no records for {c.product_code}")
    num = [r for r in denom if (r.event_type or "").lower() == c.event_type.lower()]
    pct = 100.0 * len(num) / len(denom)
    ids = tuple(r.report_id for r in num[:20])
    if abs(pct - c.value_pct) <= SHARE_TOLERANCE_PP:
        return ClaimVerdict(
            c, "pass", f"recomputed {pct:.1f}% ({len(num)}/{len(denom)})", ids, round(pct, 2)
        )
    return ClaimVerdict(
        c,
        "block",
        f"claimed {c.value_pct}%, records show {pct:.1f}% ({len(num)}/{len(denom)})",
        ids,
        round(pct, 2),
    )


def _verify_device(c: DeviceClaim, store: EvidenceStore) -> ClaimVerdict:
    dev = store.device(c.k_number)
    source = "catalog"
    if dev is None:
        dev = store.clearance(c.k_number)
        source = "openFDA 510(k)"
    if dev is None:
        return ClaimVerdict(
            c, "block", f"{c.k_number} not in the 510(k) catalog or stored 510(k) records"
        )
    if c.product_code and c.product_code.upper() != dev.product_code.upper():
        return ClaimVerdict(
            c,
            "block",
            f"{c.k_number} is product code {dev.product_code}, not {c.product_code}",
            (dev.k_number,),
        )
    if c.device_name and normalize_text(c.device_name) not in normalize_text(dev.device_name):
        return ClaimVerdict(
            c,
            "block",
            f"{c.k_number} is '{dev.device_name}', not '{c.device_name}'",
            (dev.k_number,),
        )
    return ClaimVerdict(c, "pass", f"{source}: {dev.device_name}", (dev.k_number,))


def _verify_record(c: RecordClaim, store: EvidenceStore) -> ClaimVerdict:
    rec = store.record(c.report_id)
    if rec is None:
        return ClaimVerdict(c, "block", f"report {c.report_id} not in evidence store")
    if c.product_code and rec.product_code != c.product_code:
        return ClaimVerdict(
            c,
            "block",
            f"report {c.report_id} is product code {rec.product_code}, not {c.product_code}",
            (rec.report_id,),
        )
    return ClaimVerdict(c, "pass", "record exists", (rec.report_id,))


def _verify_recall(c: RecallClaim, store: EvidenceStore) -> ClaimVerdict:
    matches = store.recalls_by_number(c.recall_number)
    if not matches:
        return ClaimVerdict(c, "block", f"recall {c.recall_number} not in stored FDA recalls")
    ids = tuple(r.recall_number for r in matches[:10])
    if c.product_code:
        codes = sorted({r.product_code for r in matches})
        if c.product_code.upper() not in {pc.upper() for pc in codes}:
            return ClaimVerdict(
                c,
                "block",
                f"recall {c.recall_number} is product code {', '.join(codes)}, "
                f"not {c.product_code}",
                ids,
            )
    r0 = matches[0]
    return ClaimVerdict(
        c, "pass", f"FDA recall: {r0.recalling_firm or '?'} ({r0.recall_status or '?'})", ids
    )


def _verify_recall_count(c: RecallCountClaim, store: EvidenceStore) -> ClaimVerdict:
    rows = store.select_recalls(
        product_code=c.product_code, date_from=c.date_from, date_to=c.date_to
    )
    n = len(rows)
    ids = tuple(r.recall_number for r in rows[:20])
    if n == c.value:
        return ClaimVerdict(c, "pass", f"recomputed {n} stored recalls", ids, float(n))
    return ClaimVerdict(c, "block", f"claimed {c.value}, stored recalls show {n}", ids, float(n))


def _verify_literature(c: LiteratureClaim, store: EvidenceStore) -> ClaimVerdict:
    art = store.article(c.pmid)
    if art is None:
        return ClaimVerdict(c, "block", f"PMID {c.pmid} not in stored literature")
    if c.year is not None and art.year != c.year:
        return ClaimVerdict(
            c, "block", f"PMID {c.pmid} was published {art.year}, not {c.year}", (art.pmid,)
        )
    return ClaimVerdict(c, "pass", f"PubMed: {art.title[:80]}", (f"PMID {art.pmid}",))


def _verify_regulation(c: RegulationClaim) -> ClaimVerdict:
    sec = c.section.strip().lstrip("§").strip()
    if sec in CFR_SECTIONS:
        return ClaimVerdict(c, "pass", f"21 CFR {sec}: {CFR_SECTIONS[sec]}", (f"21 CFR {sec}",))
    if sec in SUPERSEDED_SECTIONS:
        return ClaimVerdict(c, "block", f"21 CFR {sec} {SUPERSEDED_SECTIONS[sec]}")
    return ClaimVerdict(c, "block", f"21 CFR {sec} is not in the curated CFR list")


# ---------------------------------------------------------------------------
# Sentence / answer verification
# ---------------------------------------------------------------------------


def _looks_like_date(token: str) -> bool:
    """True for YYYYMMDD tokens (dates are not report ids)."""
    if len(token) != 8 or not token.isdigit():
        return False
    y, m, d = int(token[:4]), int(token[4:6]), int(token[6:])
    return 1990 <= y <= 2100 and 1 <= m <= 12 and 1 <= d <= 31


def _strip_quoted_spans(text: str, claims: list[Claim]) -> str:
    """Remove each quote claim's text from the sentence where it appears in quotation marks.

    Only spans inside quotation marks are removed, so a number cannot be
    smuggled past the count/share checks by tagging an unquoted phrase as a quote.
    """
    for c in claims:
        if isinstance(c, QuoteClaim) and len(normalize_text(c.quote)) >= 8:
            body = r"\s+".join(re.escape(w) for w in c.quote.split())
            pattern = r"[\"“‘']\s*" + body + r"[\s.,;:!?]*[\"”’']"
            text = re.sub(pattern, " ", text, flags=re.IGNORECASE)
    return text


def _ungrounded_mentions(text: str, claims: list[Claim]) -> list[str]:
    """Find checkable-looking mentions in the sentence that no claim covers.

    Spans covered by a quote claim are skipped: a number inside a verbatim
    quote (e.g. an abstract's "F1-score=85%") is checked by that quote claim —
    if the quote does not verify, the claim blocks the sentence anyway.
    """
    out: list[str] = []
    text = _strip_quoted_spans(text, claims)
    source_ids = {
        c.source_id.strip().upper() for c in claims if isinstance(c, QuoteClaim) and c.source_id
    }
    pmid_claimed = {c.pmid for c in claims if isinstance(c, LiteratureClaim)}
    pmid_claimed |= {normalize_pmid(s) for s in source_ids}
    for m in _PMID_RE.finditer(text):
        if m.group(1) not in pmid_claimed:
            out.append(f"PMID {m.group(1)} has no literature claim")
    # Checked above; drop "PMID n" so "PMID 123 reports ..." is not read as a report count.
    text = _PMID_RE.sub(" ", text)
    k_claimed = {c.k_number.upper() for c in claims if isinstance(c, DeviceClaim)}
    for m in _K_RE.finditer(text):
        if m.group(0).upper() not in k_claimed:
            out.append(f"510(k) {m.group(0)} has no device claim")
    cfr_claimed = {c.section.strip() for c in claims if isinstance(c, RegulationClaim)}
    for sec in find_cfr_citations(text):
        if sec not in cfr_claimed:
            out.append(f"21 CFR {sec} has no regulation claim")
    pct_claimed = [c.value_pct for c in claims if isinstance(c, ShareClaim)]
    for m in _PCT_RE.finditer(text):
        v = float(m.group(1))
        if not any(abs(v - p) < 1e-6 for p in pct_claimed):
            out.append(f"{m.group(0)} has no share claim")
    count_claimed = {c.value for c in claims if isinstance(c, CountClaim | SourceCountClaim)}
    for m in _COUNT_RE.finditer(text):
        token = m.group(1).rstrip(",")
        if _looks_like_date(token):
            # "... to 20260831, including reports 504..." is a date, not "20260831 reports"
            # (a false block in the 2026-10-28 recording).
            continue
        v = int(token.replace(",", ""))
        if v not in count_claimed:
            out.append(f"'{m.group(0)}' has no count claim")
    recall_count_claimed = {c.value for c in claims if isinstance(c, RecallCountClaim)}
    for m in _RECALL_COUNT_RE.finditer(text):
        token = m.group(1).rstrip(",")
        if _looks_like_date(token):
            continue
        v = int(token.replace(",", ""))
        if v not in recall_count_claimed:
            out.append(f"'{m.group(0)}' has no recall_count claim")
    recall_claimed = {c.recall_number.strip().upper() for c in claims if isinstance(c, RecallClaim)}
    for m in _RECALL_NO_RE.finditer(text):
        if m.group(0).upper() not in recall_claimed | source_ids:
            out.append(f"recall {m.group(0)} has no recall claim")
    record_claimed = {c.report_id for c in claims if isinstance(c, RecordClaim)}
    record_claimed |= {c.report_id for c in claims if isinstance(c, QuoteClaim) and c.report_id}
    record_claimed |= pmid_claimed  # a claimed PMID is not an untagged MAUDE report id
    for token in re.findall(r"\b\d{7}-\d{4}-\d{5}\b|\bMW\d{7}\b|\b\d{7,9}\b", text):
        if _looks_like_date(token):
            continue
        if token not in record_claimed:
            out.append(f"report {token} has no record claim")
    return out


def verify_sentence(text: str, claims: list[Claim], store: EvidenceStore) -> SentenceVerdict:
    """Verify one sentence: all its claims must pass and nothing checkable may be untagged."""
    verdicts = tuple(verify_claim(c, store) for c in claims)
    ungrounded = tuple(_ungrounded_mentions(text, claims))
    ok = all(v.status == "pass" for v in verdicts) and not ungrounded
    return SentenceVerdict(text, "pass" if ok else "block", verdicts, ungrounded)


def verify_answer(sentences: list[tuple[str, list[Claim]]], store: EvidenceStore) -> GateReport:
    """Verify a structured answer: a list of (sentence, claims) pairs."""
    return GateReport([verify_sentence(t, cs, store) for t, cs in sentences])


def verify(claims: list[Claim], store: EvidenceStore) -> list[ClaimVerdict]:
    """Verify a flat list of claims (convenience for tools and tests)."""
    return [verify_claim(c, store) for c in claims]
