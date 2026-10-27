"""Claim-level citation gate.

HACKATHON-BUILT — Meta Global AI Developer Hackathon (Oct 26 – Nov 4, 2026).
The ``regulatory-citation-verifier`` Skill spec existed before the hackathon but
had zero call sites; this module is the enforcement, written during the event.

What it guarantees, for every sentence the copilot shows a user:

* every **number** is recomputed from stored records and must match exactly
  (counts) or within 0.5 percentage points (shares);
* every **quote** must appear verbatim in the narrative of the report it is
  attributed to (a real quote pinned to the wrong report is blocked);
* every **510(k) number** must exist in the catalog and belong to the stated
  product code / device;
* every **MAUDE report id** must exist (and match the stated product code);
* every **21 CFR section** must be in the curated allowlist (superseded QS-reg
  sections are blocked with the reason);
* a sentence that mentions a K-number, CFR section, percentage or report count
  *without* a matching structured claim is blocked as ungrounded.

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
    QuoteClaim,
    RecordClaim,
    RegulationClaim,
    ShareClaim,
)
from maudesignal.gate.evidence import EvidenceStore, normalize_text

Status = Literal["pass", "block"]

SHARE_TOLERANCE_PP = 0.5

_K_RE = re.compile(r"\b[KkDd][Ee]?N?\d{6}\b")
_PCT_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(?:%|percent\b)")
_COUNT_RE = re.compile(
    r"\b(\d[\d,]*)\s+(?:\w+\s+){0,2}?"
    r"(?:reports?|events?|deaths?|injur(?:y|ies)|malfunctions?|MDRs?|records?)\b",
    re.IGNORECASE,
)


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
    return _verify_regulation(claim)


def _verify_quote(c: QuoteClaim, store: EvidenceStore) -> ClaimVerdict:
    q = normalize_text(c.quote)
    if len(q) < 8:
        return ClaimVerdict(c, "block", "quote too short to verify")
    rec = store.record(c.report_id)
    if rec is None:
        return ClaimVerdict(c, "block", f"report {c.report_id} not in evidence store")
    if q in rec.normalized_text:
        return ClaimVerdict(c, "pass", "verbatim match", (rec.report_id,))
    elsewhere = store.find_quote(c.quote)
    if elsewhere:
        return ClaimVerdict(
            c,
            "block",
            f"quote is real but belongs to {', '.join(elsewhere[:3])}, not {c.report_id}",
            tuple(elsewhere[:3]),
        )
    return ClaimVerdict(c, "block", f"quote not found verbatim in {c.report_id}")


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
    if dev is None:
        return ClaimVerdict(c, "block", f"{c.k_number} not in the 510(k) catalog")
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
    return ClaimVerdict(c, "pass", f"catalog: {dev.device_name}", (dev.k_number,))


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


def _ungrounded_mentions(text: str, claims: list[Claim]) -> list[str]:
    """Find checkable-looking mentions in the sentence that no claim covers."""
    out: list[str] = []
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
    count_claimed = {c.value for c in claims if isinstance(c, CountClaim)}
    for m in _COUNT_RE.finditer(text):
        v = int(m.group(1).replace(",", ""))
        if v not in count_claimed:
            out.append(f"'{m.group(0)}' has no count claim")
    record_claimed = {c.report_id for c in claims if isinstance(c, (RecordClaim, QuoteClaim))}
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
