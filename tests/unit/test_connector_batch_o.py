"""Tests for the O-api batch (HACKATHON-BUILT). No network, no model key.

Covers: the durable global cost ledger in the private Blob store (reserve before the call,
settle after, fail closed, cold start, concurrency), the keyed ask counted against it, name
redaction, the outside-mentions endpoint and its quote gate, the demo key and labelled keys,
/v1/connect, the /privacy and /terms pages, and malformed input.
"""

from __future__ import annotations

import json
import threading
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("fastapi")

from maudesignal.connector import mentions as mn  # noqa: E402
from maudesignal.connector.blob_store import (  # noqa: E402
    BlobRef,
    ObjectGoneError,
    StoreError,
)
from maudesignal.connector.forbidden import forbidden_in  # noqa: E402
from maudesignal.connector.live import LiveConfig  # noqa: E402
from tests.unit.test_connector import (
    KEY,
)  # noqa: E402
from tests.unit.test_connector_live import (  # noqa: E402
    ORIGIN,
    Env,
)

DAY = date(2026, 10, 30)
ADMIN = "admin-key-NOT-REAL-0123456789"
ORIGINS = frozenset({ORIGIN})

# Words the task forbids on any page or doc, as whole words (a superset of forbidden.py).
DROP_WORDS = (
    "FDA-approved",
    "Part 11 compliant",
    "validated",
    "overnight",
    "worsening signals",
    "citation-checked",
    "complaint data",
    "safe",
    "unsafe",
    "compliant",
    "approved",
)


def has_drop_word(text: str) -> list[str]:
    import re

    return [
        w for w in DROP_WORDS if re.search(rf"(?<![A-Za-z]){re.escape(w)}(?![A-Za-z])", text, re.I)
    ]


class FakeBlobStore:
    """A private-Blob-like store: overwrite honoured, failures and races injectable."""

    backend = "blob_private"

    def __init__(self) -> None:
        self.items: dict[str, bytes] = {}
        self.lock = threading.Lock()
        self.fail_list = self.fail_put = self.fail_get = self.fail_overwrite = False
        self.fail_delete = False
        self.after_put: Any = None
        self.after_list: Any = None
        self.puts = 0
        self.overwrites = 0
        self._seeds = 0
        self.gets = 0

    def put_json(self, pathname: str, record: dict[str, Any], *, overwrite: bool = False) -> None:
        if self.fail_put:
            raise StoreError("blob store unreachable")
        with self.lock:
            if pathname in self.items and not overwrite:
                raise StoreError("exists")
            self.items[pathname] = json.dumps(record, sort_keys=True).encode()
            self.puts += 1
        if self.after_put:
            self.after_put(pathname)

    def overwrite_json(self, pathname: str, record: dict[str, Any]) -> None:
        if self.fail_overwrite:
            raise StoreError("blob store unreachable")
        with self.lock:
            self.items[pathname] = json.dumps(record, sort_keys=True).encode()
            self.overwrites += 1

    def list_prefix(self, prefix: str, *, strict: bool = False) -> list[BlobRef]:
        if self.fail_list:
            raise StoreError("blob store unreachable")
        with self.lock:
            out = [
                BlobRef(p, "https://blob.test/" + p)
                for p in sorted(self.items)
                if p.startswith(prefix)
            ]
        if self.after_list:
            self.after_list(prefix)
        return out

    def get(self, ref: BlobRef) -> bytes:
        if self.fail_get:
            raise StoreError("blob store unreachable")
        with self.lock:
            try:
                return self.items[ref.pathname]
            except KeyError:
                raise ObjectGoneError("not found") from None

    def delete(self, ref: BlobRef) -> None:
        if self.fail_delete:
            raise StoreError("blob store unreachable")
        with self.lock:
            self.items.pop(ref.pathname, None)

    def seed_ledger(self, usd: float, day: date = DAY, name: str = "") -> None:
        """Replace the day's ledger entries with one settled call that cost ``usd``."""
        prefix = f"ledger/{day.isoformat()}/"
        for p in [p for p in self.items if p.startswith(prefix)]:
            del self.items[p]
        self._seeds += 1  # a settled object never changes: a new seed is a new object
        self.items[f"{prefix}{'0' * 31}{self._seeds:x}.json"] = json.dumps(
            {"hold_usd": usd, "actual_usd": usd, "settled_ok": True}
        ).encode()

    def ledger_usd(self, day: date = DAY, name: str = "") -> float:
        """What the ledger counts for the day: actual if settled_ok, else the hold."""
        prefix = f"ledger/{day.isoformat()}/"
        total = 0.0
        for p, raw in self.items.items():
            if p.startswith(prefix):
                rec = json.loads(raw)
                total += rec["actual_usd"] if rec.get("settled_ok") is True else rec["hold_usd"]
        return total


def blob_env(tmp_path: Path, store: FakeBlobStore, **kw: Any) -> Env:
    return Env(
        tmp_path,
        store=store,
        config=LiveConfig(daily_usd=3.0, burst_per_min=1000, ask_per_day=1000),
        **kw,
    )


# --- 3. outside mentions -------------------------------------------------------------------

RECALL_SENTENCE = "The firm recalled the LLZ imaging system after a software fault was found."
GOOD_SENTENCE = "The agency said the LLZ image processing software had a labeling problem in 2026."
GDELT = {
    "articles": [
        {
            "url": "https://news.example.com/a",
            "title": GOOD_SENTENCE,
            "seendate": "20261030T120000Z",
        },
        {
            "url": "https://news.example.com/b",
            "title": "LLZ software update draws a long and detailed review.",
            "seendate": "20261029T010000Z",
        },
        {
            "url": "https://news.example.com/c",
            "title": "Patient John Smith reported that the LLZ device failed him.",
            "seendate": "20261028T000000Z",
        },
        {
            "url": "https://news.example.com/d",
            "title": "A story about something else entirely, long enough to count.",
            "seendate": "20261027T000000Z",
        },
    ]
}


def rss(items: list[tuple[str, str, str]]) -> str:
    body = "".join(
        f"<item><title>{t}</title><link>{u}</link><description>{d}</description>"
        "<pubDate>Fri, 30 Oct 2026 10:00:00 GMT</pubDate></item>"
        for t, u, d in items
    )
    return f"<?xml version='1.0'?><rss><channel>{body}</channel></rss>"


class FakeHttp:
    """Maps a URL prefix to ``(status, body)``; anything else is a network error."""

    def __init__(self, routes: dict[str, tuple[int, str]]) -> None:
        self.routes = routes
        self.requested: list[str] = []

    def get(self, url: str, timeout_s: float) -> tuple[int, str]:
        self.requested.append(url)
        best = max((p for p in self.routes if url.startswith(p)), key=len, default=None)
        if best is None:
            raise ConnectionError("no route")
        return self.routes[best]


def page(sentence: str) -> str:
    return (
        "<html><head><title>x</title><script>var a='LLZ';</script></head>"
        f"<body><p>{sentence}</p></body></html>"
    )


def standard_http() -> FakeHttp:
    return FakeHttp(
        {
            "https://api.gdeltproject.org/": (200, json.dumps(GDELT)),
            "https://www.fda.gov/about-fda/contact-fda/stay-informed/rss-feeds/recalls/": (
                200,
                rss(
                    [
                        (
                            "Recall of LLZ system",
                            "https://www.fda.gov/safety/recalls/1",
                            RECALL_SENTENCE,
                        )
                    ]
                ),
            ),
            "https://www.fda.gov/": (500, ""),
            "https://www.medtechdive.com/": (200, "<rss><channel></channel></rss>"),
            "https://news.example.com/a": (200, page(GOOD_SENTENCE)),
            # b: the headline offered by the source is NOT on the fetched page
            "https://news.example.com/b": (
                200,
                page("Something unrelated, but LLZ is named here in a long enough line."),
            ),
            "https://news.example.com/c": (
                200,
                page("Patient John Smith reported that the LLZ device failed him."),
            ),
            "https://news.example.com/d": (
                200,
                page("Nothing about the product code at all in this long sentence."),
            ),
            "https://www.fda.gov/safety/recalls/1": (
                200,
                page("The firm recalled the LLZ imaging system after a software fault was found."),
            ),
        }
    )


def run_search(http: FakeHttp) -> mn.SearchResult:
    return mn.search_mentions(
        "llz",
        ["image processing"],
        http,
        now=lambda: datetime(2026, 10, 31, 1, 0, tzinfo=UTC),
        sleep=lambda _s: None,
    )


def test_quote_not_on_the_page_personal_details_and_off_topic_are_dropped() -> None:
    r = run_search(standard_http())
    quotes = {m["quote"] for m in r.mentions}
    assert GOOD_SENTENCE in quotes
    assert not any("John Smith" in q for q in quotes)  # personal details
    assert not any("long and detailed review" in q for q in quotes)  # not on the fetched page
    assert r.dropped == {"quote_not_found": 1, "personal_details": 1, "off_topic": 1}
    for m in r.mentions:
        assert m["badge"] == mn.BADGE and m["why_matched"].startswith(
            "The quoted sentence contains"
        )
        assert m["quote"] in mn.page_text(standard_http().routes[m["url"]][1])
        assert set(m) == {
            "source_name",
            "source_kind",
            "date",
            "url",
            "quote",
            "why_matched",
            "badge",
        }


def test_fda_host_is_official_and_news_is_news() -> None:
    r = run_search(standard_http())
    kinds = {m["url"]: m["source_kind"] for m in r.mentions}
    assert kinds["https://www.fda.gov/safety/recalls/1"] == "official"
    assert kinds["https://news.example.com/a"] == "news"
    assert r.mentions and r.network_ok


def test_sources_tried_report_each_status_and_search_terms_are_not_echoed() -> None:
    r = run_search(standard_http())
    status = {s["name"]: s["status"] for s in r.sources_tried}
    assert status["GDELT DOC 2.0 (news index)"] == "ok"
    assert status["FDA press releases (RSS)"].startswith("failed")
    assert status["FDA MedWatch safety alerts (RSS)"].startswith("failed")
    assert "MassDevice (RSS)" not in status
    assert all("?" not in s["url"] and "LLZ" not in s["url"] for s in r.sources_tried)
    assert all(set(s) == {"name", "url", "status", "n"} for s in r.sources_tried)
    assert all({"step", "ms", "status"} <= set(t) for t in r.trace)


def test_everything_unreachable_is_not_a_live_result() -> None:
    r = run_search(FakeHttp({}))
    assert not r.network_ok and r.mentions == []


def test_at_most_ten_mentions_and_forbidden_words_are_dropped() -> None:
    items = [
        (
            f"LLZ report number {i} is described here in some detail",
            f"https://news.example.com/n{i}",
            f"LLZ report number {i} is described here in some detail.",
        )
        for i in range(12)
    ]
    routes = {"https://api.gdeltproject.org/": (200, json.dumps({"articles": []}))}
    routes["https://www.medtechdive.com/"] = (200, rss(items))
    for i in range(12):
        routes[f"https://news.example.com/n{i}"] = (
            200,
            page(f"LLZ report number {i} is described here in some detail."),
        )
    r = mn.search_mentions(
        "LLZ", [], FakeHttp(routes), sources=tuple(s for s in mn.SOURCES if "MedTech" in s.name)
    )
    assert len(r.mentions) <= 8  # per-source candidate cap; never more than 10 in any case
    banned = mn.search_mentions(
        "LLZ",
        [],
        FakeHttp(
            {
                "https://www.medtechdive.com/": (
                    200,
                    rss(
                        [
                            (
                                "LLZ",
                                "https://news.example.com/x",
                                "The LLZ device was approved by the agency last week as stated.",
                            )
                        ]
                    ),
                ),
                "https://news.example.com/x": (
                    200,
                    page("The LLZ device was approved by the agency last week as stated."),
                ),
            }
        ),
        sources=tuple(s for s in mn.SOURCES if "MedTech" in s.name),
    )
    assert banned.mentions == [] and banned.dropped["off_topic"] == 1


@pytest.mark.parametrize(
    "sentence",
    [
        "Mrs. Jones said the LLZ system stopped during her scan last week at the clinic.",
        "A 67-year-old man was scanned with the LLZ system when the fault happened to it.",
        "Contact jane@example.com about the LLZ system fault that was found last week.",
        "Call 555-123-4567 about the LLZ system fault that was found last week in the field.",
        "The LLZ system fault was reported for patient Brown during a routine check last week.",
    ],
)
def test_personal_detail_patterns(sentence: str) -> None:
    assert mn.has_personal_details(sentence)


def test_plain_sentences_are_not_personal_details() -> None:
    assert not mn.has_personal_details(GOOD_SENTENCE)
    assert not mn.has_personal_details(
        "The U.S. Food and Drug Administration posted a recall for LLZ devices."
    )


def make_recorded(directory: Path) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "LLZ.json").write_text(
        json.dumps(
            {
                "product_code": "LLZ",
                "searched_utc": "2026-10-29T10:00:00Z",
                "sources_tried": [],
                "mentions": [
                    {
                        "source_name": "x",
                        "source_kind": "news",
                        "date": "2026-10-28",
                        "url": "https://n.example/1",
                        "quote": "A stored sentence about LLZ devices.",
                        "why_matched": "w",
                        "badge": "old",
                    }
                ],
                "dropped": {"quote_not_found": 0, "personal_details": 0, "off_topic": 0},
                "trace": [],
                "mode": "recorded",
            }
        )
    )


def test_route_live_shape_and_label(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MAUDESIGNAL_ALLOW_PER_INSTANCE_CAP", "1")
    env = Env(tmp_path, fetcher=standard_http())
    r = env.client.post(
        "/v1/live/mentions", json={"product_code": "llz", "device_terms": ["image processing"]}
    )
    assert r.status_code == 200
    b = r.json()
    assert (
        b["mode"] == "live" and b["label"] == "news and public web" and b["product_code"] == "LLZ"
    )
    assert {"searched_utc", "sources_tried", "mentions", "dropped", "trace", "limits"} <= set(b)
    assert "recorded_note" not in b and len(b["mentions"]) <= 10
    assert b["limits"]["remaining_today"] == 9
    assert all(m["badge"] == mn.BADGE for m in b["mentions"])
    # source_kind is a fixed machine value ("official" | "news" | "web") the contract requires;
    # every free-text field is screened
    shown = {
        **b,
        "mentions": [{k: v for k, v in m.items() if k != "source_kind"} for m in b["mentions"]],
    }
    assert not forbidden_in(json.dumps(shown))
    assert {m["source_kind"] for m in b["mentions"]} <= {"official", "news", "web"}


def test_route_falls_back_to_the_stored_file_when_nothing_is_reachable(tmp_path: Path) -> None:
    make_recorded(tmp_path / "stored")
    env = Env(tmp_path, fetcher=FakeHttp({}), mentions_dir=tmp_path / "stored")
    b = env.client.post("/v1/live/mentions", json={"product_code": "LLZ"}).json()
    assert b["mode"] == "recorded" and "2026-10-29" in b["recorded_note"]
    assert b["mentions"][0]["badge"] == mn.BADGE  # the badge is always the current one
    none = env.client.post("/v1/live/mentions", json={"product_code": "QIH"}).json()
    assert (
        none["mode"] == "recorded"
        and none["mentions"] == []
        and "No stored mentions" in none["recorded_note"]
    )


def test_mentions_make_no_meta_call_and_write_nothing_to_the_ledger(tmp_path: Path) -> None:
    store = FakeBlobStore()
    store.seed_ledger(2.90)  # the daily ledger is full: a free route does not care
    http = standard_http()
    env = blob_env(tmp_path, store, fetcher=http)
    ok = env.client.post("/v1/live/mentions", json={"product_code": "LLZ"}).json()
    assert ok["mode"] == "live" and http.requested
    assert len(store.items) == 1 and store.ledger_usd() == 2.90
    assert not env.spark.requests


def test_mentions_per_ip_limit_is_ten_per_day(tmp_path: Path) -> None:
    env = Env(tmp_path, fetcher=standard_http())
    codes = [
        env.client.post("/v1/live/mentions", json={"product_code": "LLZ"}).status_code
        for _ in range(11)
    ]
    assert codes[:10] == [200] * 10 and codes[10] == 429


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"product_code": "LL"},
        {"product_code": "LLZ1"},
        {"product_code": 123},
        {"product_code": "LLZ", "device_terms": "x"},
        {"product_code": "LLZ", "device_terms": ["a", "b", "c", "d", "e", "f"]},
        {"product_code": "LLZ", "device_terms": [""]},
        {"product_code": "LLZ", "device_terms": ["x" * 61]},
        {"product_code": "LLZ", "device_terms": [5]},
        {"product_code": "LLZ", "extra": 1},
        [],
        "text",
        None,
    ],
)
def test_mentions_rejects_malformed_bodies(tmp_path: Path, body: Any) -> None:
    env = Env(tmp_path, fetcher=standard_http())
    r = env.client.post("/v1/live/mentions", json=body)
    assert r.status_code == 422
    assert (
        env.client.post(
            "/v1/live/mentions", content=b"{bad", headers={"content-type": "application/json"}
        ).status_code
        == 422
    )


def test_mentions_refuses_patient_details_in_terms_and_big_bodies(tmp_path: Path) -> None:
    http = standard_http()
    env = Env(tmp_path, fetcher=http)
    r = env.client.post(
        "/v1/live/mentions", json={"product_code": "LLZ", "device_terms": ["Mrs. Jones"]}
    )
    assert r.status_code == 422 and r.json()["code"] == "patient_data"
    assert http.requested == []
    big = env.client.post("/v1/live/mentions", content=b"x" * 70_000)
    assert big.status_code == 413


def test_mentions_cors_allows_only_listed_origins(tmp_path: Path) -> None:
    env = Env(tmp_path, fetcher=standard_http())
    ok = env.client.post(
        "/v1/live/mentions", json={"product_code": "LLZ"}, headers={"Origin": ORIGIN}
    )
    assert ok.headers["access-control-allow-origin"] == ORIGIN
    bad = env.client.post(
        "/v1/live/mentions",
        json={"product_code": "LLZ"},
        headers={"Origin": "https://evil.example"},
    )
    assert bad.status_code == 403 and "access-control-allow-origin" not in bad.headers
    assert "/v1/live/mentions" not in env.client.get("/openapi.json").json()["paths"]


def test_http_fetcher_refuses_private_and_non_http_urls() -> None:
    f = mn.HttpFetcher()
    for url in (
        "file:///etc/passwd",
        "ftp://example.com/x",
        "http://127.0.0.1/",
        "http://localhost/",
        "http://10.0.0.5/x",
        "http://169.254.169.254/latest",
    ):
        with pytest.raises(ValueError):
            f.get(url, 1.0)


def test_record_script_parses_requests_and_the_request_file_is_off() -> None:
    import importlib.util

    root = Path(__file__).resolve().parents[2]
    spec = importlib.util.spec_from_file_location(
        "record_mentions", root / "scripts" / "record_mentions.py"
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert set(mod.parse_request("0\n")) == {"LLZ"}
    got = mod.parse_request("1 qih\njak=heart monitor;ecg  # note\n# only a comment\n")
    assert set(got) == {"LLZ", "QIH", "JAK"} and got["JAK"] == ["heart monitor", "ecg"]
    first = (root / "demo" / "mentions" / "REQUEST").read_text().split()[:1]
    assert first in (["0"], ["1"])  # off, or on for one free recording run
    wf = (root / ".github" / "workflows" / "mentions-record.yml").read_text()
    assert "branches: [track-c-live]" in wf and 'paths: ["demo/mentions/REQUEST"]' in wf
    assert "secrets." not in wf and "META_MODEL_API_KEY" not in wf


# --- 3b. outside mentions: each source parser, GDELT retries, honest empty result -------------

ATOM = (
    "<?xml version='1.0'?><feed xmlns='http://www.w3.org/2005/Atom'>"
    "<entry><title>MedWatch alert about LLZ imaging software</title>"
    "<link href='https://www.fda.gov/safety/medwatch/1'/>"
    "<summary>The LLZ imaging software may show the wrong image order.</summary>"
    "<updated>2026-10-30T10:00:00Z</updated></entry></feed>"
)
SAFETY_SENTENCE = "The LLZ imaging software may show the wrong image order."


def _src(name: str) -> mn.Source:
    return next(s for s in mn.SOURCES if s.name == name)


def test_massdevice_and_the_dead_warning_letter_feed_are_not_searched() -> None:
    names = [s.name for s in mn.SOURCES]
    assert not any("MassDevice" in n for n in names)
    assert not any("warning" in n.lower() for n in names)
    assert not any("massdevice" in s.url for s in mn.SOURCES)
    assert not any("warning-letters" in s.url for s in mn.SOURCES)
    assert "FDA MedWatch safety alerts (RSS)" in names
    assert "FDA medical devices feed (RSS)" in names


def test_gdelt_parser_reads_articles_dates_and_rejects_garbage() -> None:
    src = _src("GDELT DOC 2.0 (news index)")
    cands = mn.parse_gdelt(json.dumps(GDELT), src)
    assert [c.url for c in cands][:2] == [
        "https://news.example.com/a",
        "https://news.example.com/b",
    ]
    assert cands[0].date == "2026-10-30" and cands[0].title == GOOD_SENTENCE
    assert mn.parse_gdelt(json.dumps({"articles": []}), src) == []
    assert mn.parse_gdelt(json.dumps({"articles": [{"title": "no url"}, 5]}), src) == []
    with pytest.raises(ValueError):
        mn.parse_gdelt("<html>rate limited</html>", src)


@pytest.mark.parametrize(
    "name",
    [
        "FDA press releases (RSS)",
        "FDA recalls (RSS)",
        "FDA MedWatch safety alerts (RSS)",
        "FDA medical devices feed (RSS)",
        "MedTech Dive (RSS)",
    ],
)
def test_every_rss_source_parses_rss_and_atom_and_rejects_garbage(name: str) -> None:
    src = _src(name)
    assert src.style == "rss"
    items = mn.parse_rss(rss([("LLZ headline here", "https://x.example.com/1", "body text")]), src)
    assert [(c.url, c.title, c.summary, c.date) for c in items] == [
        ("https://x.example.com/1", "LLZ headline here", "body text", "2026-10-30")
    ]
    atom = mn.parse_rss(ATOM, src)
    assert atom[0].url == "https://www.fda.gov/safety/medwatch/1" and atom[0].date == "2026-10-30"
    assert atom[0].summary == SAFETY_SENTENCE
    with pytest.raises(ValueError):
        mn.parse_rss("not xml at all", src)


def test_medwatch_and_device_feeds_give_official_mentions_end_to_end() -> None:
    http = FakeHttp(
        {
            "https://api.gdeltproject.org/": (200, json.dumps({"articles": []})),
            "https://www.fda.gov/about-fda/contact-fda/stay-informed/rss-feeds/medwatch/": (
                200,
                ATOM,
            ),
            "https://www.fda.gov/about-fda/contact-fda/stay-informed/rss-feeds/medical-devices/": (
                200,
                rss([("Nothing relevant", "https://www.fda.gov/safety/x", "no code here at all")]),
            ),
            "https://www.fda.gov/safety/medwatch/1": (
                200,
                page(f"MedWatch alert about LLZ imaging software. {SAFETY_SENTENCE}"),
            ),
        }
    )
    r = run_search(http)
    # the sentence the feed offered first (its headline) is the one found on the page
    assert [m["quote"] for m in r.mentions] == ["MedWatch alert about LLZ imaging software."]
    assert r.mentions[0]["source_kind"] == "official" and r.mentions[0]["date"] == "2026-10-30"
    status = {s["name"]: (s["status"], s["n"]) for s in r.sources_tried}
    assert status["FDA MedWatch safety alerts (RSS)"] == ("ok", 1)
    assert status["FDA medical devices feed (RSS)"] == ("ok", 0)


class Flaky:
    """GDELT answers with the given statuses in turn; everything else is a network error."""

    def __init__(self, answers: list[Any]) -> None:
        self.answers = list(answers)
        self.gdelt_calls = 0
        self.timeouts: list[float] = []

    def get(self, url: str, timeout_s: float) -> tuple[int, str]:
        if not url.startswith("https://api.gdeltproject.org/"):
            raise ConnectionError("no route")
        self.gdelt_calls += 1
        self.timeouts.append(timeout_s)
        answer = self.answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer


def _gdelt_only() -> tuple[mn.Source, ...]:
    return (_src("GDELT DOC 2.0 (news index)"),)


def test_gdelt_uses_a_20_second_timeout_and_two_retries_with_backoff() -> None:
    src = _src("GDELT DOC 2.0 (news index)")
    assert src.timeout_s == 20.0 and src.retries == 2
    assert all(s.retries == 0 and s.timeout_s == mn.FEED_TIMEOUT_S for s in mn.SOURCES[1:])
    http = Flaky([TimeoutError(), (429, ""), (200, json.dumps({"articles": []}))])
    waits: list[float] = []
    r = mn.search_mentions(
        "LLZ",
        [],
        http,
        sources=_gdelt_only(),
        sleep=waits.append,
        now=lambda: datetime(2026, 10, 31, tzinfo=UTC),
    )
    assert http.gdelt_calls == 3 and http.timeouts[0] == 20.0
    assert waits == [2.0, 4.0]  # backoff before the 2nd and the 3rd try
    assert r.sources_tried == [
        {"name": src.name, "url": mn._public_url(src), "status": "ok", "n": 0}
    ]


def test_gdelt_gives_up_after_three_tries_and_says_so() -> None:
    http = Flaky([TimeoutError(), (503, ""), (429, "")])
    r = mn.search_mentions(
        "LLZ",
        [],
        http,
        sources=_gdelt_only(),
        sleep=lambda _s: None,
        now=lambda: datetime(2026, 10, 31, tzinfo=UTC),
    )
    assert http.gdelt_calls == 3
    assert r.sources_tried[0]["status"] == "failed: http 429 (after 3 tries)"
    assert r.network_ok is False


def test_gdelt_does_not_retry_a_reply_that_retrying_cannot_fix() -> None:
    for answer in ((404, ""), (200, "<html>no json</html>")):
        http = Flaky([answer])
        r = mn.search_mentions(
            "LLZ",
            [],
            http,
            sources=_gdelt_only(),
            sleep=lambda _s: None,
            now=lambda: datetime(2026, 10, 31, tzinfo=UTC),
        )
        assert http.gdelt_calls == 1
        assert r.sources_tried[0]["status"].startswith("failed")


def test_gdelt_retries_stay_inside_the_time_budget() -> None:
    clock = {"t": 0.0}

    class Slow:
        calls = 0

        def get(self, url: str, timeout_s: float) -> tuple[int, str]:
            Slow.calls += 1
            clock["t"] += timeout_s  # each try uses its whole timeout, then fails
            raise TimeoutError

    r = mn.search_mentions(
        "LLZ",
        [],
        Slow(),
        sources=_gdelt_only(),
        clock=lambda: clock["t"],
        sleep=lambda s: clock.__setitem__("t", clock["t"] + s),
        now=lambda: datetime(2026, 10, 31, tzinfo=UTC),
    )
    assert clock["t"] < 50.0  # the whole route stays under its limit
    assert clock["t"] <= mn.FEED_PHASE_BUDGET_S + mn.GDELT_TIMEOUT_S
    assert r.sources_tried[0]["status"].startswith("failed: TimeoutError")


def test_nothing_found_still_lists_every_source_with_status_count_and_date() -> None:
    http = FakeHttp(
        {
            "https://api.gdeltproject.org/": (200, json.dumps({"articles": []})),
            "https://www.fda.gov/": (200, rss([])),
            "https://www.medtechdive.com/": (503, ""),
        }
    )
    r = run_search(http)
    assert r.mentions == [] and r.network_ok
    body = r.as_dict()
    assert body["searched_utc"] == "2026-10-31T01:00:00Z"
    assert [s["name"] for s in body["sources_tried"]] == [s.name for s in mn.SOURCES]
    assert all({"name", "status", "n"} <= set(s) for s in body["sources_tried"])
    assert body["summary"].startswith("0 found in these sources (2026-10-31 UTC): ")
    for s in mn.SOURCES:
        assert s.name in body["summary"]
    assert "MedTech Dive (RSS) (failed: http 503)" in body["summary"]


def test_stored_file_without_a_summary_gets_one_from_its_sources() -> None:
    doc = mn.load_recorded(Path("demo/mentions"), "LLZ")
    assert doc is not None
    assert doc["summary"].startswith("0 found in these sources (2026-10-31 UTC): ")
    assert mn.empty_recorded("LLZ", datetime(2026, 10, 31, tzinfo=UTC))["summary"].startswith(
        "0 found"
    )


# --- security: nothing personal or secret in logs, ledgers or records -------------------------


def test_no_address_key_or_query_text_in_logs_or_the_ledger(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    store = FakeBlobStore()
    env = blob_env(tmp_path, store, fetcher=standard_http())
    env.client.post(
        "/v1/live/mentions", json={"product_code": "LLZ", "device_terms": ["secret device phrase"]}
    )
    env.ask("What changed this week for LLZ? unique-question-marker")
    env.client.get("/v1/tools/recalls?product_code=LLZ", headers={"X-API-Key": KEY})
    seen = capsys.readouterr()
    logged = seen.out + seen.err
    for needle in (
        "testclient",
        "127.0.0.1",
        KEY,
        "secret device phrase",
        "unique-question-marker",
    ):
        assert needle not in logged, needle
    stored_text = b"".join(store.items.values()).decode()
    for needle in ("testclient", KEY, "secret device phrase", "unique-question-marker"):
        assert needle not in stored_text
    ledger_docs = [json.loads(v) for k, v in store.items.items() if k.startswith("ledger/")]
    assert ledger_docs and all(
        set(d) in ({"hold_usd"}, {"hold_usd", "actual_usd", "settled_ok"}) for d in ledger_docs
    )


def test_no_redis_key_or_limiter_key_contains_the_raw_address(tmp_path: Path) -> None:
    """Failed-key counters and the public-check limiter see only a peppered hash."""
    import httpx

    from maudesignal.connector.store import ConnectorState, UpstashClient
    from tests.unit.test_connector_store import TOKEN, URL, FakeRedis

    fake = FakeRedis()
    http = httpx.Client(transport=httpx.MockTransport(fake.handler))
    env = Env(tmp_path, state=ConnectorState(UpstashClient(URL, TOKEN, http=http)))
    # a wrong key (failed-auth counter) and a public check (public limiter), from a known address
    env.client.get("/v1/tools/recalls?product_code=LLZ", headers={"X-API-Key": "wrong-" + "x" * 40})
    env.client.get("/v1/public/check_device_type?product_code=LLZ")
    keys = [c[1] for c in fake.calls if len(c) > 1]
    assert any(":rl:failed-auth:" in k for k in keys)
    assert any(":rl:public-check:" in k for k in keys)
    for k in keys:
        assert "testclient" not in k and "127.0.0.1" not in k, k


def test_http_fetcher_connects_to_the_address_it_checked(monkeypatch: pytest.MonkeyPatch) -> None:
    import httpx

    seen: list[httpx.Request] = []
    lookups: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.host == "93.184.216.34" and request.url.path == "/a":
            return httpx.Response(302, headers={"location": "https://other.example/b"})
        return httpx.Response(200, text="<p>ok</p>")

    def resolve(host: str, timeout_s: float) -> str | None:
        lookups.append(host)
        return {"news.example": "93.184.216.34", "other.example": "93.184.216.35"}.get(host)

    monkeypatch.setattr(mn, "_resolve_public", resolve)
    f = mn.HttpFetcher(httpx.Client(transport=httpx.MockTransport(handler)))
    status, text = f.get("https://news.example/a", 5.0)
    assert status == 200 and "ok" in text
    # each hop resolved once, then connected by address with the name kept for Host and TLS
    assert lookups == ["news.example", "other.example"]
    assert [r.url.host for r in seen] == ["93.184.216.34", "93.184.216.35"]
    assert [r.headers["host"] for r in seen] == ["news.example", "other.example"]
    assert all(r.extensions.get("sni_hostname") for r in seen)
    # a redirect to a name that resolves to a private address is refused
    monkeypatch.setattr(
        mn, "_resolve_public", lambda h, t: None if h == "other.example" else "93.184.216.34"
    )
    with pytest.raises(ValueError):
        f.get("https://news.example/a", 5.0)


def test_http_fetcher_has_a_wall_clock_deadline_for_slow_pages(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import time

    import httpx

    class Drip(httpx.SyncByteStream):
        def __iter__(self) -> Any:
            for _ in range(100):
                time.sleep(0.02)
                yield b"x" * 10

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, stream=Drip())

    monkeypatch.setattr(mn, "_resolve_public", lambda h, t: "93.184.216.34")
    f = mn.HttpFetcher(httpx.Client(transport=httpx.MockTransport(handler)))
    started = time.monotonic()
    with pytest.raises(TimeoutError):
        f.get("https://slow.example/", 0.15)
    assert time.monotonic() - started < 1.0


# --- fix round: demo key and the audit list, blob listing, running total, Upstash margin -------


def test_blob_listing_longer_than_the_page_limit_fails_closed() -> None:
    import httpx

    from maudesignal.connector import blob_store as bs

    page = {"blobs": [{"pathname": "ledger/x/1.json", "url": "u"}], "hasMore": True, "cursor": "c"}
    transport = httpx.MockTransport(lambda _req: httpx.Response(200, json=page))
    store = bs.VercelBlobStore("tok", client=httpx.Client(transport=transport))
    assert len(store.list_prefix("ledger/")) == bs.MAX_LIST_PAGES  # exports keep the old cut-off
    with pytest.raises(bs.StoreError):
        store.list_prefix("ledger/", strict=True)
