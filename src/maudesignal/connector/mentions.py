"""Outside mentions of a device type: news and public web pages, kept apart from FDA facts.

HACKATHON-BUILT — Meta Global AI Developer Hackathon (Oct 26 – Nov 4, 2026).

``search_mentions`` looks for a product code or device terms in free public sources only
(GDELT DOC 2.0 for news, FDA press-release / recall / MedWatch safety-alert / medical-device
feeds, and public news RSS). No paid API, no login, no scraping behind a login. For each
candidate it fetches the page and keeps a mention only when the quoted sentence is found word
for word in the fetched page text. A sentence that looks like personal data is dropped,
and so is one with a term this service never uses. Every kept mention carries the badge
``BADGE`` and is never mixed with claim-gated FDA facts. No model is called.

The fetcher is injected (``Fetcher``), so tests run with fake HTTP; the real one refuses
non-http(s) URLs and addresses that are not public.
"""

from __future__ import annotations

import html
import ipaddress
import json
import re
import socket
import time
import xml.etree.ElementTree as ET  # noqa: S405 - feeds are fetched from fixed public hosts
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FuturesTimeout
from dataclasses import dataclass, field
from datetime import UTC, datetime
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Literal, Protocol
from urllib.parse import quote_plus, urlparse

import httpx

from maudesignal.connector.forbidden import is_clean

BADGE = "Unverified — not checked against FDA records"
LABEL = "news and public web"
MAX_MENTIONS = 10
MAX_TERMS = 5
MAX_CANDIDATES_PER_SOURCE = 8
MAX_PAGES = 14
MAX_PAGE_BYTES = 1_500_000
FEED_TIMEOUT_S = 6.0
GDELT_TIMEOUT_S = 20.0
GDELT_RETRIES = 2
RETRY_BACKOFF_S = (2.0, 4.0)  # waits before the 2nd and 3rd try
#: The feeds (with their retries) must be done by now, leaving time to fetch pages.
FEED_PHASE_BUDGET_S = 32.0
PAGE_TIMEOUT_S = 6.0
TOTAL_BUDGET_S = 45.0  # the whole search; the route's own limit is under 50 s
MIN_CALL_S = 2.0
WORKERS = 6
MIN_SENTENCE = 40
MAX_SENTENCE = 400
USER_AGENT = "MaudeSignal-mentions/1 (open-source research project; read-only)"

Kind = Literal["official", "news", "web"]


@dataclass(frozen=True)
class Source:
    """One free public source."""

    name: str
    kind: Kind
    url: str  # may hold {query}
    style: Literal["gdelt", "rss"]
    timeout_s: float = FEED_TIMEOUT_S
    retries: int = 0  # extra tries after a timeout, a network error, HTTP 429 or a 5xx


_FDA_RSS = "https://www.fda.gov/about-fda/contact-fda/stay-informed/rss-feeds/"

#: NOT CHECKED from the build sandbox (its proxy refused fda.gov and GDELT): the ``medwatch`` and
#: ``medical-devices`` feed addresses below, and the feed title of the latter, must be confirmed
#: from a networked machine during the free recording. The label says "feed" and nothing more
#: about what the device feed contains. GDELT gets up to three tries only when the earlier ones
#: fail fast: after a 20 s timeout plus backoffs, the third no longer fits in
#: ``FEED_PHASE_BUDGET_S``, so a slow GDELT gets two.

#: FDA warning letters have no RSS feed that could be confirmed: the address used before
#: (``.../rss-feeds/warning-letters/rss.xml``) answered HTTP 404 in the recorded run of
#: 2026-10-31, and the warning-letter list on fda.gov is a script-driven table, not a feed.
#: It is therefore not searched, and the response never lists it.
SOURCES: tuple[Source, ...] = (
    Source(
        "GDELT DOC 2.0 (news index)",
        "news",
        "https://api.gdeltproject.org/api/v2/doc/doc?query={query}&mode=ArtList"
        "&format=json&maxrecords=10&timespan=3months&sort=DateDesc",
        "gdelt",
        timeout_s=GDELT_TIMEOUT_S,
        retries=GDELT_RETRIES,
    ),
    Source("FDA press releases (RSS)", "official", _FDA_RSS + "press-releases/rss.xml", "rss"),
    Source("FDA recalls (RSS)", "official", _FDA_RSS + "recalls/rss.xml", "rss"),
    Source("FDA MedWatch safety alerts (RSS)", "official", _FDA_RSS + "medwatch/rss.xml", "rss"),
    Source(
        "FDA medical devices feed (RSS)",
        "official",
        _FDA_RSS + "medical-devices/rss.xml",
        "rss",
    ),
    Source("MedTech Dive (RSS)", "news", "https://www.medtechdive.com/feeds/news/", "rss"),
)


class Fetcher(Protocol):
    """What the search needs from HTTP: one GET returning ``(status, text)``."""

    def get(self, url: str, timeout_s: float) -> tuple[int, str]:
        """GET ``url``; raises on a network failure or a refused URL."""


DNS_TIMEOUT_S = 3.0


def _resolve_public(host: str, timeout_s: float) -> str | None:
    """One public IP address for ``host``, or None.

    Every address the name resolves to must be public (global). The lookup runs in a helper
    thread so a slow resolver cannot hold the request past ``timeout_s``.
    """
    try:
        literal = ipaddress.ip_address(host)
        return host if literal.is_global else None
    except ValueError:
        pass
    pool = ThreadPoolExecutor(max_workers=1)
    try:
        infos = pool.submit(socket.getaddrinfo, host, None).result(timeout=timeout_s)
    except (OSError, TimeoutError, FuturesTimeout):
        return None
    finally:
        pool.shutdown(wait=False)
    addresses = [str(i[4][0]) for i in infos]
    if not addresses or not all(ipaddress.ip_address(a).is_global for a in addresses):
        return None
    return addresses[0]


class HttpFetcher:
    """Real fetcher: http(s) only, public addresses only, size-capped, wall-clock bounded.

    The name is resolved once per hop and the connection is made to THAT address (the host
    name is kept for the ``Host`` header and for TLS server-name and certificate checks), so
    the address that was checked is the address that is used: a name cannot resolve to a
    public address for the check and to an internal one for the connection. The ``timeout_s``
    passed to :meth:`get` is a deadline for the whole call (DNS, redirects, headers and body).
    """

    def __init__(self, client: httpx.Client | None = None) -> None:
        """Create the fetcher (``client`` is for tests)."""
        self._client = client

    def get(self, url: str, timeout_s: float) -> tuple[int, str]:
        """GET a page or feed (at most two redirects, each checked); the body is size-capped."""
        deadline = time.monotonic() + timeout_s

        def left() -> float:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("deadline reached")
            return remaining

        client = self._client or httpx.Client(
            timeout=timeout_s, follow_redirects=False, headers={"User-Agent": USER_AGENT}
        )
        try:
            current = url
            for _ in range(3):
                parts = urlparse(current)
                if parts.scheme not in ("http", "https") or not parts.hostname:
                    raise ValueError("url refused")
                ip = _resolve_public(parts.hostname, min(DNS_TIMEOUT_S, left()))
                if ip is None:
                    raise ValueError("address refused")
                target = httpx.URL(current).copy_with(host=ip)
                extensions: dict[str, Any] = {}
                if parts.scheme == "https":
                    extensions["sni_hostname"] = parts.hostname
                headers = {"Host": parts.netloc.rsplit("@", 1)[-1], "User-Agent": USER_AGENT}
                with client.stream(
                    "GET", target, headers=headers, extensions=extensions, timeout=left()
                ) as r:
                    if 300 <= r.status_code < 400 and r.headers.get("location"):
                        current = str(httpx.URL(current).join(r.headers["location"]))
                        continue
                    data = b""
                    for chunk in r.iter_bytes():
                        data += chunk
                        left()  # a page that drips slowly cannot run past the deadline
                        if len(data) >= MAX_PAGE_BYTES:
                            break
                    return r.status_code, data.decode(r.encoding or "utf-8", "replace")
            raise ValueError("too many redirects")
        finally:
            if self._client is None:
                client.close()


# ---------------------------------------------------------------------------
# Text handling
# ---------------------------------------------------------------------------


class _TextExtractor(HTMLParser):
    _SKIP = {"script", "style", "noscript", "template", "svg", "head"}
    _BLOCK = {"p", "div", "li", "br", "h1", "h2", "h3", "h4", "tr", "section", "article"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in self._SKIP:
            self._skip += 1
        elif tag in self._BLOCK:
            self.parts.append(" ")

    def handle_endtag(self, tag: str) -> None:
        if tag in self._SKIP and self._skip:
            self._skip -= 1
        elif tag in self._BLOCK:
            self.parts.append(" ")

    def handle_data(self, data: str) -> None:
        if not self._skip:
            self.parts.append(data)


def norm(text: str) -> str:
    """Whitespace-normalised text (the form in which a quote is looked up)."""
    return " ".join(text.replace(" ", " ").split())


def page_text(markup: str) -> str:
    """Visible text of an HTML page, whitespace-normalised."""
    parser = _TextExtractor()
    try:
        parser.feed(markup)
        parser.close()
    except Exception:  # noqa: BLE001 - HTMLParser can raise on broken markup
        return norm(re.sub(r"<[^>]+>", " ", markup))
    return norm(html.unescape("".join(parser.parts)))


_SENT_SPLIT = re.compile(r"(?<=[.!?])[\"”’)]?\s+(?=[\"“‘(]?[A-Z0-9])")


def with_stop(title: str) -> str:
    """``title`` ending in a full stop (unless it already ends in one) so it splits off."""
    t = title.strip()
    return t if not t or t[-1] in ".!?" else t + "."


def sentences(text: str) -> list[str]:
    """Sentences of ``text`` with a usable length."""
    return [
        s
        for s in (norm(x) for x in _SENT_SPLIT.split(norm(text)))
        if MIN_SENTENCE <= len(s) <= MAX_SENTENCE
    ]


# Personal details: an email, a phone number, an age, a title with a name, "patient <Name>".
_PERSONAL: tuple[re.Pattern[str], ...] = (
    re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+"),
    re.compile(r"(?<!\d)(?:\+?1[\s.-]?)?\(?\d{3}\)?[\s.-]\d{3}[\s.-]\d{4}(?!\d)"),
    re.compile(
        r"\b(?:aged?\s*:?\s*\d{1,3}\b|\d{1,3}\s*-?\s*(?:year|yr)s?\s*-?\s*old\b|\d{1,3}\s*y/?o\b)",
        re.IGNORECASE,
    ),
    re.compile(r"\b(?:Mr|Mrs|Ms|Miss|Mx|Dr|Prof|Sen|Rep|Judge)\.?\s+[A-Z][a-z]+"),
    re.compile(r"\b[Pp]atients?\s+(?:named\s+|identified\s+as\s+)?[A-Z][a-z]+"),
    re.compile(r"\b(?:DOB|date\s+of\s+birth|MRN)\b", re.IGNORECASE),
)


def has_personal_details(sentence: str) -> bool:
    """True when ``sentence`` looks like it holds a person's details (a guard, not a guarantee)."""
    return any(p.search(sentence) for p in _PERSONAL)


def term_pattern(term: str) -> re.Pattern[str]:
    """Case-insensitive whole-word pattern for a term (spaces match any whitespace)."""
    words = [re.escape(w) for w in term.split()]
    return re.compile(r"(?<![A-Za-z0-9])" + r"\s+".join(words) + r"(?![A-Za-z0-9])", re.IGNORECASE)


def matched_terms(text: str, patterns: dict[str, re.Pattern[str]]) -> list[str]:
    """The terms (in request order) found in ``text``."""
    return [t for t, p in patterns.items() if p.search(text)]


# ---------------------------------------------------------------------------
# Feeds
# ---------------------------------------------------------------------------


@dataclass
class Candidate:
    """One item a source offered: a page URL, its date and any text the feed gave."""

    source: Source
    url: str
    title: str = ""
    summary: str = ""
    date: str = ""


def _date_iso(raw: str) -> str:
    raw = raw.strip()
    if re.fullmatch(r"\d{8}T\d{6}Z", raw):  # GDELT: 20261030T120000Z
        return f"{raw[0:4]}-{raw[4:6]}-{raw[6:8]}"
    if re.match(r"\d{4}-\d{2}-\d{2}", raw):
        return raw[:10]
    from email.utils import parsedate_to_datetime

    try:
        return parsedate_to_datetime(raw).date().isoformat()
    except (TypeError, ValueError):
        return ""


def parse_gdelt(body: str, source: Source) -> list[Candidate]:
    """Articles of a GDELT DOC 2.0 ``ArtList`` JSON reply."""
    try:
        doc = json.loads(body)
        arts = doc.get("articles") or []
    except (ValueError, AttributeError):
        raise ValueError("unreadable reply") from None
    out: list[Candidate] = []
    for a in arts if isinstance(arts, list) else []:
        if isinstance(a, dict) and isinstance(a.get("url"), str):
            out.append(
                Candidate(
                    source,
                    a["url"],
                    title=norm(str(a.get("title") or "")),
                    date=_date_iso(str(a.get("seendate") or "")),
                )
            )
    return out


def parse_rss(body: str, source: Source) -> list[Candidate]:
    """Items of an RSS 2.0 or Atom feed."""
    try:
        root = ET.fromstring(body)  # noqa: S314 - public feed; no entity expansion in ET
    except ET.ParseError:
        raise ValueError("unreadable feed") from None
    out: list[Candidate] = []

    def text(el: ET.Element, *names: str) -> str:
        for child in el:
            if child.tag.split("}")[-1] in names and (child.text or "").strip():
                return child.text or ""
        return ""

    for item in root.iter():
        tag = item.tag.split("}")[-1]
        if tag not in ("item", "entry"):
            continue
        link = text(item, "link")
        if not link:
            for child in item:
                if child.tag.split("}")[-1] == "link" and child.get("href"):
                    link = child.get("href") or ""
                    break
        if not link:
            continue
        summary_html = text(item, "description", "summary", "encoded", "content")
        out.append(
            Candidate(
                source,
                link.strip(),
                title=norm(html.unescape(text(item, "title"))),
                summary=page_text(summary_html) if summary_html else "",
                date=_date_iso(text(item, "pubDate", "published", "updated", "date")),
            )
        )
    return out


# ---------------------------------------------------------------------------
# The search
# ---------------------------------------------------------------------------


@dataclass
class SearchResult:
    """What a search found, in the response shape."""

    product_code: str
    searched_utc: str
    sources_tried: list[dict[str, Any]] = field(default_factory=list)
    mentions: list[dict[str, Any]] = field(default_factory=list)
    dropped: dict[str, int] = field(
        default_factory=lambda: {"quote_not_found": 0, "personal_details": 0, "off_topic": 0}
    )
    trace: list[dict[str, Any]] = field(default_factory=list)
    network_ok: bool = False

    def summary(self) -> str:
        """One honest line: how many were found, in which sources, on which UTC date."""
        return summarize(len(self.mentions), self.searched_utc, self.sources_tried)

    def as_dict(self) -> dict[str, Any]:
        """The response body parts this module owns."""
        return {
            "product_code": self.product_code,
            "searched_utc": self.searched_utc,
            "sources_tried": self.sources_tried,
            "summary": self.summary(),
            "mentions": self.mentions,
            "dropped": self.dropped,
            "trace": self.trace,
        }


class _RetryError(Exception):
    """Internal: this try failed in a way worth another try (429, 5xx)."""


def _host_kind(url: str, default: Kind) -> Kind:
    host = (urlparse(url).hostname or "").lower()
    return "official" if host == "fda.gov" or host.endswith(".fda.gov") else default


def search_mentions(
    product_code: str,
    device_terms: list[str],
    fetcher: Fetcher,
    *,
    clock: Callable[[], float] = time.monotonic,
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
    budget_s: float = TOTAL_BUDGET_S,
    sources: tuple[Source, ...] = SOURCES,
    sleep: Callable[[float], None] = time.sleep,
) -> SearchResult:
    """Search the free sources and keep only mentions whose sentence is on the fetched page.

    Args:
        product_code: Three-letter FDA product code (searched as a term).
        device_terms: Up to five device names or phrases.
        fetcher: HTTP client.
        clock: Monotonic clock (tests).
        now: UTC clock (tests).
        budget_s: Total time allowed; no call starts when less than a few seconds remain.
        sources: The sources to try.
        sleep: Waits between tries (tests pass a no-op).
    """
    code = product_code.upper()
    terms = list(dict.fromkeys([code, *[t.strip() for t in device_terms if t.strip()]]))[
        : MAX_TERMS + 1
    ]
    patterns = {t: term_pattern(t) for t in terms}
    result = SearchResult(code, now().strftime("%Y-%m-%dT%H:%M:%SZ"))
    deadline = clock() + budget_s

    def left() -> float:
        return deadline - clock()

    def run_source(src: Source) -> tuple[dict[str, Any], list[Candidate], float]:
        t0 = clock()
        info: dict[str, Any] = {"name": src.name, "url": _public_url(src), "n": 0}
        if left() < MIN_CALL_S:
            return info | {"status": "skipped: time"}, [], 0.0
        query = quote_plus(" OR ".join(f'"{t}"' for t in terms) + " sourcelang:english")
        url = src.url.replace("{query}", query)
        feed_deadline = t0 + FEED_PHASE_BUDGET_S
        tries = 1 + src.retries
        note = "no try"
        cands: list[Candidate] | None = None
        for attempt in range(tries):
            room = min(left(), feed_deadline - clock())
            if room < MIN_CALL_S:
                note = note if attempt else "time"
                break
            try:
                status, body = fetcher.get(url, min(src.timeout_s, room))
                if status != 200:
                    note = f"http {status}"
                    if status != 429 and status < 500:
                        break  # a 4xx other than 429 will not change on a retry
                    raise _RetryError
                cands = parse_gdelt(body, src) if src.style == "gdelt" else parse_rss(body, src)
                break
            except _RetryError:
                pass
            except ValueError as exc:  # the reply could not be read: retrying will not help
                note = str(exc)
                break
            except Exception as exc:  # noqa: BLE001 - one source failing never stops the others
                note = type(exc).__name__
            if attempt + 1 < tries:
                sleep(
                    min(RETRY_BACKOFF_S[min(attempt, len(RETRY_BACKOFF_S) - 1)], max(0.0, left()))
                )
        if cands is None:
            tried = "" if tries == 1 else f" (after {attempt + 1} tries)"
            return info | {"status": f"failed: {note}{tried}"[:80]}, [], clock() - t0
        if src.style == "rss":  # a feed lists everything: keep items that mention a term
            cands = [c for c in cands if matched_terms(f"{c.title} {c.summary}", patterns)]
        cands = cands[:MAX_CANDIDATES_PER_SOURCE]
        return info | {"status": "ok", "n": len(cands)}, cands, clock() - t0

    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        fetched = list(pool.map(run_source, sources))
    all_cands: list[Candidate] = []
    for info, cands, secs in fetched:
        result.sources_tried.append(info)
        result.trace.append(
            {
                "step": f"Search: {info['name']}",
                "ms": int(secs * 1000),
                "status": info["status"][:40],
            }
        )
        all_cands.extend(cands)
    result.network_ok = any(i["status"] == "ok" for i in result.sources_tried)

    seen: set[str] = set()
    unique: list[Candidate] = []
    for c in all_cands:
        if c.url not in seen:
            seen.add(c.url)
            unique.append(c)
    unique = unique[:MAX_PAGES]

    def check(c: Candidate) -> tuple[str, dict[str, Any] | None]:
        """Check one page: ``(outcome, mention)``.

        The outcome is kept, quote_not_found, personal_details, off_topic or fetch_failed.
        """
        if left() < MIN_CALL_S:
            return "fetch_failed", None
        try:
            status, markup = fetcher.get(c.url, min(PAGE_TIMEOUT_S, left()))
            if status != 200:
                return "fetch_failed", None
        except Exception:  # noqa: BLE001
            return "fetch_failed", None
        text = page_text(markup)
        if not matched_terms(text, patterns):
            return "off_topic", None
        # The sentence the source itself offered comes first; it must be on the page.
        offered = [
            s for s in sentences(f"{with_stop(c.title)} {c.summary}") if matched_terms(s, patterns)
        ]
        if offered:
            quote = offered[0]
            if quote not in text:
                return "quote_not_found", None
        else:
            found = [s for s in sentences(text) if matched_terms(s, patterns)]
            if not found:
                return "off_topic", None
            quote = found[0]
        if has_personal_details(quote):
            return "personal_details", None
        if not is_clean(quote):
            return "off_topic", None  # a term this service never uses
        hits = matched_terms(quote, patterns)
        return "kept", {
            "source_name": c.source.name,
            "source_kind": _host_kind(c.url, c.source.kind),
            "date": c.date,
            "url": c.url,
            "quote": quote,
            "why_matched": "The quoted sentence contains: " + ", ".join(f'"{h}"' for h in hits),
            "badge": BADGE,
        }

    t0 = clock()
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        checked = list(pool.map(check, unique))
    for outcome, mention in checked:
        if outcome == "kept" and mention is not None:
            if len(result.mentions) < MAX_MENTIONS:
                result.mentions.append(mention)
        elif outcome in result.dropped:
            result.dropped[outcome] += 1
    result.trace.append(
        {
            "step": "Fetch pages and check each quote against the page text",
            "ms": int((clock() - t0) * 1000),
            "status": f"{len(unique)} page(s) tried",
        }
    )
    return result


def _public_url(src: Source) -> str:
    """The source URL without the query part (the search terms are not echoed)."""
    return src.url.split("?")[0].replace("{query}", "")


# ---------------------------------------------------------------------------
# Response shape and stored files
# ---------------------------------------------------------------------------


def response_body(
    result: SearchResult, *, mode: Literal["live", "recorded"], limits: dict[str, Any]
) -> dict[str, Any]:
    """The full response: the result plus label, mode and limits."""
    body = result.as_dict() | {"label": LABEL, "mode": mode, "limits": limits}
    return body


def summarize(found: int, searched_utc: str, sources_tried: list[dict[str, Any]]) -> str:
    """One line for the UI: how many were found, where, on which date, with each status."""
    names = "; ".join(f"{i.get('name')} ({i.get('status')})" for i in sources_tried)
    when = f" ({searched_utc[:10]} UTC)" if searched_utc else ""
    return f"{found} found in these sources{when}: {names or 'none'}."


def load_recorded(directory: Path, code: str) -> dict[str, Any] | None:
    """The stored file ``<dir>/<CODE>.json`` when it exists and has the expected shape."""
    path = directory / f"{code.upper()}.json"
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(doc, dict) or not isinstance(doc.get("mentions"), list):
        return None
    clean: list[dict[str, Any]] = []
    for m in doc["mentions"]:
        if isinstance(m, dict) and is_clean(str(m.get("quote", ""))):
            clean.append(m | {"badge": BADGE})
    doc["mentions"] = clean[:MAX_MENTIONS]
    doc["summary"] = summarize(
        len(doc["mentions"]), str(doc.get("searched_utc") or ""), doc.get("sources_tried") or []
    )
    return doc


def empty_recorded(code: str, now: datetime) -> dict[str, Any]:
    """The shape with nothing in it, for a code with no stored file."""
    return {
        "product_code": code.upper(),
        "searched_utc": "",
        "sources_tried": [],
        "summary": "0 found: no stored search exists for this product code.",
        "mentions": [],
        "dropped": {"quote_not_found": 0, "personal_details": 0, "off_topic": 0},
        "trace": [],
    }
