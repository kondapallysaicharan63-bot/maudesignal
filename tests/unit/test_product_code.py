"""Tests for the deterministic product-code check (HACKATHON-BUILT).

No network, no model: the check is pure string logic, so a misheard code
can never be "corrected" by an unverifiable guess.
"""

from __future__ import annotations

from maudesignal.copilot.product_code import (
    KNOWN_PRODUCT_CODES,
    check_product_code,
    levenshtein_distance,
)


def test_known_code_unchanged_no_suggestion() -> None:
    check = check_product_code("What changed this week for LLZ devices?")
    assert check.heard_code == "LLZ"
    assert check.suggested_code is None
    assert check.used_code == "LLZ"
    assert check.status == "known"
    assert check.corrected_text == "What changed this week for LLZ devices?"
    assert check.display == "Heard: LLZ"


def test_llg_corrects_to_llz() -> None:
    check = check_product_code("What changed this week for LLG devices?")
    assert check.heard_code == "LLG"
    assert check.suggested_code == "LLZ"
    assert check.used_code == "LLZ"
    assert check.status == "corrected"
    assert "LLZ devices" in check.corrected_text
    assert check.display == "Heard: LLG → did you mean LLZ?"


def test_lnz_corrects_to_llz() -> None:
    check = check_product_code("My colleague says LNZ had fifty injury reports last week.")
    assert check.heard_code == "LNZ"
    assert check.suggested_code == "LLZ"
    assert check.used_code == "LLZ"
    assert check.status == "corrected"


def test_far_code_not_corrected() -> None:
    check = check_product_code("What changed this week for XYZ devices?")
    assert check.heard_code == "XYZ"
    assert check.suggested_code is None
    assert check.used_code == "XYZ"
    assert check.status == "unknown"
    assert check.corrected_text == "What changed this week for XYZ devices?"
    assert check.display == "Heard: XYZ"


def test_tie_at_distance_one_not_corrected() -> None:
    # QAH is 1 edit from both QIH and QAS in the correction vocabulary.
    check = check_product_code("What changed this week for QAH devices?")
    assert check.heard_code == "QAH"
    assert check.suggested_code is None
    assert check.used_code == "QAH"
    assert check.status == "ambiguous"
    assert check.corrected_text == "What changed this week for QAH devices?"


def test_no_code_found() -> None:
    check = check_product_code("Hello, how are you today?")
    assert check.heard_code is None
    assert check.used_code is None
    assert check.status == "none"
    assert check.display is None


def test_voice_block_and_html_carry_heard_suggested_used() -> None:
    from maudesignal.copilot.voice import Transcript
    from maudesignal.dashboard.copilot_pages import HIDDEN_VOICE_LABELS, _voice_html

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
    assert block["heard_code"] == "LLG"
    assert block["suggested_code"] == "LLZ"
    assert block["used_code"] == "LLZ"
    out = _voice_html(block)
    assert "Heard: LLG → did you mean LLZ? Using LLZ." in out
    assert "00-voice-main" in HIDDEN_VOICE_LABELS


def test_levenshtein_examples() -> None:
    assert levenshtein_distance("LLG", "LLZ") == 1
    assert levenshtein_distance("LNZ", "LLZ") == 1
    assert levenshtein_distance("XYZ", "LLZ") == 2  # still > 1, so never corrected
    assert levenshtein_distance("LLZ", "LLZ") == 0
    assert "LLZ" in KNOWN_PRODUCT_CODES and "QIH" in KNOWN_PRODUCT_CODES
