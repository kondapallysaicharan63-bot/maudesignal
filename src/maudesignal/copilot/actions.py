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
from collections.abc import Iterable, Mapping
from typing import Any

from maudesignal.common.exceptions import MaudeSignalError
from maudesignal.storage.database import Database
from maudesignal.storage.models import CapaDraftRecord

COPILOT_ACTOR = "copilot:muse-spark"

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
    capa_id: str | None = None,
) -> CapaDraftRecord:
    """Create a CAPA-need evidence pack (audit-first).

    ``capa_id`` is only for restoring a pack that a stored transcript recorded (see
    ``restore_recorded_capas``); a new pack always gets a fresh random id.
    """
    if not report_ids:
        raise ActionError("a CAPA-need evidence pack must cite at least one report")
    capa_id = capa_id or f"CAPA-DRAFT-{uuid.uuid4().hex[:8].upper()}"
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


def restore_recorded_capas(db: Database, transcripts: Iterable[Mapping[str, Any]]) -> list[str]:
    """Re-create, in ``db``, the packs that stored transcripts recorded their copilot drafting.

    The stored ``draft_capa`` call (title, problem statement, cited reports) is replayed under
    the id the transcript recorded in ``capa_ids``, so the pack and the searches that prepared
    it share a real id. Packs already present, or whose cited reports are not all in ``db``,
    are skipped. Returns the ids restored.
    """
    restored: list[str] = []
    for t in transcripts:
        ids = [str(i) for i in t.get("capa_ids") or []]
        calls = [c for c in t.get("tool_calls") or [] if c.get("name") == "draft_capa"]
        for capa_id, call in zip(ids, calls, strict=False):
            args = call.get("arguments") or {}
            report_ids = [str(r) for r in args.get("report_ids") or []]
            if db.get_capa_draft(capa_id) is not None or not report_ids:
                continue
            if len(db.list_raw_reports(report_ids)) != len(set(report_ids)):
                continue
            draft_capa(
                db,
                product_code=str(args.get("product_code", "")),
                title=str(args.get("title", "")),
                problem_statement=str(args.get("problem_statement", "")),
                report_ids=report_ids,
                actor=COPILOT_ACTOR,
                capa_id=capa_id,
            )
            restored.append(capa_id)
    return restored
