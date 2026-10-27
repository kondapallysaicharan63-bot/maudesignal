"""Tests for the tool-using copilot, CAPA actions and audit chain (HACKATHON-BUILT).

The model is a scripted fake OpenAI-compatible client, so these tests make no
network calls and spend no credits.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from maudesignal.copilot.actions import ActionError, decide_capa, draft_capa
from maudesignal.copilot.agent import CopilotAgent, parse_answer
from maudesignal.copilot.meta_provider import MetaProvider
from maudesignal.copilot.tools import ToolContext, call_tool, deadline_check
from maudesignal.gate.loader import store_from_database
from maudesignal.storage.database import Database

RID = ["1111111-2026-00001", "1111111-2026-00002", "1111111-2026-00003"]


def _db(tmp_path: Path) -> Database:
    db = Database(tmp_path / "c.db")
    rows = [
        (RID[0], "20260825", "Malfunction", "Triage alert was not sent after a server update."),
        (RID[1], "20260826", "Malfunction", "Study failed to load; the app crashed on open."),
        (RID[2], "20260827", "Injury", "Delayed notification of a large vessel occlusion."),
    ]
    for rid, d, et, text in rows:
        db.upsert_raw_report(
            maude_report_id=rid,
            product_code="QIH",
            date_received=d,
            date_of_event=None,
            raw_payload={"report_number": rid},
        )
        db.upsert_normalized_event(
            maude_report_id=rid,
            product_code="QIH",
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


def _call(name: str, args: dict[str, Any], cid: str = "c1") -> Any:
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


def _answer(*sentences: tuple[str, list[dict[str, Any]]]) -> str:
    return json.dumps({"sentences": [{"text": t, "claims": c} for t, c in sentences]})


def test_tool_then_grounded_answer_passes(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path)
    client = FakeClient(
        [
            _msg(tool_calls=[_call("product_summary", {"product_code": "QIH"})]),
            _msg(
                _answer(
                    (
                        "QIH has 3 reports.",
                        [{"kind": "count", "product_code": "QIH", "value": 3}],
                    ),
                    ("A reviewer should confirm the failure mode.", []),
                )
            ),
        ]
    )
    res = CopilotAgent(client, ctx).ask("How many QIH reports?")
    assert res.report.blocked == 0 and res.report.passed == 2
    assert [t.name for t in res.tool_calls] == ["product_summary"]
    assert "QIH has 3 reports." in res.answer
    assert res.input_tokens == 200 and res.cost_usd > 0
    tool_msg = client.calls[1]["messages"][-1]
    assert tool_msg["role"] == "tool" and json.loads(tool_msg["content"])["report_count"] == 3
    assert client.calls[0]["temperature"] == 0.0 and client.calls[0]["tools"]


def test_blocked_claim_is_repaired(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path)
    client = FakeClient(
        [
            _msg(
                _answer(
                    ("QIH has 5 reports.", [{"kind": "count", "product_code": "QIH", "value": 5}])
                )
            ),
            _msg(
                _answer(
                    ("QIH has 3 reports.", [{"kind": "count", "product_code": "QIH", "value": 3}])
                )
            ),
        ]
    )
    res = CopilotAgent(client, ctx).ask("count?")
    assert res.first_pass_report.blocked == 1
    assert res.repaired and res.report.passed == 1 and res.sentences_repaired == 1
    repair_prompt = client.calls[1]["messages"][-1]["content"]
    assert repair_prompt.startswith("GATE BLOCKED") and "recomputed=3.0" in repair_prompt


def test_unrepaired_claim_is_withheld(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path)
    bad = _answer(("File under 21 CFR 820.100.", [{"kind": "regulation", "section": "820.100"}]))
    res = CopilotAgent(FakeClient([_msg(bad), _msg(bad)]), ctx).ask("which CFR?")
    assert res.report.blocked == 1
    assert "Withheld" in res.answer and "QMSR" in res.answer


def test_prose_answer_with_number_is_blocked(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path)
    prose = "There were 40 death reports last week."
    res = CopilotAgent(FakeClient([_msg(prose), _msg(prose), _msg(prose), _msg(prose)]), ctx).ask(
        "deaths?"
    )
    assert res.parse_failed and res.report.blocked == 1


def test_draft_capa_tool_and_human_approval(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path)
    client = FakeClient(
        [
            _msg(
                tool_calls=[
                    _call(
                        "draft_capa",
                        {
                            "product_code": "QIH",
                            "title": "Alert delivery after server update",
                            "problem_statement": "Two reports describe missed or delayed alerts.",
                            "report_ids": [RID[0], RID[2]],
                        },
                    )
                ]
            ),
            _msg(_answer(("A CAPA draft is awaiting your approval.", []))),
        ]
    )
    res = CopilotAgent(client, ctx).ask("Open a CAPA for the alert failures")
    assert len(res.capa_ids) == 1
    capa = ctx.db.get_capa_draft(res.capa_ids[0])
    assert capa is not None and capa.status == "draft"
    with pytest.raises(ActionError):
        decide_capa(ctx.db, capa_id=capa.capa_id, decision="approved", reviewer="copilot:x")
    done = decide_capa(ctx.db, capa_id=capa.capa_id, decision="approved", reviewer="J. Analyst")
    assert done.status == "approved" and done.decided_by == "J. Analyst"
    with pytest.raises(ActionError):
        decide_capa(ctx.db, capa_id=capa.capa_id, decision="rejected", reviewer="J. Analyst")
    actions = [a.action for a in ctx.db.list_audit()]
    assert actions == ["capa.draft", "copilot.answer", "capa.approved"]
    assert ctx.db.verify_audit_chain() == (True, None)


def test_audit_chain_detects_tampering(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path)
    draft_capa(
        ctx.db,
        product_code="QIH",
        title="t",
        problem_statement="p",
        report_ids=[RID[0]],
        actor="copilot:test",
    )
    ctx.db.append_audit(actor="a", action="x", entity_id="e", payload={"k": 1})
    from sqlalchemy import update

    from maudesignal.storage.models import ActionAuditRecord

    with ctx.db._session() as s:  # noqa: SLF001 - deliberate tamper for the test
        s.execute(update(ActionAuditRecord).where(ActionAuditRecord.seq == 1).values(actor="evil"))
        s.commit()
    assert ctx.db.verify_audit_chain() == (False, 1)


def test_draft_capa_rejects_unknown_reports(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path)
    out = call_tool(
        ctx,
        "draft_capa",
        json.dumps(
            {"product_code": "QIH", "title": "t", "problem_statement": "p", "report_ids": ["nope"]}
        ),
    )
    assert "error" in out and out["unknown"] == ["nope"]


def test_tools_return_errors_not_exceptions(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path)
    assert "error" in call_tool(ctx, "nope", "{}")
    assert "error" in call_tool(ctx, "get_report", "{}")
    assert "error" in call_tool(ctx, "get_report", json.dumps({"report_id": "x"}))
    assert call_tool(ctx, "get_report", json.dumps({"report_id": RID[1]}))["event_type"] == (
        "Malfunction"
    )
    found = call_tool(ctx, "search_reports", json.dumps({"keyword": "crashed"}))
    assert found["matched"] == 1 and found["reports"][0]["report_id"] == RID[1]
    sig = call_tool(ctx, "overnight_signals", "{}")
    assert sig["as_of"] == "20260827" and "headline" in sig


def test_deadline_check(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path)
    thirty = deadline_check(ctx, "20261001")
    assert thirty["due_date"] == "20261031" and thirty["regulation_section"] == "803.50"
    five = deadline_check(ctx, "20261030", five_day_trigger=True)  # a Friday
    assert five["due_date"] == "20261106" and five["regulation_section"] == "803.53"


def test_parse_answer_handles_fences_and_bad_claims() -> None:
    raw = '```json\n{"sentences":[{"text":"x","claims":[{"kind":"bogus"}]}]}\n```'
    ((text, claims),) = parse_answer(raw)
    assert text == "x" and claims[0].kind == "record"
    with pytest.raises(ValueError):
        parse_answer("no json here")


def test_contributor_models_refused(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        CopilotAgent(FakeClient([]), _ctx(tmp_path), model="muse-spark-1.3-contributor")


def test_meta_provider_cost_estimate() -> None:
    p = MetaProvider(api_key="test-not-a-key", model="muse-spark-1.3", base_url="http://x")
    assert p.estimate_cost_usd(1_000_000, 1_000_000) == pytest.approx(5.5)
    assert p.client is not None
