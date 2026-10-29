"""Safety tests for ``ask`` (HACKATHON-BUILT): read-only, no forbidden words, every spoken
sentence linked, recordings used only for the same question. No network, no model key.
"""

from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from maudesignal.connector.ask import AskRuntime, ask
from maudesignal.connector.data import ConnectorData
from maudesignal.connector.forbidden import FORBIDDEN_TERMS, forbidden_in
from maudesignal.connector.models import ADVISORY, ToolAnswer
from maudesignal.connector.readonly import READ_ONLY_TOOLS, REFUSED_TOOL, WRITE_TOOLS
from maudesignal.connector.speech import compose
from maudesignal.copilot.agent import CopilotAgent
from maudesignal.copilot.spend import SpendCaps
from maudesignal.copilot.tools import TOOL_SCHEMAS, TOOLS

REPORT_ID = "50426770"


@pytest.fixture(scope="module")
def data(tmp_path_factory: pytest.TempPathFactory) -> ConnectorData:
    return ConnectorData(work_dir=tmp_path_factory.mktemp("connector-safety"))


def recorded_runtime(tmp_path: Path) -> AskRuntime:
    def boom(*_: Any) -> CopilotAgent:
        raise AssertionError("the live model must not be called")

    return AskRuntime(agent_factory=boom, live_enabled=lambda: False, ledger_dir=tmp_path / "led")


def stored_questions(d: ConnectorData) -> list[str]:
    return [str(t["question"]) for t in d.transcripts() if t.get("question")]


# --- read-only ----------------------------------------------------------------------------


def test_every_copilot_tool_is_classified_read_or_write() -> None:
    assert set(TOOLS) == READ_ONLY_TOOLS | WRITE_TOOLS
    assert not READ_ONLY_TOOLS & WRITE_TOOLS
    assert {s["function"]["name"] for s in TOOL_SCHEMAS} == set(TOOLS)


def _tool_call(name: str, args: dict[str, Any]) -> Any:
    call = SimpleNamespace(
        id="call-1",
        type="function",
        function=SimpleNamespace(name=name, arguments=json.dumps(args)),
    )
    msg = SimpleNamespace(content=None, tool_calls=[call])
    return SimpleNamespace(
        choices=[SimpleNamespace(message=msg, finish_reason="tool_calls")],
        usage=SimpleNamespace(prompt_tokens=10, completion_tokens=10),
    )


def _final(sentences: list[dict[str, Any]]) -> Any:
    msg = SimpleNamespace(content=json.dumps({"sentences": sentences}), tool_calls=None)
    return SimpleNamespace(
        choices=[SimpleNamespace(message=msg, finish_reason="stop")],
        usage=SimpleNamespace(prompt_tokens=10, completion_tokens=10),
    )


class ScriptedClient:
    """First tool round calls draft_capa; every later call returns the final answer."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kwargs: Any) -> Any:
        self.calls.append(json.loads(json.dumps(kwargs, default=str)))
        if len(self.calls) == 1:
            return _tool_call(
                "draft_capa",
                {
                    "product_code": "LLZ",
                    "title": "x",
                    "problem_statement": "y",
                    "report_ids": [REPORT_ID],
                },
            )
        return _final([{"text": "Nothing was recorded.", "claims": []}])


def _count(db_file: Path, table: str) -> int:
    con = sqlite3.connect(db_file)
    try:
        return int(con.execute(f"select count(*) from {table}").fetchone()[0])  # noqa: S608
    finally:
        con.close()


def test_ask_cannot_write_a_capa_draft_even_if_the_model_calls_draft_capa(tmp_path: Path) -> None:
    d = ConnectorData(work_dir=tmp_path / "w")
    client = ScriptedClient()
    db_file = tmp_path / "w" / "demo.db"
    assert d.db is not None  # makes the working copy
    before = _count(db_file, "capa_drafts")
    rt = AskRuntime(
        # a factory that builds the agent the plain way, as a careless caller would
        agent_factory=lambda dd, g: CopilotAgent(g.wrap(client), dd.tool_context()),
        live_enabled=lambda: True,
        caps=SpendCaps(session_usd=1.0, session_calls=20, daily_usd=5.0),
        ledger_dir=tmp_path / "led",
    )
    a = ask(d, "Draft a CAPA for LLZ please", key_id="abc", runtime=rt)
    assert _count(db_file, "capa_drafts") == before == 0
    assert "CAPA-DRAFT" not in json.dumps(a.model_dump())
    # the model was never offered the writing tool ...
    offered = {t["function"]["name"] for c in client.calls for t in c.get("tools") or []}
    assert offered and "draft_capa" not in offered and offered <= READ_ONLY_TOOLS
    # ... and its call was answered with an error, not run
    tool_msgs = [m for m in client.calls[1]["messages"] if m.get("role") == "tool"]
    assert (
        tool_msgs and "error" in tool_msgs[0]["content"] and REFUSED_TOOL in tool_msgs[0]["content"]
    )
    assert "audit" not in a.speakable.lower()


# --- forbidden terms ----------------------------------------------------------------------


def _assert_clean(a: ToolAnswer) -> None:
    assert forbidden_in(json.dumps(a.model_dump())) == []
    assert a.advisory == ADVISORY


def test_forbidden_matcher() -> None:
    for term in FORBIDDEN_TERMS:
        assert forbidden_in(f"This is {term} data.") != [], term
    assert forbidden_in("The approval clock and a named human approves it.") == []


def test_ask_on_every_stored_question_has_no_forbidden_term(
    data: ConnectorData, tmp_path: Path
) -> None:
    for q in stored_questions(data):
        _assert_clean(ask(data, q, key_id="k", runtime=recorded_runtime(tmp_path)))


@pytest.mark.parametrize("term", FORBIDDEN_TERMS)
def test_ask_on_every_forbidden_term_has_none_in_the_answer(
    data: ConnectorData, tmp_path: Path, term: str
) -> None:
    for q in (f"Is the LLZ device {term}?", f"What changed this week, is it {term}?", term):
        if len(q) >= 3:
            _assert_clean(ask(data, q, key_id="k", runtime=recorded_runtime(tmp_path)))


def test_the_overnight_worsening_recording_is_never_used(
    data: ConnectorData, tmp_path: Path
) -> None:
    a = ask(
        data,
        "What came in overnight? Is anything worsening?",
        key_id="k",
        runtime=recorded_runtime(tmp_path),
    )
    _assert_clean(a)
    assert "no verified answer" in a.speakable


class OneAnswerClient:
    def __init__(self, sentences: list[dict[str, Any]]) -> None:
        self.sentences = sentences
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **_: Any) -> Any:
        return _final(self.sentences)


def live_rt(tmp_path: Path, client: Any) -> AskRuntime:
    return AskRuntime(
        agent_factory=lambda d, g: CopilotAgent(g.wrap(client), d.tool_context()),
        live_enabled=lambda: True,
        caps=SpendCaps(session_usd=1.0, session_calls=20, daily_usd=5.0),
        ledger_dir=tmp_path / "led",
    )


LLZ_33 = {
    "kind": "count",
    "product_code": "LLZ",
    "value": 33,
    "date_from": "20260825",
    "date_to": "20260831",
}


def test_live_sentence_with_a_forbidden_term_is_withheld_not_spoken(tmp_path: Path) -> None:
    d = ConnectorData(work_dir=tmp_path / "w")
    client = OneAnswerClient(
        [
            {"text": "LLZ had 33 reports from August 25 to August 31, 2026.", "claims": [LLZ_33]},
            {"text": "LLZ had 33 validated reports in that week.", "claims": [LLZ_33]},
        ]
    )
    a = ask(d, "How many LLZ reports this week?", key_id="abc", runtime=live_rt(tmp_path, client))
    _assert_clean(
        a.model_copy(update={"withheld": []})
    )  # the withheld text is shown as NOT VERIFIED
    assert "validated" not in a.speakable and "33 reports" in a.speakable
    assert len(a.withheld) == 1 and "validated" in a.withheld[0].text


# --- every spoken sentence has a linked fact ----------------------------------------------

_LEAD = re.compile(
    r"^(?:Live answers are not switched on here|Today's live-answer budget is used up"
    r"|The live model is not available just now), so this is a recorded answer to a "
    r"different, similar question: \".*?\"(?:, using stored reports through [A-Za-z]+ \d+, "
    r"\d{4})?\.\s*"
)
_NOTICE = re.compile(r"(?:One sentence was|\d+ sentences were) left out[^.]*\.")
_NO_RECORDING = (
    "I have no verified answer to that question right now.",
    "Try the what changed, device check, report or recalls tools instead.",
)
_NONE = "I could not verify an answer to that, so I am not stating one."


def spoken_body(a: ToolAnswer) -> str:
    """Speakable text without the lead, the left-out notice and the nothing-verified line."""
    text = _LEAD.sub("", a.speakable)
    text = _NOTICE.sub("", text)
    for line in (_NONE, *_NO_RECORDING):
        text = text.replace(compose([line]), "")
    return text.strip()


def assert_every_spoken_sentence_has_a_fact(a: ToolAnswer) -> None:
    body = spoken_body(a)
    for f in a.facts:
        assert f.link.startswith("https://api.fda.gov/") or f.link.startswith("https://")
        body = body.replace(compose([f.text]), "")
    assert body.strip() == "", f"spoken text without a linked fact: {body!r}"
    for w in a.withheld:
        assert compose([w.text]) not in a.speakable


def test_every_spoken_sentence_of_ask_maps_to_a_fact(data: ConnectorData, tmp_path: Path) -> None:
    covered = 0
    for q in stored_questions(data):
        a = ask(data, q, key_id="k", runtime=recorded_runtime(tmp_path))
        assert_every_spoken_sentence_has_a_fact(a)
        covered += bool(a.facts)
    assert covered >= 5, "the check must run on real linked answers, not only empty ones"


def test_what_changed_recording_links_every_count_including_the_zero_counts(
    data: ConnectorData, tmp_path: Path
) -> None:
    a = ask(data, "What changed this week for LLZ?", key_id="k", runtime=recorded_runtime(tmp_path))
    assert_every_spoken_sentence_has_a_fact(a)
    count_links = [f.link for f in a.facts if "device/event.json" in f.link]
    joined = " ".join(count_links)
    for code in ("LLZ", "MYN", "POK", "QIH"):
        assert code in joined, f"no openFDA count link for {code}"
    llz = next(f for f in a.facts if "LLZ" in f.link)
    assert "20260825" in llz.link and "20260831" in llz.link  # the count query, not one report
    assert llz.link_label == "openFDA count for LLZ"


def test_live_sentence_without_a_link_is_left_out_of_speakable(tmp_path: Path) -> None:
    d = ConnectorData(work_dir=tmp_path / "w")
    client = OneAnswerClient(
        [
            {"text": "LLZ had 33 reports from August 25 to August 31, 2026.", "claims": [LLZ_33]},
            {"text": "A named human must review this.", "claims": []},
        ]
    )
    a = ask(d, "How many LLZ reports this week?", key_id="abc", runtime=live_rt(tmp_path, client))
    assert_every_spoken_sentence_has_a_fact(a)
    assert "named human" not in a.speakable
    assert [w.text for w in a.withheld] == ["A named human must review this."]
    assert "no openFDA or record link" in a.withheld[0].reason


# --- a recording answers only the question it was recorded for ----------------------------


@pytest.mark.parametrize(
    "q",
    [
        "What changed this week for QIH?",
        "What changed this week for MYN?",
        "How many recalls does QIH have?",
        "Is the LLZ device FDA approved?",
        "Tell me a story",
        "Hello, my name is Sam, nice to meet you",
    ],
)
def test_recording_for_a_different_question_is_not_offered(
    data: ConnectorData, tmp_path: Path, q: str
) -> None:
    a = ask(data, q, key_id="k", runtime=recorded_runtime(tmp_path))
    _assert_clean(a)
    assert a.facts == [] and "no verified answer" in a.speakable
    assert "Alistair" not in a.speakable and "recorded answer" not in a.speakable


def test_voice_and_greeting_recordings_are_not_in_the_fallback_pool(
    data: ConnectorData, tmp_path: Path
) -> None:
    voice = [t for t in data.transcripts() if "voice" in str(t.get("label"))]
    assert voice, "the fixture recordings include voice-mode runs"
    for t in voice:
        a = ask(data, str(t["question"]), key_id="k", runtime=recorded_runtime(tmp_path))
        assert "Alistair" not in a.speakable
        if a.facts:  # it matched the text twin of that question, not the voice run
            assert a.provenance.kind == "recorded_answer"


def test_spoken_lead_names_the_recorded_question_and_the_data_date(
    data: ConnectorData, tmp_path: Path
) -> None:
    a = ask(data, "What changed this week for LLZ?", key_id="k", runtime=recorded_runtime(tmp_path))
    assert a.speakable.startswith("Live answers are not switched on here")
    assert "What changed this week" in a.speakable
    assert "stored reports through August 31, 2026" in a.speakable
