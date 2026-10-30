"""Device statuses: set only by a named simulated person, forward-only, hash-chained.

The tool never sets a status. Every change is an entry in ``demo/company/audit.json``:
an append-only list whose entries are chained with the same SHA-256 helper the copilot
audit trail uses (``Database.audit_entry_hash`` / ``copilot.audit_export.verify_entries``),
so any edit, removal or reordering is detected when the chain is re-verified.

Rules (see ``constants.STATUS_RANK``):

* the first entry of a device is a ``register`` entry (any status);
* every later entry is a ``change`` that moves to a strictly higher rank;
* the actor is a named simulated person (``"<Name> (simulated)"``), never the tool;
* each status carries the details it needs (owner, due date, reference, reason);
* entries are chronological.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from maudesignal.company.constants import (
    ACTION_CHANGE,
    ACTION_REGISTER,
    BANNER,
    COMPANY_NAME,
    SIMULATED_SUFFIX,
    STATUS_RANK,
    STATUS_REQUIRED,
    TOOL_ACTORS,
    contains_forbidden,
)
from maudesignal.copilot.audit_export import verify_entries
from maudesignal.storage.database import Database

GENESIS = "GENESIS"


class StatusError(ValueError):
    """A status change that the rules reject."""


@dataclass(frozen=True)
class StatusEntry:
    """One parsed audit entry."""

    seq: int
    ts: datetime
    actor: str
    action: str
    device_id: str
    from_status: str | None
    to_status: str
    details: Mapping[str, str] = field(default_factory=dict)
    note: str = ""
    entry_hash: str = ""

    @property
    def date_label(self) -> str:
        """Date (UTC) of the change."""
        return self.ts.date().isoformat()


def validate_actor(actor: str) -> None:
    """Accept only a named simulated person."""
    name = actor.strip()
    if not name.endswith(SIMULATED_SUFFIX) or len(name) <= len(SIMULATED_SUFFIX) + 3:
        raise StatusError(
            f'actor must be a named simulated person, like "Ana Diaz {SIMULATED_SUFFIX}"'
        )
    if set(name.removesuffix(SIMULATED_SUFFIX).lower().split()) & TOOL_ACTORS:
        raise StatusError("the tool never sets a status")


def _validate_details(status: str, details: Mapping[str, str]) -> None:
    if status not in STATUS_RANK:
        raise StatusError(f"unknown status {status!r}")
    for key in STATUS_REQUIRED[status]:
        if not str(details.get(key, "")).strip():
            raise StatusError(f"status {status!r} needs {key.replace('_', ' ')}")
    if "due_date" in STATUS_REQUIRED[status]:
        try:
            date.fromisoformat(str(details["due_date"]))
        except ValueError as exc:
            raise StatusError("due date must be YYYY-MM-DD") from exc
    for value in details.values():
        if contains_forbidden(str(value)):
            raise StatusError("status text uses a word these screens never print")


def _payload(
    device_id: str,
    from_status: str | None,
    to_status: str,
    details: Mapping[str, str],
    note: str,
) -> str:
    return json.dumps(
        {
            "device_id": device_id,
            "from_status": from_status,
            "to_status": to_status,
            "details": dict(sorted(details.items())),
            "note": note,
        },
        sort_keys=True,
        ensure_ascii=False,
    )


def parse_entries(entries: Iterable[Mapping[str, Any]]) -> list[StatusEntry]:
    """Parse raw audit entries into :class:`StatusEntry` objects."""
    out: list[StatusEntry] = []
    for e in entries:
        p = json.loads(e["payload_json"])
        out.append(
            StatusEntry(
                seq=int(e["seq"]),
                ts=datetime.fromisoformat(e["ts"]),
                actor=str(e["actor"]),
                action=str(e["action"]),
                device_id=str(p["device_id"]),
                from_status=p.get("from_status"),
                to_status=str(p["to_status"]),
                details=dict(p.get("details") or {}),
                note=str(p.get("note") or ""),
                entry_hash=str(e["entry_hash"]),
            )
        )
    return out


def current_statuses(entries: Iterable[Mapping[str, Any]]) -> dict[str, StatusEntry]:
    """Latest entry of each device (its current status)."""
    latest: dict[str, StatusEntry] = {}
    for e in parse_entries(entries):
        latest[e.device_id] = e
    return latest


def _check_step(
    prev: StatusEntry | None,
    *,
    device_id: str,
    to_status: str,
    actor: str,
    details: Mapping[str, str],
    last_ts: datetime | None,
    ts: datetime,
) -> str:
    """Validate one step; returns the action name to record."""
    validate_actor(actor)
    _validate_details(to_status, details)
    if ts.tzinfo is None:
        raise StatusError("time stamp must carry a time zone")
    if last_ts is not None and ts < last_ts:
        raise StatusError("entries must be in time order")
    if prev is None:
        return ACTION_REGISTER
    if STATUS_RANK[to_status] <= STATUS_RANK[prev.to_status]:
        raise StatusError(
            f"{device_id}: {prev.to_status!r} -> {to_status!r} is not forward "
            "(statuses only move forward)"
        )
    return ACTION_CHANGE


def append_status(
    entries: list[dict[str, Any]],
    *,
    device_ids: Iterable[str],
    device_id: str,
    to_status: str,
    actor: str,
    ts: datetime,
    details: Mapping[str, str] | None = None,
    note: str = "",
) -> dict[str, Any]:
    """Validate and append one status entry to the chain (mutates ``entries``).

    Raises:
        StatusError: unknown device, actor is not a named simulated person, the move is
            not forward, details are missing, or the time goes backwards.
    """
    if device_id not in set(device_ids):
        raise StatusError(f"unknown device {device_id!r}")
    details = details or {}
    parsed = parse_entries(entries)
    prev = next((e for e in reversed(parsed) if e.device_id == device_id), None)
    action = _check_step(
        prev,
        device_id=device_id,
        to_status=to_status,
        actor=actor,
        details=details,
        last_ts=parsed[-1].ts if parsed else None,
        ts=ts,
    )
    payload = _payload(device_id, prev.to_status if prev else None, to_status, details, note)
    prev_hash = entries[-1]["entry_hash"] if entries else GENESIS
    entry = {
        "seq": len(entries) + 1,
        "ts": ts.isoformat(),
        "actor": actor,
        "action": action,
        "entity_id": device_id,
        "payload_json": payload,
        "prev_hash": prev_hash,
        "entry_hash": Database.audit_entry_hash(prev_hash, ts, actor, action, device_id, payload),
    }
    entries.append(entry)
    return entry


def validate_history(entries: Iterable[Mapping[str, Any]], device_ids: Iterable[str]) -> None:
    """Replay every rule over stored entries (the chain check cannot see a rule break).

    Raises:
        StatusError: on the first entry that breaks a rule.
    """
    known = set(device_ids)
    last: dict[str, StatusEntry] = {}
    last_ts: datetime | None = None
    for e in parse_entries(entries):
        if e.device_id not in known:
            raise StatusError(f"entry {e.seq}: unknown device {e.device_id!r}")
        action = _check_step(
            last.get(e.device_id),
            device_id=e.device_id,
            to_status=e.to_status,
            actor=e.actor,
            details=e.details,
            last_ts=last_ts,
            ts=e.ts,
        )
        if action != e.action:
            raise StatusError(f"entry {e.seq}: action {e.action!r} should be {action!r}")
        prev = last.get(e.device_id)
        if (prev.to_status if prev else None) != e.from_status:
            raise StatusError(f"entry {e.seq}: from-status does not match the history")
        last[e.device_id] = e
        last_ts = e.ts


# ── files ────────────────────────────────────────────────────────────────────


def audit_path(folder: Path) -> Path:
    """``audit.json`` inside the company folder."""
    return folder / "audit.json"


def save_audit(path: Path, entries: list[dict[str, Any]]) -> None:
    """Write the audit file (entries in chain order)."""
    ok, _ = verify_entries(entries)
    doc = {
        "schema_version": "1.0",
        "company": COMPANY_NAME,
        "banner": BANNER,
        "kind": "simulated-company-status-audit",
        "chain": "SHA-256, same helper as the copilot audit trail (Database.audit_entry_hash)",
        "chain_ok_at_export": ok,
        "entries": entries,
    }
    path.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def load_audit(path: Path) -> list[dict[str, Any]]:
    """Read the audit entries (empty list when the file is missing)."""
    if not path.is_file():
        return []
    doc = json.loads(path.read_text(encoding="utf-8"))
    entries: list[dict[str, Any]] = list(doc.get("entries", []))
    return entries


def verify_chain(entries: list[dict[str, Any]]) -> tuple[bool, int | None]:
    """Recompute the whole chain now: ``(ok, first_bad_seq)``."""
    return verify_entries(entries)


def utc(year: int, month: int, day: int, hour: int = 15, minute: int = 0) -> datetime:
    """A UTC time stamp (used by the seed script)."""
    return datetime(year, month, day, hour, minute, tzinfo=UTC)
