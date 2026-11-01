"""Investigate a complaint against public FDA data (deterministic, no model, nothing stored).

HACKATHON-BUILT — Meta Global AI Developer Hackathon (Oct 26 – Nov 4, 2026). Feature F25.

Real post-market surveillance is reactive: a complaint arrives and a person has to look at what
FDA already holds. Given a product code and a short description of the device problem, this
module assembles, from openFDA only:

1. similar MAUDE events at any maker: counts by month for the last 12 months, for the whole
   product code and, separately, for the reports whose narrative mentions the description's
   keywords; plus up to five verbatim quotes from those narratives (each checked by the claim
   gate's verbatim-quote rule against the very record it came from);
2. the reports about the code that were not filed by a manufacturer (the F12 report-source
   normalization of ``gate/evidence.py``);
3. recalls and 510(k) clearances for the code, with links.

Nothing here calls a model. Keywords are the lowercased content words of the description after
a fixed stop-word filter. The description is never stored or logged: it lives in this function
call and in the queries sent to openFDA. The answer states what could not be done (reports of
the person's own company cannot be separated) instead of guessing.

``Source`` is the one seam to the outside: :class:`OpenFdaSource` is the real one (tests and the
recorded example use ``investigate_stored.StoredSource``). Every figure comes with the openFDA
URL that shows it.
"""

from __future__ import annotations

import re
import time
from collections import defaultdict
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta
from typing import Any, Literal, Protocol
from urllib.parse import urlencode

import httpx
from pydantic import BaseModel, ConfigDict, Field

from maudesignal.common.exceptions import (
    MaudeSignalError,
    OpenFDAAPIError,
    OpenFDAForbiddenError,
    OpenFDARateLimitError,
    OpenFDAUnavailableError,
)
from maudesignal.connector import links
from maudesignal.connector.feedback import looks_like_phi
from maudesignal.connector.forbidden import is_clean
from maudesignal.gate.claims import DeviceClaim, QuoteClaim, RecallClaim, RecordClaim
from maudesignal.gate.evidence import (
    DeviceRef,
    EvidenceRecord,
    EvidenceStore,
    RecallRef,
    normalize_source,
)
from maudesignal.gate.gate import verify_claim
from maudesignal.ingestion.openfda_client import USER_AGENT

EVENT_URL = "https://api.fda.gov/device/event.json"
RECALL_URL = "https://api.fda.gov/device/recall.json"
K510_URL = "https://api.fda.gov/device/510k.json"
CLASSIFICATION_URL = "https://api.fda.gov/device/classification.json"

MONTHS = 12
MIN_DESCRIPTION = 5
MAX_DESCRIPTION = 500
MAX_KEYWORDS = 6
MIN_WORD = 3
MAX_QUOTES = 5
MAX_LISTED = 5
QUOTE_MIN_CHARS = 25
QUOTE_MAX_CHARS = 300
CANDIDATE_REPORTS = 25
LIST_NOTE_CHARS = 240

#: Fixed notice, word for word (also the last paragraph of the evidence text).
NOTICE = (
    "This is evidence assembled from public FDA data to attach to your complaint record, your "
    "MDR-reportability assessment (21 CFR 803) and your PMS board. MaudeSignal does not decide "
    "reportability, similarity, or whether a CAPA is needed; your team does."
)
BANNER = "Do not enter patient data. Describe the device problem only."
OWN_MAKER_NOTE = (
    "Reports filed by your own company cannot be separated here: the form does not ask which "
    "company you are, and the maker name on a MAUDE report is free text that is spelled "
    "differently from report to report. Each quote shows the maker name as filed, so your team "
    "can set its own reports aside."
)
LAG_NOTE = "openFDA runs weeks behind real time, so the newest months are incomplete."

_STOP_WORDS = frozenset("""
    a about above after again against all also am an and any are aren as at be because been before
    being below between both but by can cannot could couldn did didn do does doesn doing don down
    during each few for from further had hadn has hasn have haven having he her here hers herself
    him himself his how i if in into is isn it its itself just let me more most mustn my myself
    no nor not now of off on once only or other ought our ours ourselves out over own same shan
    she should shouldn so some such than that the their theirs them themselves then there these
    they this those through to too under until up upon very was wasn we were weren what when
    where which while who whom whose why will with won would wouldn you your yours yourself
    yourselves get got gets getting went going gone come came comes make made makes took take
    takes taken one two three then thus per via yet still since while within without often
    sometimes sometime always never ever like likely said says say see saw seen seems seemed
    something anything nothing everything someone anyone everyone user users staff customer
    customers another called call reported reports report reporting reporter problem problems issue
    issues event events device devices
    """.split())  # noqa: SIM905
_WORD = re.compile(r"[a-z0-9]+")
_SENTENCE = re.compile(r".+?(?:[.!?](?=\s|$)|$)", re.DOTALL)


# ---------------------------------------------------------------------------
# Keywords
# ---------------------------------------------------------------------------


_AFTER_NAME = re.compile(r"\bname\s*[:=]\s*\S+(?:\s+[A-Z][a-z]+)?", re.IGNORECASE)
_CAP_PAIR = re.compile(r"\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)+\b")


def scrub_names(text: str) -> str:
    """Drop what looks like a person's name before keywords are taken.

    The words after ``name:`` and runs of two or more Capitalised words are removed. This is a
    second line behind the patient-data guard, so a name that slipped past it is not sent to
    openFDA as a keyword. It can also drop a Capitalised product name; the keywords are fewer then,
    never wrong.
    """
    return _CAP_PAIR.sub(" ", _AFTER_NAME.sub(" ", text))


def extract_keywords(text: str, limit: int = MAX_KEYWORDS) -> list[str]:
    """Lowercased content words of ``text`` in order of first appearance, at most ``limit``.

    A word is a run of letters and digits with at least three characters that is not a number and
    not in the fixed stop-word list. No stemming, no synonyms, no model.
    """
    seen: list[str] = []
    for word in _WORD.findall(scrub_names(text).lower()):
        if len(word) < MIN_WORD or word.isdigit() or word in _STOP_WORDS or word in seen:
            continue
        seen.append(word)
        if len(seen) >= limit:
            break
    return seen


def narrative_words(text: str) -> set[str]:
    """The word set of a narrative (what a keyword is matched against)."""
    return set(_WORD.findall(text.lower()))


# ---------------------------------------------------------------------------
# Queries (one place builds both the request and the link shown to the reader)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class EventFilter:
    """Which MAUDE events: a product code, a ``date_received`` window, optional narrative words.

    ``keywords`` match when the narrative mentions at least one of them. ``sources`` are exact
    ``report_source_code`` values as openFDA wrote them (for example ``User facility report``).
    """

    product_code: str
    start: str  # YYYYMMDD
    end: str  # YYYYMMDD
    keywords: tuple[str, ...] = ()
    sources: tuple[str, ...] = ()


@dataclass(frozen=True)
class Query:
    """One openFDA request: the endpoint and its parameters (no API key)."""

    endpoint: str
    params: tuple[tuple[str, str], ...]
    #: For event queries, the filter they were built from (a stored source reads this).
    event: EventFilter | None = None

    @property
    def url(self) -> str:
        """The public URL a reader can open to see the same figure (never holds a key)."""
        return f"{self.endpoint}?{urlencode(self.params)}"


_SAFE_SOURCE = re.compile(r"^[A-Za-z][A-Za-z ]{1,40}$")


def event_search(f: EventFilter) -> str:
    """The openFDA ``search`` text for an event filter (spaces, not ``+``)."""
    parts = [
        f"device.device_report_product_code:{f.product_code}",
        f"date_received:[{f.start} TO {f.end}]",
    ]
    if f.keywords:
        parts.append("mdr_text.text:(" + " OR ".join(f.keywords) + ")")
    clean = [s for s in f.sources if _SAFE_SOURCE.match(s)]
    if clean:
        parts.append("report_source_code:(" + " OR ".join(f'"{s}"' for s in clean) + ")")
    return " AND ".join(parts)


def event_query(
    f: EventFilter, *, count: str | None = None, limit: int = 1, sort: str | None = None
) -> Query:
    """A count query (per-bucket numbers) or a search query (``meta.results.total`` and rows)."""
    params: list[tuple[str, str]] = [("search", event_search(f))]
    if count:
        params += [("count", count), ("limit", "1000")]
    else:
        params.append(("limit", str(limit)))
        if sort:
            params.append(("sort", sort))
    return Query(EVENT_URL, tuple(params), f)


def recall_query(product_code: str, limit: int = 1) -> Query:
    """Recalls of a product code, newest first."""
    return Query(
        RECALL_URL,
        (
            ("search", f"product_code:{product_code}"),
            ("limit", str(limit)),
            ("sort", "event_date_initiated:desc"),
        ),
    )


def k510_query(product_code: str, limit: int = 1) -> Query:
    """510(k) clearances of a product code, newest decision first."""
    return Query(
        K510_URL,
        (
            ("search", f"product_code:{product_code}"),
            ("limit", str(limit)),
            ("sort", "decision_date:desc"),
        ),
    )


def classification_query(product_code: str) -> Query:
    """The FDA name of a product code."""
    return Query(CLASSIFICATION_URL, (("search", f"product_code:{product_code}"), ("limit", "1")))


@dataclass(frozen=True)
class Reply:
    """What a source returns for one query: the match total and the rows or buckets."""

    total: int
    rows: tuple[dict[str, Any], ...]


class Source(Protocol):
    """Where the facts come from (tests and the recorded example inject a stored one)."""

    def run(self, query: Query, *, timeout_s: float | None = None) -> Reply:
        """Answer one query; an empty result is ``Reply(0, ())``; failures raise."""
        ...


class OpenFdaSource:
    """The real thing: openFDA over HTTPS (User-Agent sent, optional key, errors named)."""

    def __init__(
        self,
        api_key: str | None = None,
        *,
        transport: httpx.BaseTransport | None = None,
        timeout_s: float = 15.0,
    ) -> None:
        """Create the source; the key is sent as a parameter and is never part of a link."""
        self._key = api_key
        self._client = httpx.Client(
            timeout=timeout_s, transport=transport, headers={"User-Agent": USER_AGENT}
        )

    def close(self) -> None:
        """Close the HTTP client."""
        self._client.close()

    def run(self, query: Query, *, timeout_s: float | None = None) -> Reply:
        """One GET; 404 is an empty answer, 403 / 429 / 5xx raise a named error."""
        params = dict(query.params)
        if self._key:
            params["api_key"] = self._key
        try:
            resp = self._client.get(
                query.endpoint,
                params=params,
                timeout=timeout_s if timeout_s is not None else httpx.USE_CLIENT_DEFAULT,
            )
        except httpx.HTTPError as exc:  # class name only: the message can hold a URL
            raise OpenFDAAPIError(f"HTTP error contacting openFDA ({type(exc).__name__})") from exc
        if resp.status_code == 404:
            return Reply(0, ())
        if resp.status_code == 403:
            raise OpenFDAForbiddenError("openFDA refused the request (403)")
        if resp.status_code == 429:
            raise OpenFDARateLimitError("openFDA returned 429")
        if resp.status_code in (500, 503):
            raise OpenFDAUnavailableError(f"openFDA server error {resp.status_code}")
        if resp.status_code != 200:
            raise OpenFDAAPIError(f"Unexpected openFDA status {resp.status_code}")
        try:
            body = resp.json()
        except ValueError as exc:
            raise OpenFDAAPIError("openFDA returned non-JSON") from exc
        rows = tuple(r for r in (body.get("results") or []) if isinstance(r, dict))
        total = int(((body.get("meta") or {}).get("results") or {}).get("total", len(rows)))
        return Reply(total, rows)


# ---------------------------------------------------------------------------
# Answer
# ---------------------------------------------------------------------------


class _M(BaseModel):
    model_config = ConfigDict(extra="forbid")


class InvestigateRequest(_M):
    """Body of ``POST /v1/investigate``. The description is used once and never stored."""

    product_code: str = Field(pattern=r"^[A-Za-z]{3}$", description="Three-letter FDA code.")
    description: str = Field(
        min_length=MIN_DESCRIPTION,
        max_length=MAX_DESCRIPTION,
        description="The device problem in a few words. No patient details.",
    )


class MonthRow(_M):
    """One calendar month of the window."""

    month: str = Field(description="YYYY-MM.")
    code_wide: int = Field(description="Reports received that month for the whole product code.")
    code_wide_url: str
    keyword_matched: int | None = Field(
        description="Of those, reports whose narrative mentions a keyword (null: no keywords)."
    )
    keyword_url: str | None
    partial: bool = Field(description="The window starts or ends inside this month.")


class Counted(_M):
    """A number with the openFDA query that shows it."""

    value: int
    url: str


class Quote(_M):
    """One verbatim sentence from a report narrative."""

    report_number: str | None
    mdr_report_key: str
    date_received: str | None
    source: str = Field(description="Who filed it: manufacturer, user facility, ... or ''.")
    maker: str | None = Field(description="Maker name as written on the report (free text).")
    quote: str
    truncated: bool = Field(description="The sentence continues after the quote.")
    keywords_in_quote: list[str]
    url: str
    gate: str = Field(description="What the claim gate checked, e.g. 'verbatim match'.")


class ListedReport(_M):
    """A report listed without a quote."""

    report_number: str | None
    mdr_report_key: str
    date_received: str | None
    source: str
    maker: str | None
    url: str


class SourceBucket(_M):
    """Reports of one filer type in the window."""

    source: str = Field(description="As openFDA wrote it, e.g. 'User facility report'.")
    normalized: str = Field(description="manufacturer, user facility, voluntary, distributor.")
    count: int


class SourcesBlock(_M):
    """Who filed the reports about the product code in the window (F12)."""

    buckets: list[SourceBucket]
    buckets_url: str
    manufacturer_count: int
    non_manufacturer: Counted
    no_source_count: int = Field(description="Reports with no filer type on them.")
    reports: list[ListedReport] = Field(description="Newest non-manufacturer reports, at most 5.")
    note: str | None = None


class RecallItem(_M):
    """One FDA recall record."""

    recall_number: str
    firm: str | None
    status: str | None
    date_initiated: str | None
    reason: str
    url: str


class ClearanceItem(_M):
    """One 510(k) record."""

    k_number: str
    device_name: str
    applicant: str | None
    decision_date: str | None
    url: str


class RecallsBlock(_M):
    """Recalls of the product code (all dates), newest five."""

    total: Counted | None
    items: list[RecallItem]
    note: str | None = None


class ClearancesBlock(_M):
    """510(k)s of the product code (all dates), newest five decisions."""

    total: Counted | None
    items: list[ClearanceItem]
    note: str | None = None


class Dropped(_M):
    """What was left out and why (counted, never shown)."""

    quote_not_verbatim: int = 0
    quote_personal_details: int = 0
    quote_wording: int = 0
    record_not_confirmed: int = 0


class InvestigateAnswer(_M):
    """The whole investigation. It never holds the description the person typed."""

    mode: Literal["live", "recorded"] = "live"
    product_code: str
    device_type_name: str | None
    retrieved_utc: str = Field(description="When openFDA was asked (ISO 8601, UTC).")
    retrieved_date: str = Field(description="YYYY-MM-DD of the retrieval.")
    window_start: str = Field(description="YYYYMMDD.")
    window_end: str = Field(description="YYYYMMDD.")
    keywords: list[str]
    keyword_rule: str
    months: list[MonthRow]
    total_code_wide: Counted
    total_keyword_matched: Counted | None
    quotes: list[Quote]
    sources: SourcesBlock | None
    recalls: RecallsBlock
    clearances: ClearancesBlock
    dropped: Dropped
    own_maker_note: str = OWN_MAKER_NOTE
    lag_note: str = LAG_NOTE
    notice: str = NOTICE
    not_medical_advice: bool = True
    source_note: str | None = Field(
        default=None, description="Recorded runs: where the numbers come from."
    )
    notes: list[str] = Field(default_factory=list)


class InvestigateError(MaudeSignalError):
    """The investigation cannot run (openFDA gave nothing usable for the main count)."""

    def __init__(self, message: str, *, limited: bool = False) -> None:
        """Create the error; ``limited`` is True when openFDA answered 429."""
        super().__init__(message)
        self.limited = limited


class DeadlineExceededError(MaudeSignalError):
    """The overall time limit of one investigation ran out before this call could start."""


DEFAULT_DEADLINE_S = 30.0
MAX_DEADLINE_S = 40.0
CALL_TIMEOUT_S = 10.0
#: Hard wall-clock cap per openFDA call (an httpx timeout applies per phase, not per call).
CALL_WALL_S = 8.0


class Budget:
    """The overall time limit: every openFDA call asks it for its own timeout."""

    def __init__(self, deadline_s: float, clock: Callable[[], float] = time.monotonic) -> None:
        """Start the clock now; ``deadline_s`` is clamped to 40 seconds."""
        self._clock = clock
        self._end = clock() + min(max(deadline_s, 1.0), MAX_DEADLINE_S)
        self.expired = False

    def left(self) -> float:
        """Seconds left (never negative)."""
        return max(0.0, self._end - self._clock())

    def call(self, source: Source, query: Query) -> Reply:
        """Run one query with min(10 s, time left) as its timeout; skip it when no time is left."""
        left = self.left()
        if left <= 0.05:
            self.expired = True
            raise DeadlineExceededError("time limit")
        pool = ThreadPoolExecutor(max_workers=1)
        future = pool.submit(source.run, query, timeout_s=min(CALL_TIMEOUT_S, left))
        try:
            return future.result(timeout=min(CALL_WALL_S, left))
        except FutureTimeout as exc:
            raise OpenFDAUnavailableError("openFDA call took longer than its time limit") from exc
        finally:
            pool.shutdown(wait=False)


# ---------------------------------------------------------------------------
# The run
# ---------------------------------------------------------------------------

KEYWORD_RULE = (
    "Lowercased words of the description with at least 3 letters or digits, after dropping "
    "common English words and the generic words device, problem, issue, report and event; the "
    "first 6, in the order written. A report counts as matched when its narrative mentions at "
    "least one of them. No model, no synonyms, no stemming."
)


def _ymd(d: date) -> str:
    return d.strftime("%Y%m%d")


def window_for(now: datetime) -> tuple[date, date]:
    """First day of the month 11 months before ``now``'s month, through ``now``'s date."""
    month_index = now.year * 12 + (now.month - 1) - (MONTHS - 1)
    return date(month_index // 12, month_index % 12 + 1, 1), now.date()


def _months(start: date, end: date) -> list[tuple[str, date, date]]:
    out: list[tuple[str, date, date]] = []
    y, m = start.year, start.month
    while (y, m) <= (end.year, end.month):
        first = date(y, m, 1)
        nxt = date(y + (m == 12), m % 12 + 1, 1)
        out.append((f"{y:04d}-{m:02d}", max(first, start), min(nxt - timedelta(days=1), end)))
        y, m = nxt.year, nxt.month
    return out


def _text(row: dict[str, Any]) -> str:
    """The narrative of an event row: every ``mdr_text`` block, joined."""
    parts = [str(t.get("text") or "") for t in row.get("mdr_text") or [] if isinstance(t, dict)]
    return " ".join(p for p in parts if p).strip()


def _maker(row: dict[str, Any]) -> str | None:
    name = row.get("manufacturer_name")
    if not name:
        dev = row.get("device") or [{}]
        name = dev[0].get("manufacturer_d_name") if isinstance(dev[0], dict) else None
    return " ".join(str(name).split())[:80] if name else None


def _first_text(value: Any) -> str:
    if isinstance(value, list):
        value = value[0] if value else ""
    return " ".join(str(value or "").split())


def _best_sentence(text: str, keywords: list[str]) -> tuple[str, bool, list[str]] | None:
    """The sentence that mentions the most keywords: ``(quote, truncated, keywords_in_it)``."""
    best: tuple[int, int, str, list[str]] | None = None
    for i, m in enumerate(_SENTENCE.finditer(text)):
        sentence = " ".join(m.group(0).split())
        if len(sentence) < QUOTE_MIN_CHARS:
            continue
        words = narrative_words(sentence)
        hits = [k for k in keywords if k in words]
        if hits and (best is None or len(hits) > best[0]):
            best = (len(hits), i, sentence, hits)
    if best is None:
        return None
    sentence = best[2]
    if len(sentence) <= QUOTE_MAX_CHARS:
        return sentence, False, best[3]
    cut = sentence[:QUOTE_MAX_CHARS].rsplit(" ", 1)[0]
    return cut, True, [k for k in best[3] if k in narrative_words(cut)]


def _quotes(
    rows: tuple[dict[str, Any], ...],
    keywords: list[str],
    code: str,
    dropped: Dropped,
) -> list[Quote]:
    """Up to five verbatim quotes, each confirmed by the gate against its own record."""
    candidates: list[tuple[int, str, str, dict[str, Any], str, bool, list[str]]] = []
    for row in rows:
        key = str(row.get("mdr_report_key") or "")
        found = _best_sentence(_text(row), keywords)
        if key and found:
            quote, truncated, hits = found
            candidates.append(
                (len(hits), str(row.get("date_received") or ""), key, row, quote, truncated, hits)
            )
    # Most keywords first, then newest, then report key: the same input gives the same quotes.
    candidates.sort(key=lambda c: (-c[0], _neg(c[1]), c[2]))
    store = EvidenceStore.from_iterables(
        EvidenceRecord(
            report_id=str(r["mdr_report_key"]),
            product_code=code,
            date_received=str(r.get("date_received") or "") or None,
            text=_text(r),
            manufacturer=_maker(r),
            report_source=str(r.get("report_source_code") or "") or None,
        )
        for r in rows
        if r.get("mdr_report_key")
    )
    out: list[Quote] = []
    for _n, _d, key, row, quote, truncated, hits in candidates:
        if len(out) >= MAX_QUOTES:
            break
        if looks_like_phi(quote):
            dropped.quote_personal_details += 1
            continue
        if not is_clean(quote):
            dropped.quote_wording += 1
            continue
        verdict = verify_claim(QuoteClaim(quote=quote, report_id=key), store)
        if verdict.status != "pass":
            dropped.quote_not_verbatim += 1
            continue
        out.append(
            Quote(
                report_number=str(row.get("report_number") or "") or None,
                mdr_report_key=key,
                date_received=str(row.get("date_received") or "") or None,
                source=normalize_source(str(row.get("report_source_code") or "")),
                maker=_maker(row),
                quote=quote,
                truncated=truncated,
                keywords_in_quote=hits,
                url=links.report_link(key),
                gate=verdict.reason,
            )
        )
    return out


def _neg(value: str) -> str:
    """Sort key that puts the larger string first (dates as YYYYMMDD)."""
    return "".join(chr(0x10FFFF - ord(c)) for c in value)


def _by_month(
    buckets: tuple[dict[str, Any], ...], months: list[tuple[str, date, date]]
) -> dict[str, int]:
    totals: dict[str, int] = defaultdict(int)
    for b in buckets:
        day = str(b.get("time") or b.get("term") or "")
        if len(day) == 8 and day.isdigit():
            totals[f"{day[:4]}-{day[4:6]}"] += int(b.get("count") or 0)
    return {m: totals.get(m, 0) for m, _a, _b in months}


def run_investigation(
    source: Source,
    product_code: str,
    description: str,
    *,
    now: datetime,
    deadline_s: float = DEFAULT_DEADLINE_S,
    clock: Callable[[], float] = time.monotonic,
) -> InvestigateAnswer:
    """Assemble the investigation for one complaint.

    Args:
        source: openFDA (or a stored stand-in).
        product_code: Three-letter FDA product code, upper case.
        description: The device problem as typed. Used for keywords only; not kept.
        now: The retrieval time (UTC).
        deadline_s: Overall time limit in seconds (at most 40). After it, the calls not yet
            started are skipped and the page says so.
        clock: Monotonic clock (tests).

    Returns:
        The answer. Every number has an openFDA URL; the description is not in it.

    Raises:
        InvestigateError: openFDA could not give the code-wide monthly counts.
    """
    budget = Budget(deadline_s, clock)
    code = product_code.upper()
    start, end = window_for(now)
    keywords = extract_keywords(description)
    base = EventFilter(code, _ymd(start), _ymd(end))
    with_kw = EventFilter(code, _ymd(start), _ymd(end), tuple(keywords)) if keywords else None
    notes: list[str] = []
    dropped = Dropped()
    months = _months(start, end)

    try:
        days_all = budget.call(source, event_query(base, count="date_received"))
    except OpenFDARateLimitError as exc:
        raise InvestigateError("openFDA is limiting requests", limited=True) from exc
    except MaudeSignalError as exc:
        raise InvestigateError(f"openFDA could not be reached ({type(exc).__name__})") from exc
    per_month = _by_month(days_all.rows, months)

    # The independent calls run side by side: keyword counts, who filed, recalls, 510(k)s, name.
    with ThreadPoolExecutor(max_workers=5) as pool:
        f_kw = (
            pool.submit(budget.call, source, event_query(with_kw, count="date_received"))
            if with_kw is not None
            else None
        )
        f_src = pool.submit(
            budget.call, source, event_query(base, count="report_source_code.exact")
        )
        f_rec = pool.submit(budget.call, source, recall_query(code, MAX_LISTED))
        f_k = pool.submit(budget.call, source, k510_query(code, MAX_LISTED))
        f_name = pool.submit(budget.call, source, classification_query(code))
        per_month_kw: dict[str, int] | None = None
        if f_kw is not None:
            try:
                per_month_kw = _by_month(f_kw.result().rows, months)
            except MaudeSignalError:
                notes.append("The keyword-matched counts could not be read.")
        total_all = Counted(value=sum(per_month.values()), url=event_query(base).url)
        total_kw = (
            Counted(value=sum(per_month_kw.values()), url=event_query(with_kw).url)
            if with_kw is not None and per_month_kw is not None
            else None
        )
        # Quotes and the list of non-manufacturer reports depend on the answers above.
        f_quotes = (
            pool.submit(
                budget.call,
                source,
                event_query(with_kw, limit=CANDIDATE_REPORTS, sort="date_received:desc"),
            )
            if with_kw is not None and total_kw is not None and total_kw.value
            else None
        )
        sources_block = _sources(budget, source, code, base, total_all.value, dropped, notes, f_src)
        quotes: list[Quote] = []
        if f_quotes is not None:
            try:
                quotes = _quotes(f_quotes.result().rows, keywords, code, dropped)
            except MaudeSignalError:
                notes.append("Quotes could not be read.")
        recalls = _recalls(f_rec, code, dropped)
        clearances = _clearances(f_k, code, dropped)
        type_name = _device_type_name(f_name, code, total_all.value, notes)
    if budget.expired:
        notes.append(
            "The time limit of this search was reached, so some sections are missing. "
            "Run it again to fill them in."
        )

    rows_out: list[MonthRow] = []
    for name, a, b in months:
        rng = EventFilter(code, _ymd(a), _ymd(b), tuple(keywords))
        rows_out.append(
            MonthRow(
                month=name,
                code_wide=per_month[name],
                code_wide_url=event_query(EventFilter(code, _ymd(a), _ymd(b))).url,
                keyword_matched=None if per_month_kw is None else per_month_kw[name],
                keyword_url=None if per_month_kw is None else event_query(rng).url,
                partial=(a != date(a.year, a.month, 1)) or b < _month_end(a),
            )
        )

    stamp = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    return InvestigateAnswer(
        product_code=code,
        device_type_name=type_name,
        retrieved_utc=stamp,
        retrieved_date=stamp[:10],
        window_start=_ymd(start),
        window_end=_ymd(end),
        keywords=keywords,
        keyword_rule=KEYWORD_RULE,
        months=rows_out,
        total_code_wide=total_all,
        total_keyword_matched=total_kw,
        quotes=quotes,
        sources=sources_block,
        recalls=recalls,
        clearances=clearances,
        dropped=dropped,
        notes=notes,
    )


def _month_end(d: date) -> date:
    nxt = date(d.year + (d.month == 12), d.month % 12 + 1, 1)
    return nxt - timedelta(days=1)


def _device_type_name(fut: Future[Reply], code: str, reports: int, notes: list[str]) -> str | None:
    try:
        r = fut.result()
    except MaudeSignalError:
        return None
    if not r.rows:
        if reports == 0:
            notes.append(
                f"FDA's classification list has no product code {code}. Check the spelling; "
                "a device name can be turned into a code with the lookup_device tool."
            )
        return None
    return _first_text(r.rows[0].get("device_name")) or None


def _sources(
    budget: Budget,
    source: Source,
    code: str,
    base: EventFilter,
    all_total: int,
    dropped: Dropped,
    notes: list[str],
    fut: Future[Reply],
) -> SourcesBlock | None:
    """Counts by filer type and the newest reports not filed by a manufacturer (F12)."""
    q = event_query(base, count="report_source_code.exact")
    try:
        got = fut.result()
    except MaudeSignalError:
        notes.append("Who filed the reports could not be read.")
        return None
    buckets = [
        SourceBucket(
            source=str(b.get("term")),
            normalized=normalize_source(str(b.get("term"))),
            count=int(b.get("count") or 0),
        )
        for b in got.rows
        if b.get("term")
    ]
    buckets.sort(key=lambda b: (-b.count, b.source))
    # Only terms that really go into the query are counted, so the number and its link agree.
    non_terms = tuple(
        b.source
        for b in buckets
        if b.normalized not in ("", "manufacturer") and _SAFE_SOURCE.match(b.source)
    )
    skipped = [
        b for b in buckets if b.normalized not in ("", "manufacturer") and b.source not in non_terms
    ]
    non_n = sum(b.count for b in buckets if b.source in non_terms)
    mfr_n = sum(b.count for b in buckets if b.normalized == "manufacturer")
    total = sum(b.count for b in buckets)
    note: str | None = None
    if skipped:
        note = "Some filer types could not be put into a query and are not in the count above."
    listed: list[ListedReport] = []
    only = EventFilter(code, base.start, base.end, sources=non_terms)
    if non_terms and non_n:
        try:
            rows = budget.call(
                source, event_query(only, limit=MAX_LISTED, sort="date_received:desc")
            ).rows
        except MaudeSignalError:
            rows = ()
            note = "The newest of these reports could not be listed."
        store = EvidenceStore.from_iterables(
            EvidenceRecord(report_id=str(r["mdr_report_key"]), product_code=code)
            for r in rows
            if r.get("mdr_report_key")
        )
        for r in rows:
            key = str(r.get("mdr_report_key") or "")
            if not key or verify_claim(RecordClaim(key, code), store).status != "pass":
                dropped.record_not_confirmed += 1
                continue
            listed.append(
                ListedReport(
                    report_number=str(r.get("report_number") or "") or None,
                    mdr_report_key=key,
                    date_received=str(r.get("date_received") or "") or None,
                    source=normalize_source(str(r.get("report_source_code") or "")),
                    maker=_maker(r),
                    url=links.report_link(key),
                )
            )
    # With no such filer type there is no query that returns "0 reports", so the figure is not
    # linked; the by-filer-type query (buckets_url) is what shows it.
    return SourcesBlock(
        buckets=buckets,
        buckets_url=q.url,
        manufacturer_count=mfr_n,
        non_manufacturer=Counted(value=non_n, url=event_query(only).url if non_terms else ""),
        no_source_count=max(0, all_total - total),
        reports=listed,
        note=note,
    )


def _recalls(fut: Future[Reply], code: str, dropped: Dropped) -> RecallsBlock:
    q = recall_query(code, MAX_LISTED)
    try:
        got = fut.result()
    except MaudeSignalError:
        return RecallsBlock(total=None, items=[], note="Recalls could not be read.")
    refs = [
        RecallRef(
            recall_number=str(r.get("product_res_number") or ""),
            product_code=code,
            recalling_firm=_first_text(r.get("recalling_firm")) or None,
            product_description=_first_text(r.get("product_description")),
            reason_for_recall=_first_text(r.get("reason_for_recall")),
            recall_status=_first_text(r.get("recall_status")) or None,
            date_initiated=_first_text(r.get("event_date_initiated")) or None,
        )
        for r in got.rows
        if r.get("product_res_number")
    ]
    store = EvidenceStore.from_iterables((), recalls=refs)
    items: list[RecallItem] = []
    for ref in refs:
        if verify_claim(RecallClaim(ref.recall_number, code), store).status != "pass":
            dropped.record_not_confirmed += 1
            continue
        items.append(
            RecallItem(
                recall_number=ref.recall_number,
                firm=ref.recalling_firm,
                status=ref.recall_status,
                date_initiated=ref.date_initiated,
                reason=_cut(ref.reason_for_recall, LIST_NOTE_CHARS),
                url=links.recall_link(ref.recall_number),
            )
        )
    return RecallsBlock(total=Counted(value=got.total, url=_one_url(q)), items=items)


def _clearances(fut: Future[Reply], code: str, dropped: Dropped) -> ClearancesBlock:
    q = k510_query(code, MAX_LISTED)
    try:
        got = fut.result()
    except MaudeSignalError:
        return ClearancesBlock(total=None, items=[], note="510(k)s could not be read.")
    refs = [
        DeviceRef(
            k_number=str(r.get("k_number") or "").upper(),
            product_code=code,
            device_name=_first_text(r.get("device_name")),
            company_name=_first_text(r.get("applicant")) or None,
            decision_date=_first_text(r.get("decision_date")) or None,
        )
        for r in got.rows
        if r.get("k_number")
    ]
    store = EvidenceStore.from_iterables((), clearances=refs)
    items: list[ClearanceItem] = []
    for ref in refs:
        if verify_claim(DeviceClaim(ref.k_number, code), store).status != "pass":
            dropped.record_not_confirmed += 1
            continue
        items.append(
            ClearanceItem(
                k_number=ref.k_number,
                device_name=ref.device_name,
                applicant=ref.company_name,
                decision_date=ref.decision_date,
                url=links.k510_link(ref.k_number),
            )
        )
    return ClearancesBlock(total=Counted(value=got.total, url=_one_url(q)), items=items)


def _cut(text: str, limit: int) -> str:
    """``text`` cut at a word boundary with an ellipsis when it is longer than ``limit``."""
    if len(text) <= limit:
        return text
    return text[:limit].rsplit(" ", 1)[0].rstrip(".,;: ") + "\u2026"


def _one_url(q: Query) -> str:
    """The link for a total: the same query, one row."""
    return replace(q, params=tuple((k, "1" if k == "limit" else v) for k, v in q.params)).url
