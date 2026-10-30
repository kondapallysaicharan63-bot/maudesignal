"""The retired voice test clip (drop-list wording) is never shown or offered as a fallback."""

from __future__ import annotations

from maudesignal.copilot.transcript import load_transcripts
from maudesignal.dashboard.copilot_pages import (
    DISPLAY_EXCLUDED_LABELS,
    TRANSCRIPT_DIR,
    displayable_transcripts,
)
from maudesignal.dashboard.spend_ui import recorded_fallback


def test_excluded_clips_are_filtered_and_nothing_else() -> None:
    every = load_transcripts(TRANSCRIPT_DIR)
    shown = displayable_transcripts()
    assert {str(t["label"]) for t in shown}.isdisjoint(DISPLAY_EXCLUDED_LABELS)
    assert len(shown) == len(every) - sum(str(t["label"]) in DISPLAY_EXCLUDED_LABELS for t in every)


def test_fallback_never_returns_an_excluded_clip() -> None:
    questions = [
        "Is anything getting worse?",
        "What came in since yesterday?",
        "anything new overnight?",
        "What came in overnight? Is anything worsening?",
        "What changed this week?",
    ]
    for q in questions:
        t = recorded_fallback(q, displayable_transcripts())
        assert t is None or str(t["label"]) not in DISPLAY_EXCLUDED_LABELS, q


def test_one_exclusion_list_covers_the_tts_clips_and_keeps_the_rest() -> None:
    assert set(DISPLAY_EXCLUDED_LABELS) == {
        "00-voice-main",
        "00-voice-a",
        "00-voice-b",
        "00-voice-c",
        "00-voice-e",
    }
    shown = {str(t["label"]) for t in displayable_transcripts()}
    assert {"00-voice-d", "00-voice-take1", "00-voice-take4", "00-voice-take6"} <= shown
