"""Export and re-verify the hash-chained audit trail of a recording run.

HACKATHON-BUILT — Meta Global AI Developer Hackathon (Oct 26 – Nov 4, 2026).

Live recordings run on a throwaway copy of the demo database, so the entries
they write (``voice.transcribed``, ``copilot.answer``, ``capa.draft`` ...) would
be lost with it. The recorder saves them as JSON next to the transcripts and
the public dashboard shows them, re-checking every hash from the stored fields.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from maudesignal.storage.database import Database

EXPORT_GLOB = "audit-*.json"


def export_audit(db: Database, path: Path, *, run_label: str) -> Path:
    """Write every audit entry of ``db`` to ``path`` as JSON.

    Args:
        db: Database the recording ran against.
        path: Output file (parents are created).
        run_label: Which recording run wrote the entries (shown on the page).

    Returns:
        ``path``.
    """
    ok, bad = db.verify_audit_chain()
    entries = [
        {
            "seq": r.seq,
            "ts": r.ts.isoformat(),
            "actor": r.actor,
            "action": r.action,
            "entity_id": r.entity_id,
            "payload_json": r.payload_json,
            "prev_hash": r.prev_hash,
            "entry_hash": r.entry_hash,
        }
        for r in db.list_audit()
    ]
    doc = {
        "run_label": run_label,
        "chain_ok_at_export": ok,
        "first_bad_seq_at_export": bad,
        "entries": entries,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


def verify_entries(entries: list[dict[str, Any]]) -> tuple[bool, int | None]:
    """Recompute the chain over exported entries.

    Args:
        entries: The ``entries`` list of an export, in chain order.

    Returns:
        ``(ok, first_bad_seq)``.
    """
    prev = "GENESIS"
    for e in entries:
        expected = Database.audit_entry_hash(
            prev,
            datetime.fromisoformat(e["ts"]),
            e["actor"],
            e["action"],
            e["entity_id"],
            e["payload_json"],
        )
        if e["prev_hash"] != prev or e["entry_hash"] != expected:
            return False, int(e["seq"])
        prev = e["entry_hash"]
    return True, None


def load_exports(directory: Path) -> list[dict[str, Any]]:
    """Load every audit export in ``directory`` (sorted by file name).

    Args:
        directory: Usually ``demo/transcripts``.

    Returns:
        Export documents, each with ``verified`` = ``(ok, first_bad_seq)``
        recomputed now (not trusted from the file).
    """
    docs = []
    for p in sorted(directory.glob(EXPORT_GLOB)):
        doc = json.loads(p.read_text(encoding="utf-8"))
        doc["file"] = p.name
        doc["verified"] = verify_entries(doc.get("entries", []))
        docs.append(doc)
    return docs
