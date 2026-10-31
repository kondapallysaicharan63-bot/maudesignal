"""Tier 2 of the chat (HACKATHON-BUILT): direct answers pass through the claim gate. Offline.

Every number in a direct answer must recompute from the stored records (the same gate that
checks Muse Spark's sentences), every FDA fact must carry its openFDA link, and a number the
stored records do not back is never shown. The quoted LLZ figures (33 reports, weekly average
8.75) stay exactly as stored.
"""

from __future__ import annotations

import copy
import re
from pathlib import Path
from typing import Any

import pytest

from maudesignal.connector.chat import direct_body, direct_tool_answer
from maudesignal.connector.data import ConnectorData
from maudesignal.connector.direct import WITHHELD_REASON, Draft, answer, gate
from maudesignal.connector.forbidden import is_clean
from maudesignal.connector.tiers import BADGE_DIRECT, route
from maudesignal.gate.claims import CountClaim, RecallCountClaim

_NUMBER = re.compile(r"\d")


@pytest.fixture(scope="module")
def data(tmp_path_factory: pytest.TempPathFactory) -> ConnectorData:
    return ConnectorData(work_dir=tmp_path_factory.mktemp("direct"))


def ask(data: ConnectorData, q: str) -> Any:
    r = route(q, data.known_product_codes())
    assert r.tier == "direct", q
    return answer(data, r)


QUESTIONS = [
    "What changed this week?",
    "What changed this week for LLZ?",
    "Any alerts?",
    "Check product code LLZ",
    "Check QIH",
    "Recalls for QIH",
    "Recalls for LLZ",
    "Recalls for POK",
    "Who filed MYN reports?",
    "Who filed LLZ reports?",
    "show report 19864749",
    "show report 1234567",
    "510(k) for K261677",
    "K999999",
    "Show the AI device sweep",
    "my devices",
    "recalls",
    "what changed for LLX",
]


@pytest.mark.parametrize("q", QUESTIONS)
def test_every_direct_answer_is_clean_and_every_fact_is_linked(data: ConnectorData, q: str) -> None:
    a = ask(data, q)
    assert a.sentences, q
    for s in a.sentences:
        assert is_clean(s.text)
        for word in ("approved", "validated", "compliant", " safe ", "unsafe"):
            assert word not in f" {s.text.lower()} "
        if _NUMBER.search(s.text.replace("510(k)", "")):
            assert s.links, f"a sentence with a number has no link: {s.text}"
        for url, label in s.links:
            assert url.startswith("https://") and label
    assert not a.withheld, (q, a.withheld)


def test_llz_figures_are_the_stored_ones_and_gated(data: ConnectorData) -> None:
    a = ask(data, "What changed this week for LLZ?")
    text = a.sentences[0].text
    assert "33 reports received" in text and "weekly average of 8.75" in text
    assert "(35 reports)" in text  # the baseline the average comes from, also recomputed
    urls = [u for u, _ in a.sentences[0].links]
    assert any("20260825" in u and "20260831" in u for u in urls)
    assert any("20260728" in u and "20260824" in u for u in urls)
    assert a.gate_checked == 1


def test_a_number_the_records_do_not_back_is_held_back(data: ConnectorData) -> None:
    good = Draft("The stored snapshot holds 2 recalls for QIH.", [RecallCountClaim("QIH", 2)])
    bad = Draft("The stored snapshot holds 3 recalls for QIH.", [RecallCountClaim("QIH", 3)])
    untagged = Draft("LLZ had 34 reports.", [])  # a number with no claim
    wrong_count = Draft(
        "LLZ had 34 reports.", [CountClaim("LLZ", 34, date_from="20260825", date_to="20260831")]
    )
    shown, withheld, n = gate([good, bad, untagged, wrong_count], data)
    assert [s.text for s in shown] == [good.text]
    assert withheld == [WITHHELD_REASON] * 3 and n == 4


def test_a_changed_digest_number_never_reaches_the_answer(
    data: ConnectorData, tmp_path: Path
) -> None:
    """If the stored digest said 34 for LLZ, the gate recomputes 33 and holds the sentence."""
    d = ConnectorData(work_dir=tmp_path / "w")
    digest = copy.deepcopy(data.digest())
    for s in digest["signals"]:
        if s["product_code"] == "LLZ":
            s["current_count"] = 34
    d._digest = digest
    a = answer(d, route("What changed this week for LLZ?", d.known_product_codes()))
    assert a.sentences == [] and a.withheld == [WITHHELD_REASON]
    body = direct_body(a, 0.0)
    assert "34" not in str(body["answer"])
    assert body["answer"]["withheld"] == [{"reason": WITHHELD_REASON}]


def test_a_wrong_weekly_average_is_held_back(tmp_path: Path, data: ConnectorData) -> None:
    d = ConnectorData(work_dir=tmp_path / "w")
    digest = copy.deepcopy(data.digest())
    for s in digest["signals"]:
        if s["product_code"] == "LLZ":
            s["baseline_weekly_mean"] = 9.5
    d._digest = digest
    a = answer(d, route("What changed this week for LLZ?", d.known_product_codes()))
    assert not any("9.5" in s.text for s in a.sentences)


def test_recall_and_report_ids_are_gated(data: ConnectorData) -> None:
    a = ask(data, "Recalls for QIH")
    assert a.sentences[0].text.startswith("The stored snapshot holds 2 recalls")
    assert any("Z-2767-2026" in s.text for s in a.sentences)
    assert all(s.links for s in a.sentences)
    r = ask(data, "show report 19864749")
    assert r.sentences[0].text.startswith("Report 19864749: product code QIH")
    quote = [s for s in r.sentences if "word for word" in s.text]
    assert quote and quote[0].links
    missing = ask(data, "show report 1234567")
    assert "1234567" not in missing.sentences[0].text  # an unstored id is never stated


def test_code_outside_the_snapshot_opens_the_check_page_without_numbers(
    data: ConnectorData,
) -> None:
    a = ask(data, "Check product code QAS")
    assert a.open == {"view": "check-device", "code": "QAS"}
    assert not any(_NUMBER.search(s.text) for s in a.sentences)


def test_did_you_mean_is_a_question_never_an_answer(data: ConnectorData) -> None:
    a = ask(data, "what changed for LLX")
    assert a.did_you_mean == ["LLZ"]
    assert "Did you mean LLZ?" in a.sentences[0].text
    assert a.suggestions == ["What changed this week for LLZ?"]
    assert not any("33" in s.text for s in a.sentences)


def test_who_filed_uses_source_count_claims(data: ConnectorData) -> None:
    a = ask(data, "Who filed MYN reports?")
    texts = " ".join(s.text for s in a.sentences)
    assert "5 reports for MYN" in texts
    assert "2 manufacturer reports, 3 voluntary reports" in texts
    assert "3 reports were not filed by a manufacturer" in texts


def test_sweep_uses_the_stored_sweep(data: ConnectorData) -> None:
    a = ask(data, "Show the AI device sweep")
    texts = " ".join(s.text for s in a.sentences)
    assert "checked 181 product codes" in texts and "6 of them" in texts
    assert a.open == {"view": "ai-sweep"}


def test_connector_shape_of_a_direct_answer(data: ConnectorData) -> None:
    a = direct_tool_answer(ask(data, "Recalls for QIH"), data)
    assert a.tier == "direct" and a.cost_usd == 0.0 and a.badge == BADGE_DIRECT
    assert a.facts and all(f.link.startswith("https://") for f in a.facts)
    assert a.provenance.kind == "stored_demo_snapshot"
    assert "no AI model" in (a.provenance.note or "")
