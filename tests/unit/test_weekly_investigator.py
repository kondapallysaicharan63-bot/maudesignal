"""Tests for the weekly investigator (workflow 1), HACKATHON-BUILT.

The model is a scripted fake OpenAI-compatible client: no network, no credits, and
nothing here is a recorded run.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
import yaml
from typer.testing import CliRunner

from maudesignal.cli import app
from maudesignal.copilot.investigator import (
    ALLOWED_TOOLS,
    NOT_FLAGGED,
    flagged_codes,
    investigate,
    investigation_to_dict,
    save_investigation,
)
from maudesignal.copilot.protocol import protocol_from_transcript
from maudesignal.copilot.tools import ToolContext
from maudesignal.extraction.skill_loader import SkillLoader
from maudesignal.gate import claim_from_dict, verify_answer
from maudesignal.gate.claims import GroupCountClaim
from maudesignal.gate.loader import store_from_database
from maudesignal.storage.database import Database

ROOT = Path(__file__).resolve().parents[2]
RID = ["1111111-2026-00001", "1111111-2026-00002", "1111111-2026-00003"]
OTHER = "2222222-2026-00001"
LATE = "3333333-2026-00001"  # received before the week
WINDOW = {"date_from": "20260821", "date_to": "20260827"}


def _db(tmp_path: Path) -> Database:
    db = Database(tmp_path / "i.db")
    rows = [
        (
            RID[0],
            "QIH",
            "20260825",
            "Malfunction",
            "Triage alert was not sent after a server update.",
        ),
        (
            RID[1],
            "QIH",
            "20260826",
            "Malfunction",
            "Study failed to load; the app crashed on open.",
        ),
        (
            RID[2],
            "QIH",
            "20260827",
            "Injury",
            "Alert was not sent after the update; delayed notice.",
        ),
        (OTHER, "LLZ", "20260826", "Malfunction", "Report and displayed images may not match."),
        (LATE, "QIH", "20260820", "Malfunction", "An older report, outside the week."),
    ]
    for rid, code, d, et, text in rows:
        db.upsert_raw_report(
            maude_report_id=rid,
            product_code=code,
            date_received=d,
            date_of_event=None,
            raw_payload={"report_number": rid},
        )
        db.upsert_normalized_event(
            maude_report_id=rid,
            product_code=code,
            event_type=et,
            event_date=None,
            narrative=text,
            mfr_narrative=None,
            manufacturer="Acme",
            brand_name="Acme Triage",
        )
    return db


def _ctx(tmp_path: Path) -> ToolContext:
    db = _db(tmp_path)
    return ToolContext(db=db, store=store_from_database(db))


def _msg(content: str | None = None, tool_calls: list[Any] | None = None) -> Any:
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content, tool_calls=tool_calls))],
        usage=SimpleNamespace(prompt_tokens=100, completion_tokens=50),
    )


def _call(name: str, args: dict[str, Any], cid: str) -> Any:
    return SimpleNamespace(id=cid, function=SimpleNamespace(name=name, arguments=json.dumps(args)))


class FakeClient:
    """Scripted OpenAI-compatible client."""

    def __init__(self, script: list[Any]) -> None:
        self.script = list(script)
        self.calls: list[dict[str, Any]] = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kwargs: Any) -> Any:
        self.calls.append({**kwargs, "messages": list(kwargs["messages"])})
        return self.script.pop(0)


def _group(label: str, ids: list[str], value: int | None = None) -> dict[str, Any]:
    return {
        "kind": "group_count",
        "product_code": "QIH",
        "label": label,
        "report_ids": ids,
        "value": len(ids) if value is None else value,
        "date_from": WINDOW["date_from"],
        "date_to": WINDOW["date_to"],
    }


def _answer(*sentences: tuple[str, list[dict[str, Any]]]) -> str:
    return json.dumps({"sentences": [{"text": t, "claims": c} for t, c in sentences]})


def _tool_round() -> Any:
    return _msg(
        tool_calls=[
            _call("search_reports", {"product_code": "QIH", **WINDOW, "limit": 10}, "c1"),
            _call("report_sources", {"product_code": "QIH", **WINDOW}, "c2"),
            _call("recalls", {"product_code": "QIH"}, "c3"),
            _call("draft_capa", {"product_code": "QIH"}, "c4"),
        ]
    )


GOOD = _answer(
    (
        "QIH has 3 reports received in the window.",
        [
            {
                "kind": "count",
                "product_code": "QIH",
                "value": 3,
                "event_type": None,
                "date_from": WINDOW["date_from"],
                "date_to": WINDOW["date_to"],
            }
        ],
    ),
    (
        "2 reports describe alerts not sent after an update.",
        [_group("alerts not sent after an update", [RID[0], RID[2]])],
    ),
    (
        "1 report describes a study that failed to load.",
        [_group("study failed to load", [RID[1]])],
    ),
    ("A QA/RA reviewer should read these reports and decide.", []),
)


def _run(tmp_path: Path, script: list[Any], code: str = "QIH") -> tuple[Any, FakeClient]:
    ctx = _ctx(tmp_path)
    client = FakeClient(script)
    return investigate(client, ctx, code), client


# ---------------------------------------------------------------- gate: group_count


def _gate(tmp_path: Path, claim: dict[str, Any], text: str = "2 reports describe it.") -> Any:
    store = _ctx(tmp_path).store
    return verify_answer([(text, [claim_from_dict(claim)])], store).sentences[0]


def test_group_count_parses_and_passes_with_recomputed_count(tmp_path: Path) -> None:
    claim = claim_from_dict(_group("alerts", [RID[0], RID[2]]))
    assert isinstance(claim, GroupCountClaim) and claim.report_ids == (RID[0], RID[2])
    v = _gate(tmp_path, _group("alerts", [RID[0], RID[2]]))
    assert v.status == "pass"
    assert v.claim_verdicts[0].reason == "recomputed 2 from 2 listed report ids"


def test_group_count_blocks_wrong_value_and_reports_recomputed(tmp_path: Path) -> None:
    v = _gate(tmp_path, _group("alerts", [RID[0], RID[2]], value=5), "5 reports describe it.")
    assert v.status == "block"
    cv = v.claim_verdicts[0]
    assert "claimed 5, group lists 2" in cv.reason and cv.recomputed == 2


@pytest.mark.parametrize(
    ("ids", "needle"),
    [
        (["9999999-2026-00009"], "not in evidence store"),
        ([OTHER], "is not a QIH report"),
        ([LATE], "outside the stated dates"),
        ([RID[0], RID[0]], "more than once"),
        ([], "no report ids"),
    ],
)
def test_group_count_blocks_bad_ids(tmp_path: Path, ids: list[str], needle: str) -> None:
    v = _gate(tmp_path, _group("alerts", ids, value=max(len(ids), 1)), "1 report describes it.")
    assert v.status == "block" and needle in v.claim_verdicts[0].reason


def test_group_sentence_count_without_claim_is_ungrounded(tmp_path: Path) -> None:
    store = _ctx(tmp_path).store
    v = verify_answer([("2 reports describe alerts not sent.", [])], store).sentences[0]
    assert v.status == "block" and v.ungrounded


# ---------------------------------------------------------------- the loop


def test_loop_pulls_reports_groups_and_gates(tmp_path: Path) -> None:
    script = [_tool_round(), _msg(GOOD), _msg(GOOD)]
    res, client = _run(tmp_path, script)
    rep = res.copilot.report
    assert rep.blocked == 0 and rep.passed == 4
    assert [g.to_dict() for g in res.groups] == [
        {
            "label": "alerts not sent after an update",
            "report_ids": [RID[0], RID[2]],
            "count": 2,
        },
        {"label": "study failed to load", "report_ids": [RID[1]], "count": 1},
    ]
    names = [t.name for t in res.copilot.tool_calls]
    assert names == ["search_reports", "report_sources", "recalls", "draft_capa"]
    # the write tool is not offered and not executed
    offered = {t["function"]["name"] for t in client.calls[0]["tools"]}
    assert offered == ALLOWED_TOOLS and "draft_capa" not in offered
    assert "not available" in res.copilot.tool_calls[3].result_preview
    # skill is the investigator's, request is data only, temperature 0
    system = client.calls[0]["messages"][0]["content"]
    assert system.startswith("# Skill: weekly-investigator")
    user = json.loads(client.calls[0]["messages"][1]["content"])
    assert user["product_code"] == "QIH" and user["window"]["date_to"] == "20260827"
    assert client.calls[0]["temperature"] == 0.0
    # search_reports honours the window: only the 3 in-window QIH reports
    tool_msg = next(m for m in client.calls[1]["messages"] if m.get("tool_call_id") == "c1")
    assert json.loads(tool_msg["content"])["matched"] == 3


def test_flagged_trigger_and_not_flagged_trigger(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path)
    flagged = {f["product_code"]: f for f in flagged_codes(ctx)}
    assert "QIH" in flagged
    res, _ = _run(tmp_path, [_msg(GOOD), _msg(GOOD)])
    assert res.trigger == f"weekly check: {flagged['QIH']['label']}"
    res2, _ = _run(tmp_path, [_msg(GOOD), _msg(GOOD)], code="ZZZ")
    assert res2.trigger == NOT_FLAGGED


def test_wrong_group_count_is_repaired(tmp_path: Path) -> None:
    bad = _answer(
        (
            "5 reports describe alerts not sent after an update.",
            [_group("alerts not sent after an update", [RID[0], RID[2]], value=5)],
        )
    )
    script = [_msg(bad), _msg(bad), _msg(GOOD), _msg(GOOD)]
    res, client = _run(tmp_path, script)
    assert res.copilot.first_pass_report.blocked == 1
    assert res.copilot.repaired and res.copilot.report.blocked == 0
    repair = client.calls[2]["messages"][-1]["content"]
    assert repair.startswith("GATE BLOCKED") and "recomputed=2.0" in repair
    assert len(res.groups) == 2


def test_unrepaired_sentence_is_withheld_and_makes_no_group(tmp_path: Path) -> None:
    bad = _answer(
        (
            "5 reports describe alerts not sent after an update.",
            [_group("alerts not sent after an update", [RID[0], RID[2]], value=5)],
        ),
        (
            "1 report describes a study that failed to load.",
            [_group("study failed to load", [RID[1]])],
        ),
    )
    res, _ = _run(tmp_path, [_msg(bad), _msg(bad), _msg(bad), _msg(bad)])
    assert res.copilot.report.blocked == 1 and res.copilot.report.passed == 1
    assert [g.label for g in res.groups] == ["study failed to load"]
    shown = res.copilot.answer
    assert "[Withheld" in shown and "5 reports describe" not in shown
    saved = investigation_to_dict(res)
    statuses = [s["status"] for s in saved["sentences"]]
    assert statuses == ["block", "pass"]
    assert saved["sentences"][0]["reasons"]
    assert [g["label"] for g in saved["groups"]] == ["study failed to load"]


# ---------------------------------------------------------------- saved JSON


def test_saved_json_shape_matches_data_contract(tmp_path: Path) -> None:
    res, _ = _run(tmp_path, [_tool_round(), _msg(GOOD), _msg(GOOD)])
    path = save_investigation(res, tmp_path / "demo" / "investigations")
    assert path.name.endswith("-weekly-qih.json") and path.name[8] == "T"
    d = json.loads(path.read_text(encoding="utf-8"))
    for key in (
        "id",
        "kind",
        "product_code",
        "trigger",
        "recorded_at_utc",
        "model",
        "tool_steps",
        "sentences",
        "groups",
        "protocol",
    ):
        assert key in d
    assert d["id"] == path.stem and d["kind"] == "weekly-investigator"
    assert d["product_code"] == "QIH" and d["recorded_at_utc"].endswith("Z")
    assert d["skill_version"] == "1.0.0"
    s0 = d["sentences"][1]
    assert set(s0) == {"text", "status", "reasons", "claims"}
    assert s0["claims"][0]["kind"] == "group_count"
    assert s0["claims"][0]["reason"] == "recomputed 2 from 2 listed report ids"
    assert s0["claims"][0]["evidence_ids"] == [RID[0], RID[2]]
    assert d["groups"][0] == {
        "label": "alerts not sent after an update",
        "report_ids": [RID[0], RID[2]],
        "count": 2,
    }
    step = d["tool_steps"][0]
    assert step == {
        "name": "search_reports",
        "arguments": {"product_code": "QIH", **WINDOW, "limit": 10},
        "summary": "searched 3 reports",
    }
    assert [s["summary"] for s in d["tool_steps"]][1:3] == ["searched 3 reports", "checked recalls"]
    # protocol: one row per search call (draft_capa is not a search), same as the stored log
    assert [r["tool"] for r in d["protocol"]] == ["search_reports", "report_sources", "recalls"]
    assert d["protocol"][0]["count"] == 3 and d["protocol"][0]["date_from"] == "20260821"
    assert d["protocol"][0]["run_at"] == d["recorded_at_utc"]
    assert [r.to_dict() for r in protocol_from_transcript(d)] == d["protocol"]
    assert d["usage"]["input_tokens"] == 300 and d["usage"]["cost_usd"] > 0
    assert d["first_pass"]["blocked"] == 0 and d["repaired"] is False


# ---------------------------------------------------------------- skill, CLI, workflow


def test_skill_folder_is_complete_and_examples_pass_the_gate(tmp_path: Path) -> None:
    sk = SkillLoader(ROOT / "skills").load("weekly-investigator")
    assert sk.version == "1.0.0" and "## Changelog" in sk.system_prompt
    assert sk.good_examples and sk.bad_examples
    branches = sk.output_schema["properties"]["sentences"]["items"]["properties"]["claims"][
        "items"
    ]["anyOf"]
    kinds = [b["properties"]["kind"]["enum"][0] for b in branches]
    assert "group_count" in kinds and len(kinds) == len(set(kinds))
    for b in branches:  # strict-mode: every property required, no extras
        assert b["additionalProperties"] is False
        assert set(b["required"]) == set(b["properties"])
    store = _ctx(tmp_path).store
    for ex in sk.good_examples:
        pairs = [
            (s["text"], [claim_from_dict(c) for c in s["claims"]])
            for s in ex["expected_output"]["sentences"]
        ]
        assert verify_answer(pairs, store).blocked == 0


def test_cli_keyless_prints_needs_key(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv("META_MODEL_API_KEY", raising=False)
    r = CliRunner().invoke(
        app, ["investigate", "--product-code", "QIH", "--out-dir", str(tmp_path)]
    )
    assert r.exit_code == 2
    assert "needs META_MODEL_API_KEY" in r.output
    assert list(tmp_path.iterdir()) == []


def test_workflow_yaml_parses_and_is_gated_on_the_request_file() -> None:
    wf = yaml.safe_load((ROOT / ".github/workflows/investigator-record.yml").read_text())
    on = wf.get("on", wf.get(True))
    assert on["push"]["paths"] == ["demo/INVESTIGATE_REQUEST"]
    assert on["push"]["branches"] == ["hackathon-day2"]
    assert (ROOT / "demo/INVESTIGATE_REQUEST").is_file()
    text = (ROOT / ".github/workflows/investigator-record.yml").read_text()
    assert "secrets.META_MODEL_API_KEY" in text and "maudesignal.cli investigate" in text
