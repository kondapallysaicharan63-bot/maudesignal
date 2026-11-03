"""PMS board (PRD-19): flagged code, why flagged, status, owner, due date, decision link.

HACKATHON-BUILT — Meta Global AI Developer Hackathon (Oct 26 – Nov 4, 2026), 2026-11-03.

The board keeps no state of its own: every row's status is replayed from the
hash-chained audit trail (``action = "board_status"``). A status changes only when a
named person asks for it, and the change is written to the audit trail first. The due
date is the advisory MDR clock (21 CFR 803.50 / 803.53) from an awareness date the person
types; it does not decide reportability. This is not a QMS.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

from maudesignal.storage.database import Database

BOARD_ACTION = "board_status"
BOARD_LABEL = "This is not a QMS. Status, owner and due date are typed by a named person."

STATUSES: tuple[str, ...] = ("new", "under_review", "note_to_file", "escalated", "closed")
STATUS_LABELS: dict[str, str] = {
    "new": "New",
    "under_review": "Under review",
    "note_to_file": "Note to file",
    "escalated": "Escalated",
    "closed": "Closed",
}
#: Allowed moves. Closed can be reopened to Under review; nothing jumps straight from New
#: to a decision.
TRANSITIONS: dict[str, tuple[str, ...]] = {
    "new": ("under_review",),
    "under_review": ("note_to_file", "escalated", "closed"),
    "note_to_file": ("under_review", "closed"),
    "escalated": ("under_review", "closed"),
    "closed": ("under_review",),
}
_NAME = re.compile(r"^[A-Za-z][A-Za-z .'\-]{1,79}$")


class BoardError(ValueError):
    """A status change that is not allowed (no name, wrong move, bad date)."""


@dataclass(frozen=True)
class BoardRow:
    """One flagged product code on the board.

    Attributes:
        product_code: FDA 3-letter product code.
        why: Plain-words reason with counts (e.g. "Report mix changed: ...").
        status: One of :data:`STATUSES`.
        owner: Name the person typed, or None.
        due: Advisory MDR due date (ISO day), or None.
        due_basis: e.g. "30 calendar days, 21 CFR 803.50 (advisory)".
        audit_seq: Audit sequence number of the last status change, or None.
        history: ``(seq, from, to, actor)`` for every change, oldest first.
    """

    product_code: str
    why: str
    status: str = "new"
    owner: str | None = None
    due: str | None = None
    due_basis: str | None = None
    audit_seq: int | None = None
    history: tuple[tuple[int, str, str, str], ...] = field(default_factory=tuple)


def valid_name(name: str) -> bool:
    """A typed person's name: letters first, 2-80 characters of letters/space/.'-."""
    return bool(_NAME.match(name.strip()))


def mdr_due(awareness: str, five_day: bool = False) -> tuple[str, str]:
    """Advisory MDR clock from an awareness date (``YYYY-MM-DD``).

    Args:
        awareness: The date the company became aware (typed by the person).
        five_day: True for the 5-work-day report (21 CFR 803.53).

    Returns:
        ``(due ISO day, basis words)``.

    Raises:
        BoardError: The date is not a real ``YYYY-MM-DD`` day.
    """
    try:
        start = date.fromisoformat(awareness.strip())
    except ValueError as exc:
        raise BoardError(f"awareness date must be YYYY-MM-DD, got {awareness!r}") from exc
    if five_day:
        d, added = start, 0
        while added < 5:
            d += timedelta(days=1)
            if d.weekday() < 5:
                added += 1
        return d.isoformat(), "5 work days, 21 CFR 803.53 (advisory; a person decides)"
    return (
        (start + timedelta(days=30)).isoformat(),
        "30 calendar days, 21 CFR 803.50 (advisory; a person decides)",
    )


def board_state(db: Database, flagged: dict[str, str]) -> list[BoardRow]:
    """Replay the board from the audit trail.

    Args:
        db: Database holding the hash-chained audit trail.
        flagged: ``product_code -> why flagged`` for the rows to show.

    Returns:
        One row per flagged code (plus any code that has a board entry), in code order.
    """
    rows: dict[str, dict[str, Any]] = {
        code: {"why": why, "status": "new", "history": []} for code, why in flagged.items()
    }
    for e in db.list_audit():
        if e.action != BOARD_ACTION or not e.entity_id.startswith("board:"):
            continue
        code = e.entity_id.split(":", 1)[1]
        p = json.loads(e.payload_json)
        r = rows.setdefault(code, {"why": p.get("why", ""), "status": "new", "history": []})
        r["history"].append((e.seq, p.get("from"), p.get("to"), e.actor))
        r.update(
            status=p.get("to", r["status"]),
            owner=p.get("owner") or r.get("owner"),
            due=p.get("due") or r.get("due"),
            due_basis=p.get("due_basis") or r.get("due_basis"),
            audit_seq=e.seq,
        )
    return [
        BoardRow(
            product_code=code,
            why=r["why"],
            status=r["status"],
            owner=r.get("owner"),
            due=r.get("due"),
            due_basis=r.get("due_basis"),
            audit_seq=r.get("audit_seq"),
            history=tuple(r["history"]),
        )
        for code, r in sorted(rows.items())
    ]


def change_status(
    db: Database,
    *,
    product_code: str,
    why: str,
    current: str,
    to: str,
    actor: str,
    owner: str | None = None,
    awareness: str | None = None,
    five_day: bool = False,
    note: str = "",
) -> int:
    """Move one board row to a new status, audit-first.

    Args:
        db: Database holding the audit trail.
        product_code: The row's product code.
        why: Why it was flagged (kept in the audit payload).
        current: The status the person saw (stale screens are refused).
        to: The status the person chose.
        actor: The named person making the change.
        owner: Owner name the person typed (optional).
        awareness: Awareness date for the advisory MDR clock (optional).
        five_day: Use the 5-work-day clock.
        note: Free text the person typed (optional).

    Returns:
        The audit sequence number of the change.

    Raises:
        BoardError: No valid name, unknown status, or a move that is not allowed.
    """
    if not valid_name(actor):
        raise BoardError("a status changes only by a named person (type your name)")
    if owner and not valid_name(owner):
        raise BoardError("owner must be a typed name")
    if to not in STATUSES or current not in STATUSES:
        raise BoardError(f"unknown status {to!r}")
    if to not in TRANSITIONS[current]:
        raise BoardError(
            f"{STATUS_LABELS[current]} cannot move to {STATUS_LABELS[to]}; allowed: "
            + ", ".join(STATUS_LABELS[t] for t in TRANSITIONS[current])
        )
    payload: dict[str, Any] = {"from": current, "to": to, "why": why, "note": note[:500]}
    if owner:
        payload["owner"] = owner.strip()
    if awareness:
        due, basis = mdr_due(awareness, five_day)
        payload.update(awareness=awareness, due=due, due_basis=basis)
    row = db.append_audit(
        actor=actor.strip(),
        action=BOARD_ACTION,
        entity_id=f"board:{product_code.upper()}",
        payload=payload,
    )
    return row.seq
