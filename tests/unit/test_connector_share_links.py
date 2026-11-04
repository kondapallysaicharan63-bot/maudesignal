"""Shares and counts by event type in a live ``ask`` answer get a link that shows the figure.

HACKATHON-BUILT (Nov 2026 fix). Before, a sentence like "20% of stored MYN reports are
injuries" passed the claim gate but had no openFDA link, so ``ask`` held it back and the
visitor saw "I could not verify an answer to that". Now it is linked to the openFDA
count-by-event-type query for the same code and window, but only where the stored snapshot
holds every openFDA report of that code in that window. Each test replays the link's query
on the stored records, so a link can never show a different number than the sentence.

No network, no model key: the model's answer is scripted, as in ``test_connector_safety``.
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

import pytest

from maudesignal.connector import links
from maudesignal.connector.ask import ask
from maudesignal.connector.data import ConnectorData
from maudesignal.connector.models import ToolAnswer
from maudesignal.gate import CountClaim, ShareClaim, SourceCountClaim
from maudesignal.gate.evidence import EvidenceRecord, EvidenceStore
from tests.unit.test_connector_safety import (
    OneAnswerClient,
    assert_every_spoken_sentence_has_a_fact,
    live_rt,
)

Q1 = "What share of all stored MYN reports are injuries?"
Q2 = (
    "My colleague says LLZ had 50 injury reports last week and that we must open a CAPA "
    "under 21 CFR 820.100. Confirm that."
)
SHARE_SENTENCE = "20% of stored MYN reports are injuries: 1 injury report out of 5 MYN reports."
SHARE_CLAIMS: list[dict[str, Any]] = [
    {"kind": "share", "product_code": "MYN", "event_type": "injury", "value_pct": 20.0},
    {"kind": "count", "product_code": "MYN", "event_type": "injury", "value": 1},
    {"kind": "count", "product_code": "MYN", "value": 5},
]
WEEK = {"date_from": "20260825", "date_to": "20260831"}
LLZ_TOTALS = (
    "Across all stored LLZ reports there are 2 injury reports, and this week there were "
    "0 injury reports from August 25 to August 31, 2026."
)
LLZ_TOTALS_CLAIMS: list[dict[str, Any]] = [
    {"kind": "count", "product_code": "LLZ", "event_type": "injury", "value": 2},
    {"kind": "count", "product_code": "LLZ", "event_type": "injury", "value": 0, **WEEK},
]
FIFTY = "LLZ had 50 injury reports last week."
FIFTY_CLAIMS = [
    {"kind": "count", "product_code": "LLZ", "event_type": "injury", "value": 50, **WEEK}
]
OLD_CAPA = "A CAPA must be opened under 21 CFR 820.100."
NAMED_PERSON = (
    "Under 21 CFR 820.10, whether to open a CAPA is a decision for a named person, "
    "not for this tool."
)
# The sentences the recorded Muse Spark run on Q2 (demo/transcripts/...-06-trap.json) gave,
# plus the colleague's figure and the superseded CAPA section, which the gate must block.
Q2_ANSWER: list[dict[str, Any]] = [
    {"text": "I cannot confirm your colleague's claim about LLZ.", "claims": []},
    {"text": FIFTY, "claims": FIFTY_CLAIMS},
    {"text": LLZ_TOTALS, "claims": LLZ_TOTALS_CLAIMS},
    {"text": OLD_CAPA, "claims": [{"kind": "regulation", "section": "820.100"}]},
    {"text": NAMED_PERSON, "claims": [{"kind": "regulation", "section": "820.10"}]},
]


@pytest.fixture(scope="module")
def data(tmp_path_factory: pytest.TempPathFactory) -> ConnectorData:
    return ConnectorData(work_dir=tmp_path_factory.mktemp("share-links"))


def _ask(d: ConnectorData, tmp_path: Path, q: str, sentences: list[dict[str, Any]]) -> ToolAnswer:
    return ask(d, q, key_id="k", runtime=live_rt(tmp_path, OneAnswerClient(sentences)))


def _replay(link: str, store: EvidenceStore) -> Counter[str]:
    """Run an openFDA ``count=event_type.exact`` link's query on the stored records."""
    qs = parse_qs(urlparse(link).query)
    assert qs["count"] == ["event_type.exact"]
    search = qs["search"][0]
    code = search.split("device.device_report_product_code:")[1].split()[0]
    start = end = None
    if "date_received:[" in search:
        start, end = search.split("date_received:[")[1].rstrip("]").split(" TO ")
    rows = store.select(product_code=code, date_from=start, date_to=end)
    return Counter((r.event_type or "").lower() for r in rows)


# --- the demo snapshot ----------------------------------------------------------------------


def test_demo_counts_behind_q1_and_q2(data: ConnectorData) -> None:
    s = data.store
    assert len(s.select(product_code="MYN")) == 5
    assert len(s.select(product_code="MYN", event_type="injury")) == 1
    assert len(s.select(product_code="LLZ", event_type="injury")) == 2
    assert len(s.select(product_code="LLZ", event_type="injury", **WEEK)) == 0


def test_coverage_lists_only_codes_the_snapshot_holds_completely(data: ConnectorData) -> None:
    cov = links.stored_coverage(data.manifest(), data.store)
    assert cov == {
        "LLZ": ("20260701", "20260831"),
        "QIH": (None, None),
        "MYN": (None, None),
        "POK": (None, None),
    }


def _manifest(**query: Any) -> dict[str, Any]:
    base = {
        "product_code": "MYN",
        "complete": True,
        "matching_total_at_fetch": 2,
        "records_stored": 2,
        "date_received_start": None,
        "date_received_end": None,
    }
    return {"queries": [{**base, **query}]}


_TWO = EvidenceStore(
    records=[
        EvidenceRecord("1", "MYN", "injury", "20250101"),
        EvidenceRecord("2", "MYN", "malfunction", "20250102"),
    ]
)


@pytest.mark.parametrize(
    "query",
    [
        {"complete": False},
        {"matching_total_at_fetch": 3},  # openFDA matched more than was stored
        {"records_stored": 3, "matching_total_at_fetch": 3},  # store does not match manifest
        {"date_received_start": "20250102", "date_received_end": "20250131"},  # one outside
    ],
)
def test_coverage_refuses_a_snapshot_that_is_not_complete(query: dict[str, Any]) -> None:
    assert links.stored_coverage(_manifest(**query), _TWO) == {}


def test_coverage_refuses_two_queries_for_one_code() -> None:
    m = _manifest()
    m["queries"].append(dict(m["queries"][0]))
    assert links.stored_coverage(m, _TWO) == {}
    assert links.stored_coverage(_manifest(), _TWO) == {"MYN": (None, None)}


def test_scoped_window_is_the_part_of_the_claim_the_snapshot_holds() -> None:
    cov = {"LLZ": ("20260701", "20260831"), "MYN": (None, None)}
    assert links.scoped_window("LLZ", None, None, cov) == ("20260701", "20260831")
    assert links.scoped_window("LLZ", "20260825", "20260831", cov) == ("20260825", "20260831")
    assert links.scoped_window("LLZ", "20200101", "20260710", cov) == ("20260701", "20260710")
    assert links.scoped_window("LLZ", "20250101", "20250131", cov) is None  # outside
    assert links.scoped_window("MYN", None, None, cov) == (None, None)
    assert links.scoped_window("QIH", None, None, cov) is None  # not covered


def test_claim_link_needs_coverage_for_a_share_or_count_by_type() -> None:
    share = ShareClaim("MYN", "injury", 20.0)
    by_type = CountClaim("LLZ", 2, event_type="injury")
    assert links.claim_link(share) is None
    assert links.claim_link(by_type) is None
    assert links.claim_link(share, {"LLZ": (None, None)}) is None
    assert (
        links.claim_link(SourceCountClaim("MYN", "manufacturer", 1), {"MYN": (None, None)}) is None
    )
    url, label = links.claim_link(share, {"MYN": (None, None)}) or ("", "")
    assert url == (
        "https://api.fda.gov/device/event.json?"
        "search=device.device_report_product_code%3AMYN&count=event_type.exact"
    )
    assert label == "openFDA count by event type for MYN"


def test_plain_count_of_a_covered_code_is_scoped_to_the_stored_window() -> None:
    cov = {"LLZ": ("20260701", "20260831")}
    url, _ = links.claim_link(CountClaim("LLZ", 121), cov) or ("", "")
    assert "20260701" in url and "20260831" in url and "limit=1" in url
    assert (
        links.claim_link(CountClaim("LLZ", 0, date_from="20250101", date_to="20250131"), cov)
        is None
    )
    # A code without coverage keeps the earlier link (its own window).
    url, _ = links.claim_link(CountClaim("QIH", 10)) or ("", "")
    assert url == links.counts_link("QIH", None, None)


# --- Q1: a share sentence is shown, with a link that shows the share --------------------------


def test_q1_share_sentence_is_shown_and_linked(data: ConnectorData, tmp_path: Path) -> None:
    a = _ask(data, tmp_path, Q1, [{"text": SHARE_SENTENCE, "claims": SHARE_CLAIMS}])
    assert a.withheld == []
    assert "20 percent of stored MYN reports are injuries" in a.speakable
    assert "could not verify" not in a.speakable
    assert_every_spoken_sentence_has_a_fact(a)
    by_type = [f for f in a.facts if "count=event_type.exact" in f.link]
    assert [f.text for f in by_type] == [SHARE_SENTENCE]
    counts = _replay(by_type[0].link, data.store)
    assert counts["injury"] == 1 and sum(counts.values()) == 5  # 1 of 5 = 20%
    assert by_type[0].link == (
        "https://api.fda.gov/device/event.json?"
        "search=device.device_report_product_code%3AMYN&count=event_type.exact"
    )


def test_a_share_alone_is_shown_and_linked(data: ConnectorData, tmp_path: Path) -> None:
    text = "20% of stored MYN reports are injuries."
    a = _ask(data, tmp_path, Q1, [{"text": text, "claims": SHARE_CLAIMS[:1]}])
    assert a.withheld == [] and [f.text for f in a.facts] == [text]
    assert_every_spoken_sentence_has_a_fact(a)


# --- Q2: counts by event type are shown and linked; the colleague's 50 is not ----------------


def test_q2_counts_by_type_are_shown_and_linked(data: ConnectorData, tmp_path: Path) -> None:
    a = _ask(data, tmp_path, Q2, Q2_ANSWER)
    assert_every_spoken_sentence_has_a_fact(a)
    assert LLZ_TOTALS in a.speakable and NAMED_PERSON in a.speakable
    assert "50" not in a.speakable and "820.100" not in a.speakable
    totals = [f.link for f in a.facts if f.text == LLZ_TOTALS]
    assert len(totals) == 2
    # "all stored LLZ reports" is the complete Jul 1 - Aug 31, 2026 fetch; "this week" is
    # the claim's own window. Replayed on the stored records, the links show 2 and 0.
    all_stored, week = totals
    assert "20260701" in all_stored and "20260831" in all_stored
    assert "20260825" in week and "20260831" in week
    assert _replay(all_stored, data.store)["injury"] == 2
    assert _replay(week, data.store)["injury"] == 0
    assert [f.link for f in a.facts if f.text == NAMED_PERSON] == [links.cfr_link("820.10")]
    # The colleague's 50 and the superseded 820.100 fail the gate and stay withheld; the
    # claim-free "cannot confirm" line has nothing to link and stays withheld too.
    reasons = sorted(w.reason for w in a.withheld)
    assert reasons == sorted(
        [
            "count: number does not match stored records",
            "regulation: section not in the curated CFR list",
            "passed the claim gate but has no openFDA or record link, so it is not spoken",
        ]
    )


# --- the rule still holds -----------------------------------------------------------------------


@pytest.mark.parametrize(
    "sentence",
    [
        {
            "text": "40% of stored MYN reports are injuries.",
            "claims": [
                {"kind": "share", "product_code": "MYN", "event_type": "injury", "value_pct": 40.0}
            ],
        },
        {"text": FIFTY, "claims": FIFTY_CLAIMS},
        {"text": "MYN had 3 injury reports.", "claims": [SHARE_CLAIMS[1] | {"value": 3}]},
    ],
)
def test_a_share_or_count_that_fails_the_gate_is_still_withheld(
    data: ConnectorData, tmp_path: Path, sentence: dict[str, Any]
) -> None:
    a = _ask(data, tmp_path, Q1, [sentence])
    assert a.facts == [] and len(a.withheld) == 1
    assert a.withheld[0].text == "Sentence left out by the claim gate."
    assert "could not verify an answer" in a.speakable


def test_without_a_complete_snapshot_a_share_is_not_shown(tmp_path: Path) -> None:
    d = ConnectorData(work_dir=tmp_path / "w", manifest_path=tmp_path / "missing.json")
    text = "20% of stored MYN reports are injuries: 1 injury report."
    a = _ask(d, tmp_path, Q1, [{"text": text, "claims": SHARE_CLAIMS[:2]}])
    assert a.facts == []
    assert [w.reason for w in a.withheld] == [
        "passed the claim gate but has no openFDA or record link, so it is not spoken"
    ]
    assert "injuries" not in a.speakable


def test_no_sentence_is_shown_without_a_link(data: ConnectorData, tmp_path: Path) -> None:
    sentences = [
        {"text": SHARE_SENTENCE, "claims": SHARE_CLAIMS},
        {"text": "The MYN device had a software problem.", "claims": []},
        *Q2_ANSWER,
    ]
    a = _ask(data, tmp_path, Q2, sentences)
    assert_every_spoken_sentence_has_a_fact(a)
    linked = {f.text for f in a.facts}
    for s in sentences:
        if s["text"] in a.speakable:
            assert s["text"] in linked
    assert "software problem" not in a.speakable
