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

import pytest

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
from maudesignal.gate import (
    CountClaim,
    GroupCountClaim,
    RecordClaim,
    ShareClaim,
    SourceCountClaim,
    claim_from_dict,
    verify_answer,
    verify_sentence,
)
from maudesignal.gate.claims import normalize_ymd
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


# --- review fixes: the real demo store, the gate, ISO dates, recalls -----------------------


def _demo_ctx(tmp_path: Path) -> ToolContext:
    return ConnectorData(work_dir=tmp_path / "w").tool_context()


def _recalls(ctx: ToolContext, **args: str) -> dict[str, Any]:
    return call_tool(ctx, "recalls", json.dumps(args))


def test_real_demo_store_never_moves_a_year_the_data_covers(tmp_path: Path) -> None:
    """QIH runs 2024-07-29..2026-07-02 and MYN ..2025-03-13 in the demo store."""
    ctx = _demo_ctx(tmp_path)
    w = stored_window(ctx.store, "QIH")
    assert w is not None and (w.earliest, w.latest) == ("20240729", "20260702")
    # "last week" as of today (2026-11-01): a year the data covers, but after its last report
    qih = product_summary(ctx, "QIH", "20261020", "20261026")
    assert qih["no_data_for_range"] is True and "date_adjusted" not in qih
    assert "report_count" not in qih
    assert "No stored QIH report is dated in 2026-10-20 to 2026-10-26" in qih["date_note"]
    assert "the stored QIH reports run 2024-07-29 to 2026-07-02" in qih["date_note"]
    # a real 2026 week inside the overall window is never moved to 2025
    # (QIH's last report is 2026-07-02, so that week is empty: said so, not shifted to 2025)
    assert not check_range(ctx.store, "QIH", "20260801", "20260807").adjusted
    after = product_summary(ctx, "QIH", "20260801", "20260807")
    assert after["no_data_for_range"] is True and "date_adjusted" not in after
    assert product_summary(ctx, "QIH", "20260101", "20260131")["report_count"] == 0
    # MYN stops in 2025: 2026 is not a covered year and the shifted 2025 week is still empty
    myn = product_summary(ctx, "MYN", "20261020", "20261026")
    assert myn["no_data_for_range"] is True and "date_adjusted" not in myn
    assert ctx.date_shifts == []  # nothing was moved, so the gate has nothing to check


def test_year_boundary_note_names_the_new_range_only(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path)
    qih = check_range(ctx.store, "QIH", "20261228", "20270103")
    assert qih.no_data and not qih.adjusted  # 2026 is covered: never moved
    # a year-crossing request never lands fully inside the data after a +1 year move: not moved
    assert check_range(ctx.store, "LLZ", "20251228", "20260103").no_data
    moved = check_range(ctx.store, "LLZ", "20250825", "20250831")
    assert moved.adjusted and moved.note is not None
    assert "2026-08-25 to 2026-08-31" in moved.note and "2025-08-25 to 2025-08-31" in moved.note


def test_unscoped_note_says_stored_reports(tmp_path: Path) -> None:
    out = product_summary(_ctx(tmp_path), "ZZZ", "20270101", "20270131")
    assert out["no_data_for_range"] is True
    assert "stored ZZZ" not in out["date_note"] and "stored report" in out["date_note"]


def test_iso_dates_are_normalised(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path)
    out = product_summary(ctx, "LLZ", "2026-08-25", "2026-08-31")
    assert out["report_count"] == 3 and "no_data_for_range" not in out
    assert (out["date_from"], out["date_to"]) == ("20260825", "20260831")
    moved = product_summary(ctx, "LLZ", "2025-08-25", "2025-08-31")
    assert moved["report_count"] == 3 and moved["date_adjusted"] is True


def test_recall_dates_use_the_guard_only_outside_their_years(tmp_path: Path) -> None:
    ctx = _demo_ctx(tmp_path)
    old = _recalls(ctx, product_code="LLZ", date_from="20190101", date_to="20191231")
    assert "date_note" not in old  # LLZ recalls run 2002..2026: untouched
    myn = _recalls(ctx, product_code="MYN", date_from="20260101", date_to="20260131")
    assert myn["no_data_for_range"] is True and "stored_recall_count" not in myn
    assert "stored MYN recalls run 2006-05-04 to 2015-04-06" in myn["date_note"]
    none = _recalls(ctx, product_code="ZZZ", date_from="20260101")
    assert "date_note" not in none  # no stored recall window for the code: left alone


def test_compare_signals_as_of_after_the_data_uses_the_latest_week(tmp_path: Path) -> None:
    ctx = _demo_ctx(tmp_path)
    args = {"product_codes": ["LLZ"], "as_of": "20261030"}
    out = call_tool(ctx, "compare_signals", json.dumps(args))
    assert "after the latest stored report" in out["note"]


# --- the gate sees a moved range -----------------------------------------------------------


def _count(code: str, n: int, frm: str | None, to: str | None) -> CountClaim:
    return CountClaim(code, n, None, frm, to)


def test_gate_blocks_a_sentence_naming_the_requested_year(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path)
    product_summary(ctx, "LLZ", "20250825", "20250831")
    shifts = tuple(ctx.date_shifts)
    assert len(shifts) == 1 and shifts[0].used_label == "2026-08-25 to 2026-08-31"
    claim = _count("LLZ", 3, "20260825", "20260831")
    text = "LLZ had 3 reports in the last week of August 2025."
    assert verify_sentence(text, [claim], ctx.store).status == "pass"  # blind without shifts
    v = verify_sentence(text, [claim], ctx.store, shifts)
    assert v.status == "block" and "names 2025" in " ".join(v.reasons)


def test_gate_adds_dates_used_to_a_sentence_without_a_year(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path)
    product_summary(ctx, "LLZ", "20250825", "20250831")
    shifts = tuple(ctx.date_shifts)
    claim = _count("LLZ", 3, "20260825", "20260831")
    v = verify_sentence("LLZ had 3 reports in the last week of August.", [claim], ctx.store, shifts)
    assert v.status == "pass"
    assert v.text.endswith("(Dates used: 2026-08-25 to 2026-08-31.)")
    # a sentence that names the used year is shown as written
    ok = verify_sentence("LLZ had 3 reports on Aug 25-31, 2026.", [claim], ctx.store, shifts)
    assert ok.status == "pass" and "Dates used" not in ok.text
    # a claim on other dates is not touched
    other = verify_sentence("LLZ had 5 reports.", [_count("LLZ", 5, None, None)], ctx.store, shifts)
    assert other.status == "pass" and "Dates used" not in other.text


def test_agent_answer_carries_the_dates_used(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path, today=date(2026, 11, 1))
    claim = {
        "kind": "count",
        "product_code": "LLZ",
        "value": 3,
        "event_type": None,
        "date_from": "20260825",
        "date_to": "20260831",
    }
    sentence = {"text": "LLZ had 3 reports in the last week of August.", "claims": [claim]}
    answer = json.dumps({"sentences": [sentence]})
    guess = {"product_code": "LLZ", "date_from": "20250825", "date_to": "20250831"}
    script = [_msg(tool_calls=[_call("product_summary", guess)]), _msg(answer), _msg(answer)]
    res = CopilotAgent(FakeClient(script), ctx).ask(QUESTION)
    assert res.report.blocked == 0
    assert "(Dates used: 2026-08-25 to 2026-08-31.)" in res.answer
    assert len(ctx.date_shifts) == 1
    # the next question starts with no shifts
    CopilotAgent(FakeClient([_msg(answer), _msg(answer)]), ctx).ask("again")
    assert ctx.date_shifts == []


# --- round 2 review: several moved ranges, group counts, +1 year only, false zeros ----------


def _moved_ctx(tmp_path: Path) -> ToolContext:
    ctx = _ctx(tmp_path)
    product_summary(ctx, "LLZ", "20250825", "20250831")  # -> 2026-08-25..31 (3 reports)
    product_summary(ctx, "LLZ", "20250701", "20250731")  # -> 2026-07-01..31 (1 report)
    assert len(ctx.date_shifts) == 2
    return ctx


def test_every_moved_range_in_a_year_less_sentence_is_listed(tmp_path: Path) -> None:
    ctx = _moved_ctx(tmp_path)
    shifts = tuple(ctx.date_shifts)
    claims = [_count("LLZ", 3, "20260825", "20260831"), _count("LLZ", 1, "20260701", "20260731")]
    text = "LLZ had 3 reports in late August and 1 report in July."
    v = verify_sentence(text, claims, ctx.store, shifts)
    assert v.status == "pass"
    assert v.text.endswith("(Dates used: 2026-08-25 to 2026-08-31; 2026-07-01 to 2026-07-31.)")
    # claim order decides the order; a repeated range is listed once
    again = verify_sentence(text, [claims[1], claims[0], claims[0]], ctx.store, shifts)
    assert again.text.endswith("(Dates used: 2026-07-01 to 2026-07-31; 2026-08-25 to 2026-08-31.)")
    # either range named with its requested year withholds the sentence
    bad = verify_sentence(
        "LLZ had 3 reports in late August and 1 report in July 2025.", claims, ctx.store, shifts
    )
    assert bad.status == "block"


def test_group_count_on_a_moved_range_is_checked(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path)
    found = search_reports(ctx, product_code="LLZ", date_from="20250825", date_to="20250831")
    ids = tuple(r["report_id"] for r in found["reports"])
    assert len(ids) == 3
    group = GroupCountClaim("LLZ", "display failure", ids, 3, "20260825", "20260831")
    shifts = tuple(ctx.date_shifts)
    text = "In the last week of August 2025, 3 reports describe display failure."
    assert verify_sentence(text, [group], ctx.store).status == "pass"  # blind without shifts
    v = verify_sentence(text, [group], ctx.store, shifts)
    assert v.status == "block" and "names 2025" in " ".join(v.reasons)
    ok = verify_sentence(
        "In the last week of August, 3 reports describe display failure.",
        [group],
        ctx.store,
        shifts,
    )
    assert ok.status == "pass" and "Dates used: 2026-08-25 to 2026-08-31" in ok.text
    # a group with no dates, and a record claim, are tied to the moved search by their report ids
    undated = GroupCountClaim("LLZ", "display failure", ids, 3)
    assert verify_sentence(text, [undated], ctx.store, shifts).status == "block"
    rec = RecordClaim(ids[0], "LLZ")
    named = verify_sentence(f"In August 2025, report {ids[0]} was filed.", [rec], ctx.store, shifts)
    assert named.status == "block"
    plain = verify_sentence(f"Report {ids[0]} was filed.", [rec], ctx.store, shifts)
    assert plain.status == "pass" and "Dates used: 2026-08-25 to 2026-08-31" in plain.text


def test_only_the_one_year_slip_is_moved(tmp_path: Path) -> None:
    ctx = _demo_ctx(tmp_path)
    # LLZ: 2025 -> 2026 (33 reports) still works
    ok = product_summary(ctx, "LLZ", "20250825", "20250831")
    assert ok["date_adjusted"] is True and ok["report_count"] == 33
    for code, frm, to in (
        ("LLZ", "20270825", "20270831"),  # a later year is never moved backward
        ("MYN", "19990601", "19990607"),  # MYN runs 2006..2025-03-13
        ("MYN", "20050601", "20050607"),  # ... not 2025 either, and not a +1 move into 2006
        ("QIH", "20230101", "20230107"),  # two or more years off
        ("LLZ", "20240825", "20240831"),  # two years behind
    ):
        out = product_summary(ctx, code, frm, to)
        assert out["no_data_for_range"] is True, (code, frm)
        assert "date_adjusted" not in out and "report_count" not in out, (code, frm)


def test_a_false_zero_outside_the_stored_window_is_blocked(tmp_path: Path) -> None:
    ctx = _demo_ctx(tmp_path)
    store = ctx.store
    z = _count("LLZ", 0, "20250825", "20250831")
    v = verify_sentence("LLZ had 0 reports in the last week of August 2025.", [z], store)
    assert v.status == "block" and "no stored data for that range" in " ".join(v.reasons)
    q = verify_sentence(
        "QIH had 0 reports in October 2026.", [_count("QIH", 0, "20261001", "20261031")], store
    )
    assert q.status == "block" and "the newest stored report is 2026-08-31" in q.reasons[0]
    src = SourceCountClaim("LLZ", "non-manufacturer", 0, "20250825", "20250831")
    assert verify_sentence("0 LLZ reports came from users.", [src], store).status == "block"
    share = ShareClaim("LLZ", "Injury", 0.0, "20250825", "20250831")
    sv = verify_sentence("0% of LLZ reports were injuries.", [share], store)
    assert sv.status == "block" and "no stored data for that range" in " ".join(sv.reasons)
    # a true zero INSIDE the stored dates still passes: QIH has none in 2026-01, nor in the
    # last week of August 2026 although LLZ has reports then
    inside = verify_sentence(
        "QIH had 0 reports in January 2026.", [_count("QIH", 0, "20260101", "20260131")], store
    )
    assert inside.status == "pass"
    week = verify_sentence(
        "QIH had 0 reports this week.", [_count("QIH", 0, "20260825", "20260831")], store
    )
    assert week.status == "pass"
    assert verify_sentence("QIH had 0 deaths.", [_count("QIH", 0, None, None)], store).status in (
        "pass",
        "block",
    )  # undated zero is judged by the count itself, not the window guard


def test_claim_dates_are_normalised(tmp_path: Path) -> None:
    ctx = _demo_ctx(tmp_path)
    for frm, to in (("2026-08-25", "2026-08-31"), ("2026-8-25", "2026-8-31")):
        c = claim_from_dict(
            {"kind": "count", "product_code": "LLZ", "value": 33, "date_from": frm, "date_to": to}
        )
        assert isinstance(c, CountClaim) and (c.date_from, c.date_to) == ("20260825", "20260831")
        assert verify_sentence("LLZ had 33 reports.", [c], ctx.store).status == "pass"
    assert normalize_ymd("2025-8-5") == "20250805" and normalize_ymd("junk") == "junk"
    assert normalize_ymd(None) is None


@pytest.mark.parametrize("form", ["Aug '25", "FY25", "'25", "FY 2025", "Aug ’25", "CY25"])
def test_short_year_forms_name_the_year(tmp_path: Path, form: str) -> None:
    ctx = _ctx(tmp_path)
    product_summary(ctx, "LLZ", "20250825", "20250831")
    claim = _count("LLZ", 3, "20260825", "20260831")
    v = verify_sentence(
        f"LLZ had 3 reports in the week of {form}.", [claim], ctx.store, tuple(ctx.date_shifts)
    )
    assert v.status == "block", form


def test_a_date_block_is_not_counted_as_a_claim(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path)
    product_summary(ctx, "LLZ", "20250825", "20250831")
    claim = _count("LLZ", 3, "20260825", "20260831")
    report = verify_answer(
        [("LLZ had 3 reports in August 2025.", [claim])], ctx.store, tuple(ctx.date_shifts)
    )
    assert report.blocked == 1
    assert report.claim_counts == {"pass": 1, "block": 0}  # one claim, counted once
    assert report.sentences[0].date_issues and "[Withheld" in report.render()


# --- round 3: zero claims on a range a tool found empty, compact dates, report numbers -------


@pytest.mark.parametrize(
    ("code", "frm", "to", "claim_from", "claim_to"),
    [
        ("MYN", "20250825", "20250831", "20250825", "20250831"),
        ("MYN", "20260101", "20260107", "20260101", "20260107"),
        ("QIH", "20260825", "20260831", "20260825", "20260831"),
        ("MYN", "20250801", "20250831", "20250825", "20250831"),  # a narrower claimed range
    ],
)
def test_zero_on_a_range_a_tool_called_empty_is_blocked(
    tmp_path: Path, code: str, frm: str, to: str, claim_from: str, claim_to: str
) -> None:
    ctx = _demo_ctx(tmp_path)
    out = product_summary(ctx, code, frm, to)
    assert out["no_data_for_range"] is True and len(ctx.no_data) == 1
    zero = _count(code, 0, claim_from, claim_to)
    text = f"{code} had 0 reports in that range."
    assert verify_sentence(text, [zero], ctx.store).status in ("pass", "block")  # blind: no check
    v = verify_sentence(text, [zero], ctx.store, (), tuple(ctx.no_data))
    assert v.status == "block" and "no stored data for that range" in " ".join(v.reasons)
    # source-count and share zeros on the same range are blocked too
    src = SourceCountClaim(code, "non-manufacturer", 0, claim_from, claim_to)
    assert verify_sentence("0 reports.", [src], ctx.store, (), tuple(ctx.no_data)).status == "block"
    share = ShareClaim(code, "Injury", 0.0, claim_from, claim_to)
    assert (
        verify_sentence("0% injury.", [share], ctx.store, (), tuple(ctx.no_data)).status == "block"
    )
    # another code, or a non-zero claim, is not affected by the pair
    other = verify_sentence(
        "LLZ had 0 reports.",
        [_count("LLZ", 0, claim_from, claim_to)],
        ctx.store,
        (),
        tuple(ctx.no_data),
    )
    assert "tool call said so" not in " ".join(other.reasons)


def test_direct_tier_zero_without_a_tool_call_still_passes(tmp_path: Path) -> None:
    ctx = _demo_ctx(tmp_path)
    zero = _count("QIH", 0, "20260825", "20260831")
    assert verify_sentence("QIH had 0 reports this week.", [zero], ctx.store).status == "pass"


def test_agent_withholds_a_zero_after_a_no_data_tool_call(tmp_path: Path) -> None:
    ctx = _demo_ctx(tmp_path)
    claim = {
        "kind": "count",
        "product_code": "MYN",
        "value": 0,
        "event_type": None,
        "date_from": "20250825",
        "date_to": "20250831",
    }
    answer = json.dumps(
        {"sentences": [{"text": "MYN had 0 reports that week.", "claims": [claim]}]}
    )
    args = {"product_code": "MYN", "date_from": "20250825", "date_to": "20250831"}
    script = [
        _msg(tool_calls=[_call("product_summary", args)]),
        *[_msg(answer) for _ in range(6)],
    ]
    agent = CopilotAgent(FakeClient(script), ctx)
    res = agent.ask("MYN reports in the last week of August?")
    assert res.report.blocked == 1 and "no stored data for that range" in res.answer
    # cleared for the next question
    CopilotAgent(FakeClient([_msg(answer), _msg(answer), _msg(answer)]), ctx).ask("again")
    assert ctx.no_data == []


@pytest.mark.parametrize(
    "form", ["between 20250825 and 20250831", "on 20250825", "report 3012345-2025-00012 in 2025"]
)
def test_compact_dates_name_the_year(tmp_path: Path, form: str) -> None:
    ctx = _ctx(tmp_path)
    product_summary(ctx, "LLZ", "20250825", "20250831")
    claim = _count("LLZ", 3, "20260825", "20260831")
    v = verify_sentence(f"LLZ had 3 reports {form}.", [claim], ctx.store, tuple(ctx.date_shifts))
    assert v.status == "block", form
    assert "Dates used" not in v.text  # never a contradictory note on a withheld sentence


def test_a_report_number_does_not_name_the_year(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path)
    product_summary(ctx, "LLZ", "20250825", "20250831")
    claim = _count("LLZ", 3, "20260825", "20260831")
    text = "LLZ had 3 reports; see report 3012345-2025-00012."
    v = verify_sentence(
        text, [claim, RecordClaim("3012345-2025-00012")], ctx.store, tuple(ctx.date_shifts)
    )
    # blocked only because that report id is unknown, not because of the year in its number
    assert not v.date_issues
    assert v.text.endswith("(Dates used: 2026-08-25 to 2026-08-31.)")
