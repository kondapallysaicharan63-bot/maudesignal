"""Export stored MaudeSignal data for the static web workspace.

HACKATHON-BUILT — Meta Global AI Developer Hackathon (Oct 26 – Nov 4, 2026).

Reads the committed inputs (demo database, digests, copilot transcripts, audit
exports, evidence pack, vision runs, AI-device sweep) and writes the JSON files
described in ``web/DATA_CONTRACT.md`` to ``web/public/data/``. No network, no
API key, no LLM call. Every number is copied from an input or counted from it;
a missing input becomes ``null`` plus a line in that file's ``notes``.

    python3 scripts/export_web_data.py
    python3 scripts/export_web_data.py --out /tmp/web-data
    python3 scripts/export_web_data.py --parity-fixtures   # TypeScript detector parity cases
"""

from __future__ import annotations

import argparse
import json
import random
import re
import shutil
import sqlite3
import subprocess
import sys
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from maudesignal.copilot.audit_export import verify_entries  # noqa: E402
from maudesignal.gate import (  # noqa: E402
    CountClaim,
    EvidenceRecord,
    EvidenceStore,
    QuoteClaim,
    RecallCountClaim,
    RecallRef,
    verify_claim,
)
from maudesignal.gate.evidence import normalize_source  # noqa: E402

SCHEMA_VERSION = "1.0"
MAUDE_DETAIL_URL = (
    "https://www.accessdata.fda.gov/scripts/cdrh/cfdocs/cfmaude/detail.cfm?mdrfoi__id={}"
)
# Same renaming the Streamlit app uses (dashboard/copilot_pages.py _TOOL_LABELS).
TOOL_LABELS = {"overnight_signals": "weekly_signals", "draft_capa": "capa_need_evidence"}
OVERNIGHT_LABELS = ("01", "02", "13", "15", "20", "22")
CAPA_LABELS = ("05",)
GREETING_LABELS = ("00-voice-a", "00-voice-b")
# Clips kept out of the web data: the question text uses words the product does not show
# (see docs/hackathon/PRD.md). They stay in demo/transcripts; only the display skips them.
DISPLAY_EXCLUDED_LABELS = ("00-voice-main",)
WORKFLOW_TITLES = {
    "weekly-signals": "What changed this week",
    "ask-copilot": "Ask the copilot",
    "capa-need-evidence": "CAPA-need evidence",
}
# What a tool did, in words, when its stored preview holds no number.
TOOL_WORDS = {
    "weekly_signals": "checked the weekly signals",
    "product_summary": "summarised a device type",
    "search_reports": "searched stored reports",
    "get_report": "read a report",
    "recalls": "checked recalls",
    "device_510k": "looked up a 510(k)",
    "literature": "searched stored literature",
    "compare_signals": "compared device types",
    "my_device_types": "listed the chosen device types",
    "report_sources": "split reports by who filed them",
    "mhra_alerts": "checked MHRA (UK) alerts",
    "deadline_check": "checked a reporting deadline",
    "capa_need_evidence": "put together CAPA-need evidence for human review (nothing filed)",
}
# Dataset a tool reads, used only when the stored preview carries no "source".
TOOL_DATASETS = {
    "weekly_signals": "openFDA MAUDE (stored copy)",
    "product_summary": "openFDA MAUDE (stored copy)",
    "search_reports": "openFDA MAUDE (stored copy)",
    "get_report": "openFDA MAUDE (stored copy)",
    "compare_signals": "openFDA MAUDE (stored copy)",
    "report_sources": "openFDA MAUDE (stored copy)",
    "recalls": "openFDA recalls (stored copy)",
    "device_510k": "FDA 510(k) AI/ML catalog (stored copy)",
    "literature": "PubMed (stored copy)",
    "mhra_alerts": "MHRA (UK) device safety alerts (stored copy)",
}
DEMO_DB = "data/demo/maudesignal_demo.db"


# ── helpers ──────────────────────────────────────────────────────────────────
def read_json(path: Path) -> Any:
    """Parse a JSON file."""
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, doc: Any) -> None:
    """Write ``doc`` as indented UTF-8 JSON with a trailing newline."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def tool_label(name: str) -> str:
    """Name of a copilot tool as shown on screen."""
    return TOOL_LABELS.get(name, name)


def git_sha(root: Path) -> str | None:
    """Current commit of ``root`` or ``None`` when git is unavailable."""
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=root, capture_output=True, text=True, check=True
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    return out.stdout.strip() or None


def number_in(preview: str, key: str) -> int | None:
    """Integer value of ``"key": N`` in a (possibly cut) JSON preview."""
    m = re.search(rf'"{re.escape(key)}":\s*(\d+)\b', preview)
    return int(m.group(1)) if m else None


def string_in(preview: str, key: str) -> str | None:
    """String value of ``"key": "..."`` in a (possibly cut) JSON preview."""
    m = re.search(rf'"{re.escape(key)}":\s*("(?:[^"\\]|\\.)*")', preview)
    if not m:
        return None
    try:
        return str(json.loads(m.group(1)))
    except json.JSONDecodeError:
        return None


def tool_count(name: str, preview: str) -> int | None:
    """The one count a tool reported in its stored preview, if any."""
    for key in ("report_count", "matched", "stored_recall_count"):
        n = number_in(preview, key)
        if n is not None:
            return n
    return None


def tool_summary(name: str, arguments: dict[str, Any], preview: str) -> str:
    """One line for a tool step, built only from the stored preview and arguments."""
    code = arguments.get("product_code")
    n = number_in(preview, "report_count") if name == "product_summary" else None
    if name == "product_summary" and n is not None:
        return f"counted {n} reports" + (f" for {code}" if code else "")
    if name == "search_reports":
        n = number_in(preview, "matched")
        if n is not None:
            return f"found {n} matching reports"
    if name == "recalls":
        n = number_in(preview, "stored_recall_count")
        if n is not None:
            return f"checked {n} stored recalls"
    if name == "literature":
        n = number_in(preview, "matched")
        if n is not None:
            return f"found {n} matching articles"
    if name == "weekly_signals":
        headline = string_in(preview, "headline")
        if headline:
            return f"weekly signals: {headline}"
    if name == "get_report" and arguments.get("report_id"):
        return f"read report {arguments['report_id']}"
    if name == "device_510k" and arguments.get("k_number"):
        return f"looked up {arguments['k_number']}"
    return TOOL_WORDS.get(name, name.replace("_", " "))


# ── threads, evidence, protocol ──────────────────────────────────────────────
def workflow_for(label: str) -> str:
    """Workflow id for a transcript label (rules in the data contract)."""
    if label.startswith("00-voice-"):
        return "ask-copilot"
    if label.split("-", 1)[0] in OVERNIGHT_LABELS:
        return "weekly-signals"
    if label.split("-", 1)[0] in CAPA_LABELS:
        return "capa-need-evidence"
    return "ask-copilot"


def thread_sort_key(label: str) -> tuple[int, str]:
    """Product questions in label order, the two greeting clips last."""
    if label in GREETING_LABELS:
        return (2, label)
    if label.startswith("00-voice-"):
        return (1, label)
    return (0, label)


def load_transcripts(root: Path) -> list[dict[str, Any]]:
    """Every ``demo/transcripts/<ts>-<label>.json`` (audit exports excluded)."""
    files = sorted(
        p for p in (root / "demo" / "transcripts").glob("2*.json") if not p.name.startswith("audit")
    )
    docs = [read_json(p) for p in files]
    return [d for d in docs if d["label"] not in DISPLAY_EXCLUDED_LABELS]


def build_threads(transcripts: list[dict[str, Any]]) -> dict[str, Any]:
    """``threads.json``."""
    threads: list[dict[str, Any]] = []
    for t in sorted(transcripts, key=lambda d: thread_sort_key(d["label"])):
        steps = []
        for call in t.get("tool_calls", []):
            name = tool_label(call["name"])
            steps.append(
                {
                    "name": name,
                    "arguments": call.get("arguments", {}),
                    "summary": tool_summary(
                        name, call.get("arguments", {}), call.get("result_preview", "")
                    ),
                }
            )
        fp = t.get("first_pass", {})
        threads.append(
            {
                "id": t["label"],
                "workflow": workflow_for(t["label"]),
                "question": t.get("question"),
                "voice": t.get("voice"),
                "recorded_at_utc": t.get("recorded_at_utc"),
                "model": t.get("model"),
                "tool_steps": steps,
                "sentences": t["final"]["sentences"],
                "first_pass": {
                    "passed": fp.get("passed"),
                    "blocked": fp.get("blocked"),
                    "sentences": fp.get("sentences", []),
                },
                "repaired": t.get("repaired"),
                "usage": t.get("usage"),
            }
        )
    workflows = []
    for wid, title in WORKFLOW_TITLES.items():
        ids = [th["id"] for th in threads if th["workflow"] == wid]
        workflows.append({"id": wid, "title": title, "thread_ids": ids})
    return {"schema_version": SCHEMA_VERSION, "workflows": workflows, "threads": threads}


def header_counts(threads: dict[str, Any], audit: dict[str, Any]) -> dict[str, Any]:
    """Header numbers of the manifest (rules in the data contract)."""
    claims_verified = sentences_verified = sentences_withheld = 0
    for th in threads["threads"]:
        for s in th["sentences"]:
            if s["status"] == "pass":
                sentences_verified += 1
            elif s["status"] == "block":
                sentences_withheld += 1
            claims_verified += sum(1 for c in s.get("claims", []) if c["status"] == "pass")
    runs = audit["runs"]
    return {
        "claims_verified": claims_verified,
        "sentences_verified": sentences_verified,
        "sentences_withheld": sentences_withheld,
        "answers": len(threads["threads"]),
        "audit_chain_ok": bool(runs) and all(r["chain_ok"] for r in runs),
    }


def evidence_ids(threads: dict[str, Any]) -> list[str]:
    """Every evidence id referenced by a claim, final or first pass."""
    seen: dict[str, None] = {}
    for th in threads["threads"]:
        for group in (th["sentences"], th["first_pass"]["sentences"]):
            for s in group:
                for c in s.get("claims", []):
                    for e in c.get("evidence_ids", []):
                        seen.setdefault(str(e), None)
    return list(seen)


def build_evidence(conn: sqlite3.Connection, threads: dict[str, Any]) -> dict[str, Any]:
    """``evidence.json``: stored rows behind every cited id."""
    reports: dict[str, Any] = {}
    other: dict[str, Any] = {}
    notes: list[str] = []
    for eid in evidence_ids(threads):
        if re.fullmatch(r"\d+", eid):
            row = conn.execute(
                "select n.product_code, r.date_received, n.event_type, n.report_source,"
                " n.brand_name, n.narrative, n.mfr_narrative"
                " from normalized_events n join raw_reports r using (maude_report_id)"
                " where n.maude_report_id = ?",
                (eid,),
            ).fetchone()
            if row is None:
                other[eid] = {"kind": "report", "label": None, "url": None}
                notes.append(f"report {eid} is not in the demo database")
                continue
            text = (row[5] or row[6] or "").strip()
            reports[eid] = {
                "product_code": row[0],
                "date_received": row[1],
                "event_type": (row[2] or "").capitalize() or None,
                "report_source": normalize_source(row[3]) or None,
                "brand": row[4],
                "excerpt": text[:400],
                "maude_url": MAUDE_DETAIL_URL.format(eid),
            }
            continue
        if eid.startswith("21 CFR"):
            other[eid] = {"kind": "regulation", "label": eid, "url": None}
            continue
        if eid.startswith("PMID"):
            kind, source_id = "pubmed", eid.removeprefix("PMID").strip()
        elif re.fullmatch(r"K\d+", eid):
            kind, source_id = "510k", eid
        elif eid.startswith("Z-"):
            kind, source_id = "recall", eid
        else:
            kind, source_id = "unknown", eid
        stype = {"pubmed": "pubmed", "510k": "fda_510k", "recall": "fda_recall"}.get(kind)
        row = None
        if stype:
            row = conn.execute(
                "select title, url from external_sources where source_type = ? and source_id = ?",
                (stype, source_id),
            ).fetchone()
        if row is None:
            other[eid] = {"kind": kind, "label": None, "url": None}
            notes.append(f"{eid} has no stored row; label and url are null")
        else:
            other[eid] = {"kind": kind, "label": row[0], "url": row[1]}
    return {"schema_version": SCHEMA_VERSION, "reports": reports, "other": other, "notes": notes}


def build_protocol(transcripts: list[dict[str, Any]]) -> dict[str, Any]:
    """``protocol.json``: the searches behind each answer, from stored tool calls only."""
    protocols: dict[str, Any] = {}
    for t in sorted(transcripts, key=lambda d: thread_sort_key(d["label"])):
        entries = []
        for call in t.get("tool_calls", []):
            name = tool_label(call["name"])
            args = dict(call.get("arguments", {}))
            preview = call.get("result_preview", "")
            date_from = args.pop("date_from", None) or string_in(preview, "date_from")
            date_to = args.pop("date_to", None) or string_in(preview, "date_to")
            entries.append(
                {
                    "tool": name,
                    "dataset": string_in(preview, "source") or TOOL_DATASETS.get(name),
                    "filters": args,
                    "date_from": date_from,
                    "date_to": date_to,
                    "count": tool_count(name, preview),
                    "run_at": t.get("recorded_at_utc"),
                }
            )
        protocols[t["label"]] = entries
    return {"schema_version": SCHEMA_VERSION, "protocols": protocols}


# ── briefs, audit, dossier, vision, sweep ────────────────────────────────────
def build_briefs(root: Path) -> dict[str, Any]:
    """``briefs.json``: one entry per digest, newest first."""
    briefs = []
    notes: list[str] = []
    for p in sorted((root / "digests").glob("*.json"), reverse=True):
        d = read_json(p)
        entry: dict[str, Any] = {"date": d.get("as_of") or p.stem}
        for key in (
            "headline",
            "counts",
            "window",
            "signals",
            "device_types",
            "ranking",
            "window_sources",
            "footer",
        ):
            if key not in d:
                notes.append(f"{p.name} has no '{key}'")
            entry[key] = d.get(key)
        briefs.append(entry)
    if not briefs:
        notes.append("no digests/*.json found")
    return {"schema_version": SCHEMA_VERSION, "briefs": briefs, "notes": notes}


def relabel_tools(value: Any) -> Any:
    """Show tool names by their display label inside an audit payload (display copy only)."""
    if isinstance(value, str):
        return TOOL_LABELS.get(value, value)
    if isinstance(value, list):
        return [relabel_tools(v) for v in value]
    if isinstance(value, dict):
        return {k: relabel_tools(v) for k, v in value.items()}
    return value


def build_audit(root: Path) -> dict[str, Any]:
    """``audit.json``: audit exports with the hash chain re-verified here."""
    runs = []
    notes: list[str] = []
    for p in sorted((root / "demo" / "transcripts").glob("audit-*.json")):
        d = read_json(p)
        ok, bad = verify_entries(d["entries"])
        if d["run_label"] in DISPLAY_EXCLUDED_LABELS:
            # Chain was verified above; the run itself is not exported (its question text uses
            # words the product does not show).
            notes.append(f"{d['run_label']}: not exported (display-excluded); chain re-verified")
            continue
        if ok != d.get("chain_ok_at_export"):
            notes.append(f"{d['run_label']}: re-verified chain_ok={ok} differs from the export")
        entries = [
            {
                "seq": e["seq"],
                "ts": e["ts"],
                "actor": e["actor"],
                "action": e["action"],
                "entity_id": e["entity_id"],
                "payload": relabel_tools(json.loads(e["payload_json"])),
                "prev_hash": e["prev_hash"],
                "entry_hash": e["entry_hash"],
            }
            for e in d["entries"]
        ]
        runs.append(
            {"run_label": d["run_label"], "chain_ok": ok, "first_bad_seq": bad, "entries": entries}
        )
    if not runs:
        notes.append("no demo/transcripts/audit-*.json found")
    return {"schema_version": SCHEMA_VERSION, "runs": runs, "notes": notes}


def build_dossier(root: Path, out: Path) -> tuple[dict[str, Any], list[str]]:
    """``dossier.json`` and the PDFs copied next to it."""
    src = root / "demo" / "dossier"
    narratives = sorted(src.glob("*-narrative.json"))
    notes: list[str] = []
    if not narratives:
        return (
            {
                "schema_version": SCHEMA_VERSION,
                "doc_id": None,
                "pdf": None,
                "narrative": None,
                "review": None,
                "notes": ["no demo/dossier/*-narrative.json found"],
            },
            [],
        )
    if len(narratives) > 1:
        notes.append(f"{len(narratives)} dossiers found; the newest by name is exported")
    narrative = read_json(narratives[-1])
    doc_id = narrative["doc_id"]
    assets: list[str] = []
    pdf: dict[str, str | None] = {}
    for kind in ("draft", "approved"):
        f = src / f"{doc_id}-{kind}.pdf"
        if f.exists():
            dest = out / "dossier" / f.name
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(f, dest)
            pdf[kind] = f"dossier/{f.name}"
            assets.append(f"dossier/{f.name}")
        else:
            pdf[kind] = None
            notes.append(f"{f.name} is missing")
    review_path = src / f"{doc_id}-review.json"
    review: dict[str, Any] | None = None
    if review_path.exists():
        r = read_json(review_path)
        review = {
            "model": r.get("model"),
            "findings": r.get("findings"),
            "parse_error": r.get("parse_error"),
        }
    else:
        notes.append(f"{review_path.name} is missing")
    doc = {
        "schema_version": SCHEMA_VERSION,
        "doc_id": doc_id,
        "pdf": pdf,
        "narrative": narrative,
        "review": review,
        "notes": notes,
    }
    return doc, assets


def build_vision(root: Path, out: Path) -> tuple[dict[str, Any], list[str]]:
    """``vision.json`` and the label images copied next to it."""
    vdir = root / "demo" / "vision"
    notes: list[str] = []
    assets: list[str] = []
    k510 = [read_json(p) for p in sorted(vdir.glob("510k-*.json"))]
    labels = []
    for p in sorted(vdir.glob("label-*.json")):
        if p.name.startswith("label-match-"):
            continue  # possible-match records are attached to their label below
        d = read_json(p)
        image = None
        img_name = d.get("image_file")
        src_img = vdir / "labels" / str(img_name) if img_name else None
        if src_img is not None and src_img.exists():
            dest = out / "vision" / src_img.name
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src_img, dest)
            image = f"vision/{src_img.name}"
            assets.append(image)
        else:
            notes.append(f"{p.name}: image {img_name} not found")
        mp = vdir / f"label-match-{p.stem.removeprefix('label-')}.json"
        matches: dict[str, Any] | None = None
        if mp.exists():
            matches = read_json(mp)
            if matches.get("confirmed") is not None:
                # A person confirms in the app, never in a stored file.
                notes.append(f"{mp.name}: stored 'confirmed' value dropped (always null here)")
                matches["confirmed"] = None
        else:
            notes.append(f"{mp.name} not found; {p.name} has no possible matches")
        labels.append({**d, "image": image, "matches": matches})
    if not k510:
        notes.append("no demo/vision/510k-*.json found")
    if not labels:
        notes.append("no demo/vision/label-*.json found")
    return {
        "schema_version": SCHEMA_VERSION,
        "k510": k510,
        "labels": labels,
        "notes": notes,
    }, assets


def build_sweep(root: Path) -> dict[str, Any]:
    """``sweep.json``: the AI-device sweep as stored."""
    p = root / "demo" / "sweep" / "ai-device-sweep.json"
    if not p.exists():
        return {
            "schema_version": SCHEMA_VERSION,
            "meta": None,
            "rows": None,
            "errors": None,
            "notes": [f"{p.relative_to(root)} not found"],
        }
    return {"schema_version": SCHEMA_VERSION, **read_json(p)}


def build_investigations(root: Path) -> dict[str, Any]:
    """``investigations.json``: recorded agentic runs; never synthesized here."""
    files = sorted((root / "demo" / "investigations").glob("*.json"))
    runs = [read_json(p) for p in files]
    notes = []
    if not runs:
        notes.append("No recorded runs yet.")
    return {"schema_version": SCHEMA_VERSION, "investigations": runs, "notes": notes}


# ── sources, schedules ───────────────────────────────────────────────────────
def build_sources(conn: sqlite3.Connection) -> dict[str, Any]:
    """``sources.json``: record counts straight from the demo database tables."""
    maude_n, maude_last = conn.execute(
        "select count(*), max(date_received) from raw_reports"
    ).fetchone()
    sources: list[dict[str, Any]] = [
        {
            "id": "maude",
            "label": "openFDA MAUDE",
            "records": maude_n,
            "last_refresh": maude_last,
            "last_refresh_basis": "newest date_received",
        }
    ]
    spec = [
        ("recalls", "openFDA recalls", "fda_recall"),
        ("510k", "FDA 510(k)", "fda_510k"),
        ("pubmed", "PubMed", "pubmed"),
        ("mhra", "MHRA (UK)", "mhra_alert"),
    ]
    for sid, label, stype in spec:
        n, fetched = conn.execute(
            "select count(*), max(fetched_at) from external_sources where source_type = ?",
            (stype,),
        ).fetchone()
        sources.append(
            {
                "id": sid,
                "label": label,
                "records": n,
                "last_refresh": fetched[:10] if fetched else None,
                "last_refresh_basis": "newest fetched_at",
            }
        )
    return {
        "schema_version": SCHEMA_VERSION,
        "sources": sources,
        "notes": ["MHRA (UK) is regulator context only; it is never counted in a MAUDE number."],
    }


def workflow_cron(root: Path, name: str) -> str | None:
    """First ``cron:`` expression in a workflow file."""
    p = root / ".github" / "workflows" / name
    if not p.exists():
        return None
    m = re.search(r'cron:\s*"([^"]+)"', p.read_text(encoding="utf-8"))
    return m.group(1) if m else None


def build_schedules(root: Path, briefs: dict[str, Any], sweep: dict[str, Any]) -> dict[str, Any]:
    """``schedules.json``: read from the workflow files and the newest outputs."""
    notes: list[str] = []
    newest = briefs["briefs"][0] if briefs["briefs"] else None
    monitor_last = {"date": newest["date"], "headline": newest["headline"]} if newest else None
    if monitor_last is None:
        notes.append("no digest yet; daily-monitor last_result is null")
    sweep_last = None
    if sweep.get("rows") is not None and sweep.get("meta"):
        sweep_last = {
            "date": sweep["meta"].get("generated_utc"),
            "flagged": sum(1 for r in sweep["rows"] if r.get("classification") != "stable"),
            "checked": sweep["meta"].get("codes_checked"),
        }
    else:
        notes.append("no sweep file; ai-sweep last_result is null")
    schedules = [
        {
            "id": "daily-monitor",
            "label": "Daily monitor",
            "cron": workflow_cron(root, "monitor.yml"),
            "workflow": ".github/workflows/monitor.yml",
            "last_result": monitor_last,
        },
        {
            "id": "ai-sweep",
            "label": "AI device sweep",
            "cron": workflow_cron(root, "ai-sweep.yml"),
            "workflow": ".github/workflows/ai-sweep.yml",
            "last_result": sweep_last,
        },
    ]
    return {"schema_version": SCHEMA_VERSION, "schedules": schedules, "notes": notes}


# ── company.json (simulated company, real FDA evidence) ──────────────────────
COMPANY_DIR = "demo/company"
COMPANY_BANNER = "Simulated company — sample data. Problem evidence is real FDA data."
NOT_FETCHED = "evidence not fetched yet"
STATUS_RANK = {
    "Needs review": 1,
    "Testing in progress": 2,
    "Already covered": 3,
    "Not applicable to our device": 3,
    "Monitoring — nothing open": 4,
}
# Words no company screen prints; a quote or text that holds one is dropped, never shown.
COMPANY_FORBIDDEN = re.compile(
    r"\b(safe|unsafe|compliant|validated|overnight)\b"
    r"|fda[- ]approved|part 11 compliant|worsening signals?|citation-checked|complaint data",
    re.I,
)
MIN_PATTERN_REPORTS = 2
MAX_QUOTES = 2
QUOTE_MIN_CHARS = 40
QUOTE_MAX_CHARS = 220
_FAIL = r"(?:unable to|not able to|fail\w* to|cannot|could not|can ?not|did not|does not|won't)"
# Keyword rules v2.0, the same rules as maudesignal.company.patterns.RULES (Track A). Used only
# when that module is not importable; a report joins on a MAUDE problem term or a strong phrase.
KEYWORD_RULES: tuple[tuple[str, str, tuple[str, ...], str, str], ...] = (
    (
        "load-transfer",
        "Images or data fail to load, transfer or send",
        ("failure to transmit record", "intermittent communication failure", "loss of data"),
        rf"\b{_FAIL} (?:\w+ ){{0,2}}(?:load|fetch|retrieve|transfer|transmit|send|import|"
        r"export|save)\b",
        r"\b(?:transmi\w*|transfer\w*|communicat\w*|data loss|lost data)\b",
    ),
    (
        "freeze-crash",
        "Software freezes, crashes or does not start",
        ("application program freezes or fails to launch",),
        r"\b(?:freez(?:es|ing)|froze|frozen|unresponsive|(?:system|software|application|"
        r"program|unit|console|workstation|computer|monitor|screen) (?:has |had )?"
        r"(?:crash(?:es|ed|ing)?|hung|hangs|hanging)|"
        r"(?:fail\w*|unable|not able) to (?:launch|start up|boot|start the (?:software|"
        r"application|system)))\b",
        r"\b(?:freez\w*|froze|frozen|crash\w*|launch\w*|unresponsive)\b",
    ),
    (
        "wrong-result",
        "Result or measurement is incorrect or imprecise",
        (
            "incorrect, inadequate or imprecise result or readings",
            "incorrect measurement",
            "application program problem: parameter calculation error",
        ),
        r"\b(?:(?:incorrect|inaccurate|erroneous|wrong)(?: [\w%]+){0,2} "
        r"(?:results?|readings?|measurements?|values?|calculations?|rhythms?|detections?|"
        r"diagnos[ie]s|output)|false (?:positive|negative)s?|miscalculat\w*|mismeasur\w*|"
        r"(?:over|under)-?estimat\w*)\b",
        r"\b(?:incorrect\w*|inaccura\w*|imprecis\w*|calculat\w*)\b",
    ),
    (
        "display-quality",
        "Display problem or image artifact",
        (
            "image display error/artifact",
            "poor quality image",
            "display or visual feedback problem",
            "no display/image",
        ),
        r"\b(?:image artifacts?|artifacts? (?:on|in|appear\w*|visible)|blurr(?:y|ed|ing)|"
        r"distorted (?:image|display|screen)|(?:not|no longer|failed to) display(?:ed|ing)?|"
        r"display error|missing image|blank (?:screen|image|display))\b",
        r"\b(?:artifacts?|display\w*|image quality|blurr\w*|distort\w*)\b",
    ),
    (
        "patient-data",
        "Patient data, record or label mix-up",
        ("patient data problem", "wrong label"),
        r"\b(?:wrong patient|incorrect patient|different patient|another patient|mislabel\w*|"
        r"patient (?:data|records?)\W+(?:\w+ ){0,2}(?:merged|mismatch\w*|mixed)|"
        r"mismatched patient|mixed[- ]up|wrong (?:label|study))\b",
        r"\b(?:patient (?:data|records?)|merge\w*|mismatch\w*|label\w*)\b",
    ),
    (
        "install-update",
        "Installation, update or compatibility problem",
        (
            "problem with software installation",
            "installation-related problem",
            "computer operating system problem",
        ),
        r"\b(?:(?:fail\w*|unable|unsuccessful\w*|errors?|problems?|issues?)"
        r"(?: (?:to|with|during|while|in|on))? (?:the )?(?:software |firmware )?"
        r"(?:install\w*|updat\w*|upgrad\w*)|"
        r"(?:after|following|during) (?:the |a |an )?(?:recent )?(?:software |firmware |"
        r"system )?(?:install(?:ation)?|update|upgrade)\b(?! of)|"
        r"incompatib\w*|compatibility (?:issue|problem|error)s?)\b",
        r"\b(?:install\w*|updat\w*|upgrad\w*|operating system|compatib\w*)\b",
    ),
    (
        "access-security",
        "Log-in, access or security problem",
        ("computer system security problem",),
        r"\b(?:(?:unable|not able|fail\w*|cannot|could not|can ?not|unsuccessful\w*) "
        r"(?:to )?log ?(?:in|on)|log ?(?:in|on) (?:failure|problem|issue|error)s?|"
        r"unauthori[sz]ed (?:access|user)|cyber\w*|access denied|locked out|"
        r"security (?:breach|vulnerabilit\w*|incident))\b",
        r"\b(?:security|cyber\w*|log ?in|access)\b",
    ),
)
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")
_WS = re.compile(r"\s+")


def _squash(text: str) -> str:
    return _WS.sub(" ", text).strip()


def _sentences(text: str) -> list[str]:
    return [_squash(s) for s in _SENTENCE_SPLIT.split(text) if s.strip()]


def _company_history(entries: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """Per-device history from the audit entries; raises when a status rule is broken."""
    out: dict[str, list[dict[str, Any]]] = {}
    for e in entries:
        p = json.loads(e["payload_json"])
        actor = str(e["actor"])
        if not actor.endswith("(simulated)"):
            raise ValueError(f"audit seq {e['seq']}: a status is set by a named simulated person")
        dev, to = str(p["device_id"]), str(p["to_status"])
        prev = out.get(dev, [])
        if to not in STATUS_RANK:
            raise ValueError(f"audit seq {e['seq']}: unknown status {to!r}")
        if prev and STATUS_RANK[to] <= STATUS_RANK[prev[-1]["to_status"]]:
            raise ValueError(f"audit seq {e['seq']}: a status only moves forward")
        if not prev and e["action"] != "company.status.register":
            raise ValueError(f"audit seq {e['seq']}: first entry of a device is a register entry")
        ts = datetime.fromisoformat(e["ts"])
        out.setdefault(dev, []).append(
            {
                "seq": int(e["seq"]),
                "date": ts.date().isoformat(),
                "ts": ts.isoformat(),
                "actor": actor,
                "action": "register" if e["action"] == "company.status.register" else "change",
                "from_status": p.get("from_status"),
                "to_status": to,
                "details": dict(p.get("details") or {}),
                "note": str(p.get("note") or ""),
                "entry_hash": e["entry_hash"],
            }
        )
    return out


def _status_detail(details: dict[str, Any]) -> str:
    parts: list[str] = []
    if details.get("owner"):
        parts.append(f"owner {details['owner']}")
    if details.get("due_date"):
        parts.append(f"due {details['due_date']}")
    for key in ("reference", "reason"):
        if details.get(key):
            parts.append(str(details[key]))
    return "; ".join(parts)


def _pick_quote(text: str, rx: re.Pattern[str]) -> str | None:
    """First short sentence that matches ``rx`` and holds none of the withheld words."""
    return next(
        (
            s
            for s in _sentences(text)
            if QUOTE_MIN_CHARS <= len(s) <= QUOTE_MAX_CHARS
            and not COMPANY_FORBIDDEN.search(s)
            and rx.search(s)
        ),
        None,
    )


_STOP_WORDS = frozenset({"describe", "reports", "including", "report", "errors", "error", "unable"})


def _label_regex(label: str) -> re.Pattern[str] | None:
    words = [w for w in re.findall(r"[a-z]{5,}", label.lower()) if w not in _STOP_WORDS]
    return re.compile("|".join(re.escape(w) for w in words), re.I) if words else None


def _gated_quotes(
    members: list[dict[str, Any]],
    pick: Callable[[dict[str, Any]], str | None],
    store: EvidenceStore,
) -> tuple[list[dict[str, str]], int]:
    """Up to ``MAX_QUOTES`` quotes the claim gate passes; the second value counts withheld ones."""
    quotes: list[dict[str, str]] = []
    withheld = 0
    for r in members:
        if len(quotes) >= MAX_QUOTES:
            break
        text = pick(r)
        if text is None:
            continue
        rid = str(r["report_id"])
        if verify_claim(QuoteClaim(quote=text, report_id=rid), store).status == "pass":
            quotes.append({"report_id": rid, "text": text, "url": MAUDE_DETAIL_URL.format(rid)})
        else:
            withheld += 1
    return quotes, withheld


def _company_pattern(
    code: str,
    pattern_id: str,
    label: str,
    basis: str,
    kind: str,
    members: list[dict[str, Any]],
    pick: Callable[[dict[str, Any]], str | None],
    by_id: dict[str, dict[str, Any]],
    store: EvidenceStore,
) -> dict[str, Any]:
    ids = list(dict.fromkeys(str(r["report_id"]) for r in members))
    # the group count is recomputed here: the listed ids must be distinct stored reports
    count_ok = bool(ids) and all(i in by_id for i in ids)
    quotes, withheld = _gated_quotes(members, pick, store)
    dates = sorted(str(r["date_received"]) for r in members if r.get("date_received"))
    return {
        "id": pattern_id,
        "label": label,
        "kind": kind,
        "display_label": f"Keyword match (unreviewed): {label}" if kind == "keyword" else label,
        "basis": basis,
        "count": len(ids),
        "report_ids": ids,
        "first_received": dates[0] if dates else None,
        "last_received": dates[-1] if dates else None,
        "quotes": quotes,
        "links": [{"label": f"MAUDE report {i}", "url": MAUDE_DETAIL_URL.format(i)} for i in ids],
        "gate": {
            "count": "pass" if count_ok else "block",
            "reason": f"recomputed {len(ids)} from {len(ids)} listed report ids",
            "quotes_passed": len(quotes),
            "quotes_withheld": withheld,
        },
    }


def _latest_investigation(root: Path, code: str) -> tuple[str, list[tuple[str, list[str]]]] | None:
    """Newest recorded weekly-investigator run for a code: ``(run id, [(label, ids)])``."""
    best: tuple[str, list[tuple[str, list[str]]]] | None = None
    for path in sorted((root / "demo" / "investigations").glob(f"*weekly-{code.lower()}.json")):
        doc = read_json(path)
        if doc.get("kind") != "weekly-investigator" or doc.get("product_code") != code:
            continue
        groups = [
            (str(g["label"]), [str(i) for i in g["report_ids"]])
            for g in doc.get("groups", [])
            if g.get("label") and g.get("report_ids")
        ]
        if groups:
            best = (str(doc.get("id") or path.stem), groups)
    return best


def _company_patterns(
    root: Path, code: str, records: list[dict[str, Any]], store: EvidenceStore
) -> list[dict[str, Any]]:
    """Recorded investigator groups when a run exists, else keyword groups; counts recomputed."""
    by_id = {str(r["report_id"]): r for r in records}
    ordered = sorted(records, key=lambda r: str(r["report_id"]))
    patterns: list[dict[str, Any]] = []
    inv = _latest_investigation(root, code)
    if inv is not None:
        run_id, groups = inv
        usable = [(lab, ids) for lab, ids in groups if all(i in by_id for i in ids)]
        for n, (label, ids) in enumerate(usable, start=1):
            lrx = _label_regex(label)

            def pick_inv(r: dict[str, Any], lrx: re.Pattern[str] | None = lrx) -> str | None:
                return _pick_quote(str(r.get("text") or ""), lrx) if lrx else None

            patterns.append(
                _company_pattern(
                    code,
                    f"{code}-inv-{n}",
                    label[:1].upper() + label[1:],
                    f"weekly investigator group, recorded run {run_id}; count recomputed",
                    "investigator",
                    [by_id[i] for i in ids],
                    pick_inv,
                    by_id,
                    store,
                )
            )
    if not patterns:
        for rule_id, label, problems, phrase_re, hint_re in KEYWORD_RULES:
            phrase = re.compile(phrase_re, re.I)
            both = re.compile(f"(?:{phrase_re})|(?:{hint_re})", re.I) if hint_re else None
            members = [
                r
                for r in ordered
                if {str(p).strip().lower() for p in r.get("product_problems") or []} & set(problems)
                or (r.get("text") and phrase.search(str(r["text"])))
            ]
            if len(members) < MIN_PATTERN_REPORTS:
                continue

            def pick_kw(
                r: dict[str, Any],
                phrase: re.Pattern[str] = phrase,
                both: re.Pattern[str] | None = both,
            ) -> str | None:
                text = str(r.get("text") or "")
                rx = phrase if phrase.search(text) else both
                return _pick_quote(text, rx) if rx else None

            patterns.append(
                _company_pattern(
                    code,
                    f"{code}-{rule_id}",
                    label,
                    f"keyword rules v2.0 ({rule_id})",
                    "keyword",
                    members,
                    pick_kw,
                    by_id,
                    store,
                )
            )
    patterns.sort(key=lambda p: (-p["count"], p["label"]))
    return [p for p in patterns if p["gate"]["count"] == "pass"]


def _recall_item(rc: dict[str, Any], store: EvidenceStore) -> dict[str, Any]:
    first = _sentences(str(rc.get("reason_for_recall") or ""))[:1]
    excerpt: str | None = None
    truncated = False
    if first:
        cand = first[0]
        if len(cand) > QUOTE_MAX_CHARS:
            cand = cand[:QUOTE_MAX_CHARS].rsplit(" ", 1)[0].rstrip()
            truncated = True
        passed = (
            verify_claim(QuoteClaim(quote=cand, source_id=str(rc["recall_number"])), store).status
            == "pass"
        )
        if passed and len(cand) >= QUOTE_MIN_CHARS and not COMPANY_FORBIDDEN.search(cand):
            excerpt = cand
    cfres = rc.get("cfres_id")
    return {
        "recall_number": rc["recall_number"],
        "recalling_firm": rc.get("recalling_firm"),
        "status": rc.get("recall_status"),
        "date_initiated": rc.get("date_initiated"),
        "excerpt": excerpt,
        # true when the excerpt is only the start of a longer sentence (shown with an ellipsis)
        "excerpt_truncated": bool(excerpt) and truncated,
        "url": (
            f"https://www.accessdata.fda.gov/scripts/cdrh/cfdocs/cfRES/res.cfm?id={cfres}"
            if cfres
            else None
        ),
    }


def _missing_evidence() -> dict[str, Any]:
    return {
        "origin": "missing",
        "available": False,
        "note": NOT_FETCHED,
        "report_count": None,
        "window": None,
        "queries": [],
        "recalls": None,
    }


def _load_fetched(folder: Path, code: str) -> dict[str, Any] | None:
    """Neutral evidence dict from ``demo/company/evidence/<code>.json`` (None when absent)."""
    path = folder / "evidence" / f"{code}.json"
    if not path.is_file():
        return None
    doc = read_json(path)
    win = doc.get("window") or {}
    cls = doc.get("classification") or {}
    return {
        "origin": "fetched",
        "reports": list(doc["reports"]["records"]),
        "recalls": list(doc["recalls"]["records"]),
        "matched_total": doc["recalls"].get("matched_total"),
        "window": (win.get("date_from"), win.get("date_to")),
        "queries": [
            ("openFDA MAUDE query (last 8 weeks, limit 100)", doc["reports"]["query_url"]),
            ("openFDA recall query (latest 100)", doc["recalls"]["query_url"]),
        ],
        "classification": (
            {
                "device_name": cls["device_name"],
                "query_url": cls.get("query_url"),
                "source": "openFDA device classification (fetched)",
            }
            if cls.get("device_name")
            else None
        ),
        "fetched_utc": doc.get("fetched_utc"),
        "note": "; ".join(doc.get("notes") or []) or None,
    }


def _ymd(iso: str | None) -> str | None:
    return iso.replace("-", "") if iso else None


def _load_demo_db(root: Path, code: str) -> dict[str, Any] | None:
    """Neutral evidence dict from the demo database, opened read-only (None: no stored rows)."""
    path = root / DEMO_DB
    if not path.is_file():
        return None
    con = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)
    try:
        rows = con.execute(
            "SELECT e.maude_report_id, e.event_type, r.date_received, e.report_source, "
            "e.brand_name, e.manufacturer, e.narrative, e.mfr_narrative, r.raw_json "
            "FROM normalized_events e JOIN raw_reports r "
            "ON r.maude_report_id = e.maude_report_id "
            "WHERE e.product_code = ? ORDER BY e.maude_report_id",
            (code,),
        ).fetchall()
        if not rows:
            return None
        reports: list[dict[str, Any]] = []
        for rid, etype, drec, src, brand, mfr, narr, mnarr, raw in rows:
            doc = json.loads(raw)
            reports.append(
                {
                    "report_id": str(rid),
                    "event_type": etype,
                    "date_received": drec,
                    "report_source": src,
                    "brand_name": brand,
                    "manufacturer": mfr,
                    "product_problems": [str(p) for p in doc.get("product_problems") or []],
                    "text": " ".join(t for t in (narr, mnarr) if t),
                }
            )
        recalls: list[dict[str, Any]] = []
        for sid, raw in con.execute(
            "SELECT source_id, raw_json FROM external_sources "
            "WHERE source_type = 'fda_recall' AND product_code = ? ORDER BY source_id",
            (code,),
        ):
            d = json.loads(raw)
            recalls.append(
                {
                    "recall_number": str(d.get("product_res_number") or sid),
                    "event_number": d.get("res_event_number"),
                    "recalling_firm": d.get("recalling_firm"),
                    "product_description": str(d.get("product_description") or ""),
                    "reason_for_recall": str(d.get("reason_for_recall") or ""),
                    "recall_status": d.get("recall_status"),
                    "date_initiated": _ymd(d.get("event_date_initiated")),
                    "cfres_id": d.get("cfres_id"),
                }
            )
        recalls.sort(key=lambda c: c["date_initiated"] or "", reverse=True)
        cat = con.execute(
            "SELECT device_name FROM device_catalog "
            "WHERE product_code = ? AND source_keyword = 'openfda_classification'",
            (code,),
        ).fetchone()
    finally:
        con.close()
    dates = sorted(r["date_received"] for r in reports if r["date_received"])
    queries: list[tuple[str, str]] = []
    manifest = root / "data" / "demo" / "SEED_MANIFEST.json"
    if manifest.is_file():
        for q in read_json(manifest).get("queries", []):
            if q.get("product_code") == code and q.get("example_url"):
                queries.append(
                    ("openFDA MAUDE query that filled the demo database", str(q["example_url"]))
                )
                break
    if recalls:
        recall_url = f"https://api.fda.gov/device/recall.json?search=product_code:{code}"
        queries.append(("openFDA recall query", recall_url))
    cls_url = f"https://api.fda.gov/device/classification.json?search=product_code:{code}"
    return {
        "origin": "demo_db",
        "reports": reports,
        "recalls": recalls,
        "matched_total": None,  # the demo database holds a stored subset; no openFDA match total
        "window": (dates[0] if dates else None, dates[-1] if dates else None),
        "queries": queries,
        "classification": (
            {
                "device_name": str(cat[0]),
                "query_url": cls_url,
                "source": "openFDA device classification (stored in the demo database)",
            }
            if cat and cat[0]
            else None
        ),
        "fetched_utc": None,
        "note": None,
    }


def _company_evidence(
    root: Path, code: str
) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any] | None]:
    """``(evidence, patterns, classification)`` for one code.

    The demo database is read first for the codes it holds (origin ``demo_db``), then the
    fetched evidence file (origin ``fetched``); a code with neither is ``missing``.
    """
    ev = _load_demo_db(root, code) or _load_fetched(root / COMPANY_DIR, code)
    if ev is None:
        return _missing_evidence(), [], None
    records: list[dict[str, Any]] = ev["reports"]
    recalls: list[dict[str, Any]] = ev["recalls"]
    store = EvidenceStore.from_iterables(
        [
            EvidenceRecord(
                report_id=str(r["report_id"]),
                product_code=code,
                event_type=r.get("event_type"),
                date_received=r.get("date_received"),
                text=str(r.get("text") or ""),
                manufacturer=r.get("manufacturer"),
                brand_name=r.get("brand_name"),
                report_source=r.get("report_source"),
            )
            for r in records
        ],
        recalls=[
            RecallRef(
                recall_number=str(c["recall_number"]),
                product_code=code,
                event_number=c.get("event_number"),
                recalling_firm=c.get("recalling_firm"),
                product_description=str(c.get("product_description") or ""),
                reason_for_recall=str(c.get("reason_for_recall") or ""),
                recall_status=c.get("recall_status"),
                date_initiated=c.get("date_initiated"),
            )
            for c in recalls
        ],
    )
    patterns = _company_patterns(root, code, records, store)
    # real claim-gate verdicts: the report count, the recall count, every quote and excerpt shown
    count_v = verify_claim(CountClaim(product_code=code, value=len(records)), store)
    recall_v = verify_claim(RecallCountClaim(product_code=code, value=len(recalls)), store)
    items = [_recall_item(rc, store) for rc in recalls[:3]]
    gate_pass = (
        sum(p["gate"]["quotes_passed"] for p in patterns)
        + sum(1 for it in items if it["excerpt"])
        + int(count_v.status == "pass")
        + int(recall_v.status == "pass")
    )
    gate_block = (
        sum(p["gate"]["quotes_withheld"] for p in patterns)
        + int(count_v.status != "pass")
        + int(recall_v.status != "pass")
    )
    evidence = {
        "origin": ev["origin"],
        "available": True,
        "note": ev["note"],
        "fetched_utc": ev["fetched_utc"],
        "report_count": {"value": len(records), "gate": count_v.status, "reason": count_v.reason},
        "window": {"date_from": ev["window"][0], "date_to": ev["window"][1]},
        "queries": [{"label": a, "url": b} for a, b in ev["queries"]],
        "recalls": {
            "stored": len(recalls),
            "matched_total": ev["matched_total"],
            "gate": recall_v.status,
            "reason": recall_v.reason,
            "latest": items,
        },
        # verdicts of src/maudesignal/gate: report count, recall count, quotes, recall excerpts
        "gate_totals": {"pass": gate_pass, "block": gate_block},
        # group counts are recomputed here from the listed report ids; they are not gate claims
        "recomputed": {"pass": len(patterns), "block": 0},
    }
    return evidence, patterns, ev["classification"]


def _company_from_files(root: Path) -> dict[str, Any]:
    """The company document built from ``demo/company`` alone (when Track A's module is absent)."""
    folder = root / COMPANY_DIR
    doc = read_json(folder / "company.json")
    entries = read_json(folder / "audit.json")["entries"]
    history = _company_history(entries)
    chain_ok, bad = verify_entries(entries)
    devices: list[dict[str, Any]] = []
    notes = list(doc.get("notes", []))
    cache: dict[str, tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any] | None]] = {}
    for d in doc["devices"]:
        code = d["product_code"]
        if code not in cache:
            cache[code] = _company_evidence(root, code)
        evidence, patterns, cls = cache[code]
        hist = history.get(d["device_id"], [])
        last = hist[-1] if hist else None
        dt = dict(d.get("device_type") or {})
        if cls and cls.get("device_name"):
            dt = {
                "name": cls["device_name"],
                "source": cls["source"],
                "query_url": cls.get("query_url"),
            }
        if not evidence["available"]:
            note = f"{code}: {NOT_FETCHED}; no count, pattern or quote is shown for it."
            if note not in notes:
                notes.append(note)
        devices.append(
            {
                "id": d["device_id"],
                "name": d["name"],
                "model": d["model"],
                "product_code": code,
                "owner": d["owner"],
                "device_type": {
                    "name": dt.get("name"),
                    "source": dt.get("source"),
                    "query_url": dt.get("query_url"),
                },
                "sweep": d.get("sweep"),
                "status": (
                    None
                    if last is None
                    else {
                        "label": last["to_status"],
                        "set_by": last["actor"],
                        "date": last["date"],
                        "detail": _status_detail(last["details"]),
                        "details": last["details"],
                    }
                ),
                "history": hist,
                "evidence": evidence,
                "patterns": patterns,
            }
        )
    return {
        "company": doc.get("company"),
        "statuses": [{"label": s, "rank": r} for s, r in STATUS_RANK.items()],
        "devices": devices,
        "audit": {
            "file": f"{COMPANY_DIR}/audit.json",
            "chain_ok": chain_ok,
            "first_bad_seq": bad,
            "entries": entries,
        },
        "notes": notes,
    }


def build_company(root: Path, generated_utc: str | None = None) -> dict[str, Any]:
    """``company.json``: the simulated company with real FDA evidence (see DATA_CONTRACT.md).

    Uses ``maudesignal.company`` (Track A) when it is importable; otherwise builds the same
    shape from ``demo/company`` with the same keyword rules. The audit chain is re-verified here.
    """
    stamp = generated_utc or datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    folder = root / COMPANY_DIR
    head: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "generated_utc": stamp,
        "banner": COMPANY_BANNER,
    }
    if not (folder / "company.json").is_file() or not (folder / "audit.json").is_file():
        return {
            **head,
            "company": None,
            "statuses": [{"label": s, "rank": r} for s, r in STATUS_RANK.items()],
            "devices": [],
            "audit": {
                "file": f"{COMPANY_DIR}/audit.json",
                "chain_ok": None,
                "first_bad_seq": None,
                "entries": [],
            },
            "notes": ["demo/company was not found; no simulated company is shown."],
        }
    try:
        from maudesignal.company.build import (  # type: ignore[import-not-found]  # noqa: PLC0415
            export_company,
            load_company,
        )
    except ImportError:
        return {**head, **_company_from_files(root)}
    body: dict[str, Any] = export_company(
        load_company(
            folder, db_path=root / DEMO_DB, investigations=root / "demo" / "investigations"
        )
    )
    # the audit chain is recomputed here whichever module built the document
    ok, bad = verify_entries(body["audit"]["entries"])
    body["audit"]["chain_ok"], body["audit"]["first_bad_seq"] = ok, bad
    return {**body, **head}


# ── main ─────────────────────────────────────────────────────────────────────
def export(root: Path, out: Path, *, generated_utc: str | None = None) -> dict[str, Any]:
    """Write every output file under ``out`` and return the manifest.

    Args:
        root: Repository root holding the inputs.
        out: Output directory (``web/public/data``).
        generated_utc: Timestamp to record; now when omitted.

    Returns:
        The manifest document.
    """
    out.mkdir(parents=True, exist_ok=True)
    transcripts = load_transcripts(root)
    notes: list[str] = []
    db_path = root / DEMO_DB
    if not db_path.exists():
        raise SystemExit(f"demo database not found: {db_path}")
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        threads = build_threads(transcripts)
        evidence = build_evidence(conn, threads)
        sources = build_sources(conn)
    finally:
        conn.close()
    audit = build_audit(root)
    briefs = build_briefs(root)
    sweep = build_sweep(root)
    dossier, dossier_assets = build_dossier(root, out)
    vision, vision_assets = build_vision(root, out)
    sys.path.insert(0, str(ROOT / "scripts"))
    import export_alerts  # noqa: PLC0415  (imports this module; loaded late to avoid a cycle)

    company = build_company(root, generated_utc)
    files: dict[str, Any] = {
        "threads.json": threads,
        "evidence.json": evidence,
        "briefs.json": briefs,
        "audit.json": audit,
        "dossier.json": dossier,
        "vision.json": vision,
        "company.json": company,
        "sweep.json": sweep,
        "investigations.json": build_investigations(root),
        "protocol.json": build_protocol(transcripts),
        "sources.json": sources,
        "schedules.json": build_schedules(root, briefs, sweep),
        "alerts.json": export_alerts.build_alerts(root, generated_utc, company),
        "mentions.json": export_alerts.build_mentions(root),
    }
    for name, doc in files.items():
        write_json(out / name, doc)
    if not transcripts:
        notes.append("no copilot transcripts found")
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "generated_utc": generated_utc or datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source_commit": git_sha(root),
        "files": list(files),
        "assets": dossier_assets + vision_assets,
        "header": header_counts(threads, audit),
        "notes": notes,
    }
    write_json(out / "manifest.json", manifest)
    return manifest


# ── TypeScript parity fixtures ───────────────────────────────────────────────
PARITY_FILE = ROOT / "web" / "src" / "fixtures" / "liveCheckParity.json"
_KINDS = ("injury", "malfunction", "death", "other", "unknown", "no answer provided")


def _split(
    rng: random.Random, total: int, kinds: tuple[str, ...], must: tuple[str, ...] = ()
) -> list[list[Any]]:
    """Spread ``total`` reports over some of ``kinds`` (sorted, zero buckets dropped).

    ``must`` kinds are always among those chosen (when ``total`` allows one report each).
    """
    chosen = rng.sample(kinds, rng.randint(1, len(kinds))) if total else []
    chosen = list(dict.fromkeys([*must[:total], *chosen]))
    counts = dict.fromkeys(chosen, 0)
    for k in must[:total]:
        counts[k] += 1
    for _ in range(total - sum(counts.values())):
        counts[rng.choice(chosen)] += 1
    return [[k, v] for k, v in sorted(counts.items()) if v > 0]


def _parity_counts(rng: random.Random, edge: dict[str, Any] | None) -> dict[str, Any]:
    if edge is not None:
        return edge
    scale = rng.choice((3, 8, 30, 200))
    cur = rng.randint(0, scale)
    base = rng.choice((0, rng.randint(0, scale * 4), rng.randint(0, 8)))
    prior = rng.choice((0, rng.randint(0, 5), rng.randint(0, scale * 20)))
    current_types = _split(rng, cur, _KINDS)
    # Most of the time the history already holds every kind seen this week (so "new kind of
    # problem" fires in a minority of cases, as it does on real data).
    seen = tuple(k for k, _ in current_types) if rng.random() < 0.75 else ()
    return {
        "current_total": cur,
        "baseline_total": base,
        "prior_total": prior,
        "current_types": current_types,
        "baseline_types": _split(rng, base, _KINDS[:5]),
        "prior_types": _split(rng, prior, _KINDS, seen) if cur else [],
    }


def _edge_cases() -> list[dict[str, Any]]:
    """Boundaries of every rule: 3 reports, exactly 2x the weekly mean, exactly +15 points."""

    def c(
        cur: int, base: int, prior: int, ct: list[Any], bt: list[Any], pt: list[Any]
    ) -> dict[str, Any]:
        return {
            "current_total": cur,
            "baseline_total": base,
            "prior_total": prior,
            "current_types": ct,
            "baseline_types": bt,
            "prior_types": pt if cur else [],
        }

    m = [["malfunction", 1]]
    return [
        c(0, 0, 0, [], [], []),
        c(0, 12, 400, [], [["malfunction", 12]], []),
        c(3, 0, 10, [["malfunction", 3]], [], [["malfunction", 10]]),
        c(3, 6, 50, [["malfunction", 3]], [["malfunction", 6]], [["malfunction", 50]]),
        c(3, 7, 50, [["malfunction", 3]], [["malfunction", 7]], [["malfunction", 50]]),
        c(2, 0, 50, [["malfunction", 2]], [], [["malfunction", 50]]),
        c(
            20,
            40,
            90,
            [["injury", 3], ["malfunction", 17]],
            [["malfunction", 40]],
            [["injury", 5], ["malfunction", 85]],
        ),
        c(
            20,
            20,
            90,
            [["injury", 3], ["malfunction", 17]],
            [["malfunction", 20]],
            [["injury", 5], ["malfunction", 85]],
        ),
        c(
            20,
            20,
            90,
            [["injury", 2], ["malfunction", 18]],
            [["malfunction", 20]],
            [["injury", 5], ["malfunction", 85]],
        ),
        c(1, 8, 9, [["death", 1]], [["malfunction", 8]], [["malfunction", 9]]),
        c(5, 5, 0, [["malfunction", 5]], [["malfunction", 5]], []),
        c(
            4,
            1,
            1278,
            [["injury", 4]],
            [["malfunction", 1]],
            [["injury", 100], ["malfunction", 1178]],
        ),
        c(1, 0, 3, m, [], [["injury", 3]]),
        c(8, 16, 3, [["malfunction", 8]], [["malfunction", 16]], [["malfunction", 3]]),
        c(
            7,
            16,
            700,
            [["death", 1], ["injury", 1], ["malfunction", 5]],
            [["malfunction", 16]],
            [["malfunction", 700]],
        ),
        c(1000, 4, 1, [["malfunction", 1000]], [["malfunction", 4]], [["malfunction", 1]]),
        c(3, 1, 8, [["unknown", 3]], [["malfunction", 1]], [["malfunction", 8]]),
        c(
            3,
            3,
            3,
            [["injury", 1], ["malfunction", 2]],
            [["injury", 1], ["malfunction", 2]],
            [["injury", 1], ["malfunction", 2]],
        ),
        c(7, 7, 7, [["injury", 7]], [["injury", 7]], [["injury", 7]]),
        c(
            6,
            3,
            12,
            [["injury", 1], ["malfunction", 5]],
            [["malfunction", 3]],
            [["malfunction", 12]],
        ),
    ]


def parity_fixtures() -> dict[str, Any]:
    """Cases for the TypeScript port of ``monitor.live_check``, computed by the Python code.

    Each case is inputs plus the answer ``classify_counts`` / ``_norm`` / ``build_window`` /
    ``verify_url`` give; ``web/src/liveCheck.test.ts`` requires the same from the TypeScript.
    Deterministic (seeded), so a unit test can check the committed file is current.
    """
    from maudesignal.monitor.deterioration import build_window
    from maudesignal.monitor.live_check import (
        WindowCounts,
        _norm,
        classify_counts,
        verify_url,
    )

    rng = random.Random(20261029)
    edges = _edge_cases()
    classify: list[dict[str, Any]] = []
    for i in range(320):
        counts = _parity_counts(rng, edges[i] if i < len(edges) else None)
        as_of = date(2026, 9, 30) - timedelta(days=rng.randint(0, 400))
        window = build_window(as_of)
        wc = WindowCounts(
            current_total=counts["current_total"],
            baseline_total=counts["baseline_total"],
            prior_total=counts["prior_total"],
            current_types=tuple((k, n) for k, n in counts["current_types"]),
            baseline_types=tuple((k, n) for k, n in counts["baseline_types"]),
            prior_types=tuple((k, n) for k, n in counts["prior_types"]),
        )
        code = "".join(rng.choice("ABCDEFGHIJKLMNOPQRSTUVWXYZ") for _ in range(3))
        want = classify_counts(code, wc, window).to_dict()
        want.pop("queries")
        want.pop("change")
        classify.append(
            {"code": code, "counts": counts, "as_of": as_of.strftime("%Y%m%d"), "expected": want}
        )

    norm: list[dict[str, Any]] = []
    terms = ("Injury", "injury ", " MALFUNCTION", "Death", "", "Other", "No answer provided", "  ")
    for _ in range(60):
        rows = [[rng.choice(terms), rng.randint(0, 40)] for _ in range(rng.randint(0, 6))]
        total = sum(n for _, n in rows) + rng.choice((0, 0, 1, 7))
        norm.append(
            {
                "rows": rows,
                "total": total,
                "expected": [list(x) for x in _norm([(t, n) for t, n in rows], total)],
            }
        )

    windows: list[dict[str, Any]] = []
    for _ in range(40):
        d = date(2024, 1, 1) + timedelta(days=rng.randint(0, 1100))
        w = build_window(d)
        windows.append(
            {
                "as_of": d.strftime("%Y%m%d"),
                "expected": {k: v.strftime("%Y%m%d") for k, v in vars(w).items()},
            }
        )
    windows.append(
        {
            "as_of": "20240229",
            "expected": {
                k: v.strftime("%Y%m%d") for k, v in vars(build_window(date(2024, 2, 29))).items()
            },
        }
    )

    urls: list[dict[str, Any]] = []
    for _ in range(30):
        code = "".join(rng.choice("ABCDEFGHIJKLMNOPQRSTUVWXYZ") for _ in range(3))
        start = rng.choice((None, "19900101", "20241029", "20260827"))
        end = rng.choice((None, "20260923", "20261029"))
        count = rng.choice((None, "event_type.exact", "date_received"))
        urls.append(
            {"args": [code, start, end, count], "expected": verify_url(code, start, end, count)}
        )
    return {"classify": classify, "norm": norm, "windows": windows, "urls": urls}


def main() -> int:
    """CLI entry point."""
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--root", type=Path, default=ROOT, help="repository root (inputs)")
    ap.add_argument(
        "--out", type=Path, default=ROOT / "web" / "public" / "data", help="output directory"
    )
    ap.add_argument(
        "--parity-fixtures",
        action="store_true",
        help="write web/src/fixtures/liveCheckParity.json (cases for the TypeScript detector)",
    )
    args = ap.parse_args()
    if args.parity_fixtures:
        PARITY_FILE.parent.mkdir(parents=True, exist_ok=True)
        PARITY_FILE.write_text(
            json.dumps(parity_fixtures(), separators=(",", ":")) + "\n", encoding="utf-8"
        )
        print(f"wrote {PARITY_FILE.relative_to(ROOT)}")
        return 0
    manifest = export(args.root, args.out)
    h = manifest["header"]
    print(
        f"wrote {len(manifest['files']) + 1} files to {args.out}: "
        f"{h['claims_verified']} claims verified, {h['sentences_withheld']} sentences withheld, "
        f"audit_chain_ok={h['audit_chain_ok']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
