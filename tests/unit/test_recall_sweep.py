"""Tests for the recall-triggered sweep (workflow 2), HACKATHON-BUILT.

The model is a scripted fake OpenAI-compatible client: no network, no credits, and
nothing here is a recorded run. Recall text and report ids are synthetic.
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
from maudesignal.copilot.investigator import InvestigationError
from maudesignal.copilot.protocol import protocol_from_transcript
from maudesignal.copilot.recall_sweep import (
    ALLOWED_TOOLS,
    build_request,
    find_recall,
    save_sweep,
    sweep,
    sweep_to_dict,
)
from maudesignal.copilot.tools import ToolContext
from maudesignal.extraction.skill_loader import SkillLoader
from maudesignal.gate import claim_from_dict, verify_answer
from maudesignal.gate.loader import store_from_database
from maudesignal.storage.database import Database

ROOT = Path(__file__).resolve().parents[2]
RID = ["1111111-2026-00001", "1111111-2026-00002", "1111111-2026-00003"]
OTHER = "2222222-2026-00001"
RECALL = "Z-9001-2026"
REASON = "Software may fail to send a notification when the worklist exceeds 200 studies."
NARR = [
    "Triage alert was not sent after a server update.",
    "Study failed to load; the app crashed on open.",
    "Alert was not sent when the worklist was long; delayed notice.",
]
WINDOW = {"date_from": "20260825", "date_to": "20260827"}


def _db(tmp_path: Path) -> Database:
    db = Database(tmp_path / "s.db")
    rows = [
        (RID[0], "QIH", "20260825", NARR[0]),
        (RID[1], "QIH", "20260826", NARR[1]),
        (RID[2], "QIH", "20260827", NARR[2]),
        (OTHER, "LLZ", "20260826", "Report and displayed images may not match."),
    ]
    for rid, code, d, text in rows:
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
            event_type="Malfunction",
            event_date=None,
            narrative=text,
            mfr_narrative=None,
            manufacturer="Acme",
            brand_name="Acme Triage",
        )
    for number, code in ((RECALL, "QIH"), ("Z-9004-2026", "ZZZ")):
        db.upsert_external_source(
            record_id=f"fda_recall:{number}",
            source_type="fda_recall",
            source_id=number,
            product_code=code,
            title="Synthetic Stroke Triage software",
            authors="Example Medical",
            publication_date="2026-08-20",
            abstract=REASON,
            url=None,
            raw_payload={"res_event_number": "99001", "k_numbers": ["K990001"]},
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


def _group(ids: list[str], value: int | None = None) -> dict[str, Any]:
    return {
        "kind": "group_count",
        "product_code": "QIH",
        "label": "notification not sent",
        "report_ids": ids,
        "value": len(ids) if value is None else value,
        **WINDOW,
    }


def _quote(text: str, **attr: str) -> dict[str, Any]:
    return {"kind": "quote", "quote": text, "report_id": None, "source_id": None, **attr}


def _answer(*sentences: tuple[str, list[dict[str, Any]]]) -> str:
    return json.dumps({"sentences": [{"text": t, "claims": c} for t, c in sentences]})


QUOTE_REASON = REASON.rstrip(".")
GOOD = _answer(
    (
        f'Recall {RECALL} states "{QUOTE_REASON}".',
        [
            {"kind": "recall", "recall_number": RECALL, "product_code": "QIH"},
            _quote(QUOTE_REASON, source_id=RECALL),
        ],
    ),
    (
        "2 reports describe the same problem as the recall.",
        [_group([RID[0], RID[2]])],
    ),
    (
        'One of them says "Triage alert was not sent after a server update".',
        [_quote("Triage alert was not sent after a server update", report_id=RID[0])],
    ),
    ("A QA/RA reviewer should read these reports and decide.", []),
)


def _tool_round() -> Any:
    return _msg(
        tool_calls=[
            _call("recalls", {"product_code": "QIH"}, "c1"),
            _call("search_reports", {"product_code": "QIH", **WINDOW, "limit": 10}, "c2"),
            _call("draft_capa", {"product_code": "QIH"}, "c3"),
        ]
    )


def _run(tmp_path: Path, script: list[Any], rid: str = RECALL) -> tuple[Any, FakeClient]:
    client = FakeClient(script)
    return sweep(client, _ctx(tmp_path), rid), client


# ---------------------------------------------------------------- recall lookup


def test_find_recall_and_request_are_data_only(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path)
    recall = find_recall(ctx, RECALL.lower())
    assert recall.recall_number == RECALL and recall.product_code == "QIH"
    req = build_request(ctx, recall)
    assert req["task"] == "recall-sweep" and req["reason_for_recall"] == REASON
    assert req["window"] == WINDOW and req["k_numbers"] == ["K990001"]


def test_find_recall_errors(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path)
    with pytest.raises(InvestigationError, match="no stored recall"):
        find_recall(ctx, "Z-0000-2026")
    with pytest.raises(InvestigationError, match="names 2 recalls"):
        find_recall(ctx, "99001")  # the event number covers both synthetic recalls
    with pytest.raises(InvestigationError, match="not a watched device type"):
        find_recall(ctx, "Z-9004-2026")  # recall for a type with no stored reports


# ---------------------------------------------------------------- the loop


def test_sweep_gates_count_and_quotes(tmp_path: Path) -> None:
    res, client = _run(tmp_path, [_tool_round(), _msg(GOOD), _msg(GOOD)])
    rep = res.copilot.report
    assert rep.blocked == 0 and rep.passed == 4
    assert [g.to_dict() for g in res.groups] == [
        {"label": "notification not sent", "report_ids": [RID[0], RID[2]], "count": 2}
    ]
    offered = {t["function"]["name"] for t in client.calls[0]["tools"]}
    assert offered == ALLOWED_TOOLS and "draft_capa" not in offered
    assert "not available" in res.copilot.tool_calls[2].result_preview
    system = client.calls[0]["messages"][0]["content"]
    assert system.startswith("# Skill: recall-sweep")
    user = json.loads(client.calls[0]["messages"][1]["content"])
    assert user["recall_number"] == RECALL and user["window"] == WINDOW
    assert client.calls[0]["temperature"] == 0.0


def test_wrong_count_is_repaired_and_unrepaired_is_withheld(tmp_path: Path) -> None:
    bad = _answer(
        (
            "5 reports describe the same problem as the recall.",
            [_group([RID[0], RID[2]], value=5)],
        ),
        ("1 report describes the same problem.", [_group([RID[1]])]),
    )
    res, client = _run(tmp_path, [_msg(bad), _msg(bad), _msg(GOOD), _msg(GOOD)])
    assert res.copilot.first_pass_report.blocked == 1
    assert res.copilot.repaired and res.copilot.report.blocked == 0
    assert "recomputed=2.0" in client.calls[2]["messages"][-1]["content"]
    res2, _ = _run(tmp_path, [_msg(bad), _msg(bad), _msg(bad), _msg(bad)])
    assert res2.copilot.report.blocked == 1 and res2.copilot.report.passed == 1
    assert [g.report_ids for g in res2.groups] == [(RID[1],)]  # the 5-count group made none
    assert "5 reports describe" not in res2.copilot.answer


def test_quote_pinned_to_wrong_report_is_blocked(tmp_path: Path) -> None:
    bad = _answer(
        (
            'A report says "Triage alert was not sent after a server update".',
            [_quote("Triage alert was not sent after a server update", report_id=RID[1])],
        )
    )
    res, _ = _run(tmp_path, [_msg(bad), _msg(bad), _msg(bad), _msg(bad)])
    assert res.copilot.report.blocked == 1 and res.groups == []
    reasons = [r for s in res.copilot.report.sentences for r in s.reasons]
    assert any(RID[0] in r and "not" in r for r in reasons)


def test_unknown_recall_raises_before_any_model_call(tmp_path: Path) -> None:
    client = FakeClient([])
    with pytest.raises(InvestigationError):
        sweep(client, _ctx(tmp_path), "Z-0000-2026")
    assert client.calls == []


# ---------------------------------------------------------------- saved JSON


def test_saved_json_shape_matches_data_contract(tmp_path: Path) -> None:
    res, _ = _run(tmp_path, [_tool_round(), _msg(GOOD), _msg(GOOD)])
    path = save_sweep(res, tmp_path / "demo" / "investigations")
    assert path.name.endswith("-recall-qih.json") and path.name[8] == "T"
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
        "recall",
    ):
        assert key in d
    assert d["id"] == path.stem and d["kind"] == "recall-sweep"
    assert d["trigger"] == f"recall {RECALL} stored for QIH"
    assert d["skill_version"] == "1.0.0" and d["recorded_at_utc"].endswith("Z")
    assert d["recall"]["recall_number"] == RECALL and d["recall"]["reason_for_recall"] == REASON
    assert d["recall"]["link"].endswith(f'product_res_number:"{RECALL}"')
    g = d["groups"][0]
    assert (g["label"], g["report_ids"], g["count"]) == (
        "notification not sent",
        [RID[0], RID[2]],
        2,
    )
    assert len(g["links"]) == 2 and g["links"][0].endswith(f'report_number:"{RID[0]}"')
    s_group = d["sentences"][1]
    assert s_group["claims"][0]["reason"] == "recomputed 2 from 2 listed report ids"
    assert d["sentences"][2]["claims"][0]["reason"].startswith("verbatim match")
    assert d["tool_steps"][1] == {
        "name": "search_reports",
        "arguments": {"product_code": "QIH", **WINDOW, "limit": 10},
        "summary": "searched 3 reports",
    }
    assert [r["tool"] for r in d["protocol"]] == ["recalls", "search_reports"]
    assert [r.to_dict() for r in protocol_from_transcript(d)] == d["protocol"]
    assert d["usage"]["input_tokens"] == 300 and d == sweep_to_dict(res)


# ---------------------------------------------------------------- skill, CLI, workflow


def test_skill_folder_is_complete_and_examples_pass_the_gate() -> None:
    sk = SkillLoader(ROOT / "skills").load("recall-sweep")
    assert sk.version == "1.0.0" and "## Changelog" in sk.system_prompt
    assert sk.good_examples and sk.bad_examples
    branches = sk.output_schema["properties"]["sentences"]["items"]["properties"]["claims"][
        "items"
    ]["anyOf"]
    kinds = [b["properties"]["kind"]["enum"][0] for b in branches]
    assert "group_count" in kinds and len(kinds) == len(set(kinds))
    for b in branches:
        assert b["additionalProperties"] is False
        assert set(b["required"]) == set(b["properties"])
    from tests.unit.test_gate import STORE  # synthetic gate store

    for ex in sk.good_examples:
        pairs = [
            (s["text"], [claim_from_dict(c) for c in s["claims"]])
            for s in ex["expected_output"]["sentences"]
        ]
        assert verify_answer(pairs, STORE).blocked == 0


def test_cli_keyless_prints_needs_key(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv("META_MODEL_API_KEY", raising=False)
    r = CliRunner().invoke(app, ["recall-sweep", "--recall-id", RECALL, "--out-dir", str(tmp_path)])
    assert r.exit_code == 2
    assert "needs META_MODEL_API_KEY" in r.output
    assert list(tmp_path.iterdir()) == []


def test_workflow_runs_the_sweep_from_the_request_file() -> None:
    wf_path = ROOT / ".github/workflows/investigator-record.yml"
    wf = yaml.safe_load(wf_path.read_text())
    on = wf.get("on", wf.get(True))
    assert on["push"]["paths"] == ["demo/INVESTIGATE_REQUEST"]
    text = wf_path.read_text()
    assert "maudesignal.cli recall-sweep" in text and "recall_ids" in text
    assert "secrets.META_MODEL_API_KEY" in text
    assert "recall_ids:" in (ROOT / "demo/INVESTIGATE_REQUEST").read_text()
