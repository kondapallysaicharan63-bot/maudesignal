"""Note to file export (PRD-20) and QMS export bundle (PRD-25).

HACKATHON-BUILT — Meta Global AI Developer Hackathon (Oct 26 – Nov 4, 2026), 2026-11-03.

A draft note for the company's own QMS: date, product code, data-as-of, counts, report
IDs, recalls, the decision a named person chose (Note to file / CAPA / Escalate), their
typed rationale, approver name and timestamp. The decision is written to the hash-chained
audit trail first; the exported text carries the audit sequence number so the two can be
matched. Every export prints the build version + commit, the data-as-of line, and a
blank field for the company's complaint / CAPA number (never pre-filled).
"""

from __future__ import annotations

import csv
import io
import json
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from maudesignal.pms.asof import AsOf, as_of_text
from maudesignal.pms.board import valid_name
from maudesignal.pms.checklists import (
    EvidencePack,
    escalation_checklist,
    has_decision_sentence,
    recall_check,
    risk_section,
)
from maudesignal.pms.simple_pdf import render_pdf
from maudesignal.storage.database import Database

NOTE_LABEL = "Draft note to file for your QMS; not filed with FDA."
NOTE_ACTION = "note_to_file"
DECISIONS: dict[str, str] = {
    "note_to_file": "Note to file",
    "capa": "Open a CAPA (in your QMS)",
    "escalate": "Escalate",
}
BLANK_FIELD = "____________________"


class NoteToFileError(ValueError):
    """A note that cannot be recorded (no approver name, no rationale, bad decision)."""


def build_version(root: Path | None = None) -> tuple[str, str]:
    """``(version, commit)`` of this build; commit is "unknown" outside a git checkout."""
    from importlib.metadata import PackageNotFoundError, version

    try:
        ver = version("maudesignal")
    except PackageNotFoundError:
        ver = "unknown"
    try:
        commit = subprocess.run(  # noqa: S603 - fixed argv, no shell
            ["git", "rev-parse", "HEAD"],  # noqa: S607
            cwd=root or Path(__file__).resolve().parent,
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        commit = ""
    return ver, commit or "unknown"


@dataclass(frozen=True)
class NoteToFile:
    """A recorded note-to-file decision.

    Attributes:
        pack: The evidence the person reviewed.
        as_of: Data dates behind the pack.
        decision: Key of :data:`DECISIONS`.
        rationale: Text typed by the person.
        approver: Name typed by the person.
        decided_utc: When the decision was recorded (UTC, ISO).
        audit_seq: Sequence number of the audit entry.
        version: Build version.
        commit: Build commit.
    """

    pack: EvidencePack
    as_of: AsOf
    decision: str
    rationale: str
    approver: str
    decided_utc: str
    audit_seq: int
    version: str
    commit: str

    # ---------------------------------------------------------------- text
    def header_lines(self) -> list[str]:
        """The traceability block every export prints."""
        return [
            f"Build: MaudeSignal {self.version} · commit {self.commit}",
            f"Data as of: {self.as_of.latest or 'not stated'} — {as_of_text(self.as_of)}",
            f"Company complaint / CAPA number: {BLANK_FIELD} (fill in your QMS)",
        ]

    def to_markdown(self) -> str:
        """The note as Markdown."""
        p = self.pack
        out = [
            f"# Note to file — {p.product_code}" + (f" ({p.device_type})" if p.device_type else ""),
            "",
            f"**{NOTE_LABEL}**",
            "",
            *[f"- {h}" for h in self.header_lines()],
            f"- Date: {self.decided_utc[:10]}",
            f"- Product code: {p.product_code}",
            "",
            "## Why flagged",
            "",
            p.why,
            "",
            "## Reports",
            "",
            f"{len(p.reports)} report(s) in this pack:",
            "",
        ]
        for r in p.reports:
            out.append(
                f"- {r.get('report_id')} · {r.get('date_received') or 'date not stated'} · "
                f"{r.get('event_type') or 'event type not stated'}"
                + (f" · {r['url']}" if r.get("url") else "")
            )
        out += ["", "## Recalls", ""]
        if p.recalls:
            for r in p.recalls:
                out.append(
                    f"- {r.get('id')} · {r.get('date') or 'date not stated'} · "
                    f"{r.get('reason') or 'reason not stored'}"
                    + (f" · {r['url']}" if r.get("url") else "")
                )
        else:
            out.append("- No recall listed in this pack.")
        out += ["", "## Escalation checklist (human decides)", ""]
        for c in escalation_checklist(p):
            out.append(f"- [ ] {c['item']} ({c['basis']}): {c['question']}")
        rs = risk_section(p)
        out += ["", "## Risk inputs (ISO 14971; counts, not rates)", ""]
        for m in rs["severity_mix"]:
            share = "n/a" if m["share"] is None else f"{m['share'] * 100:.0f}%"
            out.append(f"- {m['event_type']}: {m['count']} of {m['of']} ({share})")
        out += [f"- {rs['occurrence']}", f"- [ ] {rs['detectability_question']}"]
        rc = recall_check(p)
        out += ["", "## Recall check (question, not answer)", "", f"- {rc['summary']}"]
        out += [f"- [ ] {rc['question']}", ""]
        out += [
            "## Decision (made by the person named below)",
            "",
            f"- Decision: {DECISIONS[self.decision]}",
            f"- Rationale (typed by the approver): {self.rationale}",
            f"- Approver: {self.approver}",
            f"- Recorded: {self.decided_utc} (audit entry #{self.audit_seq})",
            "",
            "Signature (in your QMS): ____________________   Date: __________",
            "",
            "MaudeSignal prepares evidence only. It does not decide reportability, recall "
            "or CAPA need, and nothing is filed with FDA. This build is not validated.",
        ]
        return "\n".join(out) + "\n"

    def to_pdf(self) -> bytes:
        """The same note as a PDF."""
        paras: list[tuple[str, str]] = []
        for line in self.to_markdown().splitlines():
            if line.startswith("# "):
                paras.append(("h1", line[2:]))
            elif line.startswith("## "):
                paras.append(("h2", line[3:]))
            else:
                paras.append(("body", line.replace("**", "")))
        return render_pdf(
            f"Note to file {self.pack.product_code}",
            paras,
            f"{NOTE_LABEL} MaudeSignal {self.version} ({self.commit[:12]})",
        )

    def reports_csv(self) -> str:
        """CSV of the pack's reports, with the traceability block as comment rows."""
        buf = io.StringIO()
        w = csv.writer(buf)
        for h in self.header_lines():
            w.writerow([f"# {h}"])
        w.writerow(["report_id", "date_received", "event_type", "source", "url"])
        for r in self.pack.reports:
            w.writerow(
                [
                    r.get("report_id"),
                    r.get("date_received"),
                    r.get("event_type"),
                    r.get("source"),
                    r.get("url"),
                ]
            )
        return buf.getvalue()


def record_note_to_file(
    db: Database,
    *,
    pack: EvidencePack,
    as_of: AsOf,
    decision: str,
    rationale: str,
    approver: str,
    root: Path | None = None,
) -> NoteToFile:
    """Write the decision to the audit trail, then return the exportable note.

    Raises:
        NoteToFileError: Missing approver name or rationale, unknown decision, or
            evidence text that contains a tool-made decision sentence. (The rationale is
            the person's own words and is kept as typed.)
    """
    if decision not in DECISIONS:
        raise NoteToFileError(f"decision must be one of {', '.join(DECISIONS)}")
    if not valid_name(approver):
        raise NoteToFileError("the approver must type their name")
    if len(rationale.strip()) < 10:
        raise NoteToFileError("type a rationale (at least 10 characters)")
    if has_decision_sentence(pack.why):
        raise NoteToFileError("the evidence text contains a tool-made decision sentence")
    ver, commit = build_version(root)
    row = db.append_audit(
        actor=approver.strip(),
        action=NOTE_ACTION,
        entity_id=f"board:{pack.product_code.upper()}",
        payload={
            "decision": decision,
            "rationale": rationale.strip()[:2000],
            "report_ids": [str(r.get("report_id")) for r in pack.reports],
            "recall_ids": [str(r.get("id")) for r in pack.recalls],
            "data_as_of": as_of.latest,
            "build": {"version": ver, "commit": commit},
        },
    )
    return NoteToFile(
        pack=pack,
        as_of=as_of,
        decision=decision,
        rationale=rationale.strip(),
        approver=approver.strip(),
        decided_utc=row.ts.replace(tzinfo=UTC).isoformat().replace("+00:00", "Z"),
        audit_seq=row.seq,
        version=ver,
        commit=commit,
    )


def audit_export(db: Database, version: str, commit: str, as_of: AsOf) -> dict[str, Any]:
    """The audit trail as JSON, with the traceability block and the chain check result."""
    ok, bad = db.verify_audit_chain()
    return {
        "build": {"version": version, "commit": commit},
        "data_as_of": as_of_text(as_of),
        "company_complaint_or_capa_number": "",
        "chain_ok": ok,
        "first_bad_seq": bad,
        "entries": [
            {
                "seq": e.seq,
                "ts": e.ts.isoformat(),
                "actor": e.actor,
                "action": e.action,
                "entity_id": e.entity_id,
                "payload_json": e.payload_json,
                "prev_hash": e.prev_hash,
                "entry_hash": e.entry_hash,
            }
            for e in db.list_audit()
        ],
    }


def export_bundle(db: Database, note: NoteToFile) -> dict[str, bytes]:
    """CSV of the flagged reports + PDF evidence pack + Markdown note + audit export."""
    code = note.pack.product_code
    stamp = note.decided_utc[:10].replace("-", "")
    audit = audit_export(db, note.version, note.commit, note.as_of)
    return {
        f"{code}-{stamp}-reports.csv": note.reports_csv().encode("utf-8"),
        f"{code}-{stamp}-note-to-file.md": note.to_markdown().encode("utf-8"),
        f"{code}-{stamp}-evidence-pack.pdf": note.to_pdf(),
        f"{code}-{stamp}-audit.json": json.dumps(audit, indent=2).encode("utf-8"),
    }


def utc_now_iso() -> str:
    """Now in UTC as ``YYYY-MM-DDTHH:MM:SSZ``."""
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
