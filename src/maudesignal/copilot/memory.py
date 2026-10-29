"""Copilot memory: the device types you choose, and notes you pin.

HACKATHON-BUILT — Meta Global AI Developer Hackathon (Oct 26 – Nov 4, 2026).

Memory is not a separate store. It is state derived from the hash-chained
action audit trail (``entity_id = "MEMORY"``): every change is an append-only,
tamper-evident entry naming who made it, and the current memory is the replay
of those entries. Nothing here decides anything; it remembers what a person
chose so the copilot and the monitor can work on those device types.

- ``memory.device_types`` — the device types (FDA product codes) the user
  chose to watch. MaudeSignal never defines "similar devices"; it only uses
  the codes a person picked.
- ``memory.note`` / ``memory.note_removed`` — short notes a person pinned
  (for example a verified copilot sentence with its evidence ids).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from maudesignal.storage.database import Database

MEMORY_ENTITY = "MEMORY"
_CODE = re.compile(r"^[A-Z]{3}$")
MAX_NOTE_CHARS = 500
MAX_DEVICE_TYPES = 25


class CopilotMemoryError(ValueError):
    """Raised for an invalid memory change (bad product code, empty note, no actor)."""


@dataclass
class PinnedNote:
    """One note a person pinned."""

    note_id: str
    text: str
    evidence_ids: list[str]
    actor: str
    ts: str


@dataclass
class CopilotMemory:
    """Replayed memory state."""

    device_types: list[str] = field(default_factory=list)
    device_types_set_by: str | None = None
    notes: list[PinnedNote] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """JSON-serialisable view (used by the copilot tool)."""
        return {
            "device_types": self.device_types,
            "device_types_set_by": self.device_types_set_by,
            "notes": [
                {"note_id": n.note_id, "text": n.text, "evidence_ids": n.evidence_ids}
                for n in self.notes
            ],
        }


def _actor(actor: str) -> str:
    actor = (actor or "").strip()
    if not actor:
        raise CopilotMemoryError("a named person must make memory changes")
    return actor


def load_memory(db: Database) -> CopilotMemory:
    """Replay the ``MEMORY`` audit entries into the current memory."""
    mem = CopilotMemory()
    notes: dict[str, PinnedNote] = {}
    for row in db.list_audit(entity_id=MEMORY_ENTITY):
        payload = json.loads(row.payload_json)
        if row.action == "memory.device_types":
            mem.device_types = list(payload.get("device_types", []))
            mem.device_types_set_by = row.actor
        elif row.action == "memory.note":
            nid = str(payload["note_id"])
            notes[nid] = PinnedNote(
                nid,
                str(payload.get("text", "")),
                list(payload.get("evidence_ids", [])),
                row.actor,
                row.ts.isoformat(),
            )
        elif row.action == "memory.note_removed":
            notes.pop(str(payload.get("note_id")), None)
    mem.notes = list(notes.values())
    return mem


def set_device_types(db: Database, codes: list[str], *, actor: str) -> CopilotMemory:
    """Remember the device types (product codes) a person chose to watch."""
    clean = sorted({c.strip().upper() for c in codes if c and c.strip()})
    bad = [c for c in clean if not _CODE.match(c)]
    if bad:
        raise CopilotMemoryError(f"not FDA product codes (three letters): {', '.join(bad)}")
    if len(clean) > MAX_DEVICE_TYPES:
        raise CopilotMemoryError(f"at most {MAX_DEVICE_TYPES} device types")
    db.append_audit(
        actor=_actor(actor),
        action="memory.device_types",
        entity_id=MEMORY_ENTITY,
        payload={"device_types": clean},
    )
    return load_memory(db)


def pin_note(
    db: Database, text: str, *, actor: str, evidence_ids: list[str] | None = None
) -> PinnedNote:
    """Pin a short note (stored verbatim, with the evidence ids it rests on)."""
    text = (text or "").strip()
    if not text:
        raise CopilotMemoryError("a note needs text")
    if len(text) > MAX_NOTE_CHARS:
        raise CopilotMemoryError(f"notes are at most {MAX_NOTE_CHARS} characters")
    existing = [r for r in db.list_audit(entity_id=MEMORY_ENTITY) if r.action == "memory.note"]
    note_id = f"N-{len(existing) + 1:03d}"
    row = db.append_audit(
        actor=_actor(actor),
        action="memory.note",
        entity_id=MEMORY_ENTITY,
        payload={"note_id": note_id, "text": text, "evidence_ids": list(evidence_ids or [])},
    )
    return PinnedNote(note_id, text, list(evidence_ids or []), row.actor, row.ts.isoformat())


def remove_note(db: Database, note_id: str, *, actor: str) -> None:
    """Unpin a note (the original entry stays in the audit trail)."""
    if note_id not in {n.note_id for n in load_memory(db).notes}:
        raise CopilotMemoryError(f"no pinned note {note_id}")
    db.append_audit(
        actor=_actor(actor),
        action="memory.note_removed",
        entity_id=MEMORY_ENTITY,
        payload={"note_id": note_id},
    )
