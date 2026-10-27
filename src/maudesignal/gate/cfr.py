"""Curated list of CFR sections the copilot may cite.

HACKATHON-BUILT — Meta Global AI Developer Hackathon (Oct 26 – Nov 4, 2026).

Per CLAUDE.md §6.2 the verifier must never use model training data as a
source. This list is the curated primary-source allowlist: a section that is
not here is treated as unverifiable and blocked. Section titles follow the
eCFR (Title 21, Chapter I, Subchapter H).

Part 820 changed on 2026-02-02 when the Quality Management System Regulation
(QMSR) replaced the old Quality System Regulation and incorporated ISO 13485
by reference. Old QS-reg sections such as 820.100 (CAPA) are therefore
*superseded* — a model trained on older text will still cite them, and the
gate catches that.
"""

from __future__ import annotations

import re

CFR_SECTIONS: dict[str, str] = {
    # Part 803 — Medical Device Reporting
    "803.1": "What does this part cover?",
    "803.3": "How does FDA define the terms used in this part?",
    "803.10": "Generally, what are the reporting requirements that apply to me?",
    "803.17": "What are the requirements for developing, maintaining, and implementing "
    "written MDR procedures that apply to me?",
    "803.18": "What are the requirements for establishing and maintaining MDR files "
    "or records that apply to me?",
    "803.20": "How do I complete and submit an individual adverse event report?",
    "803.30": "If I am a user facility, what reporting requirements apply to me?",
    "803.50": "If I am a manufacturer, what reporting requirements apply to me?",
    "803.52": "If I am a manufacturer, what information must I submit in my individual "
    "adverse event reports?",
    "803.53": "If I am a manufacturer, in which circumstances must I submit a 5-day report?",
    "803.56": "If I am a manufacturer, in what circumstances must I submit a supplemental "
    "or followup report and what are the requirements for such reports?",
    "803.58": "Foreign manufacturers.",
    # Part 806 — Corrections and Removals
    "806.10": "Reports of corrections and removals.",
    "806.20": "Records of corrections and removals not required to be reported.",
    # Part 807 — Establishment Registration and Premarket Notification
    "807.81": "When a premarket notification submission is required.",
    "807.87": "Information required in a premarket notification submission.",
    "807.92": "Content and format of a 510(k) summary.",
    # Part 820 — Quality Management System Regulation (effective 2026-02-02)
    "820.1": "Scope.",
    "820.3": "Definitions.",
    "820.7": "Incorporation by reference.",
    "820.10": "Requirements for a quality management system.",
    "820.15": "Clarification of concepts.",
    "820.35": "Control of records.",
    "820.45": "Device labeling and packaging controls.",
}

SUPERSEDED_SECTIONS: dict[str, str] = {
    "820.30": "Design controls — superseded by QMSR (ISO 13485 clause 7.3) on 2026-02-02.",
    "820.90": "Nonconforming product — superseded by QMSR (ISO 13485 clause 8.3) on 2026-02-02.",
    "820.100": "Corrective and preventive action — superseded by QMSR "
    "(ISO 13485 clauses 8.5.2/8.5.3) on 2026-02-02.",
    "820.198": "Complaint files — superseded by QMSR (ISO 13485 clause 8.2.2) on 2026-02-02.",
}

_CFR_RE = re.compile(r"21\s*C\.?F\.?R\.?\s*(?:§+\s*)?(?:Part\s*)?(\d{3}\.\d{1,3})", re.IGNORECASE)


def find_cfr_citations(text: str) -> list[str]:
    """Return every ``21 CFR NNN.N`` section cited in the text (in order, de-duplicated)."""
    seen: list[str] = []
    for m in _CFR_RE.finditer(text):
        sec = m.group(1)
        if sec not in seen:
            seen.append(sec)
    return seen
