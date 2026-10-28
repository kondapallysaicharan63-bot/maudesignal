"""The hand-check worksheet: rates from transcripts, evidence lookup, verdicts kept."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("hand_check", ROOT / "scripts" / "hand_check.py")
assert _spec and _spec.loader
hand_check = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(hand_check)


def _t(label: str, fp: tuple[int, int], fin: tuple[int, int], repaired: bool) -> dict[str, Any]:
    sentence = {
        "text": "LLZ had 33 reports | this week.",
        "status": "pass",
        "reasons": [],
        "claims": [{"kind": "count", "status": "pass", "evidence_ids": ["50426770", "K261677"]}],
    }
    return {
        "label": label,
        "question": "q?",
        "model": "muse-spark-1.3",
        "tool_calls": [{"name": "overnight_signals"}],
        "first_pass": {"passed": fp[0], "blocked": fp[1], "sentences": []},
        "final": {"passed": fin[0], "blocked": fin[1], "sentences": [sentence]},
        "repaired": repaired,
        "usage": {"cost_usd": 0.0125},
    }


def test_rates_lookup_and_verdicts_survive_regeneration(tmp_path: Path) -> None:
    ts = [_t("01-a", (3, 1), (4, 0), True), _t("02-b", (2, 0), (2, 0), False)]
    known = {"50426770": "MAUDE report (LLZ)"}
    md = hand_check.build(ts, known, {})
    assert "first pass: 5/6 (83.3%)" in md
    assert "final (after at most one repair turn): 6/6 (100.0%)" in md
    assert "Answers with nothing blocked, first pass: 1/2; final: 2/2" in md
    assert "Answers that used the repair turn: 1" in md
    assert "Recorded model cost: $0.0250" in md
    assert "50426770 (MAUDE report (LLZ)); K261677 (not a stored record)" in md
    assert "LLZ had 33 reports \\| this week." in md  # table-safe
    assert "pending 2" in md

    out = tmp_path / "HAND_CHECK.md"
    out.write_text(md.replace("| pending |", "| ok — matches report |", 1), encoding="utf-8")
    again = hand_check.build(ts, known, hand_check._old_verdicts(out))
    assert "| 01-a#1 |" in again and "ok — matches report |" in again
    assert "ok 1" in again and "pending 1" in again


def test_a_re_recorded_sentence_is_checked_again(tmp_path: Path) -> None:
    ts = [_t("01-a", (1, 0), (1, 0), False)]
    out = tmp_path / "HAND_CHECK.md"
    md = hand_check.build(ts, {}, {})
    out.write_text(md.replace("| pending |", "| correct — ok |", 1), encoding="utf-8")
    new = [_t("01-a", (1, 0), (1, 0), False)]
    new[0]["final"]["sentences"][0]["text"] = "LLZ had 50 reports this week."
    again = hand_check.build(new, {}, hand_check._old_verdicts(out))
    assert "correct — ok" not in again and "pending 1" in again
    assert "Answers hand-checked" not in again


def test_empty_transcripts() -> None:
    assert "No recorded transcripts yet" in hand_check.build([], {}, {})


def test_prefixed_ids_resolve_to_stored_records() -> None:
    """2026-10-28 recording: the model cited "PMID 35943350" and "recall Z-2543-2025"."""
    known = {"35943350": "PubMed", "Z-2543-2025": "recall"}
    assert hand_check._describe(known, "PMID 35943350") == "PubMed"
    assert hand_check._describe(known, "recall Z-2543-2025") == "recall"
    assert hand_check._describe(known, "21 CFR 803.53") == "not a stored record"
