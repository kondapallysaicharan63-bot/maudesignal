"""The web-data exporter writes every contract file and its header counts are honest."""

from __future__ import annotations

import importlib.util
import json
import re
import shutil
import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "export_web_data", ROOT / "scripts/export_web_data.py"
)
assert SPEC and SPEC.loader
exporter = importlib.util.module_from_spec(SPEC)
sys.modules["export_web_data"] = exporter
SPEC.loader.exec_module(exporter)

JSON_FILES = [
    "manifest.json",
    "threads.json",
    "evidence.json",
    "briefs.json",
    "audit.json",
    "dossier.json",
    "vision.json",
    "company.json",
    "sweep.json",
    "investigations.json",
    "protocol.json",
    "sources.json",
    "schedules.json",
]


@pytest.fixture(scope="module")
def out(tmp_path_factory: pytest.TempPathFactory) -> Path:
    path = tmp_path_factory.mktemp("web-data")
    exporter.export(ROOT, path, generated_utc="2026-10-29T00:00:00Z")
    return path


def load(out: Path, name: str) -> Any:
    return json.loads((out / name).read_text(encoding="utf-8"))


def test_every_file_exists_with_schema_version(out: Path) -> None:
    for name in JSON_FILES:
        assert (out / name).is_file(), name
        assert load(out, name)["schema_version"] == "1.0", name


def test_header_counts_equal_direct_count_over_transcripts(out: Path) -> None:
    claims = verified = withheld = answers = 0
    for p in sorted((ROOT / "demo" / "transcripts").glob("2*.json")):
        doc = json.loads(p.read_text(encoding="utf-8"))
        if doc["label"] in exporter.DISPLAY_EXCLUDED_LABELS:
            continue
        answers += 1
        for s in doc["final"]["sentences"]:
            verified += s["status"] == "pass"
            withheld += s["status"] == "block"
            claims += sum(c["status"] == "pass" for c in s["claims"])
    header = load(out, "manifest.json")["header"]
    assert header["claims_verified"] == claims > 0
    assert header["sentences_verified"] == verified
    assert header["sentences_withheld"] == withheld
    assert header["answers"] == answers == len(load(out, "threads.json")["threads"])
    assert header["audit_chain_ok"] is True


def test_workflows_follow_the_contract(out: Path) -> None:
    wf = {w["id"]: w["thread_ids"] for w in load(out, "threads.json")["workflows"]}
    assert wf["capa-need-evidence"] == ["05-capa-need-evidence"]
    assert wf["weekly-signals"] == [
        f"{n}-{s}"
        for n, s in [
            ("01", "what-changed"),
            ("02", "why-first"),
            ("13", "llz-severity"),
            ("15", "five-day"),
            ("20", "briefing"),
            ("22", "compare"),
        ]
    ]
    assert wf["ask-copilot"][-2:] == ["00-voice-a", "00-voice-b"]
    assert "00-voice-main" not in wf["ask-copilot"]
    assert "00-voice-main" not in [t["id"] for t in load(out, "threads.json")["threads"]]


def test_tool_names_use_display_labels_and_summaries_use_stored_numbers(out: Path) -> None:
    threads = load(out, "threads.json")["threads"]
    names = {s["name"] for t in threads for s in t["tool_steps"]}
    assert "weekly_signals" in names and "overnight_signals" not in names
    trap = next(t for t in threads if t["id"] == "06-trap")
    summaries = [s["summary"] for s in trap["tool_steps"]]
    assert "counted 121 reports for LLZ" in summaries
    assert "found 2 matching reports" in summaries


def test_summary_never_invents_a_number() -> None:
    assert exporter.tool_summary("recalls", {}, '{"x": 1') == "checked recalls"
    assert exporter.tool_summary("product_summary", {"product_code": "QIH"}, "{}") == (
        "summarised a device type"
    )
    assert (
        exporter.tool_summary("product_summary", {"product_code": "QIH"}, '{"report_count": 10, ')
        == "counted 10 reports for QIH"
    )


def test_every_cited_report_has_evidence(out: Path) -> None:
    threads = load(out, "threads.json")
    evidence = load(out, "evidence.json")
    for eid in exporter.evidence_ids(threads):
        assert eid in evidence["reports"] or eid in evidence["other"], eid
    sample = next(iter(evidence["reports"].values()))
    assert sample["maude_url"].startswith("https://www.accessdata.fda.gov/")
    assert all(len(r["excerpt"]) <= 400 for r in evidence["reports"].values())


def test_audit_chain_is_reverified_not_copied(out: Path, tmp_path: Path) -> None:
    runs = load(out, "audit.json")["runs"]
    assert runs and all(r["chain_ok"] for r in runs)
    (tmp_path / "demo" / "transcripts").mkdir(parents=True)
    src = json.loads((ROOT / "demo/transcripts/audit-typed.json").read_text(encoding="utf-8"))
    src["entries"][3]["payload_json"] = '{"tampered": true}'
    (tmp_path / "demo/transcripts/audit-typed.json").write_text(json.dumps(src), encoding="utf-8")
    bad = exporter.build_audit(tmp_path)["runs"][0]
    assert bad["chain_ok"] is False and bad["first_bad_seq"] == src["entries"][3]["seq"]


def test_investigations_is_empty_with_a_note_until_runs_exist(out: Path) -> None:
    doc = load(out, "investigations.json")
    if not (ROOT / "demo" / "investigations").exists():
        assert doc["investigations"] == []
        assert doc["notes"]


def test_sources_come_from_the_demo_database(out: Path) -> None:
    import sqlite3

    conn = sqlite3.connect(ROOT / "data/demo/maudesignal_demo.db")
    n = conn.execute("select count(*) from raw_reports").fetchone()[0]
    mhra = conn.execute(
        "select count(*) from external_sources where source_type='mhra_alert'"
    ).fetchone()[0]
    conn.close()
    src = {s["id"]: s for s in load(out, "sources.json")["sources"]}
    assert src["maude"]["records"] == n
    assert src["mhra"]["label"] == "MHRA (UK)" and src["mhra"]["records"] == mhra


def test_schedules_read_workflow_files_and_newest_outputs(out: Path) -> None:
    sched = {s["id"]: s for s in load(out, "schedules.json")["schedules"]}
    assert sched["daily-monitor"]["cron"] == "17 11 * * *"
    assert sched["ai-sweep"]["cron"] == "23 12 * * 1"
    newest = sorted(p.stem for p in (ROOT / "digests").glob("*.json"))[-1]
    assert sched["daily-monitor"]["last_result"]["date"] == newest
    sweep = load(out, "sweep.json")
    flagged = sum(r["classification"] != "stable" for r in sweep["rows"])
    assert sched["ai-sweep"]["last_result"]["flagged"] == flagged


def test_files_listed_in_manifest_exist_and_assets_are_copied(out: Path) -> None:
    manifest = load(out, "manifest.json")
    for name in manifest["files"]:
        assert (out / name).is_file()
    assert manifest["assets"]
    for asset in manifest["assets"]:
        assert (out / asset).is_file()
    dossier = load(out, "dossier.json")
    assert (out / dossier["pdf"]["approved"]).is_file()


def test_no_secrets_lot_or_serial_values_in_outputs(out: Path) -> None:
    secret = re.compile(r"(sk-[A-Za-z0-9]{16,}|gsk_[A-Za-z0-9]{16,}|api[_-]?key\"\s*:\s*\"[^\"]+)")
    for name in JSON_FILES:
        text = (out / name).read_text(encoding="utf-8")
        assert not secret.search(text), name
    for label in load(out, "vision.json")["labels"]:
        assert label["session_fields_omitted"] is True
        assert not [k for k in label["fields"] if re.search(r"lot|serial", k, re.I)]


def test_missing_inputs_become_null_with_notes(tmp_path: Path) -> None:
    (tmp_path / "demo" / "dossier").mkdir(parents=True)
    doc, assets = exporter.build_dossier(tmp_path, tmp_path / "out")
    assert doc["doc_id"] is None and doc["notes"] and assets == []
    sweep = exporter.build_sweep(tmp_path)
    assert sweep["rows"] is None and sweep["notes"]
    shutil.rmtree(tmp_path)


def test_committed_manifest_assets_exist_on_disk() -> None:
    """Every asset the committed manifest advertises is a committed file (not git-ignored)."""
    import subprocess

    data = ROOT / "web" / "public" / "data"
    manifest = json.loads((data / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["assets"]
    tracked = set(
        subprocess.run(
            ["git", "ls-files", "web/public/data"], cwd=ROOT, capture_output=True, text=True
        ).stdout.split()
    )
    for asset in manifest["assets"]:
        assert (data / asset).is_file(), asset
        if tracked:  # empty outside a git checkout
            assert f"web/public/data/{asset}" in tracked, f"{asset} is not committed"


FORBIDDEN = re.compile(
    r"fda-approved|part 11 compliant|validated|overnight|worsening signals|citation-checked"
    r"|complaint data",
    re.I,
)


def test_no_forbidden_words_in_any_exported_json(out: Path) -> None:
    for name in JSON_FILES:
        hit = FORBIDDEN.search((out / name).read_text(encoding="utf-8"))
        assert hit is None, f"{name}: {hit and hit.group(0)}"


def test_parity_fixtures_are_current_and_cover_every_rule() -> None:
    """The cases the TypeScript detector is tested on come from the Python code and are fresh."""
    fresh = json.loads(json.dumps(exporter.parity_fixtures()))  # tuples become lists, as on disk
    committed = json.loads(exporter.PARITY_FILE.read_text(encoding="utf-8"))
    assert committed == fresh, "run: python3 scripts/export_web_data.py --parity-fixtures"
    cases = fresh["classify"]
    assert len(cases) >= 200
    assert {c["expected"]["classification"] for c in cases} == {
        "new_signal",
        "severity_escalation",
        "spike",
        "stable",
    }
    triggers = {t for c in cases for t in c["expected"]["triggers"]}
    assert triggers == {"new_signal", "severity_escalation", "spike"}
    # boundaries: exactly three reports, exactly twice the weekly mean, exactly +15 points
    assert any(c["expected"]["current_count"] == 3 for c in cases)
    assert any(c["expected"]["spike_ratio"] == 2.0 for c in cases)
    assert any(c["expected"]["severe_share_delta_pp"] == 15.0 for c in cases)
    assert len(fresh["norm"]) >= 50 and len(fresh["windows"]) >= 30 and len(fresh["urls"]) >= 20


def test_display_excluded_audit_run_is_not_exported_but_chain_still_checked(out: Path) -> None:
    labels = [r["run_label"] for r in load(out, "audit.json")["runs"]]
    assert "00-voice-main" not in labels and "typed" in labels


def test_capa_tool_step_uses_the_display_label(out: Path) -> None:
    raw = "".join(json.dumps(load(out, n)) for n in ("threads.json", "protocol.json", "audit.json"))
    assert "draft_capa" not in raw
    assert "capa_need_evidence" in raw
    assert exporter.tool_label("draft_capa") == "capa_need_evidence"


def test_label_matches_attach_to_their_label_and_are_never_confirmed(tmp_path: Path) -> None:
    """label-match-*.json becomes ``matches`` on its label; ``confirmed`` is always null."""
    vdir = tmp_path / "demo" / "vision"
    (vdir / "labels").mkdir(parents=True)
    (vdir / "labels" / "label-a.jpg").write_bytes(b"jpg")
    for name in ("a", "b"):
        reading = {"image_file": f"label-{name}.jpg", "fields": {}, "session_fields_omitted": True}
        (vdir / f"label-{name}.json").write_text(json.dumps(reading), encoding="utf-8")
    record = {"kind": "device_label_match", "matches": [{"record_id": "KX"}], "confirmed": "KX"}
    (vdir / "label-match-a.json").write_text(json.dumps(record), encoding="utf-8")
    doc, _ = exporter.build_vision(tmp_path, tmp_path / "out")
    assert len(doc["labels"]) == 2
    by_file = {x["image_file"]: x for x in doc["labels"]}
    assert by_file["label-a.jpg"]["matches"]["matches"] == [{"record_id": "KX"}]
    assert by_file["label-a.jpg"]["matches"]["confirmed"] is None
    assert by_file["label-b.jpg"]["matches"] is None
    assert any("label-match-b.json not found" in n for n in doc["notes"])
    assert any("confirmed" in n for n in doc["notes"])


# ── company.json (B7) ────────────────────────────────────────────────────────
BANNER = "Simulated company — sample data. Problem evidence is real FDA data."
COMPANY_WORDS = re.compile(r"\b(safe|unsafe|compliant)\b", re.I)


def _company_copy(tmp_path: Path) -> Path:
    shutil.copytree(ROOT / "demo" / "company", tmp_path / "demo" / "company")
    return tmp_path


def test_company_json_follows_the_contract(out: Path) -> None:
    doc = load(out, "company.json")
    assert doc["banner"] == BANNER
    assert [s["label"] for s in doc["statuses"]][0] == "Needs review"
    assert len(doc["devices"]) == 12
    assert doc["audit"]["chain_ok"] is True and doc["audit"]["first_bad_seq"] is None
    for d in doc["devices"]:
        assert set(d) >= {"id", "name", "product_code", "owner", "status", "history", "evidence"}
        assert d["status"]["set_by"].endswith("(simulated)")
        assert [h["to_status"] for h in d["history"]][-1] == d["status"]["label"]
    assert "company.json" in load(out, "manifest.json")["files"]


def test_company_missing_evidence_is_labelled_and_empty(out: Path) -> None:
    doc = load(out, "company.json")
    missing = [d for d in doc["devices"] if not d["evidence"]["available"]]
    for d in missing:
        ev = d["evidence"]
        assert ev["note"] == "evidence not fetched yet"
        assert ev["report_count"] is None and ev["recalls"] is None and d["patterns"] == []
        assert any(d["product_code"] in n and "not fetched yet" in n for n in doc["notes"])


def test_company_counts_are_recomputed_and_quotes_are_verbatim(out: Path) -> None:
    doc = load(out, "company.json")
    fetched = [d for d in doc["devices"] if d["evidence"]["available"]]
    assert fetched
    for d in fetched:
        ev = json.loads(
            (ROOT / "demo/company/evidence" / f"{d['product_code']}.json").read_text("utf-8")
        )
        by_id = {str(r["report_id"]): r for r in ev["reports"]["records"]}
        assert d["evidence"]["report_count"]["value"] == len(by_id)
        assert d["evidence"]["recalls"]["stored"] == len(ev["recalls"]["records"])
        for p in d["patterns"]:
            assert p["count"] == len(p["report_ids"]) == len(set(p["report_ids"]))
            assert all(i in by_id for i in p["report_ids"])
            assert p["gate"]["count"] == "pass" and p["display_label"].startswith("Keyword match")
            for q in p["quotes"]:
                assert q["report_id"] in p["report_ids"]
                squashed = " ".join(str(by_id[q["report_id"]]["text"]).split())
                assert q["text"] in squashed
                assert q["url"].endswith(q["report_id"])


def test_company_json_never_prints_the_banned_words(out: Path) -> None:
    text = (out / "company.json").read_text(encoding="utf-8")
    assert COMPANY_WORDS.search(text) is None
    assert exporter.COMPANY_FORBIDDEN.search(text) is None


def test_company_chain_is_reverified_not_copied(tmp_path: Path) -> None:
    root = _company_copy(tmp_path)
    path = root / "demo/company/audit.json"
    doc = json.loads(path.read_text(encoding="utf-8"))
    assert doc["chain_ok_at_export"] is True
    doc["entries"][4]["payload_json"] += " "
    path.write_text(json.dumps(doc), encoding="utf-8")  # chain_ok_at_export still says true
    built = exporter.build_company(root, "2026-10-30T00:00:00Z")
    assert built["audit"]["chain_ok"] is False
    assert built["audit"]["first_bad_seq"] == doc["entries"][4]["seq"]


def test_company_status_must_be_set_by_a_named_simulated_person_and_move_forward(
    tmp_path: Path,
) -> None:
    entries = json.loads((ROOT / "demo/company/audit.json").read_text("utf-8"))["entries"]
    forged = [dict(e) for e in entries]
    forged[0]["actor"] = "MaudeSignal"
    with pytest.raises(ValueError, match="simulated person"):
        exporter._company_history(forged)
    change = next(e for e in entries if e["action"].endswith("change"))
    payload = json.loads(change["payload_json"])
    back = dict(change, payload_json=json.dumps({**payload, "to_status": "Needs review"}))
    with pytest.raises(ValueError, match="only moves forward"):
        exporter._company_history([e for e in entries if e["seq"] < change["seq"]] + [back])


def test_company_folder_missing_gives_an_empty_banner_document(tmp_path: Path) -> None:
    doc = exporter.build_company(tmp_path, "2026-10-30T00:00:00Z")
    assert doc["banner"] == BANNER and doc["devices"] == [] and doc["notes"]
