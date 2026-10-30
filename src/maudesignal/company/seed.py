"""Write ``demo/company/company.json`` and ``demo/company/audit.json`` (sample data).

    PYTHONPATH=src python3 -m maudesignal.company.seed

Re-running reproduces the same two files byte for byte. The device list and the scripted
status history below are SAMPLE data (fictional devices, fictional people). The only real
data copied in are the device-type names (openFDA classification, with their query URL)
and the recorded AI-device sweep row of each product code (cited by file, code and date).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from maudesignal.company.constants import (
    BANNER,
    COMPANY_NAME,
    PROJECT_ROOT,
    S_COVERED,
    S_MONITORING,
    S_NEEDS_REVIEW,
    S_NOT_APPLICABLE,
    S_TESTING,
    company_dir,
    demo_db_path,
    sweep_path,
)
from maudesignal.company.evidence import (
    classification_url,
    demo_db_codes,
    load_demo_db_evidence,
)
from maudesignal.company.status import append_status, save_audit, utc

#: (device id, fictional name, model, product code, fictional owner)
DEVICES: tuple[tuple[str, str, str, str, str], ...] = (
    ("DMC-01", "Vellmar ViewStation", "HV-200", "LLZ", "Mara Ellison"),
    ("DMC-02", "Vellmar ReportDesk", "RD-110", "LLZ", "Devon Park"),
    ("DMC-03", "Lumenar Renal Assist", "LRA-3", "QIH", "Iris Tanaka"),
    ("DMC-04", "Tessera Slide Reader", "TSR-5", "MYN", "Tomas Reyes"),
    ("DMC-05", "Oriel Lesion Check", "OLC-2", "POK", "Lena Osei"),
    ("DMC-06", "Brindle Series 6", "BS-600", "IYN", "Noor Haddad"),
    ("DMC-07", "Kestrel Series 7", "KS-700", "OTE", "Callum Brodie"),
    ("DMC-08", "Marlow Series 4", "MS-400", "DSI", "Yuki Sato"),
    ("DMC-09", "Quillon Series 2", "QS-200", "MUD", "Ana Moreau"),
    ("DMC-10", "Fennick Series 6", "FS-600", "DQK", "Ravi Menon"),
    ("DMC-11", "Sable Series 3", "SS-300", "LNH", "Elin Strand"),
    ("DMC-12", "Pelham Series 9", "PS-900", "MWI", "Joss Whitaker"),
)

_SIM = "(simulated)"


def _sim(name: str) -> str:
    return f"{name} {_SIM}"


#: (device id, status, who, (y, m, d), details, note), in time order.
HISTORY: tuple[tuple[str, str, str, tuple[int, int, int], dict[str, str], str], ...] = (
    ("DMC-01", S_NEEDS_REVIEW, "Mara Ellison", (2026, 10, 12), {"owner": _sim("Mara Ellison")}, ""),
    ("DMC-02", S_NEEDS_REVIEW, "Devon Park", (2026, 10, 12), {"owner": _sim("Devon Park")}, ""),
    ("DMC-04", S_MONITORING, "Tomas Reyes", (2026, 10, 14), {}, "nothing open (sample note)"),
    ("DMC-05", S_MONITORING, "Lena Osei", (2026, 10, 14), {}, "nothing open (sample note)"),
    ("DMC-10", S_MONITORING, "Ravi Menon", (2026, 10, 14), {}, "nothing open (sample note)"),
    ("DMC-11", S_MONITORING, "Elin Strand", (2026, 10, 14), {}, "nothing open (sample note)"),
    (
        "DMC-12",
        S_NEEDS_REVIEW,
        "Joss Whitaker",
        (2026, 10, 15),
        {"owner": _sim("Joss Whitaker")},
        "",
    ),
    (
        "DMC-02",
        S_COVERED,
        "Devon Park",
        (2026, 10, 16),
        {
            "reference": "test report TR-104 (sample) covers the pattern "
            "'Unable to log in or connect, including server errors'"
        },
        "",
    ),
    (
        "DMC-01",
        S_TESTING,
        "Mara Ellison",
        (2026, 10, 19),
        {"owner": _sim("Mara Ellison"), "due_date": "2026-11-20"},
        "",
    ),
    ("DMC-03", S_NEEDS_REVIEW, "Iris Tanaka", (2026, 10, 20), {"owner": _sim("Iris Tanaka")}, ""),
    (
        "DMC-12",
        S_NOT_APPLICABLE,
        "Joss Whitaker",
        (2026, 10, 22),
        {
            "reason": "our device has no user log-in function, so the pattern "
            "'Log-in, access or security problem' does not apply (sample reason)"
        },
        "",
    ),
    ("DMC-06", S_NEEDS_REVIEW, "Noor Haddad", (2026, 10, 29), {"owner": _sim("Noor Haddad")}, ""),
    (
        "DMC-07",
        S_NEEDS_REVIEW,
        "Callum Brodie",
        (2026, 10, 29),
        {"owner": _sim("Callum Brodie")},
        "",
    ),
    ("DMC-08", S_NEEDS_REVIEW, "Yuki Sato", (2026, 10, 29), {"owner": _sim("Yuki Sato")}, ""),
    ("DMC-09", S_NEEDS_REVIEW, "Ana Moreau", (2026, 10, 29), {"owner": _sim("Ana Moreau")}, ""),
)

NOTES = (
    "Simulated company: every name, owner, model, status and date in this file is sample data.",
    "Problem evidence (reports, recalls) is real openFDA data kept in separate files; "
    "this file holds none of it.",
    "Product codes: LLZ (x2), QIH, MYN, POK are in the demo database; IYN, OTE, DSI, MUD are "
    "sweep-flagged codes; DQK, LNH, MWI are sweep 'no change' codes with 3 or more prior reports.",
)


def _sweep_rows(path: Path) -> dict[str, dict[str, Any]]:
    doc = json.loads(path.read_text(encoding="utf-8"))
    return {r["product_code"]: r for r in doc["rows"]}


def _sweep_block(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "file": "demo/sweep/ai-device-sweep.json",
        "product_code": row["product_code"],
        "as_of": row["as_of"],
        "classification": row["classification"],
        "triggers": list(row["triggers"]),
        "current_count": row["current_count"],
        "baseline_count": row["baseline_count"],
        "prior_report_count": row["prior_report_count"],
        "query_url": row["queries"][0][1] if row.get("queries") else None,
    }


def build_company_doc(db: Path, sweep: Path) -> dict[str, Any]:
    """The ``company.json`` document."""
    rows = _sweep_rows(sweep)
    in_db = demo_db_codes(db)
    devices = []
    for device_id, name, model, code, owner in DEVICES:
        if code in in_db:
            ev = load_demo_db_evidence(code, db)
            dtype: dict[str, Any] = {
                "name": ev.classification_name,
                "source": ev.classification_source,
                "query_url": ev.classification_query_url,
            }
        else:
            dtype = {
                "name": None,
                "source": None,
                "query_url": classification_url(code),
                "note": "name is read from the fetched evidence file (openFDA classification)",
            }
        devices.append(
            {
                "device_id": device_id,
                "name": name,
                "model": model,
                "product_code": code,
                "owner": _sim(owner),
                "device_type": dtype,
                "sweep": _sweep_block(rows[code]) if code in rows else None,
            }
        )
    return {
        "schema_version": "1.0",
        "company": COMPANY_NAME,
        "banner": BANNER,
        "notes": list(NOTES),
        "devices": devices,
    }


def build_audit_entries(device_ids: list[str]) -> list[dict[str, Any]]:
    """The scripted, chained status history."""
    entries: list[dict[str, Any]] = []
    for device_id, status, who, (y, m, d), details, note in HISTORY:
        append_status(
            entries,
            device_ids=device_ids,
            device_id=device_id,
            to_status=status,
            actor=_sim(who),
            ts=utc(y, m, d),
            details=details,
            note=note,
        )
    return entries


def main(folder: Path | None = None) -> None:
    """Write both files into ``demo/company`` (or ``folder``)."""
    out = folder or company_dir()
    out.mkdir(parents=True, exist_ok=True)
    doc = build_company_doc(demo_db_path(), sweep_path())
    (out / "company.json").write_text(
        json.dumps(doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    save_audit(out / "audit.json", build_audit_entries([d["device_id"] for d in doc["devices"]]))
    shown = out.relative_to(PROJECT_ROOT) if out.is_relative_to(PROJECT_ROOT) else out
    sys.stdout.write(f"wrote {shown}\n")


if __name__ == "__main__":
    main()
