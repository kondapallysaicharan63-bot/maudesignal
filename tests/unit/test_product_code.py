"""Tests for the deterministic product-code check (HACKATHON-BUILT).

No network, no model: the check is pure string logic, so a misheard code
can never be "corrected" by an unverifiable guess.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from maudesignal.catalog.fetcher import _SEED_PRODUCT_CODES
from maudesignal.copilot.product_code import (
    CodeSets,
    check_product_code,
    code_sets_from_db,
    confirm_prompt,
    describe_check,
    levenshtein_distance,
)
from maudesignal.storage.database import Database

# Codes on file in the demo database, plus the seed list (LLN is a real seed code).
CODES = CodeSets.of(["JAK", "LLZ", "MYN", "POK", "QIH"], _SEED_PRODUCT_CODES)
DEMO_DB = Path(__file__).resolve().parents[2] / "data" / "demo" / "maudesignal_demo.db"


def test_code_sets_come_from_the_database_and_seed_list(tmp_path: Path) -> None:
    sets = code_sets_from_db(Database(DEMO_DB))
    assert {"JAK", "LLZ", "MYN", "POK", "QIH"} <= sets.on_file
    assert set(_SEED_PRODUCT_CODES) <= sets.known
    assert "LLN" in sets.known and "LLN" not in sets.on_file
    empty = code_sets_from_db(Database(tmp_path / "e.db"))
    assert empty.on_file == frozenset() and empty.known == frozenset(_SEED_PRODUCT_CODES)


def test_known_code_unchanged_no_suggestion() -> None:
    check = check_product_code("What changed this week for LLZ devices?", CODES)
    assert (check.heard_code, check.suggested_code, check.used_code) == ("LLZ", None, "LLZ")
    assert check.status == "known"
    assert check.corrected_text == "What changed this week for LLZ devices?"
    assert check.display == "Product code: LLZ."
    assert not check.needs_confirmation


@pytest.mark.parametrize("text", ["What changed for LLN devices?", "Tell me about LLN."])
def test_real_seed_code_is_never_rewritten(text: str) -> None:
    check = check_product_code(text, CODES)
    assert check.status == "known" and check.used_code == "LLN"
    assert check.corrected_text == text


@pytest.mark.parametrize(
    "text",
    [
        "Did reports suddenly increase for any device?",
        "Are there any new devices?",
        "How many reports came in during Jan or at the pos?",
        "Is Jan a code? And pos? What about JAn or Pos?",
    ],
)
def test_ordinary_words_are_not_candidates(text: str) -> None:
    check = check_product_code(text, CODES)
    assert (check.status, check.heard_code, check.display) == ("none", None, None), text
    assert check.corrected_text == text


@pytest.mark.parametrize(
    "text",
    [
        "Did reports suddenly increase for any device?",
        "What changed for all LLZ devices?",
        "What about the LLZ product code, for the LLZ product code?",
        "Are there any new devices?",
    ],
)
def test_any_all_the_new_never_change_the_question(text: str) -> None:
    check = check_product_code(text, CODES)
    assert check.corrected_text == text
    assert check.status in {"none", "known"}
    assert check.heard_code in {None, "LLZ"}


def test_ordinary_word_before_a_wrong_code_is_skipped() -> None:
    fixed = check_product_code("What about the LLG devices?", CODES)
    assert fixed.corrected_text == "What about the LLZ devices?"
    assert (fixed.heard_code, fixed.suggested_code) == ("LLG", "LLZ")


def test_llg_corrects_to_llz_with_a_statement() -> None:
    check = check_product_code("What changed this week for LLG devices?", CODES)
    assert (check.heard_code, check.suggested_code, check.used_code) == ("LLG", "LLZ", "LLZ")
    assert check.status == "corrected" and check.needs_confirmation
    assert check.corrected_text == "What changed this week for LLZ devices?"
    assert check.display == (
        "Heard LLG -> did you mean LLZ? The answer used LLZ "
        "(one letter different; the only close code on file)."
    )


def test_llc_corrects_to_llz() -> None:
    check = check_product_code("My colleague says LLC had 50 injury reported last week.", CODES)
    assert (check.heard_code, check.suggested_code, check.status) == ("LLC", "LLZ", "corrected")
    assert check.corrected_text == "My colleague says LLZ had 50 injury reported last week."


def test_far_code_not_corrected_and_scan_continues() -> None:
    check = check_product_code("What changed this week for XYZ devices?", CODES)
    assert (check.heard_code, check.suggested_code, check.status) == ("XYZ", None, "unknown")
    assert check.corrected_text == "What changed this week for XYZ devices?"
    assert check.display == "Heard XYZ; product code not recognised, asked as heard."
    later = check_product_code("XYZ first, then LLZ devices", CODES)
    assert later.status == "known" and later.used_code == "LLZ"


def test_tie_rule_with_two_close_codes_on_file_is_ambiguous() -> None:
    # Made-up code set (QAS on file) that exercises the tie rule only; it is not the app's set.
    two_close = CodeSets.of(["QIH", "QAS"])
    check = check_product_code("What changed this week for QAH devices?", two_close)
    assert (check.heard_code, check.suggested_code, check.status) == ("QAH", None, "ambiguous")
    assert check.used_code == "QAH"
    assert check.corrected_text == "What changed this week for QAH devices?"
    assert not check.needs_confirmation


def test_qah_on_the_demo_database_is_corrected_to_qih() -> None:
    # Deviation from the milestone text ("QAH (tie, unchanged)"): correction targets are the
    # codes on file only, and on the real code set QAS is not on file, so QAH is exactly one
    # edit from exactly one code (QIH) and is corrected (confirmed by the analyst in live mode).
    sets = code_sets_from_db(Database(DEMO_DB))
    assert "QAS" not in sets.on_file
    check = check_product_code("What changed this week for QAH devices?", sets)
    assert (check.heard_code, check.suggested_code, check.status) == ("QAH", "QIH", "corrected")
    assert check.needs_confirmation
    assert confirm_prompt(check) is not None
    assert confirm_prompt(check)[0] == "Heard QAH -> did you mean QIH?"  # type: ignore[index]
    # The stored-demo statement shows both codes and says which one the answer used.
    assert check.display is not None
    assert "Heard QAH -> did you mean QIH?" in check.display and "used QIH" in check.display
    declined = describe_check("QAH", "QIH", "QAH", "declined")
    assert declined is not None and "QIH" in declined and "used QAH as heard" in declined


@pytest.mark.parametrize(
    "text",
    ["What did the FDA say?", "Is this a USA device?", "Any MDR, PMA, CFR or UDI news?"],
)
def test_regulatory_acronyms_are_not_candidates(text: str) -> None:
    check = check_product_code(text, CODES)
    assert (check.heard_code, check.status, check.display) == (None, "none", None)
    assert check.corrected_text == text


def test_acronym_is_skipped_but_a_later_code_is_still_found() -> None:
    check = check_product_code("Did the FDA flag LLG devices?", CODES)
    assert (check.heard_code, check.suggested_code) == ("LLG", "LLZ")


def test_no_code_found() -> None:
    check = check_product_code("Hello, how are you today?", CODES)
    assert (check.heard_code, check.used_code, check.status, check.display) == (
        None,
        None,
        "none",
        None,
    )


def test_recorded_runs_describe_with_the_new_statement() -> None:
    assert describe_check("LLC", "LLZ", "LLZ", "corrected") == (
        "Heard LLC -> did you mean LLZ? The answer used LLZ "
        "(one letter different; the only close code on file)."
    )
    assert describe_check("LLZ", None, "LLZ", "known") == "Product code: LLZ."
    assert describe_check(None, None, None, None) is None


def test_confirm_prompt_labels() -> None:
    check = check_product_code("for LLG devices", CODES)
    assert confirm_prompt(check) == (
        "Heard LLG -> did you mean LLZ?",
        "Ask about LLZ",
        "Ask as heard (LLG)",
    )
    assert confirm_prompt(check_product_code("for LLZ devices", CODES)) is None
    assert confirm_prompt(check_product_code("for XYZ devices", CODES)) is None


# ---- live mode: ask only after the analyst chooses ---------------------------------


class _Agent:
    def __init__(self, db: Database) -> None:
        self.context = SimpleNamespace(db=db)
        self.asked: list[str] = []

    def question_entity_id(self, q: str) -> str:
        return "Q-" + q[:8]

    def ask(self, q: str) -> Any:
        self.asked.append(q)
        return SimpleNamespace(question=q)


class _Transcriber:
    model = "muse-voice-transcribe-1.0"

    def __init__(self, text: str) -> None:
        self.text = text

    def transcribe_bytes(self, data: bytes, filename: str = "q.wav") -> Any:
        from maudesignal.copilot.voice import Transcript

        return Transcript(text=self.text, language="English", duration_s=3.0)


def _prepared(tmp_path: Path, text: str) -> tuple[_Agent, Any]:
    from maudesignal.copilot.voice import prepare_voice_question

    db = Database(tmp_path / "p.db")
    db.upsert_raw_report(
        maude_report_id="1-1",
        product_code="LLZ",
        date_received="20260801",
        date_of_event=None,
        raw_payload={},
    )
    agent = _Agent(db)
    prepared = prepare_voice_question(
        _Transcriber(text),  # type: ignore[arg-type]
        agent,  # type: ignore[arg-type]
        b"wav",
    )
    return agent, prepared


def test_live_mode_prepare_does_not_ask_the_model(tmp_path: Path) -> None:
    agent, prepared = _prepared(tmp_path, "What changed for LLG devices?")
    assert prepared.check.needs_confirmation
    assert agent.asked == []  # nothing is sent until the analyst clicks
    assert agent.context.db.list_audit() == []


@pytest.mark.parametrize(
    ("use_suggestion", "asked", "used"),
    [
        (True, "What changed for LLZ devices?", "LLZ"),
        (False, "What changed for LLG devices?", "LLG"),
    ],
)
def test_live_mode_asks_what_the_analyst_chose(
    tmp_path: Path, use_suggestion: bool, asked: str, used: str
) -> None:
    from maudesignal.copilot.voice import answer_prepared

    agent, prepared = _prepared(tmp_path, "What changed for LLG devices?")
    ans = answer_prepared(
        "muse-voice-transcribe-1.0",
        agent,  # type: ignore[arg-type]
        prepared,
        use_suggestion=use_suggestion,
    )
    assert agent.asked == [asked]
    block = ans.transcript.to_voice_block()
    got = (block["heard_code"], block["suggested_code"], block["used_code"])
    assert got == ("LLG", "LLZ", used)
    (entry,) = agent.context.db.list_audit()
    payload = json.loads(entry.payload_json)
    assert payload["used_code"] == used and payload["transcript_text"].endswith("LLG devices?")
    # Declining the suggestion is recorded as such, never as an applied correction.
    expected = "corrected" if use_suggestion else "declined"
    assert payload["product_code_status"] == expected == block["product_code_status"]


def test_declined_status_reads_as_a_statement() -> None:
    text = describe_check("LLG", "LLZ", "LLG", "declined")
    assert text == "Heard LLG -> did you mean LLZ? Not confirmed: the answer used LLG as heard."


def test_voice_block_and_html_carry_heard_suggested_used() -> None:
    from maudesignal.copilot.voice import Transcript
    from maudesignal.dashboard.copilot_pages import DISPLAY_EXCLUDED_LABELS, _voice_html

    t = Transcript(
        text="What changed this week for LLG devices?",
        language="English",
        duration_s=7.6,
        heard_code="LLG",
        suggested_code="LLZ",
        used_code="LLZ",
        product_code_status="corrected",
    )
    block = t.to_voice_block()
    assert (block["heard_code"], block["suggested_code"], block["used_code"]) == (
        "LLG",
        "LLZ",
        "LLZ",
    )
    out = _voice_html(block)
    assert "Heard LLG -&gt; did you mean LLZ? The answer used LLZ" in out
    assert "(one letter different; the only close code on file)." in out
    assert "00-voice-main" in DISPLAY_EXCLUDED_LABELS


def test_levenshtein_examples() -> None:
    assert levenshtein_distance("LLG", "LLZ") == 1
    assert levenshtein_distance("XYZ", "LLZ") == 2
    assert levenshtein_distance("LLZ", "LLZ") == 0
