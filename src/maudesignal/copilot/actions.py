"""Copilot actions with a human approval gate.

HACKATHON-BUILT — Meta Global AI Developer Hackathon (Oct 26 – Nov 4, 2026).

One pattern for every action: **audit-first, forward-only, human-decided.**

* The audit entry is written in the same transaction as the state change,
  before it, in a hash-chained table (``action_audit``).
* Status only moves forward: ``draft`` -> ``approved`` | ``rejected``.
* The model can create drafts. Only a named human (never a ``copilot:``
  actor) can approve or reject. Nothing is ever submitted to FDA.
"""

from __future__ import annotations

import uuid

from maudesignal.common.exceptions import MaudeSignalError
from maudesignal.storage.database import Database
from maudesignal.storage.models import CapaDraftRecord

ALLOWED_TRANSITIONS: dict[str, frozenset[str]] = {
    "draft": frozenset({"approved", "rejected"}),
    "approved": frozenset(),
    "rejected": frozenset(),
}


class ActionError(MaudeSignalError):
    """Illegal action: wrong actor, unknown entity, or backward transition."""


def draft_capa(
    db: Database,
    *,
    product_code: str,
    title: str,
    problem_statement: str,
    report_ids: list[str],
    actor: str,
) -> CapaDraftRecord:
    """Create a CAPA-need evidence pack (audit-first)."""
    if not report_ids:
        raise ActionError("a CAPA-need evidence pack must cite at least one report")
    capa_id = f"CAPA-DRAFT-{uuid.uuid4().hex[:8].upper()}"
    return db.create_capa_draft(
        capa_id=capa_id,
        product_code=product_code,
        title=title.strip()[:200],
        problem_statement=problem_statement.strip()[:4000],
        report_ids=list(dict.fromkeys(report_ids)),
        created_by=actor,
    )


def decide_capa(
    db: Database, *, capa_id: str, decision: str, reviewer: str, note: str | None = None
) -> CapaDraftRecord:
    """Approve or reject a draft. Only a named human reviewer may do this."""
    reviewer = reviewer.strip()
    if not reviewer or reviewer.lower().startswith("copilot"):
        raise ActionError("only a named human reviewer can decide a CAPA-need evidence pack")
    row = db.get_capa_draft(capa_id)
    if row is None:
        raise ActionError(f"unknown CAPA-need evidence pack {capa_id}")
    if decision not in ALLOWED_TRANSITIONS.get(row.status, frozenset()):
        raise ActionError(f"illegal transition {row.status} -> {decision}")
    return db.decide_capa_draft(
        capa_id=capa_id, new_status=decision, decided_by=reviewer, note=note
    )
