"""Chat tier router (HACKATHON-BUILT): which tier a typed question goes to. Offline.

Covers tier 1 (canned: greetings in English, Hindi and Telugu with typos, thanks, bye, help,
"who are you", medical advice, data source, privacy, off-topic), tier 2 (direct: one intent and
at most one product code, report id or K-number) and the rule that open questions, comparisons
and follow-ups still reach Muse Spark (tier 4).
"""

from __future__ import annotations

import pytest

from maudesignal.connector.tiers import (
    BADGE_CACHE,
    BADGE_CANNED,
    BADGE_DIRECT,
    CANNED_INTENTS,
    SUGGESTIONS,
    cacheable,
    canned_sentences,
    normalise,
    route,
)

#: A small stand-in for ``ConnectorData.known_product_codes`` (stored and sweep codes).
KNOWN = frozenset(
    {"LLZ", "QIH", "MYN", "POK", "JAK", "QAS", "QAQ", "MAX", "SIG", "MUD", "MQB", "DSI"}
)

CANNED: list[tuple[str, str]] = [
    # greetings, with typos
    ("hi", "greeting"),
    ("Hi!", "greeting"),
    ("hii", "greeting"),
    ("Hiii!!", "greeting"),
    ("hello", "greeting"),
    ("helo", "greeting"),
    ("helllo", "greeting"),
    ("hey", "greeting"),
    ("hey there", "greeting"),
    ("Hello MaudeSignal", "greeting"),
    ("good morning", "greeting"),
    ("Good evening team", "greeting"),
    ("how are you", "greeting"),
    ("how r u?", "greeting"),
    ("hi, how are you doing?", "greeting"),
    ("whats up", "greeting"),
    # Hindi and Telugu, Latin script and native script
    ("namaste", "greeting"),
    ("Namaste ji", "greeting"),
    ("namastey", "greeting"),
    ("namste", "greeting"),
    ("namaskar", "greeting"),
    ("namaskaram", "greeting"),
    ("Namaskaram garu", "greeting"),
    ("kaise ho", "greeting"),
    ("aap kaise hain?", "greeting"),
    ("ela unnaru", "greeting"),
    ("meeru ela unnaru?", "greeting"),
    ("नमस्ते", "greeting"),
    ("नमस्कार!", "greeting"),
    ("कैसे हो?", "greeting"),
    ("నమస్కారం", "greeting"),
    ("నమస్తే", "greeting"),
    ("ఎలా ఉన్నారు?", "greeting"),
    # thanks and bye
    ("thanks", "thanks"),
    ("Thank you so much!", "thanks"),
    ("thx", "thanks"),
    ("thanku", "thanks"),
    ("dhanyavad", "thanks"),
    ("bye", "bye"),
    ("ok bye", "bye"),
    ("goodbye!", "bye"),
    # about MaudeSignal
    ("who are you?", "who_are_you"),
    ("What is MaudeSignal?", "who_are_you"),
    ("what can you do?", "capabilities"),
    ("help", "capabilities"),
    ("What can I ask?", "capabilities"),
    ("hello, can you help me?", "capabilities"),
    ("Is this medical advice?", "is_medical_advice"),
    ("Where does the data come from?", "data_source"),
    ("what data sources do you use", "data_source"),
    ("Do you store my questions?", "privacy"),
    ("privacy", "privacy"),
    # medical advice, safety judgement, off-topic
    ("Should I stop using my insulin pump?", "medical_advice"),
    ("My mother has a lump, is the scan right?", "medical_advice"),
    ("Is my MRI result normal?", "medical_advice"),
    ("Is LLZ safe?", "safety_judgement"),
    ("is this device safe to use", "safety_judgement"),
    ("tell me a joke", "off_topic"),
    ("What is the weather in Hyderabad?", "off_topic"),
    ("who won the IPL", "off_topic"),
]

DIRECT: list[tuple[str, str, tuple[str, ...]]] = [
    ("What changed this week?", "what_changed", ()),
    ("what's new", "what_changed", ()),
    ("What changed this week for LLZ?", "what_changed", ("LLZ",)),
    ("what changed for llz", "what_changed", ("LLZ",)),
    ("hi, what changed for LLZ?", "what_changed", ("LLZ",)),
    ("Any alerts?", "alerts", ()),
    ("show my alerts", "alerts", ()),
    ("Check product code LLZ", "check_code", ("LLZ",)),
    ("LLZ", "check_code", ("LLZ",)),
    ("tell me about QIH", "check_code", ("QIH",)),
    ("Recalls for QIH", "recalls", ("QIH",)),
    ("any recalls for LLZ?", "recalls", ("LLZ",)),
    ("Who filed LLZ reports?", "who_filed", ("LLZ",)),
    ("who reported MYN", "who_filed", ("MYN",)),
    ("my devices", "my_devices", ()),
    ("show my watchlist", "my_devices", ()),
    ("Show the AI device sweep", "ai_sweep", ()),
    ("AI sweep", "ai_sweep", ()),
    ("show report 19864749", "report", ()),
    ("510(k) for K261677", "k510", ()),
    ("K212067", "k510", ()),
]

LIVE: list[str] = [
    "Why did LLZ reports increase this week?",
    "Compare LLZ and QIH",
    "LLZ vs QIH this week",
    "How many LLZ reports mention software?",
    "What kinds of problems do the LLZ reports describe?",
    "Summarize the injury reports for QIH",
    "Which recalls are related to the LLZ increase and what does that mean for a CAPA?",
    "What is the MDR deadline for report 19864749?",
    "Are there PubMed papers on AI triage failures?",
    "What are the most common problems reported for LLZ?",
    "Draft a short note for my team about this week's LLZ reports",
    "What did MHRA say about radiology software?",
]


@pytest.mark.parametrize(("q", "intent"), CANNED)
def test_canned_phrasings(q: str, intent: str) -> None:
    r = route(q, KNOWN)
    assert (r.tier, r.intent) == ("canned", intent), q
    assert r.suggestions == SUGGESTIONS


@pytest.mark.parametrize(("q", "intent", "codes"), DIRECT)
def test_direct_phrasings(q: str, intent: str, codes: tuple[str, ...]) -> None:
    r = route(q, KNOWN)
    assert (r.tier, r.intent) == ("direct", intent), q
    assert r.product_codes == codes


@pytest.mark.parametrize("q", LIVE)
def test_open_questions_still_reach_muse_spark(q: str) -> None:
    assert route(q, KNOWN).tier == "live", q


def test_there_are_at_least_forty_phrasings() -> None:
    assert len(CANNED) + len(DIRECT) + len(LIVE) >= 40
    assert sum(1 for _q, i in CANNED if i == "greeting") >= 25


def test_report_and_k_number_are_read() -> None:
    assert route("show report 19864749", KNOWN).report_id == "19864749"
    assert route("510(k) for k261677", KNOWN).k_number == "K261677"


def test_unclear_code_offers_did_you_mean_and_never_applies_it() -> None:
    r = route("what changed for LLX", KNOWN)
    assert (r.tier, r.intent) == ("direct", "did_you_mean")
    assert r.unclear_codes == ("LLX",) and r.product_codes == ()
    assert r.suggestions == ("What changed this week for LLZ?",)
    r = route("QAH", KNOWN)
    assert r.intent == "did_you_mean"
    assert set(r.suggestions) == {
        "Check product code QAS",
        "Check product code QAQ",
        "Check product code QIH",
    }


def test_unknown_code_with_no_close_match_is_a_check_of_that_code() -> None:
    r = route("check ZZZ", KNOWN)
    assert (r.tier, r.intent, r.unclear_codes) == ("direct", "check_code", ("ZZZ",))


def test_lower_case_english_words_are_not_codes() -> None:
    # "max", "sig" are product codes, but only when written in capitals
    assert route("what is the max for this", KNOWN).product_codes == ()
    assert route("Recalls for MAX", KNOWN).product_codes == ("MAX",)
    assert route("FDA recalls for QIH", KNOWN).product_codes == ("QIH",)


def test_chosen_product_code_fills_in_a_question_without_one() -> None:
    r = route("What changed this week?", KNOWN, product_code="QIH")
    assert (r.tier, r.intent, r.product_codes) == ("direct", "what_changed", ("QIH",))
    # a greeting stays a greeting whatever code is chosen
    assert route("hi", KNOWN, product_code="LLZ").tier == "canned"


def test_follow_ups_without_a_subject_go_to_muse_spark() -> None:
    q = "Which were not filed by the manufacturer?"
    assert route(q, KNOWN).tier == "direct"  # a first question: "which product code?"
    assert route(q, KNOWN, has_history=True).tier == "live"
    assert route("recalls for those", KNOWN).tier == "live"
    assert route("Recalls for QIH", KNOWN, has_history=True).tier == "direct"


def test_code_less_lookup_asks_which_code() -> None:
    r = route("recalls", KNOWN)
    assert (r.tier, r.intent, r.product_codes) == ("direct", "recalls", ())


def test_normalise_matches_spelling_variants() -> None:
    assert normalise("Hi!!  What's NEW?") == normalise("hi whats new")
    assert normalise("नमस्ते!") == "नमस्ते"  # vowel signs (combining marks) are kept


def test_canned_text_has_no_fda_facts_and_no_banned_words() -> None:
    from maudesignal.connector.forbidden import is_clean

    for intent in CANNED_INTENTS:
        for sentence in canned_sentences(intent):
            assert is_clean(sentence)
            assert not any(c.isdigit() for c in sentence.replace("510(k)", "")), sentence
            low = sentence.lower()
            for word in ("approved", "validated", "compliant", " safe ", "unsafe"):
                assert word not in f" {low} ", (intent, sentence)
    assert canned_sentences("medical_advice")[0] == (
        "I can't give medical advice — please ask a clinician."
    )


def test_badges() -> None:
    assert BADGE_CANNED == "No FDA facts in this message"
    assert BADGE_DIRECT == "Direct FDA lookup — no AI"
    assert BADGE_CACHE == "Answered earlier today"


def test_cacheable() -> None:
    q = "Why did LLZ reports increase?"
    assert cacheable(q, route(q, KNOWN), has_history=False)
    assert cacheable(q, route(q, KNOWN), has_history=True)  # names its subject
    f = "why did that happen?"
    assert cacheable(f, route(f, KNOWN), has_history=False)
    assert not cacheable(f, route(f, KNOWN), has_history=True)  # points back
