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


def _final(content: str) -> list[Any]:
    """A tool-free draft turn followed by the schema-constrained final-answer call."""
    return [_msg(content), _msg(content)]


def test_tool_then_grounded_answer_passes(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path)
    answer = _answer(
        ("QIH has 3 reports.", [{"kind": "count", "product_code": "QIH", "value": 3}]),
        ("A reviewer should confirm the failure mode.", []),
    )
    client = FakeClient(
        [_msg(tool_calls=[_call("product_summary", {"product_code": "QIH"})]), *_final(answer)]
    )
    res = CopilotAgent(client, ctx).ask("How many QIH reports?")
    assert res.report.blocked == 0 and res.report.passed == 2
    assert [t.name for t in res.tool_calls] == ["product_summary"]
    assert "QIH has 3 reports." in res.answer
    assert res.input_tokens == 300 and res.cost_usd > 0
    tool_msg = client.calls[1]["messages"][-1]
    assert tool_msg["role"] == "tool" and json.loads(tool_msg["content"])["report_count"] == 3
    assert client.calls[0]["temperature"] == 0.0 and client.calls[0]["tools"]


def test_blocked_claim_is_repaired(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path)
    five = _answer(("QIH has 5 reports.", [{"kind": "count", "product_code": "QIH", "value": 5}]))
    three = _answer(("QIH has 3 reports.", [{"kind": "count", "product_code": "QIH", "value": 3}]))
    client = FakeClient([*_final(five), *_final(three)])
    res = CopilotAgent(client, ctx).ask("count?")
    assert res.first_pass_report.blocked == 1
    assert res.repaired and res.report.passed == 1 and res.sentences_repaired == 1
    repair_prompt = client.calls[2]["messages"][-1]["content"]
    assert repair_prompt.startswith("GATE BLOCKED") and "recomputed=3.0" in repair_prompt


def test_unrepaired_claim_is_withheld(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path)
    bad = _answer(("File under 21 CFR 820.100.", [{"kind": "regulation", "section": "820.100"}]))
    res = CopilotAgent(FakeClient([*_final(bad), *_final(bad)]), ctx).ask("which CFR?")
    assert res.report.blocked == 1
    assert "Withheld" in res.answer and "QMSR" in res.answer


def test_prose_answer_with_number_is_blocked(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path)
    prose = "There were 40 death reports last week."
    res = CopilotAgent(FakeClient([_msg(prose) for _ in range(6)]), ctx).ask("deaths?")
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
            *_final(_answer(("A CAPA-need evidence pack is awaiting your approval.", []))),
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


def test_transcript_roundtrip(tmp_path: Path) -> None:
    from maudesignal.copilot.transcript import load_transcripts, save_transcript

    ctx = _ctx(tmp_path)
    bad = _answer(("QIH has 9 reports.", [{"kind": "count", "product_code": "QIH", "value": 9}]))
    good = _answer(("QIH has 3 reports.", [{"kind": "count", "product_code": "QIH", "value": 3}]))
    res = CopilotAgent(FakeClient([*_final(bad), *_final(good)]), ctx).ask("count?")
    out = tmp_path / "tx"
    save_transcript(res, out, label="02-b")
    save_transcript(res, out, label="01-a")
    (out / "junk.json").write_text("not json")
    loaded = load_transcripts(out)
    assert [t["label"] for t in loaded] == ["01-a", "02-b"]
    t = loaded[0]
    assert t["first_pass"]["blocked"] == 1 and t["final"]["passed"] == 1 and t["repaired"]
    assert t["final"]["sentences"][0]["claims"][0]["evidence_ids"]
    assert load_transcripts(tmp_path / "missing") == []


def test_sentence_html_marks_withheld() -> None:
    from maudesignal.dashboard.copilot_pages import _evidence_links, _sentence_html

    blocked = _sentence_html({"text": "x <b>", "status": "block", "reasons": ["count: no"]})
    assert "Withheld" in blocked and "&lt;b&gt;" in blocked and "count: no" in blocked
    assert "Verified" in _sentence_html({"text": "ok", "status": "pass"})
    s = {"claims": [{"evidence_ids": ["50426770", "21 CFR 803.50"]}]}
    assert "50426770" in _evidence_links(s) and "CFR" not in _evidence_links(s)
    mixed = _evidence_links(
        {"claims": [{"evidence_ids": ["PMID 38269880", "K192176", "Z-0186-2027"]}]}
    )
    assert "pubmed.ncbi.nlm.nih.gov/38269880" in mixed and "pmn.cfm?ID=K192176" in mixed
    assert "Z-0186-2027" in mixed and "mdrfoi__id=Z" not in mixed


# ---------------------------------------------------------------------------
# F2 — guaranteed structured final answers (Meta json_schema response_format)
# ---------------------------------------------------------------------------


def _skill_schema() -> dict[str, Any]:
    from maudesignal.copilot.agent import SKILL_NAME, default_skills_root
    from maudesignal.extraction.skill_loader import SkillLoader

    return SkillLoader(default_skills_root()).load(SKILL_NAME).output_schema


def test_final_answer_call_uses_json_schema_and_no_tools(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path)
    good = _answer(("QIH has 3 reports.", [{"kind": "count", "product_code": "QIH", "value": 3}]))
    client = FakeClient(
        [_msg(tool_calls=[_call("product_summary", {"product_code": "QIH"})]), *_final(good)]
    )
    agent = CopilotAgent(client, ctx)
    res = agent.ask("How many QIH reports?")
    assert res.report.passed == 1
    tool_rounds, final = client.calls[:2], client.calls[2]
    for c in tool_rounds:
        assert c["tools"] and c["tool_choice"] == "auto" and "response_format" not in c
    assert "tools" not in final and "tool_choice" not in final
    rf = final["response_format"]
    assert rf == agent.response_format
    assert rf["type"] == "json_schema"
    assert rf["json_schema"]["name"] == "safety_copilot_answer"
    assert rf["json_schema"]["strict"] is True
    sent = rf["json_schema"]["schema"]
    assert "$schema" not in sent and "title" not in sent
    assert sent["properties"] == _skill_schema()["properties"]
    assert "reasoning_effort" not in final  # default None: parameter omitted
    audit = ctx.db.list_audit()[-1]
    assert json.loads(audit.payload_json)["structured_output"] is True


def test_repair_and_retry_calls_are_schema_constrained(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path)
    five = _answer(("QIH has 5 reports.", [{"kind": "count", "product_code": "QIH", "value": 5}]))
    three = _answer(("QIH has 3 reports.", [{"kind": "count", "product_code": "QIH", "value": 3}]))
    client = FakeClient([_msg("draft"), _msg("not json"), _msg(five), *_final(three)])
    res = CopilotAgent(client, ctx).ask("count?")
    assert res.repaired and res.report.passed == 1
    kinds = ["rf" if "response_format" in c else "tools" for c in client.calls]
    # tool round, final, parse-retry, repair tool round, repair final
    assert kinds == ["tools", "rf", "rf", "tools", "rf"]


def test_structured_output_flag_off_keeps_legacy_path(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path)
    good = _answer(("QIH has 3 reports.", [{"kind": "count", "product_code": "QIH", "value": 3}]))
    client = FakeClient([_msg(good)])
    res = CopilotAgent(client, ctx, structured_output=False).ask("count?")
    assert res.report.passed == 1 and len(client.calls) == 1
    assert all("response_format" not in c for c in client.calls)


def test_tool_budget_exhausted_final_call_is_structured(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path)
    loop = _msg(tool_calls=[_call("product_summary", {"product_code": "QIH"})])
    good = _answer(("QIH has 3 reports.", [{"kind": "count", "product_code": "QIH", "value": 3}]))
    client = FakeClient([loop, loop, _msg(good)])
    res = CopilotAgent(client, ctx, max_tool_rounds=2).ask("count?")
    assert res.report.passed == 1
    assert "response_format" in client.calls[-1] and "tools" not in client.calls[-1]


def test_reasoning_effort_passthrough(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path)
    good = _answer(("No facts here.", []))
    client = FakeClient(_final(good))
    CopilotAgent(client, ctx, reasoning_effort="high").ask("hi")
    assert [c["reasoning_effort"] for c in client.calls] == ["high", "high"]
    with pytest.raises(ValueError):
        CopilotAgent(FakeClient([]), ctx, reasoning_effort="none")


def _walk_objects(node: Any, path: str = "$") -> list[tuple[str, dict[str, Any]]]:
    out: list[tuple[str, dict[str, Any]]] = []
    if isinstance(node, dict):
        if node.get("type") == "object":
            out.append((path, node))
        for k, v in node.items():
            out += _walk_objects(v, f"{path}.{k}")
    elif isinstance(node, list):
        for i, v in enumerate(node):
            out += _walk_objects(v, f"{path}[{i}]")
    return out


def _depth(node: Any) -> int:
    if isinstance(node, dict):
        inner = [_depth(v) for v in node.values()]
        return (1 if node.get("type") in ("object", "array") else 0) + max(inner, default=0)
    if isinstance(node, list):
        return max((_depth(v) for v in node), default=0)
    return 0


def test_output_schema_is_strict_mode_compatible() -> None:
    import jsonschema

    schema = _skill_schema()
    jsonschema.Draft202012Validator.check_schema(schema)
    assert schema["type"] == "object"
    for key in ("anyOf", "oneOf", "allOf", "enum", "not"):
        assert key not in schema, f"root must be a plain object (found {key})"
    objects = _walk_objects(schema)
    assert len(objects) >= 12  # root, sentence, 10 claim kinds
    for path, obj in objects:
        assert obj.get("additionalProperties") is False, path
        assert sorted(obj.get("required", [])) == sorted(obj["properties"]), path
    text = json.dumps(schema)
    assert '"oneOf"' not in text and '"allOf"' not in text
    assert _depth(schema) <= 10
    branches = schema["properties"]["sentences"]["items"]["properties"]["claims"]["items"]["anyOf"]
    kinds = {b["properties"]["kind"]["enum"][0] for b in branches}
    assert kinds == {
        "quote",
        "count",
        "share",
        "device",
        "record",
        "regulation",
        "recall",
        "recall_count",
        "literature",
        "source_count",
    }


def test_strict_schema_answers_parse_and_examples_validate() -> None:
    import jsonschema

    from maudesignal.copilot.agent import SKILL_NAME, default_skills_root
    from maudesignal.extraction.skill_loader import SkillLoader

    skill = SkillLoader(default_skills_root()).load(SKILL_NAME)
    for ex in skill.good_examples:
        jsonschema.validate(ex["expected_output"], skill.output_schema)
        for _, claims in parse_answer(json.dumps(ex["expected_output"])):
            assert all(getattr(c, "report_id", None) != "<malformed>" for c in claims)
    bad = {"sentences": [{"text": "x", "claims": [{"kind": "count", "value": 1}]}]}
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(bad, skill.output_schema)


def test_good_examples_pass_the_gate_on_the_demo_db(tmp_path: Path) -> None:
    """The Skill's good examples cite real demo-DB records; the gate must pass all of them."""
    import shutil

    from maudesignal.copilot.agent import SKILL_NAME, default_skills_root
    from maudesignal.extraction.skill_loader import SkillLoader
    from maudesignal.gate import verify_answer

    demo = Path(__file__).resolve().parents[2] / "data" / "demo" / "maudesignal_demo.db"
    copy = tmp_path / "demo.db"  # never touch the committed file
    shutil.copy(demo, copy)
    store = store_from_database(Database(copy))
    assert store.recalls and store.clearances and store.literature
    skill = SkillLoader(default_skills_root()).load(SKILL_NAME)
    for ex in skill.good_examples:
        report = verify_answer(parse_answer(json.dumps(ex["expected_output"])), store)
        assert report.blocked == 0, [s.reasons for s in report.sentences]


# ---------------------------------------------------------------------------
# F5 — scattered-source tools (recalls, 510(k), literature) over stored data
# ---------------------------------------------------------------------------


def _add_sources(db: Database) -> None:
    db.upsert_external_source(
        record_id="rc1",
        source_type="fda_recall",
        source_id="Z-0001-2026",
        product_code="QIH",
        title="Acme Triage v2",
        authors="Acme",
        publication_date="2026-09-05",
        abstract="Notifications may not be sent when the worklist exceeds 200 studies.",
        url=None,
        raw_payload={"res_event_number": "99001", "k_numbers": ["K990777"], "recall_status": "O"},
    )
    db.upsert_external_source(
        record_id="rc2",
        source_type="fda_recall",
        source_id="Z-0002-2021",
        product_code="QIH",
        title="Acme Triage v1",
        authors="Acme",
        publication_date="2021-01-05",
        abstract="Old issue.",
        url=None,
        raw_payload={},
    )
    db.upsert_external_source(
        record_id="k1",
        source_type="fda_510k",
        source_id="K990777",
        product_code="QIH",
        title="Acme Triage",
        authors="Acme Inc.",
        publication_date="2024-03-01",
        abstract=None,
        url=None,
        raw_payload={"decision_code": "SESE", "statement_or_summary": "Summary"},
    )
    db.upsert_external_source(
        record_id="p1",
        source_type="pubmed",
        source_id="90000001",
        product_code="QIH",
        title="AI triage notification failures.",
        authors=None,
        publication_date="2024 Mar",
        abstract="Missed notifications clustered after server updates.",
        url=None,
        raw_payload={"source": "J Synth"},
    )


def _src_ctx(tmp_path: Path) -> ToolContext:
    db = _db(tmp_path)
    _add_sources(db)
    return ToolContext(db=db, store=store_from_database(db))


def test_recalls_tool(tmp_path: Path) -> None:
    ctx = _src_ctx(tmp_path)
    out = call_tool(ctx, "recalls", json.dumps({"product_code": "QIH"}))
    assert out["stored_recall_count"] == 2
    assert [r["recall_number"] for r in out["recalls"]] == ["Z-0001-2026", "Z-0002-2021"]
    assert out["recalls"][0]["k_numbers"] == ["K990777"]
    dated = call_tool(
        ctx, "recalls", json.dumps({"product_code": "QIH", "date_from": "20260101", "limit": 1})
    )
    assert dated["stored_recall_count"] == 1
    assert call_tool(ctx, "recalls", json.dumps({"product_code": "LLZ"}))["recalls"] == []


def test_device_510k_tool(tmp_path: Path) -> None:
    ctx = _src_ctx(tmp_path)
    out = call_tool(ctx, "device_510k", json.dumps({"k_number": "k990777"}))
    assert out["applicant"] == "Acme Inc." and out["decision_date"] == "2024-03-01"
    assert out["source"].startswith("openFDA") and out["decision_code"] == "SESE"
    assert out["recalls_citing_this_k_number"] == ["Z-0001-2026"]
    assert "error" in call_tool(ctx, "device_510k", json.dumps({"k_number": "K000000"}))


def test_literature_tool(tmp_path: Path) -> None:
    ctx = _src_ctx(tmp_path)
    out = call_tool(ctx, "literature", json.dumps({"product_code": "QIH"}))
    (art,) = out["articles"]
    assert art["pmid"] == "90000001" and art["year"] == 2024 and art["journal"] == "J Synth"
    assert "server updates" in art["abstract_excerpt"]
    assert call_tool(ctx, "literature", json.dumps({"query": "server MISSED"}))["matched"] == 1
    assert call_tool(ctx, "literature", json.dumps({"query": "pacemaker"}))["matched"] == 0
    assert call_tool(ctx, "literature", json.dumps({"product_code": "LLZ"}))["matched"] == 0


def test_new_tool_schemas_registered() -> None:
    from maudesignal.copilot.tools import TOOL_SCHEMAS, TOOLS

    names = [t["function"]["name"] for t in TOOL_SCHEMAS]
    assert names == list(TOOLS)
    assert {"recalls", "device_510k", "literature"} <= set(names)


def test_agent_cross_source_answer_is_gated(tmp_path: Path) -> None:
    ctx = _src_ctx(tmp_path)
    answer = _answer(
        (
            "QIH has 2 recalls; Z-0001-2026 cites K990777.",
            [
                {"kind": "recall_count", "product_code": "QIH", "value": 2},
                {"kind": "recall", "recall_number": "Z-0001-2026", "product_code": "QIH"},
                {"kind": "device", "k_number": "K990777", "product_code": "QIH"},
            ],
        ),
        (
            'PMID 90000001 reports "missed notifications clustered after server updates".',
            [
                {"kind": "literature", "pmid": "90000001", "year": 2024},
                {
                    "kind": "quote",
                    "quote": "missed notifications clustered after server updates",
                    "report_id": None,
                    "source_id": "90000001",
                },
            ],
        ),
        (
            "PMID 90000002 says otherwise.",
            [{"kind": "literature", "pmid": "90000002", "year": None}],
        ),
    )
    client = FakeClient(
        [
            _msg(
                tool_calls=[
                    _call("recalls", {"product_code": "QIH"}, "c1"),
                    _call("literature", {"product_code": "QIH"}, "c2"),
                ]
            ),
            *_final(answer),
            *_final(answer),  # repair turn repeats itself; the fake PMID stays withheld
        ]
    )
    res = CopilotAgent(client, ctx).ask("Anything on QIH beyond MAUDE?")
    assert [t.name for t in res.tool_calls] == ["recalls", "literature"]
    assert res.report.passed == 2 and res.report.blocked == 1
    assert "90000002" in res.answer and "Withheld" in res.answer


# ---------------------------------------------------------------------------
# Regressions from the 2026-10-28 live recording
# ---------------------------------------------------------------------------


def _cut(content: str = "") -> Any:
    """A final-answer response stopped by max_tokens."""
    m = _msg(content)
    m.choices[0].finish_reason = "length"
    return m


def test_empty_or_unparsed_reply_is_withheld_not_passed(tmp_path: Path) -> None:
    # 8 recorded answers were an empty string counted as 1/1 passed.
    ctx = _ctx(tmp_path)
    script = [_msg(""), _cut(""), _cut(""), _msg(""), _cut(""), _cut("")]
    res = CopilotAgent(FakeClient(script), ctx).ask("what came in overnight?")
    assert res.parse_failed
    assert (res.report.passed, res.report.blocked) == (0, 1)
    assert res.first_pass_report.blocked == 1
    assert "did not return a structured answer" in res.answer
    assert res.length_stops == 4


def test_claims_hidden_in_json_looking_text_are_not_passed(tmp_path: Path) -> None:
    # Recorded answers 02 and 19 showed raw JSON text whose count claims were never checked.
    ctx = _ctx(tmp_path)
    leaked = '{"sentences": [{"claims": [{"kind": "count", "value": 99}], "text": "x"'
    res = CopilotAgent(FakeClient([_msg(leaked) for _ in range(6)]), ctx).ask("why first?")
    assert res.parse_failed and res.report.passed == 0 and res.report.blocked == 1


def test_unparsed_first_reply_gets_a_repair_turn(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path)
    good = _answer(("Human review is required.", []))
    script = [_msg(""), _msg(""), _msg(""), *_final(good)]
    res = CopilotAgent(FakeClient(script), ctx).ask("summary?")
    assert res.repaired and not res.parse_failed
    assert (res.report.passed, res.report.blocked) == (1, 0)
    assert res.first_pass_report.blocked == 1


def test_overnight_as_of_after_the_data_uses_latest_stored_date(tmp_path: Path) -> None:
    # The model asked for the week ending "today" (20261028) and reported 0 reports.
    ctx = _ctx(tmp_path)
    default = call_tool(ctx, "overnight_signals", "{}")
    future = call_tool(ctx, "overnight_signals", json.dumps({"as_of": "20991231"}))
    assert future["as_of"] == default["as_of"]
    assert future["current_window"] == default["current_window"]
    assert "after the latest stored report" in future["note"]
    assert "note" not in default
