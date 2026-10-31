"""Chat tiers, review fixes (HACKATHON-BUILT). Offline.

1. Regulatory "should we ..." questions are never refused as medical advice.
2. A qualifier the templates do not apply (a year, a month, since/before, last year, class I,
   by manufacturer, open recalls, compare ...) sends the question to Muse Spark.
3. A no-digit factual sentence without a claim is still listed as held back.
4. The cache key carries the data version; fully withheld answers are not cached; the demo key
   never receives a cached live answer.
5. First-person medical questions without a product code get the fixed medical reply.
6. The privacy reply says open questions go to Meta's Muse Spark and the text is not stored.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from maudesignal.connector.answer_cache import AnswerCache, cache_key
from maudesignal.connector.ask import ask, is_connective
from maudesignal.connector.chat import ask_with_tiers, has_fact
from maudesignal.connector.data import ConnectorData
from maudesignal.connector.store import ConnectorState
from maudesignal.connector.tiers import canned_sentences, is_medical, normalise, route
from tests.unit.test_chat_tiers_routes import LIVE_SENTENCES, OPEN, Counting
from tests.unit.test_connector_safety import LLZ_33, OneAnswerClient, live_rt

KNOWN = frozenset({"LLZ", "QIH", "MYN", "POK", "JAK", "QAS"})

REGULATORY_NOT_MEDICAL = [
    "Should we start a CAPA for LLZ?",
    "Should I worry about the LLZ spike?",
    "Should we use LLZ devices given the recalls?",
    "Should we file an MDR for this report?",
    "Should I escalate the QIH complaints?",
    "Should we stop using QIH while the recall is open?",
    "Is it safe to close the CAPA for LLZ?",
    "Should my team review the MAUDE reports for MYN?",
]


@pytest.mark.parametrize("q", REGULATORY_NOT_MEDICAL)
def test_regulatory_should_questions_are_not_medical(q: str) -> None:
    r = route(q, KNOWN)
    assert r.intent != "medical_advice", q
    assert r.tier == "live", q


MEDICAL = [
    "Is it safe for me to get an MRI with my pacemaker?",
    "Can you diagnose this rash?",
    "is this device dangerous for kids",
    "Should I stop using my insulin pump?",
    "What dose should my mother take?",
    "Is my CT scan normal?",
    "is it safe for my baby",
]


@pytest.mark.parametrize("q", MEDICAL)
def test_first_person_medical_questions_get_the_fixed_reply(q: str) -> None:
    r = route(q, KNOWN)
    assert (r.tier, r.intent) == ("canned", "medical_advice"), q


def test_medical_rule_needs_a_body_word_and_no_regulatory_word() -> None:
    assert is_medical(normalise("can you diagnose this rash"))
    assert not is_medical(normalise("can you diagnose this signal"))
    assert not is_medical(normalise("is it dangerous for my team"), has_code=True)
    # a code or a regulatory word always wins (coordinator decision, round 4)
    assert not is_medical(normalise("is it safe for me"), has_code=True)
    assert is_medical(normalise("is it safe for me"))


QUALIFIED = [
    "How many LLZ recalls are class I?",
    "LLZ recalls in 2019",
    "what changed for LLZ last year",
    "Recalls for LLZ since March",
    "recalls for QIH before 2024",
    "LLZ reports between July and August",
    "what changed for LLZ in the past 3 months",
    "recalls for LLZ by manufacturer",
    "open recalls for QIH",
    "most recent class II recalls for LLZ",
    "who filed LLZ reports last quarter",
    "LLZ reports from 2025",
    "what changed last week",
]


@pytest.mark.parametrize("q", QUALIFIED)
def test_qualified_questions_go_to_muse_spark(q: str) -> None:
    assert route(q, KNOWN).tier == "live", q


@pytest.mark.parametrize(
    "q",
    ["Recalls for QIH", "What changed this week for LLZ?", "Open report 19864749", "K261677"],
)
def test_plain_lookups_stay_direct(q: str) -> None:
    assert route(q, KNOWN).tier == "direct", q


def test_factual_sentence_without_a_claim_is_still_held_back(tmp_path: Path) -> None:
    assert not is_connective("Based on the records, the device was recalled for software failure.")
    assert not is_connective("Here is what I found for LLZ.")
    assert is_connective("Here is what I found.")
    d = ConnectorData(work_dir=tmp_path / "w")
    client = OneAnswerClient(
        [
            {"text": "LLZ had 33 reports from August 25 to August 31, 2026.", "claims": [LLZ_33]},
            {
                "text": "Based on the records, the device was recalled for software failure.",
                "claims": [],
            },
        ]
    )
    a = ask(d, "Why did LLZ increase?", key_id="abc", runtime=live_rt(tmp_path, client))
    assert "software failure" not in a.speakable
    assert len(a.withheld) == 1 and "no openFDA or record link" in a.withheld[0].reason


def test_cache_key_carries_the_data_version(tmp_path: Path) -> None:
    assert cache_key("live", "q a", None, "v1") != cache_key("live", "q a", None, "v2")
    st = ConnectorState()
    version = ["v1"]
    cache = AnswerCache(st, "live", version=lambda: version[0])
    cache.put("why did it rise", None, {"answer": {}})
    assert cache.get("why did it rise") is not None
    version[0] = "v2"  # a new snapshot: the old answer is not reused
    assert cache.get("why did it rise") is None
    d = ConnectorData(work_dir=tmp_path / "w")
    assert d.version() == d.version() and len(d.version()) == 12


def test_fully_withheld_answers_are_not_cached() -> None:
    assert not has_fact({"answer": {"speakable": [{"text": "I could not verify", "links": []}]}})
    assert has_fact({"answer": {"speakable": [{"text": "x", "links": [{"url": "https://a"}]}]}})


def _connector_ask(
    tmp_path: Path, client: Any, cache: AnswerCache, *, allow_live: bool = True
) -> Any:
    return ask_with_tiers(
        ConnectorData(work_dir=tmp_path / "w"),
        OPEN,
        key_id="k",
        runtime=live_rt(tmp_path, client),
        cache=cache,
        allow_live=allow_live,
    )


def test_connector_does_not_cache_an_answer_with_nothing_verified(tmp_path: Path) -> None:
    cache = AnswerCache(ConnectorState(), "tool")
    blocked = Counting([{"text": "LLZ had 34 reports.", "claims": []}])
    first = _connector_ask(tmp_path, blocked, cache)
    assert first.tier == "live" and not first.facts
    assert cache.get(OPEN) is None


def test_demo_key_never_gets_a_cached_live_answer(tmp_path: Path) -> None:
    cache = AnswerCache(ConnectorState(), "tool")
    model = Counting(LIVE_SENTENCES)
    live = _connector_ask(tmp_path, model, cache)
    assert live.tier == "live" and live.provenance.kind == "live_model"
    assert cache.get(OPEN) is not None
    demo = _connector_ask(tmp_path / "demo", model, cache, allow_live=False)
    assert demo.tier == "live" and demo.provenance.kind != "live_model"


def test_privacy_reply_says_what_goes_to_meta_and_what_is_kept() -> None:
    text = " ".join(canned_sentences("privacy"))
    assert "Muse Spark" in text and "Meta" in text
    assert "does not store the question text" in text
    assert "When live answers are on" in text  # never claims a call when live is off


# --- round 3: allow-list for tier 2 ------------------------------------------------------------

LEFTOVER = [
    "First recall for LLZ",
    "Recalls by Abbott for LLZ",
    "Recalls for LLZ this year",
    "LLZ recalls this week",
    "Newest LLZ recalls",
    "LLZ recalls older than a year",
    "Show the 3 recalls for LLZ",
    "LLZ recalls ఈ సంవత్సరం",
    "Who filed LLZ reports this year",
    "What changed for LLZ this month",
    # decided: tier 4 (the who-filed template has no split by source)
    "Who filed the LLZ reports from user facilities?",
    "LLZ recalls by year",
    "latest 5 recalls for QIH",
    "QIH recalls कृपया 2020",
]


@pytest.mark.parametrize("q", LEFTOVER)
def test_any_word_the_template_ignores_sends_the_question_to_muse_spark(q: str) -> None:
    assert route(q, KNOWN).tier == "live", q


#: Every plain lookup from the cost sample and the router tests: still answered directly.
TIER_TWO = [
    "What changed this week?",
    "What changed this week for LLZ?",
    "what changed for llz",
    "what's new",
    "hi, what changed for LLZ?",
    "Any alerts?",
    "show my alerts",
    "Check product code QIH",
    "Check product code LLZ",
    "LLZ",
    "tell me about QIH",
    "Recalls for LLZ",
    "Recalls for QIH",
    "any recalls for LLZ?",
    "FDA recalls for QIH",
    "Who filed MYN reports?",
    "who reported MYN",
    "show report 19864749",
    "Open report 19864749",
    "510(k) for K261677",
    "K212067",
    "Show the AI device sweep",
    "AI sweep",
    "my devices",
    "show my watchlist",
    "recalls",
    "what changed for LLX",
    "QAH",
    "Recalls for QIH please",
    "LLZ recalls ji",
]


@pytest.mark.parametrize("q", TIER_TWO)
def test_plain_lookups_still_hit_tier_two(q: str) -> None:
    assert route(q, KNOWN | {"MAX"}).tier == "direct", q


def test_leftover_lists_what_a_template_would_ignore() -> None:
    from maudesignal.connector.tiers import leftover

    assert leftover(normalise("first recall for llz"), "recalls", ["LLZ"], None, None) == ["first"]
    assert leftover(normalise("recalls for llz"), "recalls", ["LLZ"], None, None) == []
    assert leftover(normalise("llz recalls this week"), "recalls", ["LLZ"], None, None) == [
        "this",
        "week",
    ]


# --- round 3: strong first-person medical patterns ----------------------------------------------

STRONG_MEDICAL = [
    "Can you diagnose this rash?",
    "Is it safe for me to get an MRI with my pacemaker?",
    # CGM is not a known product code; after "my" it is read as a personal device
    "Should I stop using my CGM?",
    "I have chest pain after my MRI, what should I do?",
    "Should I get surgery for my pacemaker?",
    "Is this safe for my baby?",
]


@pytest.mark.parametrize("q", STRONG_MEDICAL)
def test_strong_first_person_medical_wins(q: str) -> None:
    r = route(q, KNOWN)
    assert (r.tier, r.intent) == ("canned", "medical_advice"), q


@pytest.mark.parametrize(
    "q",
    [
        "Should we start a CAPA for LLZ?",
        "What should I do about the LLZ spike?",
        "Should we stop shipping QIH until the recall closes?",
    ],
)
def test_team_and_regulatory_questions_stay_tier_four(q: str) -> None:
    assert route(q, KNOWN).tier == "live", q


#: Round 4: a code, an id or a regulatory word sends these to Muse Spark (its prompt declines
#: medical advice). The first three were refused as medical in round 3; they now go to tier 4
#: on purpose.
REGULATORY_WINS = [
    "My pacemaker was recalled, should I get surgery?",
    "Is my insulin pump that was recalled safe for me?",
    "I have a fever since the LLZ scan, should I go to the hospital?",
    "We have a spike in burn reports for QIH; what should I do?",
    "What should I do about the rash of complaints for LLZ?",
    "Is the recall fix safe for my team to deploy?",
    "Is this safe for my workflow?",
    "Should I get a new one of these LLZ systems for our clinic?",
    "Should I stop using QAH?",
]


@pytest.mark.parametrize("q", REGULATORY_WINS)
def test_code_id_or_regulatory_word_wins_over_medical(q: str) -> None:
    assert route(q, KNOWN | {"HGM"}).tier == "live", q


@pytest.mark.parametrize(
    "q",
    [
        "How many recalls for LLZ?",
        "number of recalls for LLZ",
        "total recalls for QIH",
        "LLZ recalls dikhao",
        "QIH recalls chupinchandi",
        "any warnings?",
    ],
)
def test_more_plain_lookups_hit_tier_two(q: str) -> None:
    assert route(q, KNOWN).tier == "direct", q


@pytest.mark.parametrize("q", ["is LLZ ok", "show all recalls for LLZ", "ok recalls for QIH"])
def test_all_and_ok_are_not_filler(q: str) -> None:
    assert route(q, KNOWN).tier == "live", q


def test_recall_total_template_states_the_total(tmp_path: Path) -> None:
    from maudesignal.connector.direct import answer

    d = ConnectorData(work_dir=tmp_path / "w")
    a = answer(d, route("How many recalls for QIH?", d.known_product_codes()))
    assert a.sentences[0].text.startswith(
        "The stored snapshot holds 2 recalls for product code QIH"
    )


# --- round 3: filler is narrow, facts first ---------------------------------------------------

HELD_BACK = [
    "A named human must review the deaths reported for this scanner.",
    "This is not medical advice; stop using the device immediately.",
    "The scanner was withdrawn.",
    "The tool misread images.",
    "Overall, the system failed twice.",
    "Here is what happened to the pump.",
    "The scanner became unusable.",
]


@pytest.mark.parametrize("t", HELD_BACK)
def test_factual_sentences_are_never_filler(t: str) -> None:
    assert not is_connective(t), t


@pytest.mark.parametrize(
    "t",
    [
        "Here is what I found.",
        "A named human must review this.",
        "Not medical advice.",
        "Nothing is filed with FDA.",
        "I checked the stored records.",
        "Overall, a good question.",
    ],
)
def test_short_transitions_and_advisory_lines_are_filler(t: str) -> None:
    assert is_connective(t), t
