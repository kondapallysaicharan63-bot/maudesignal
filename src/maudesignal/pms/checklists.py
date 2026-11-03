"""Escalation, risk and recall-check sections of an evidence pack (PRD-21).

HACKATHON-BUILT — Meta Global AI Developer Hackathon (Oct 26 – Nov 4, 2026), 2026-11-03.

Each section lists stored evidence and ends with a question for a person. No section
makes a decision: there is no risk score, no "increased device risk" sentence, no
"recall needed" and no reportability finding. Occurrence is given as counts, never as a
rate (MAUDE has no denominator — units sold are not known).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from maudesignal.monitor.deterioration import REPORT_MIX_LIMITATION

HUMAN_DECIDES = "Human decides — record the answer in your own QMS."

#: Words that must never appear in a generated section (tool-made decision sentences).
FORBIDDEN_DECISIONS: tuple[str, ...] = (
    "recall needed",
    "recall is needed",
    "recall is required",
    "is reportable",
    "must be reported",
    "increased device risk",
    "capa is required",
    "capa is needed",
    "risk score",
)


@dataclass(frozen=True)
class EvidencePack:
    """The evidence behind one flagged code (from an alert or an investigation).

    Attributes:
        product_code: FDA product code.
        device_type: FDA device type name, or None.
        why: Why it was flagged, in plain words with counts.
        reports: ``{report_id, date_received, event_type, source, url}`` dicts.
        recalls: ``{id, firm, status, reason, date, url}`` dicts.
        literature: ``{pmid, title, url}`` dicts (may be empty).
        failure_terms: Words naming the flagged failure mode (for the recall-reason check).
    """

    product_code: str
    device_type: str | None
    why: str
    reports: list[dict[str, Any]] = field(default_factory=list)
    recalls: list[dict[str, Any]] = field(default_factory=list)
    literature: list[dict[str, Any]] = field(default_factory=list)
    failure_terms: list[str] = field(default_factory=list)


def _norm_event(et: str | None) -> str:
    e = (et or "").strip().lower()
    if e in {"death", "injury", "malfunction"}:
        return e
    return "other / not stated"


def severity_mix(pack: EvidencePack) -> list[dict[str, Any]]:
    """Counts and shares of the listed reports by event type (counts, not rates)."""
    order = ["death", "injury", "malfunction", "other / not stated"]
    counts = dict.fromkeys(order, 0)
    for r in pack.reports:
        counts[_norm_event(r.get("event_type"))] += 1
    total = len(pack.reports)
    return [
        {
            "event_type": k,
            "count": counts[k],
            "share": None if total == 0 else round(counts[k] / total, 4),
            "of": total,
        }
        for k in order
    ]


def escalation_checklist(pack: EvidencePack) -> list[dict[str, Any]]:
    """Three assessments a person makes; each links the evidence it rests on."""
    ids = [str(r.get("report_id")) for r in pack.reports]
    rec = [str(r.get("id")) for r in pack.recalls]
    severe = [
        str(r.get("report_id"))
        for r in pack.reports
        if _norm_event(r.get("event_type")) in {"death", "injury"}
    ]
    return [
        {
            "item": "MDR reportability assessment",
            "basis": "21 CFR 803.50 (30 calendar days) / 21 CFR 803.53 (5 work days) — "
            "clock is advisory, from the awareness date your team records",
            "evidence": severe or ids,
            "question": "Does any event your company is aware of meet the MDR reporting "
            "criteria?",
            "decision": None,
            "decided_by": HUMAN_DECIDES,
        },
        {
            "item": "Recall / correction-and-removal assessment",
            "basis": "21 CFR 806; 21 CFR 7 Subpart C",
            "evidence": rec,
            "question": "Does this need a correction or removal under your recall procedure?",
            "decision": None,
            "decided_by": HUMAN_DECIDES,
        },
        {
            "item": "Field safety action assessment",
            "basis": "Your field action / customer notification procedure",
            "evidence": ids,
            "question": "Is a field safety action or customer notification warranted?",
            "decision": None,
            "decided_by": HUMAN_DECIDES,
        },
    ]


def risk_section(pack: EvidencePack) -> dict[str, Any]:
    """ISO 14971 framing: severity, occurrence (counts), detectability question."""
    return {
        "framing": "ISO 14971 inputs for your risk file. No numeric risk rating is computed.",
        "severity_mix": severity_mix(pack),
        "occurrence": (
            f"{len(pack.reports)} report(s) listed in this pack. These are counts of "
            "reports received by FDA, not rates: MAUDE has no denominator (units in use are "
            "not known), so no incidence or probability is stated."
        ),
        "recalls_listed": len(pack.recalls),
        "literature_listed": len(pack.literature),
        "detectability_question": (
            "Could your existing controls (labelling, alarms, service checks, complaint "
            "trending) detect this failure mode before harm? — human answers in the risk file."
        ),
        "decision": None,
        "decided_by": HUMAN_DECIDES,
    }


def recall_check(pack: EvidencePack) -> dict[str, Any]:
    """Recalls for the code and whether a flagged failure-mode word appears in a reason."""
    terms = [t.strip().lower() for t in pack.failure_terms if len(t.strip()) >= 3]
    rows = []
    for r in pack.recalls:
        reason = (r.get("reason") or "").lower()
        hits = [t for t in terms if re.search(rf"\b{re.escape(t)}", reason)]
        rows.append(
            {
                "id": r.get("id"),
                "firm": r.get("firm"),
                "status": r.get("status"),
                "reason": r.get("reason"),
                "url": r.get("url"),
                "failure_terms_in_reason": hits,
            }
        )
    matched = [x["id"] for x in rows if x["failure_terms_in_reason"]]
    return {
        "recalls": rows,
        "terms_checked": terms,
        "recalls_naming_the_failure_mode": matched,
        "summary": (
            f"{len(matched)} of {len(rows)} listed recall(s) name the flagged failure-mode "
            f"term(s) in the recall reason (a text match, not a finding)."
            if terms
            else "No failure-mode term was given, so recall reasons were not matched."
        ),
        "question": "Does this meet your recall procedure?",
        "decision": None,
        "decided_by": HUMAN_DECIDES,
    }


def has_decision_sentence(text: str) -> bool:
    """True when ``text`` contains a tool-made decision sentence (never allowed)."""
    low = text.lower().replace(REPORT_MIX_LIMITATION.lower(), "")
    low = low.replace("not proof of increased device risk", "")
    return any(f in low for f in FORBIDDEN_DECISIONS)
