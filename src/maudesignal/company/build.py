"""Assemble the "Our devices" view of the simulated company.

Company data (``demo/company/company.json``, ``audit.json``) is read as it is; real
evidence (reports, recalls) is read from the demo database or the fetched evidence files
and never written back. The same view feeds the Streamlit page, the evidence-pack PDF
section and the web export (``company.json``, see ``web/DATA_CONTRACT.md``).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from maudesignal.company.constants import (
    ACTION_CHANGE,
    BANNER,
    COMPANY_NAME,
    STATUS_RANK,
    STATUSES,
    company_dir,
    demo_db_path,
)
from maudesignal.company.evidence import CodeEvidence, demo_db_codes, load_evidence
from maudesignal.company.patterns import CodePatterns, Pattern, build_code_patterns
from maudesignal.company.status import (
    StatusEntry,
    audit_path,
    current_statuses,
    load_audit,
    parse_entries,
    validate_history,
    verify_chain,
)

SCHEMA_VERSION = "1.0"
NOT_FETCHED = "evidence not fetched yet"


@dataclass
class DeviceView:
    """One fictional device with its status history and the real evidence for its code."""

    device_id: str
    name: str
    model: str
    product_code: str
    owner: str
    device_type_name: str | None
    device_type_source: str | None
    device_type_query_url: str | None
    sweep: dict[str, Any] | None
    status: StatusEntry | None
    history: list[StatusEntry]
    evidence: CodeEvidence
    code_patterns: CodePatterns
    evidence_note: str | None = None

    @property
    def patterns(self) -> list[Pattern]:
        """Gate-passed problem patterns for this device's product code."""
        return self.code_patterns.patterns

    @property
    def has_patterns(self) -> bool:
        """True when at least one real pattern exists for the code."""
        return bool(self.code_patterns.patterns)


@dataclass
class CompanyView:
    """The whole simulated company."""

    company: str
    banner: str
    devices: list[DeviceView]
    audit_entries: list[dict[str, Any]]
    chain_ok: bool
    chain_first_bad: int | None
    notes: list[str] = field(default_factory=list)

    def device(self, device_id: str) -> DeviceView | None:
        """Device by id."""
        return next((d for d in self.devices if d.device_id == device_id), None)

    def on_code(self, product_code: str) -> list[DeviceView]:
        """Devices registered on one product code."""
        return [d for d in self.devices if d.product_code == product_code]


def status_detail(entry: StatusEntry) -> str:
    """One plain line with the details a status carries."""
    d = entry.details
    parts: list[str] = []
    if d.get("owner"):
        parts.append(f"owner {d['owner']}")
    if d.get("due_date"):
        parts.append(f"due {d['due_date']}")
    if d.get("reference"):
        parts.append(str(d["reference"]))
    if d.get("reason"):
        parts.append(str(d["reason"]))
    return "; ".join(parts)


def load_company_doc(folder: Path | None = None) -> dict[str, Any]:
    """Read ``company.json`` as stored."""
    doc: dict[str, Any] = json.loads(
        ((folder or company_dir()) / "company.json").read_text(encoding="utf-8")
    )
    return doc


def load_company(
    folder: Path | None = None,
    *,
    db_path: Path | None = None,
    evidence_folder: Path | None = None,
    investigations: Path | None = None,
) -> CompanyView:
    """Build the full company view; raises if the stored status history breaks a rule."""
    base = folder or company_dir()
    doc = load_company_doc(base)
    entries = load_audit(audit_path(base))
    device_ids = [d["device_id"] for d in doc["devices"]]
    validate_history(entries, device_ids)
    chain_ok, bad = verify_chain(entries)
    latest = current_statuses(entries)
    history: dict[str, list[StatusEntry]] = {}
    for e in parse_entries(entries):
        history.setdefault(e.device_id, []).append(e)

    dbp = db_path or demo_db_path()
    db_codes = demo_db_codes(dbp)
    evidence: dict[str, CodeEvidence] = {}
    patterns: dict[str, CodePatterns] = {}
    devices: list[DeviceView] = []
    for d in doc["devices"]:
        code = d["product_code"]
        if code not in evidence:
            evidence[code] = load_evidence(
                code,
                db_path=dbp,
                evidence_folder=evidence_folder or base / "evidence",
                db_codes=db_codes,
            )
            patterns[code] = build_code_patterns(evidence[code], investigations)
        ev = evidence[code]
        dt = d.get("device_type") or {}
        name = dt.get("name") or ev.classification_name
        devices.append(
            DeviceView(
                device_id=d["device_id"],
                name=d["name"],
                model=d["model"],
                product_code=code,
                owner=d["owner"],
                device_type_name=name,
                device_type_source=dt.get("source") or ev.classification_source,
                device_type_query_url=dt.get("query_url") or ev.classification_query_url,
                sweep=d.get("sweep"),
                status=latest.get(d["device_id"]),
                history=history.get(d["device_id"], []),
                evidence=ev,
                code_patterns=patterns[code],
                evidence_note=None if ev.available else NOT_FETCHED,
            )
        )
    return CompanyView(
        company=doc.get("company", COMPANY_NAME),
        banner=BANNER,
        devices=devices,
        audit_entries=entries,
        chain_ok=chain_ok,
        chain_first_bad=bad,
        notes=list(doc.get("notes", [])),
    )


# ── export (web/DATA_CONTRACT.md, "company.json") ────────────────────────────


def _entry_json(e: StatusEntry) -> dict[str, Any]:
    return {
        "seq": e.seq,
        "date": e.date_label,
        "ts": e.ts.isoformat(),
        "actor": e.actor,
        "action": "register" if e.action != ACTION_CHANGE else "change",
        "from_status": e.from_status,
        "to_status": e.to_status,
        "details": dict(e.details),
        "note": e.note,
        "entry_hash": e.entry_hash,
    }


def _pattern_json(p: Pattern) -> dict[str, Any]:
    return {
        "id": p.pattern_id,
        "label": p.label,
        "basis": p.basis,
        "count": p.count,
        "report_ids": list(p.report_ids),
        "first_received": p.first_received,
        "last_received": p.last_received,
        "quotes": [{"report_id": q.report_id, "text": q.text, "url": q.url} for q in p.quotes],
        "links": [{"label": a, "url": b} for a, b in p.links],
        "gate": {
            "count": p.gate_count,
            "reason": p.gate_reason,
            "quotes_passed": p.quotes_passed,
            "quotes_withheld": p.quotes_withheld,
        },
    }


def _evidence_json(dv: DeviceView) -> dict[str, Any]:
    ev, cp = dv.evidence, dv.code_patterns
    if not ev.available:
        return {
            "origin": ev.origin,
            "available": False,
            "note": dv.evidence_note,
            "report_count": None,
            "window": None,
            "queries": [],
            "recalls": None,
        }
    rc = cp.recalls
    return {
        "origin": ev.origin,
        "available": True,
        "note": "; ".join(ev.notes) or None,
        "fetched_utc": ev.fetched_utc,
        "report_count": {
            "value": cp.report_count,
            "gate": cp.report_count_gate,
            "reason": cp.report_count_reason,
        },
        "window": {"date_from": ev.window_from, "date_to": ev.window_to},
        "queries": [{"label": a, "url": b} for a, b in ev.queries],
        "recalls": (
            None
            if rc is None
            else {
                "stored": rc.stored,
                "matched_total": rc.matched_total,
                "gate": rc.gate_status,
                "reason": rc.gate_reason,
                "latest": [
                    {
                        "recall_number": i.recall_number,
                        "recalling_firm": i.recalling_firm,
                        "status": i.status,
                        "date_initiated": i.date_initiated,
                        "excerpt": i.excerpt,
                        "url": i.url,
                    }
                    for i in rc.latest
                ],
            }
        ),
        "gate_totals": {"pass": cp.gate_pass, "block": cp.gate_block},
    }


def export_company(view: CompanyView, generated_utc: datetime | None = None) -> dict[str, Any]:
    """The ``company.json`` document for the web (shape in ``web/DATA_CONTRACT.md``)."""
    notes = list(view.notes)
    for d in view.devices:
        if not d.evidence.available:
            note = f"{d.product_code}: {NOT_FETCHED}; no count, pattern or quote is shown for it."
            if note not in notes:
                notes.append(note)
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_utc": (generated_utc or datetime.now(UTC)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "banner": view.banner,
        "company": view.company,
        "statuses": [{"label": s, "rank": STATUS_RANK[s]} for s in STATUSES],
        "devices": [
            {
                "id": d.device_id,
                "name": d.name,
                "model": d.model,
                "product_code": d.product_code,
                "owner": d.owner,
                "device_type": {
                    "name": d.device_type_name,
                    "source": d.device_type_source,
                    "query_url": d.device_type_query_url,
                },
                "sweep": d.sweep,
                "status": (
                    None
                    if d.status is None
                    else {
                        "label": d.status.to_status,
                        "set_by": d.status.actor,
                        "date": d.status.date_label,
                        "detail": status_detail(d.status),
                        "details": dict(d.status.details),
                    }
                ),
                "history": [_entry_json(e) for e in d.history],
                "evidence": _evidence_json(d),
                "patterns": [_pattern_json(p) for p in d.patterns],
            }
            for d in view.devices
        ],
        "audit": {
            "file": "demo/company/audit.json",
            "chain_ok": view.chain_ok,
            "first_bad_seq": view.chain_first_bad,
            "entries": view.audit_entries,
        },
        "notes": notes,
    }
