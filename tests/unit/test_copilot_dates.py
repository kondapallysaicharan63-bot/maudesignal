"""Copilot dates: today's date + stored data window in context, and the tool range guard.

HACKATHON-BUILT. Reproduces the live-site bug: "Why did reports for LLZ jump in the last week
of August?" made the model query 2025-08-25..2025-08-31 and answer "0 reports" although the
stored LLZ reports run 2026-07-01..2026-08-31. The model is a scripted fake: no network.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from maudesignal.connector.data import PROJECT_ROOT, ConnectorData
from maudesignal.copilot.agent import (
    DATE_CONTEXT_END,
    DATE_CONTEXT_START,
    CopilotAgent,
    date_context_template,
    split_prompts,
)
from maudesignal.copilot.dates import check_range, render_date_context, stored_window
from maudesignal.copilot.tools import (
    ToolContext,
    call_tool,
    product_summary,
    report_sources,
    search_reports,
)
from maudesignal.gate.loader import store_from_database
from maudesignal.storage.database import Database

QUESTION = "Why did reports for LLZ jump in the last week of August?"
SKILL_MD = PROJECT_ROOT / "skills" / "safety-copilot" / "SKILL.md"
# (report id, product code, date received): LLZ like the demo snapshot, 2026-07-01..2026-08-31.
ROWS = [
    ("LLZ-1", "LLZ", "20260701"),
    ("LLZ-2", "LLZ", "20260820"),
    ("LLZ-3", "LLZ", "20260825"),
    ("LLZ-4", "LLZ", "20260828"),
    ("LLZ-5", "LLZ", "20260831"),
    ("QIH-1", "QIH", "20240729"),
    ("QIH-2", "QIH", "20260702"),
]


def _ctx(tmp_path: Path, **kw: Any) -> ToolContext:
    db = Database(tmp_path / "d.db")
    for rid, code, d in ROWS:
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
            narrative=f"Report {rid}: the study did not load.",
            mfr_narrative=None,
            manufacturer="Acme",
            brand_name="Acme Viewer",
        )
    return ToolContext(db=db, store=store_from_database(db), **kw)


def _msg(content: str | None = None, tool_calls: list[Any] | None = None) -> Any:
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content, tool_calls=tool_calls))],
        usage=SimpleNamespace(prompt_tokens=100, completion_tokens=50),
    )


def _call(name: str, args: dict[str, Any]) -> Any:
    return SimpleNamespace(id="c1", function=SimpleNamespace(name=name, arguments=json.dumps(args)))


class FakeClient:
    """Scripted OpenAI-compatible client."""

    def __init__(self, script: list[Any]) -> None:
        self.script = list(script)
        self.calls: list[dict[str, Any]] = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kwargs: Any) -> Any:
        self.calls.append({**kwargs, "messages": list(kwargs["messages"])})
        return self.script.pop(0)


# --- the tool-layer guard ---------------------------------------------------------------


def test_last_week_of_august_2025_is_moved_to_the_data_year(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path)
    out = product_summary(ctx, "LLZ", "20250825", "20250831")
    assert out["date_adjusted"] is True
    assert (out["date_from"], out["date_to"]) == ("20260825", "20260831")
    assert (out["requested_date_from"], out["requested_date_to"]) == ("20250825", "20250831")
    assert out["report_count"] == 3  # not 0
    assert out["data_covers"] == {"date_from": "20260701", "date_to": "20260831"}
    assert "2026-08-25 to 2026-08-31" in out["date_note"]


def test_guard_runs_through_call_tool_like_the_model(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path)
    args = {"product_code": "llz", "date_from": "20250825", "date_to": "20250831"}
    out = call_tool(ctx, "product_summary", json.dumps(args))
    assert out["report_count"] == 3 and out["date_adjusted"] is True


def test_range_with_no_data_in_any_year_is_flagged_not_zero(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path)
    out = product_summary(ctx, "LLZ", "20260101", "20260131")
    assert out["no_data_for_range"] is True
    assert "report_count" not in out  # nothing a "0 reports" claim could be read from
    assert out["data_covers"] == {"date_from": "20260701", "date_to": "20260831"}
    assert "do not report it as 0 reports" in out["date_note"]


def test_range_inside_or_overlapping_the_data_is_unchanged(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path)
    inside = product_summary(ctx, "LLZ", "20260825", "20260831")
    assert inside["report_count"] == 3 and "date_note" not in inside
    overlap = product_summary(ctx, "LLZ", "20260821", "20260915")
    assert overlap["report_count"] == 3 and "date_adjusted" not in overlap
    assert "date_note" not in product_summary(ctx, "LLZ")


def test_open_ended_range_after_the_data_is_flagged(tmp_path: Path) -> None:
    check = check_range(_ctx(tmp_path).store, "LLZ", "20261001", None)
    assert check.no_data and check.window is not None and check.window.latest == "20260831"


def test_per_code_window_is_used_not_the_whole_store(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path)
    # QIH has a 2024 report, so the whole store overlaps 2025-08; LLZ alone does not.
    assert stored_window(ctx.store) is not None
    assert check_range(ctx.store, "LLZ", "20250825", "20250831").adjusted
    qih = check_range(ctx.store, "QIH", "20250825", "20250831")
    assert not qih.adjusted and not qih.no_data  # inside QIH's 2024..2026 window


def test_search_reports_and_report_sources_use_the_guard(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path)
    found = search_reports(ctx, product_code="LLZ", date_from="20250825", date_to="20250831")
    assert found["matched"] == 3 and found["date_adjusted"] is True
    assert {r["report_id"] for r in found["reports"]} == {"LLZ-3", "LLZ-4", "LLZ-5"}
    src = report_sources(ctx, "LLZ", "20250825", "20250831")
    assert src["report_count"] == 3 and src["date_adjusted"] is True
    none = search_reports(ctx, product_code="LLZ", date_from="20260101", date_to="20260131")
    assert none["no_data_for_range"] is True and none["reports"] == []


# --- the date context ------------------------------------------------------------------


def test_skill_has_a_date_context_template_removed_from_both_prompts() -> None:
    text = SKILL_MD.read_text(encoding="utf-8")
    tpl = date_context_template(text)
    assert tpl and "{today}" in tpl and "{code_windows}" in tpl and "{sweep}" in tpl
    full, compact = split_prompts(text)
    assert compact is not None
    for prompt in (full, compact):
        assert DATE_CONTEXT_START not in prompt and DATE_CONTEXT_END not in prompt
        assert "{today}" not in prompt


def test_render_fills_today_window_codes_and_sweep(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path)
    tpl = date_context_template(SKILL_MD.read_text(encoding="utf-8")) or ""
    sweep = {"current_start": "2026-09-24", "current_end": "2026-09-30", "run_date": "2026-10-30"}
    out = render_date_context(tpl, ctx.store, today=date(2026, 11, 1), sweep_window=sweep)
    assert "Today (UTC): 2026-11-01" in out
    assert "2024-07-29 to 2026-08-31" in out
    assert "LLZ 2026-07-01 to 2026-08-31 (5 reports)" in out
    assert "openFDA week 2026-09-24 to 2026-09-30, run on 2026-10-30" in out
    assert "{" not in out


def test_exact_question_context_and_corrected_range(tmp_path: Path) -> None:
    """The live-site question end to end with a fake model that guesses 2025."""
    ctx = _ctx(
        tmp_path,
        today=date(2026, 11, 1),
        sweep_window={"current_start": "2026-09-24", "current_end": "2026-09-30"},
    )
    answer = json.dumps(
        {
            "sentences": [
                {
                    "text": "LLZ received 3 reports from 2026-08-25 to 2026-08-31.",
                    "claims": [
                        {
                            "kind": "count",
                            "product_code": "LLZ",
                            "value": 3,
                            "event_type": None,
                            "date_from": "20260825",
                            "date_to": "20260831",
                        }
                    ],
                }
            ]
        }
    )
    guess = {"product_code": "LLZ", "date_from": "20250825", "date_to": "20250831"}
    client = FakeClient(
        [_msg(tool_calls=[_call("product_summary", guess)]), _msg(answer), _msg(answer)]
    )
    agent = CopilotAgent(client, ctx)
    res = agent.ask(QUESTION)
    system = client.calls[0]["messages"][0]["content"]
    assert system.startswith(agent.system_prompt)
    assert "Today (UTC): 2026-11-01" in system
    assert "LLZ 2026-07-01 to 2026-08-31" in system
    assert "openFDA week 2026-09-24 to 2026-09-30" in system
    tool_result = json.loads(client.calls[1]["messages"][-1]["content"])
    assert tool_result["date_from"] == "20260825" and tool_result["report_count"] == 3
    assert res.report.passed == 1 and res.report.blocked == 0


def test_lean_prompt_also_gets_the_date_context(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path, today=date(2026, 11, 1))
    client = FakeClient([_msg('{"sentences": []}'), _msg('{"sentences": []}')])
    agent = CopilotAgent(client, ctx)
    agent.configure_lean(
        reasoning_effort="low", max_tool_rounds=2, max_tokens=3000, max_tool_result_chars=6000
    )
    agent.ask(QUESTION)
    system = client.calls[0]["messages"][0]["content"]
    _full, compact = split_prompts(SKILL_MD.read_text(encoding="utf-8"))
    assert compact and system.startswith(compact)
    assert "Today (UTC): 2026-11-01" in system and len(system) < 3500


def test_demo_snapshot_resolves_the_question_to_2026(tmp_path: Path) -> None:
    """Against the committed demo data: LLZ ends 2026-08-31, the sweep week is Sep 24-30."""
    data = ConnectorData(work_dir=tmp_path / "w")
    ctx = data.tool_context()
    assert ctx.sweep_window is not None
    assert ctx.sweep_window["current_start"] == "2026-09-24"
    assert ctx.sweep_window["current_end"] == "2026-09-30"
    out = product_summary(ctx, "LLZ", "20250825", "20250831")
    assert out["date_from"] == "20260825" and out["report_count"] == 33
