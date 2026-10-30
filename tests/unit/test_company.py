"""Simulated company ("Does this apply to us?"): separation, statuses, audit, gate, words.

The company is simulated; the problem evidence is real stored openFDA data. These tests
check that the two never mix, that a status only moves forward and only through a named
simulated person, that the audit chain detects any edit, and that every count and quote the
page shows is recomputed from the stored reports.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from maudesignal.company import (
    BANNER,
    STATUSES,
    StatusError,
    append_status,
    export_company,
    load_company,
    verify_chain,
)
from maudesignal.company import seed as company_seed
from maudesignal.company.constants import (
    ACTION_CHANGE,
    FORBIDDEN,
    PROJECT_ROOT,
    S_COVERED,
    S_MONITORING,
    S_NEEDS_REVIEW,
    S_NOT_APPLICABLE,
    S_TESTING,
    company_dir,
    contains_forbidden,
)
from maudesignal.company.evidence import demo_db_codes, load_demo_db_evidence
from maudesignal.company.patterns import RULES, group_by_rules, pick_quote
from maudesignal.company.status import (
    load_audit,
    parse_entries,
    validate_history,
)
from maudesignal.copilot.audit_export import verify_entries
from maudesignal.gate import GroupCountClaim, QuoteClaim, verify_claim
from maudesignal.gate.evidence import normalize_text
from maudesignal.storage.database import Database

DEMO_DB = PROJECT_ROOT / "data" / "demo" / "maudesignal_demo.db"
SWEEP = PROJECT_ROOT / "demo" / "sweep" / "ai-device-sweep.json"
FLAGGED = {"IYN", "OTE", "DSI", "MUD"}
STABLE = {"DQK", "LNH", "MWI"}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture(scope="module")
def view() -> Any:
    return load_company()


@pytest.fixture(scope="module")
def doc() -> dict[str, Any]:
    return json.loads((company_dir() / "company.json").read_text(encoding="utf-8"))


@pytest.fixture()
def entries() -> list[dict[str, Any]]:
    return copy.deepcopy(load_audit(company_dir() / "audit.json"))


def _ids() -> list[str]:
    return [d[0] for d in company_seed.DEVICES]


NOW = datetime(2026, 11, 1, 12, 0, tzinfo=UTC)


# ── the 12 devices ───────────────────────────────────────────────────────────


def test_twelve_devices_on_the_required_codes(doc: dict[str, Any]) -> None:
    codes = [d["product_code"] for d in doc["devices"]]
    assert len(codes) == 12
    assert codes.count("LLZ") == 2
    for one in ("QIH", "MYN", "POK"):
        assert codes.count(one) == 1
    assert FLAGGED <= set(codes) and STABLE <= set(codes)
    assert set(codes) == {"LLZ", "QIH", "MYN", "POK"} | FLAGGED | STABLE


def test_sweep_rows_are_cited_and_match_the_sweep_file(doc: dict[str, Any]) -> None:
    rows = {r["product_code"]: r for r in json.loads(SWEEP.read_text(encoding="utf-8"))["rows"]}
    for d in doc["devices"]:
        sw = d["sweep"]
        assert sw is not None, d["product_code"]
        row = rows[d["product_code"]]
        assert sw["file"] == "demo/sweep/ai-device-sweep.json"
        for key in (
            "as_of",
            "classification",
            "current_count",
            "baseline_count",
            "prior_report_count",
        ):
            assert sw[key] == row[key], (d["product_code"], key)
        assert sw["triggers"] == row["triggers"]
        if d["product_code"] in FLAGGED:
            assert row["classification"] != "stable" and row["triggers"]
        if d["product_code"] in STABLE:
            assert row["classification"] == "stable" and row["prior_report_count"] >= 3


def test_device_type_names_come_from_stored_openfda_data(doc: dict[str, Any]) -> None:
    con = sqlite3.connect(f"{DEMO_DB.as_uri()}?mode=ro", uri=True)
    catalog = dict(
        con.execute(
            "SELECT product_code, device_name FROM device_catalog "
            "WHERE source_keyword = 'openfda_classification'"
        )
    )
    con.close()
    for d in doc["devices"]:
        dt = d["device_type"]
        assert dt["query_url"].startswith("https://api.fda.gov/device/classification.json?search=")
        if d["product_code"] in catalog:
            assert dt["name"] == catalog[d["product_code"]]
        elif d["product_code"] in demo_db_codes(DEMO_DB):
            assert dt["name"] and dt["source"]
        else:
            assert dt["name"] is None  # filled from the fetched evidence file, never invented


def test_every_device_has_fictional_name_owner_and_a_dated_status(view: Any) -> None:
    for d in view.devices:
        assert d.name and d.model and d.owner.endswith("(simulated)")
        assert d.status is not None
        assert d.status.actor.endswith("(simulated)")
        assert d.status.date_label.startswith("2026-")
        assert d.history and d.history[0].from_status is None


def test_every_status_is_used_and_about_half_have_real_patterns(view: Any) -> None:
    used = {d.status.to_status for d in view.devices if d.status}
    assert used == set(STATUSES)
    with_patterns = [d for d in view.devices if d.has_patterns]
    assert {d.product_code for d in with_patterns} >= {"LLZ", "QIH"}


# ── separation from real records ─────────────────────────────────────────────


def test_demo_db_is_untouched_by_loading_exporting_and_checklists() -> None:
    before = sha256(DEMO_DB)
    v = load_company()
    export_company(v)
    from maudesignal.company import checklist_for

    checklist_for("LLZ")
    company_seed.build_company_doc(DEMO_DB, SWEEP)
    assert sha256(DEMO_DB) == before


def test_company_files_hold_no_real_records_and_real_records_hold_no_company(
    doc: dict[str, Any],
) -> None:
    text = (company_dir() / "company.json").read_text() + (company_dir() / "audit.json").read_text()
    con = sqlite3.connect(f"{DEMO_DB.as_uri()}?mode=ro", uri=True)
    report_ids = [r[0] for r in con.execute("SELECT maude_report_id FROM raw_reports")]
    assert not [i for i in report_ids if re.search(rf"\b{re.escape(i)}\b", text)]
    for d in doc["devices"]:
        for needle in (d["name"], d["model"], "Demo MedTech"):
            for table, col in (
                ("raw_reports", "raw_json"),
                ("normalized_events", "narrative"),
                ("normalized_events", "brand_name"),
                ("external_sources", "raw_json"),
                ("device_catalog", "device_name"),
            ):
                n = con.execute(
                    f"SELECT count(*) FROM {table} WHERE {col} LIKE ?", (f"%{needle}%",)
                ).fetchone()[0]
                assert n == 0, (needle, table)
    # the company keys never carry counts of real reports or recalls
    for d in doc["devices"]:
        assert not {"reports", "recalls", "patterns", "report_ids"} & set(d)
    con.close()


#: Well-known real device brands a fictional name must never use (the demo DB alone cannot
#: catch these, e.g. it holds no radiotherapy systems).
REAL_DEVICE_BRANDS = frozenset(
    "halcyon truebeam ethos versa cyberknife gammaknife medtronic stryker mako "
    "aidoc rapidai arterys enlitic zebra lunit paige heartflow caption butterfly "
    "clarius cleerly".split()
)


def test_statuses_point_at_patterns_the_page_shows() -> None:
    from maudesignal.company.build import load_company

    view = load_company()
    for d in view.devices:
        if d.status is None:
            continue
        text = " ".join(str(v) for v in d.status.details.values())
        quoted = re.findall(r"'([^']+)'", text)
        if d.status.to_status in ("Already covered", "Not applicable to our device"):
            assert quoted, f"{d.device_id} gives no pattern label"
        labels = {p.label for p in d.patterns}
        for q in quoted:
            assert q in labels, f"{d.device_id}: '{q}' is not a pattern shown on the page"
        if not d.evidence.available:
            assert d.status.to_status in ("Needs review", "Monitoring — nothing open")


def test_fictional_names_do_not_match_real_names_and_have_no_k_numbers(doc: dict[str, Any]) -> None:
    con = sqlite3.connect(f"{DEMO_DB.as_uri()}?mode=ro", uri=True)
    real: list[str] = []
    for col in ("manufacturer", "brand_name"):
        real += [r[0] for r in con.execute(f"SELECT DISTINCT {col} FROM normalized_events") if r[0]]
    real += [r[0] for r in con.execute("SELECT company_name FROM device_catalog") if r[0]]
    real += [r[0] for r in con.execute("SELECT device_name FROM device_catalog") if r[0]]
    for (raw,) in con.execute(
        "SELECT raw_json FROM external_sources WHERE source_type != 'pubmed'"
    ):
        j = json.loads(raw)
        real += [str(j[k]) for k in ("applicant", "device_name", "recalling_firm") if j.get(k)]
    con.close()
    real_tokens = {t for name in real for t in re.findall(r"[a-z0-9]+", name.lower())}
    real_text = " | ".join(n.lower() for n in real)
    for d in doc["devices"]:
        first = re.findall(r"[a-z0-9]+", d["name"].lower())[0]
        assert first not in real_tokens, f"{d['name']} shares a word with a real name"
        assert d["name"].lower() not in real_text
    for d in doc["devices"]:
        words = set(re.findall(r"[a-z0-9]+", d["name"].lower()))
        assert not words & REAL_DEVICE_BRANDS, f"{d['name']} uses a real device brand"
    blob = json.dumps(doc) + (company_dir() / "audit.json").read_text()
    assert not re.search(r"\bK\d{6}\b", blob)
    assert not re.search(r"\b(DEN|P)\d{6}\b", blob)


# ── statuses: forward-only, named simulated person ───────────────────────────


def test_stored_history_replays_cleanly_and_chain_is_intact(entries: list[dict[str, Any]]) -> None:
    validate_history(entries, _ids())
    assert verify_chain(entries) == (True, None)
    assert verify_entries(entries) == (True, None)


def test_forward_moves_are_accepted(entries: list[dict[str, Any]]) -> None:
    # DMC-03 is "Needs review": it may move to Testing, then to Monitoring.
    append_status(
        entries,
        device_ids=_ids(),
        device_id="DMC-03",
        to_status=S_TESTING,
        actor="Iris Tanaka (simulated)",
        ts=NOW,
        details={"owner": "Iris Tanaka (simulated)", "due_date": "2026-12-01"},
    )
    entry = append_status(
        entries,
        device_ids=_ids(),
        device_id="DMC-03",
        to_status=S_MONITORING,
        actor="Iris Tanaka (simulated)",
        ts=NOW,
    )
    assert entry["action"] == ACTION_CHANGE
    assert verify_chain(entries) == (True, None)


@pytest.mark.parametrize(
    ("device", "target", "details"),
    [
        ("DMC-01", S_NEEDS_REVIEW, {"owner": "Mara Ellison (simulated)"}),  # backwards
        ("DMC-01", S_TESTING, {"owner": "x (simulated)", "due_date": "2026-12-01"}),  # same
        ("DMC-02", S_NOT_APPLICABLE, {"reason": "sample"}),  # sideways from covered
        ("DMC-05", S_NEEDS_REVIEW, {"owner": "Lena Osei (simulated)"}),  # from monitoring
        ("DMC-04", S_COVERED, {"reference": "TR-1 (sample)"}),  # sideways
    ],
)
def test_backward_and_sideways_moves_are_rejected(
    entries: list[dict[str, Any]], device: str, target: str, details: dict[str, str]
) -> None:
    n = len(entries)
    with pytest.raises(StatusError, match="forward"):
        append_status(
            entries,
            device_ids=_ids(),
            device_id=device,
            to_status=target,
            actor="Ana Diaz (simulated)",
            ts=NOW,
            details=details,
        )
    assert len(entries) == n


@pytest.mark.parametrize(
    "actor", ["MaudeSignal", "tool (simulated)", "Claude", "Muse Spark (simulated)", "", "Ana Diaz"]
)
def test_the_tool_and_unnamed_actors_cannot_set_a_status(
    entries: list[dict[str, Any]], actor: str
) -> None:
    with pytest.raises(StatusError):
        append_status(
            entries,
            device_ids=_ids(),
            device_id="DMC-03",
            to_status=S_TESTING,
            actor=actor,
            ts=NOW,
            details={"owner": "x (simulated)", "due_date": "2026-12-01"},
        )


def test_details_unknown_device_and_time_order_are_enforced(entries: list[dict[str, Any]]) -> None:
    kw: dict[str, Any] = {"device_ids": _ids(), "actor": "Ana Diaz (simulated)", "ts": NOW}
    with pytest.raises(StatusError, match="due date"):
        append_status(
            entries, device_id="DMC-03", to_status=S_TESTING, details={"owner": "x"}, **kw
        )
    with pytest.raises(StatusError, match="due date must be"):
        append_status(
            entries,
            device_id="DMC-03",
            to_status=S_TESTING,
            details={"owner": "x", "due_date": "soon"},
            **kw,
        )
    with pytest.raises(StatusError, match="reference"):
        append_status(entries, device_id="DMC-03", to_status=S_COVERED, details={}, **kw)
    with pytest.raises(StatusError, match="unknown device"):
        append_status(entries, device_id="DMC-99", to_status=S_MONITORING, **kw)
    with pytest.raises(StatusError, match="unknown status"):
        append_status(entries, device_id="DMC-03", to_status="Safe", **kw)
    with pytest.raises(StatusError, match="time order"):
        append_status(
            entries,
            device_id="DMC-03",
            to_status=S_MONITORING,
            device_ids=_ids(),
            actor="Ana Diaz (simulated)",
            ts=datetime(2020, 1, 1, tzinfo=UTC),
        )
    with pytest.raises(StatusError, match="never print"):
        append_status(
            entries,
            device_id="DMC-03",
            to_status=S_COVERED,
            details={"reference": "this is safe"},
            **kw,
        )


def test_replay_catches_a_rule_break_even_when_hashes_are_recomputed(
    entries: list[dict[str, Any]],
) -> None:
    """A forged backward step with a valid chain passes the chain check but not the replay."""
    forged = copy.deepcopy(entries)
    payload = json.dumps(
        {
            "device_id": "DMC-01",
            "from_status": S_TESTING,
            "to_status": S_NEEDS_REVIEW,
            "details": {"owner": "Mara Ellison (simulated)"},
            "note": "",
        },
        sort_keys=True,
    )
    ts = datetime(2026, 10, 31, tzinfo=UTC)
    prev = forged[-1]["entry_hash"]
    forged.append(
        {
            "seq": len(forged) + 1,
            "ts": ts.isoformat(),
            "actor": "Mara Ellison (simulated)",
            "action": ACTION_CHANGE,
            "entity_id": "DMC-01",
            "payload_json": payload,
            "prev_hash": prev,
            "entry_hash": Database.audit_entry_hash(
                prev, ts, "Mara Ellison (simulated)", ACTION_CHANGE, "DMC-01", payload
            ),
        }
    )
    assert verify_chain(forged) == (True, None)
    with pytest.raises(StatusError, match="forward"):
        validate_history(forged, _ids())


# ── audit chain ──────────────────────────────────────────────────────────────


def test_tampering_with_any_field_breaks_the_chain(entries: list[dict[str, Any]]) -> None:
    for field in ("actor", "ts", "action", "entity_id", "payload_json"):
        bad = copy.deepcopy(entries)
        if field == "ts":
            bad[4]["ts"] = "2026-09-01T00:00:00+00:00"
        elif field == "payload_json":
            bad[4]["payload_json"] = bad[4]["payload_json"].replace("Monitoring", "Needs review")
        else:
            bad[4][field] = str(bad[4][field]) + "x"
        ok, first_bad = verify_chain(bad)
        assert not ok and first_bad == bad[4]["seq"], field


def test_removing_or_reordering_entries_breaks_the_chain(entries: list[dict[str, Any]]) -> None:
    removed = entries[:3] + entries[4:]
    assert verify_chain(removed)[0] is False
    swapped = copy.deepcopy(entries)
    swapped[2], swapped[3] = swapped[3], swapped[2]
    assert verify_chain(swapped)[0] is False
    truncated_hash = copy.deepcopy(entries)
    truncated_hash[0]["prev_hash"] = "FORGED"
    assert verify_chain(truncated_hash) == (False, 1)


def test_export_reverifies_the_chain_instead_of_trusting_the_file(
    tmp_path: Path, doc: dict[str, Any], entries: list[dict[str, Any]]
) -> None:
    (tmp_path / "company.json").write_text(json.dumps(doc))
    bad = copy.deepcopy(entries)
    bad[0]["actor"] = "Someone Else (simulated)"
    (tmp_path / "audit.json").write_text(json.dumps({"chain_ok_at_export": True, "entries": bad}))
    v = load_company(tmp_path)
    out = export_company(v)
    assert out["audit"]["chain_ok"] is False and out["audit"]["first_bad_seq"] == 1


# ── gate and recompute on counts and quotes ──────────────────────────────────


def _real_texts() -> dict[str, tuple[str, str]]:
    con = sqlite3.connect(f"{DEMO_DB.as_uri()}?mode=ro", uri=True)
    out = {
        r[0]: (r[1], " ".join(t for t in (r[2], r[3]) if t))
        for r in con.execute(
            "SELECT maude_report_id, product_code, narrative, mfr_narrative FROM normalized_events"
        )
    }
    con.close()
    return out


def test_pattern_counts_and_quotes_are_recomputed_from_stored_reports(view: Any) -> None:
    texts = _real_texts()
    seen = 0
    for d in view.devices:
        if not d.evidence.available:
            continue
        if d.evidence.origin != "demo_db":  # fetched files: recompute from the file's own reports
            texts = {**texts, **{r.report_id: (d.product_code, r.text) for r in d.evidence.reports}}
        stored = [i for i, (code, _) in texts.items() if code == d.product_code]
        assert d.code_patterns.report_count == len(stored)
        for p in d.patterns:
            assert p.count == len(set(p.report_ids)) == len(p.report_ids)
            assert all(texts[i][0] == d.product_code for i in p.report_ids)
            assert p.gate_count == "pass"
            for q in p.quotes:
                assert q.report_id in p.report_ids
                assert normalize_text(q.text) in normalize_text(texts[q.report_id][1])
                assert q.text.strip() == q.text and 40 <= len(q.text) <= 220
                seen += 1
    assert seen >= 10


def test_recall_counts_match_the_stored_recalls(view: Any) -> None:
    con = sqlite3.connect(f"{DEMO_DB.as_uri()}?mode=ro", uri=True)
    for d in view.devices:
        if d.evidence.available and d.evidence.origin == "demo_db":
            n = con.execute(
                "SELECT count(*) FROM external_sources WHERE source_type='fda_recall' "
                "AND product_code=?",
                (d.product_code,),
            ).fetchone()[0]
            assert d.code_patterns.recalls is not None
            assert d.code_patterns.recalls.stored == n
            assert d.code_patterns.recalls.gate_status == "pass"
    con.close()


def test_the_gate_blocks_a_wrong_count_and_a_made_up_quote() -> None:
    ev = load_demo_db_evidence("LLZ", DEMO_DB)
    store = ev.store()
    ids = tuple(r.report_id for r in ev.reports[:3])
    ok = verify_claim(GroupCountClaim("LLZ", "x", ids, 3), store)
    wrong = verify_claim(GroupCountClaim("LLZ", "x", ids, 4), store)
    other_code = verify_claim(GroupCountClaim("QIH", "x", ids, 3), store)
    assert (ok.status, wrong.status, other_code.status) == ("pass", "block", "block")
    with_text = next(r for r in ev.reports if len(r.text) > 80)
    fake = verify_claim(
        QuoteClaim(
            quote="the device exploded in the hospital lobby", report_id=with_text.report_id
        ),
        store,
    )
    assert fake.status == "block"
    real = pick_quote(with_text, re.compile(r"\b\w{4,}\b"))
    assert real is not None
    assert (
        verify_claim(QuoteClaim(quote=real, report_id=with_text.report_id), store).status == "pass"
    )


def test_keyword_rules_are_deterministic_and_need_two_reports() -> None:
    ev = load_demo_db_evidence("QIH", DEMO_DB)
    a = [(r.rule_id, [x.report_id for x in m]) for r, m in group_by_rules(ev.reports)]
    b = [(r.rule_id, [x.report_id for x in m]) for r, m in group_by_rules(reversed(ev.reports))]
    assert a == b and a
    assert all(len(ids) >= 2 for _, ids in a)
    assert len({r.rule_id for r in RULES}) == len(RULES)
    assert group_by_rules(ev.reports[:1]) == []


def test_missing_evidence_shows_no_numbers(tmp_path: Path) -> None:
    out = export_company(load_company(evidence_folder=tmp_path))  # no evidence files
    for d in out["devices"]:
        if d["product_code"] in FLAGGED | STABLE:
            ev = d["evidence"]
            assert ev["available"] is False and ev["note"] == "evidence not fetched yet"
            assert ev["report_count"] is None and ev["recalls"] is None
            assert d["patterns"] == []
    assert any("evidence not fetched yet" in n for n in out["notes"])


# ── export shape and words ───────────────────────────────────────────────────


def test_export_shape_matches_the_contract(view: Any) -> None:
    out = export_company(view)
    assert out["schema_version"] == "1.0" and out["banner"] == BANNER
    assert out["audit"]["chain_ok"] is True and out["audit"]["first_bad_seq"] is None
    assert len(out["devices"]) == 12 and len(out["audit"]["entries"]) == len(view.audit_entries)
    d0 = out["devices"][0]
    assert set(d0) == {
        "id", "name", "model", "product_code", "owner", "device_type", "sweep",
        "status", "history", "evidence", "patterns",
    }  # fmt: skip
    assert d0["history"][0]["action"] == "register"
    for d in out["devices"]:
        for p in d["patterns"]:
            assert p["gate"]["count"] == "pass" and p["count"] == len(p["report_ids"])
            for q in p["quotes"]:
                assert q["url"].startswith("https://www.accessdata.fda.gov/")
        for e in d["evidence"]["queries"]:
            assert e["url"].startswith("https://api.fda.gov/")
    json.dumps(out)


def test_no_forbidden_words_on_any_company_surface(view: Any) -> None:
    out = export_company(view)
    blob = json.dumps(
        {k: v for k, v in out.items() if k != "audit"}, ensure_ascii=False
    ) + json.dumps(
        [(e["actor"], e["payload_json"]) for e in out["audit"]["entries"]], ensure_ascii=False
    )
    assert not FORBIDDEN.search(blob), FORBIDDEN.search(blob)
    assert not FORBIDDEN.search((company_dir() / "company.json").read_text())
    for rel in ("dashboard/company_pages.py", "company/checklist.py", "company/build.py"):
        src = (PROJECT_ROOT / "src" / "maudesignal" / rel).read_text()
        assert not FORBIDDEN.search(src), rel
    assert contains_forbidden("This is unsafe") and contains_forbidden("fully Compliant")
    assert not contains_forbidden("safety signal; safeguards")


def test_audit_entries_parse_to_named_people(entries: list[dict[str, Any]]) -> None:
    for e in parse_entries(entries):
        assert e.actor.endswith("(simulated)") and e.date_label.startswith("2026-10")
        assert e.action.startswith("company.status.")


def test_seed_is_reproducible(tmp_path: Path) -> None:
    company_seed.main(tmp_path)
    for name in ("company.json", "audit.json"):
        assert (tmp_path / name).read_text() == (company_dir() / name).read_text(), name
