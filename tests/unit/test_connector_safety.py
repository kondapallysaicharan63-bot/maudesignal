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
    _assert_whole_clean(a)
    assert "validated" not in a.speakable and "33 reports" in a.speakable
    assert len(a.withheld) == 1 and "validated" not in a.withheld[0].text


# --- every spoken sentence has a linked fact ----------------------------------------------

_LEAD = re.compile(
    r"^(?:Live answers are not switched on here|Live answers are switched off on this server"
    r"|Today's live-answer budget is used up"
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
    assert [w.text for w in a.withheld] == ["Sentence left out by the claim gate."]
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


# --- whole-response screening and no withheld text in live mode ---------------------------


def _whole(a: ToolAnswer) -> str:
    """Everything the caller can read: speakable, facts, withheld, provenance, advisory."""
    return json.dumps(a.model_dump(mode="json"))


def _assert_whole_clean(a: ToolAnswer) -> None:
    body = _whole(a)
    assert forbidden_in(body) == []
    plain = body.lower().replace("-", " ")
    for term in FORBIDDEN_TERMS:
        assert term.lower().replace("-", " ") not in plain, term
    assert a.advisory == ADVISORY


def test_whole_response_is_clean_on_every_stored_question(
    data: ConnectorData, tmp_path: Path
) -> None:
    qs = stored_questions(data)
    assert qs
    for q in qs:
        _assert_whole_clean(ask(data, q, key_id="k", runtime=recorded_runtime(tmp_path)))


def test_recorded_withheld_sentence_with_a_term_is_replaced_by_a_neutral_text() -> None:
    from maudesignal.connector.ask import _split

    p, f, w = _split(
        [
            ("It was official and validated.", [], "count: mismatch", ["count"]),
            ("Clean but blocked sentence here.", [], "count: mismatch", ["count"]),
        ],
        hide_withheld_text=False,
    )
    assert (p, f) == ([], [])
    assert w[0].text == "Sentence left out: it contains a term this service does not use."
    assert w[1].text == "Clean but blocked sentence here."  # recorded text kept when it is clean


GOOD_SENTENCE = "LLZ had 33 reports from August 25 to August 31, 2026."
BLOCKED = [
    "LLZ logged exactly 4711 device events during the final week of August.",
    "A reviewer wrote that the pump software silently overwrote the alarm threshold twice.",
    "Under 21 CFR 999.77 every manufacturer must retrain its algorithm monthly.",
    "The LLZ device was validated and official for every clinical use anywhere.",
]
BLOCKED_SCRIPT: list[dict[str, Any]] = [
    {"text": GOOD_SENTENCE, "claims": [LLZ_33]},
    {"text": BLOCKED[0], "claims": [{**LLZ_33, "value": 4711}]},
    {
        "text": BLOCKED[1],
        "claims": [
            {
                "kind": "quote",
                "quote": "pump software silently overwrote the alarm threshold twice",
                "report_id": REPORT_ID,
                "source_id": None,
            }
        ],
    },
    {"text": BLOCKED[2], "claims": [{"kind": "regulation", "section": "999.77"}]},
    {"text": BLOCKED[3], "claims": [LLZ_33]},
]


def _windows(text: str, n: int = 20) -> set[str]:
    t = " ".join(text.lower().split())
    return {t[i : i + n] for i in range(len(t) - n + 1)}


def _assert_no_sentence_text(body: str) -> None:
    low = " ".join(body.lower().split())
    for s in BLOCKED:
        for w in _windows(s):
            assert w not in low, f"20+ characters of a withheld sentence are in the body: {w!r}"
        assert s not in body


def test_live_withheld_text_never_appears_in_the_response(tmp_path: Path) -> None:
    d = ConnectorData(work_dir=tmp_path / "w")
    rt = live_rt(tmp_path, OneAnswerClient(BLOCKED_SCRIPT))
    a = ask(d, "How many LLZ reports this week?", key_id="abc", runtime=rt)
    assert a.provenance.kind == "live_model"
    assert "33 reports" in a.speakable
    assert len(a.withheld) == 4, [w.reason for w in a.withheld]
    for w in a.withheld:
        assert w.text in (
            "Sentence left out by the claim gate.",
            "Sentence left out: it contains a term this service does not use.",
        )
        assert w.reason and w.status == "withheld"
    assert any("term this service does not use" in w.reason for w in a.withheld)
    assert {k for w in a.withheld for k in w.claim_kinds} >= {"count", "quote", "regulation"}
    _assert_whole_clean(a)
    _assert_no_sentence_text(_whole(a))
    _assert_no_sentence_text(json.dumps(a.model_dump()))  # the MCP-ready dict


def test_live_answer_with_every_forbidden_term_is_clean_everywhere(tmp_path: Path) -> None:
    d = ConnectorData(work_dir=tmp_path / "w")
    script: list[dict[str, Any]] = [{"text": GOOD_SENTENCE, "claims": [LLZ_33]}]
    script += [
        {"text": f"The LLZ report count of 33 is {t} in that week.", "claims": [LLZ_33]}
        for t in FORBIDDEN_TERMS
    ]
    rt = live_rt(tmp_path, OneAnswerClient(script))
    a = ask(d, "How many LLZ reports this week?", key_id="abc", runtime=rt)
    assert a.provenance.kind == "live_model" and len(a.withheld) >= 1
    _assert_whole_clean(a)
    for t in FORBIDDEN_TERMS:
        assert f"is {t} in" not in _whole(a)


def test_rest_raw_body_never_holds_a_withheld_sentence(tmp_path: Path) -> None:
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from maudesignal.connector.app import Settings, create_app
    from maudesignal.connector.security import KeyStore, RateLimiter
    from tests.unit.test_connector import KEY, fake_check

    settings = Settings(
        keys=KeyStore.from_env({"MAUDESIGNAL_API_KEYS": KEY}),
        limiter=RateLimiter(100),
        data=ConnectorData(work_dir=tmp_path / "w"),
        ask_runtime=live_rt(tmp_path, OneAnswerClient(BLOCKED_SCRIPT)),
        live_checker=fake_check,
    )
    c = TestClient(create_app(settings), raise_server_exceptions=False)
    r = c.post(
        "/v1/tools/ask",
        json={"question": "How many LLZ reports this week?"},
        headers={"X-API-Key": KEY},
    )
    assert r.status_code == 200 and r.json()["provenance"]["kind"] == "live_model"
    assert len(r.json()["withheld"]) == 4
    _assert_no_sentence_text(r.text)
    _assert_no_sentence_text(r.content.decode("utf-8"))
    assert forbidden_in(r.text) == []


def test_live_off_reason_when_key_is_set_but_live_is_switched_off(
    data: ConnectorData, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    q = "What changed this week for LLZ?"
    monkeypatch.setenv("META_MODEL_API_KEY", "x" * 12)
    a = ask(data, q, key_id="k", runtime=recorded_runtime(tmp_path))
    assert "switched off on this server" in a.speakable
    assert "limits are per instance" in a.provenance.note
    monkeypatch.delenv("META_MODEL_API_KEY")
    b = ask(data, q, key_id="k", runtime=recorded_runtime(tmp_path))
    assert "not switched on here" in b.speakable
    assert "No live model key is configured" in b.provenance.note


# --- model text in claim fields never reaches a live response --------------------------------

ADVICE = "patients should stop using the infusion pump right away and call their doctor"
INJECT_SCRIPT: list[dict[str, Any]] = [
    {"text": GOOD_SENTENCE, "claims": [LLZ_33]},
    {
        "text": "Blocked one about a rule.",
        "claims": [{"kind": "regulation", "section": f"999.1 {ADVICE}"}],
    },
    {
        "text": "Blocked two about a report.",
        "claims": [{"kind": "record", "report_id": f"1 {ADVICE}", "product_code": f"LLZ {ADVICE}"}],
    },
    {
        "text": "Blocked three about a source.",
        "claims": [
            {"kind": "source_count", "product_code": "LLZ", "source": f"MAUDE {ADVICE}", "value": 5}
        ],
    },
    {
        "text": "Blocked four about a recall.",
        "claims": [{"kind": "recall", "recall_number": f"Z-1 {ADVICE}", "product_code": "LLZ"}],
    },
    {
        "text": "Blocked five about a device.",
        "claims": [{"kind": "device", "k_number": f"K1 {ADVICE}", "product_code": "LLZ"}],
    },
    {
        "text": "Blocked six about a quote.",
        "claims": [{"kind": "quote", "quote": ADVICE, "report_id": f"2 {ADVICE}"}],
    },
]


def _assert_no_advice(body: str) -> None:
    low = " ".join(body.lower().split())
    for w in _windows(ADVICE):
        assert w not in low, f"model-written claim text is in the body: {w!r}"
    assert "infusion pump" not in low and "stop using" not in low


def test_live_body_never_holds_text_the_model_put_in_a_claim_field(tmp_path: Path) -> None:
    from maudesignal.connector.ask import _GENERIC_REASON, _LIVE_REASONS

    d = ConnectorData(work_dir=tmp_path / "w")
    rt = live_rt(tmp_path, OneAnswerClient(INJECT_SCRIPT))
    a = ask(d, "How many LLZ reports this week?", key_id="abc", runtime=rt)
    assert a.provenance.kind == "live_model"
    assert len(a.withheld) == 6, [w.reason for w in a.withheld]
    allowed = set(_LIVE_REASONS.values()) | {_GENERIC_REASON}
    for w in a.withheld:
        assert set(w.reason.split("; ")) <= allowed, w.reason
    _assert_no_advice(_whole(a))
    _assert_no_advice(json.dumps(a.model_dump()))
    _assert_whole_clean(a)


def test_rest_raw_body_never_holds_text_the_model_put_in_a_claim_field(tmp_path: Path) -> None:
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from maudesignal.connector.app import Settings, create_app
    from maudesignal.connector.security import KeyStore, RateLimiter
    from tests.unit.test_connector import KEY, fake_check

    settings = Settings(
        keys=KeyStore.from_env({"MAUDESIGNAL_API_KEYS": KEY}),
        limiter=RateLimiter(100),
        data=ConnectorData(work_dir=tmp_path / "w"),
        ask_runtime=live_rt(tmp_path, OneAnswerClient(INJECT_SCRIPT)),
        live_checker=fake_check,
    )
    c = TestClient(create_app(settings), raise_server_exceptions=False)
    r = c.post(
        "/v1/tools/ask",
        json={"question": "How many LLZ reports this week?"},
        headers={"X-API-Key": KEY},
    )
    assert r.status_code == 200 and r.json()["provenance"]["kind"] == "live_model"
    _assert_no_advice(r.text)
    _assert_no_advice(r.content.decode("utf-8"))
    assert forbidden_in(r.text) == []


def test_safe_reason_keeps_a_head_only_when_it_is_a_known_claim_kind() -> None:
    from maudesignal.connector.ask import _safe_reason

    sentence = "The pump overwrote the alarm threshold twice."
    assert _safe_reason("pump overwrote the alarm", sentence) == "could not be verified"
    assert (
        _safe_reason("notakind: the pump overwrote the alarm threshold", sentence)
        == "could not be verified"
    )
    assert (
        _safe_reason("count: the pump overwrote the alarm threshold", sentence)
        == "count: could not be verified"
    )


# --- question text is not kept (privacy statement in MUSE_CONNECTOR.md) --------------------

PROBE = "PRIVACYPROBE how many LLZ reports this week?"


def test_live_ask_leaves_no_question_text_in_any_table_of_the_database(tmp_path: Path) -> None:
    d = ConnectorData(work_dir=tmp_path / "w")
    rt = live_rt(tmp_path, OneAnswerClient(BLOCKED_SCRIPT))
    a = ask(d, PROBE, key_id="abc", runtime=rt)
    assert a.provenance.kind == "live_model"
    db_file = tmp_path / "w" / "demo.db"
    con = sqlite3.connect(db_file)
    try:
        tables = [r[0] for r in con.execute("select name from sqlite_master where type='table'")]
        assert "action_audit" in tables
        for table in tables:
            for row in con.execute(f'select * from "{table}"'):  # noqa: S608
                assert "PRIVACYPROBE" not in json.dumps(row, default=str), table
        rows = con.execute(
            "select payload_json from action_audit where action='copilot.answer'"
        ).fetchall()
    finally:
        con.close()
    assert rows, "the copilot's own audit entry is still written"
    assert json.loads(rows[-1][0])["question"].startswith("sha256:")
    assert b"PRIVACYPROBE" not in db_file.read_bytes()
    assert d.db.verify_audit_chain()[0] is True  # chain was recomputed, still verifies
