"""The ``lookup_device`` tool: possible FDA records for a device someone describes.

HACKATHON-BUILT — Meta Global AI Developer Hackathon (Oct 26 – Nov 4, 2026).

Muse can read a device photo itself and then ask this tool which FDA records fit what it read
(device name, model, maker, K-number, UDI or GTIN, product code). The tool is deterministic:
pure openFDA searches, no model call, nothing stored, nothing written. It searches the 510(k),
registration & listing and UDI endpoints, scores each record with fixed rules, and returns at
most three **possible** matches with ``why_matched`` and ``why_not_matched`` lists. It never
picks one: ``confirmed`` is always ``null`` and the speakable text says a person confirms.

For the product code(s) of the top matches it adds this week's change (the same deterministic
check as ``check_device_type``), the count of recalls started in the last two years and the
count of adverse-event reports, each with the openFDA link that shows the number.

The query plan and the scoring weights follow ``vision/label_match.py`` (the label-photo
matcher on the hackathon branch); they are restated here so this tool does not depend on the
Streamlit/vision stack. Both use the same weights so a label and a typed lookup rank alike.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol
from urllib.parse import quote

import httpx

from maudesignal.common.exceptions import (
    MaudeSignalError,
    OpenFDAAPIError,
    OpenFDAForbiddenError,
    OpenFDARateLimitError,
    OpenFDAUnavailableError,
)
from maudesignal.connector import links
from maudesignal.connector.errors import InvalidInputError
from maudesignal.connector.forbidden import is_clean
from maudesignal.connector.models import (
    Fact,
    LookupAnswer,
    LookupDeviceType,
    LookupLink,
    LookupMatch,
    LookupStatus,
    Provenance,
)
from maudesignal.connector.speech import compose, plural, speak_date, speak_range, were
from maudesignal.connector.tools import Clock, LiveChecker, screen, utc_now
from maudesignal.ingestion.openfda_client import USER_AGENT
from maudesignal.monitor.digest import CHANGE_LABELS
from maudesignal.monitor.live_check import LiveCheck, normalize_code
from maudesignal.vision.fda_pdf import normalize_k_number
from maudesignal.vision.label import gtin_check_digit_ok, parse_udi
from maudesignal.vision.verify import norm_company, norm_text

MAX_MATCHES = 3
MAX_DEVICE_TYPES = 2
RECALL_WINDOW_DAYS = 730
LEGAL_NOTE = "A person confirms which record, if any, is the device; nothing was chosen."

ENDPOINTS = {
    "510k": "https://api.fda.gov/device/510k.json",
    "udi": "https://api.fda.gov/device/udi.json",
    "registrationlisting": "https://api.fda.gov/device/registrationlisting.json",
    "classification": "https://api.fda.gov/device/classification.json",
    "recall": "https://api.fda.gov/device/recall.json",
    "event": "https://api.fda.gov/device/event.json",
}

# Same weights as vision/label_match.py.
W_EXACT_ID = 100
W_MANUFACTURER = 40
W_MODEL = 25
W_NAME_WORDS = 25
W_PRODUCT_CODE = 20
MIN_NAME_SHARE = 0.5

_GENERIC_COMPANY = frozenset(
    [
        *("usa", "us", "america", "americas", "international", "intl", "group", "holdings"),
        *("holding", "company", "technology", "technologies", "medical", "healthcare"),
        *("health", "systems", "system", "products", "product"),
    ]
)
_STOP_WORDS = frozenset("a an and of the for with by in to or".split())  # noqa: SIM905
_TERM_CLEAN = re.compile(r"[^A-Za-z0-9 .\-]")
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")
_SAFE = '+:"()[]*-.'
_ERROR_NAMES: dict[type[BaseException], str] = {
    OpenFDAForbiddenError: "refused (403)",
    OpenFDARateLimitError: "rate limited (429)",
    OpenFDAUnavailableError: "unavailable (5xx)",
}


# ---------------------------------------------------------------------------
# openFDA search (injectable)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Answer:
    """One openFDA answer: the public URL, the match total and the rows."""

    url: str
    total: int
    results: tuple[dict[str, Any], ...]


class Searcher(Protocol):
    """What the lookup needs from openFDA (tests inject a fake)."""

    def query(
        self, endpoint: str, search: str, *, limit: int = 25, sort: str | None = None
    ) -> Answer:
        """Run one search on ``ENDPOINTS[endpoint]``; ``search`` uses openFDA ``+`` syntax."""
        ...


def public_url(endpoint: str, search: str, limit: int, sort: str | None = None) -> str:
    """The openFDA URL a reader can open (never contains an API key)."""
    url = f"{ENDPOINTS[endpoint]}?search={quote(search, safe=_SAFE)}&limit={limit}"
    if sort:
        url += f"&sort={quote(sort, safe=_SAFE + ',')}"
    return url


class OpenFdaSearcher:
    """Real openFDA searches (User-Agent sent, optional key, 403 / 429 / 5xx raised)."""

    def __init__(
        self,
        api_key: str | None = None,
        *,
        transport: httpx.BaseTransport | None = None,
        timeout_s: float = 20.0,
    ) -> None:
        """Create the searcher; ``api_key`` raises the rate limit and is never stored in a URL."""
        self._api_key = api_key
        self._client = httpx.Client(
            timeout=timeout_s, transport=transport, headers={"User-Agent": USER_AGENT}
        )

    def close(self) -> None:
        """Close the HTTP client."""
        self._client.close()

    def query(
        self, endpoint: str, search: str, *, limit: int = 25, sort: str | None = None
    ) -> Answer:
        """Run one search; a 404 means no matches."""
        url = public_url(endpoint, search, limit, sort)
        request_url = url + (f"&api_key={quote(self._api_key, safe='')}" if self._api_key else "")
        try:
            resp = self._client.get(request_url)
        except httpx.HTTPError as exc:  # class name only: the message can hold the key URL
            raise OpenFDAAPIError(f"HTTP error contacting openFDA ({type(exc).__name__})") from exc
        if resp.status_code == 404:
            return Answer(url, 0, ())
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
        return Answer(url, total, rows)


# ---------------------------------------------------------------------------
# Inputs
# ---------------------------------------------------------------------------


def _alnum(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", text.casefold())


def _words(text: str) -> list[str]:
    seen: list[str] = []
    for w in norm_text(text).split():
        if w not in _STOP_WORDS and w not in seen:
            seen.append(w)
    return seen


def _company_core(name: str) -> list[str]:
    toks = [t for t in norm_company(name).split() if t not in _GENERIC_COMPANY]
    return toks or norm_company(name).split()


def _phrase(value: str) -> str:
    cleaned = " ".join(_TERM_CLEAN.sub(" ", value).split())
    return '"' + cleaned.replace(" ", "+") + '"'


def _strip_zeros(digits: str) -> str:
    return digits.lstrip("0") or "0"


def _text(value: str | None) -> str:
    return " ".join(_CONTROL.sub(" ", value or "").split())


@dataclass(frozen=True)
class LookupInputs:
    """The usable search inputs (cleaned) and notes about any that were dropped."""

    device_name: str
    model: str
    manufacturer: str
    k_number: str | None
    gtin: str | None
    product_code: str | None
    notes: tuple[str, ...]

    def used(self) -> list[str]:
        """Names of the inputs the search used."""
        pairs = [
            ("device_name", self.device_name),
            ("model", self.model),
            ("manufacturer", self.manufacturer),
            ("k_number", self.k_number),
            ("udi_or_gtin", self.gtin),
            ("product_code", self.product_code),
        ]
        return [name for name, value in pairs if value]


def clean_inputs(
    device_name: str | None = None,
    model: str | None = None,
    manufacturer: str | None = None,
    k_number: str | None = None,
    udi: str | None = None,
    gtin: str | None = None,
    product_code: str | None = None,
) -> LookupInputs:
    """Normalise the caller's inputs.

    A K-number or GTIN that is not valid is dropped with a note (a photo can be misread); the
    call fails only when nothing usable is left.

    Raises:
        InvalidInputError: No input was given, or none that can be searched.
    """
    notes: list[str] = []
    name, mdl, maker = _text(device_name), _text(model), _text(manufacturer)
    raw_k, raw_udi, raw_gtin, raw_code = (
        _text(k_number),
        _text(udi),
        _text(gtin),
        _text(product_code),
    )
    if not any((name, mdl, maker, raw_k, raw_udi, raw_gtin, raw_code)):
        raise InvalidInputError(
            "Give at least one of device_name, model, manufacturer, k_number, udi, gtin "
            "or product_code."
        )
    k: str | None = None
    if raw_k:
        try:
            k = normalize_k_number(raw_k)
        except ValueError:
            notes.append(f"The K-number '{raw_k}' is not K plus six digits, so it was not used.")
    digits = re.sub(r"\D", "", gtin or "")
    if not digits and raw_udi:
        digits = re.sub(r"\D", "", parse_udi(raw_udi).get("01", ""))
        if not digits and re.fullmatch(r"\d{8,14}", raw_udi):
            digits = raw_udi
    g: str | None = None
    if digits:
        if gtin_check_digit_ok(digits):
            g = digits
        else:
            notes.append("The UDI / GTIN did not pass the GS1 check digit, so it was not used.")
    elif raw_udi or raw_gtin:
        notes.append("No GTIN could be read from the UDI, so it was not used.")
    code: str | None = None
    if raw_code:
        try:
            code = normalize_code(raw_code)
        except Exception:  # LiveCheckError: a code is three letters
            notes.append(f"The product code '{raw_code}' is not three letters, so it was not used.")
    out = LookupInputs(name, mdl, maker, k, g, code, tuple(notes))
    if not out.used():
        raise InvalidInputError(" ".join(notes) or "None of the inputs can be searched.")
    return out


# ---------------------------------------------------------------------------
# Query plan, candidates, scoring
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class QuerySpec:
    """One planned openFDA search."""

    id: str
    endpoint: str
    search: str
    label: str
    limit: int = 25
    sort: str | None = None


def plan_queries(inp: LookupInputs) -> list[QuerySpec]:
    """Name / model / maker searches (maker-restricted first, name-only last)."""
    out: list[QuerySpec] = []
    core = _company_core(inp.manufacturer) if inp.manufacturer else []
    maker = f"applicant:{_phrase(' '.join(core))}" if core else ""
    firm = f"registration.owner_operator.firm_name:{_phrase(' '.join(core))}" if core else ""
    name_words = _words(inp.device_name)
    noun = name_words[-1] if name_words else ""
    model = inp.model
    model_ok = len(_alnum(model)) >= 3

    if maker and model_ok:
        out.append(
            QuerySpec(
                "510k-maker-model",
                "510k",
                f"{maker}+AND+device_name:{_phrase(model)}",
                "510(k): maker + model",
            )
        )
    if maker and noun:
        out.append(
            QuerySpec(
                "510k-maker-name",
                "510k",
                f"{maker}+AND+device_name:{_phrase(noun)}",
                "510(k): maker + device name word",
            )
        )
    if maker and not model_ok and not noun:
        out.append(QuerySpec("510k-maker", "510k", maker, "510(k): maker", 10))
    if inp.device_name:
        out.append(
            QuerySpec(
                "510k-name",
                "510k",
                f"device_name:{_phrase(inp.device_name)}",
                "510(k): device name",
            )
        )
    elif model_ok:
        out.append(
            QuerySpec("510k-model", "510k", f"device_name:{_phrase(model)}", "510(k): model")
        )
    if firm and model_ok:
        out.append(
            QuerySpec(
                "rl-maker-model",
                "registrationlisting",
                f"{firm}+AND+proprietary_name:{_phrase(model)}",
                "Registration & listing: maker + model",
            )
        )
    if firm and noun:
        out.append(
            QuerySpec(
                "rl-maker-name",
                "registrationlisting",
                f"{firm}+AND+products.openfda.device_name:{_phrase(noun)}",
                "Registration & listing: maker + device name word",
            )
        )
    elif model_ok:
        out.append(
            QuerySpec(
                "rl-model",
                "registrationlisting",
                f"proprietary_name:{_phrase(model)}",
                "Registration & listing: model",
            )
        )
    if inp.product_code and not (inp.device_name or model_ok or inp.manufacturer):
        out.append(
            QuerySpec(
                "510k-code",
                "510k",
                f"product_code:{inp.product_code}",
                "510(k): product code, newest first",
                MAX_MATCHES,
                "decision_date:desc",
            )
        )
    seen: set[tuple[str, str]] = set()
    unique: list[QuerySpec] = []
    for q in out:
        if (q.endpoint, q.search) not in seen:
            seen.add((q.endpoint, q.search))
            unique.append(q)
    return unique


@dataclass
class Candidate:
    """One openFDA record that may be the device described."""

    source: str  # 510k | udi | registrationlisting
    record_id: str
    owner: str
    device_name: str
    product_code: str
    query_url: str
    model_text: str = ""
    decision_date: str = ""
    k_number: str | None = None
    identifiers: list[str] = field(default_factory=list)
    exact_id: str | None = None  # "k_number" | "gtin"
    score: int = 0
    manufacturer_match: bool = False
    matched: list[str] = field(default_factory=list)
    not_matched: list[str] = field(default_factory=list)
    keep: bool = False


def _first(value: Any) -> str:
    if isinstance(value, list):
        return str(value[0]) if value else ""
    return str(value or "")


def candidate_from_510k(row: dict[str, Any], url: str) -> Candidate | None:
    """Candidate from a ``device/510k`` row."""
    k = str(row.get("k_number") or "").strip().upper()
    if not k:
        return None
    return Candidate(
        source="510k",
        record_id=k,
        owner=str(row.get("applicant") or ""),
        device_name=str(row.get("device_name") or ""),
        product_code=str(row.get("product_code") or ""),
        query_url=url,
        model_text=str(row.get("device_name") or ""),
        decision_date=str(row.get("decision_date") or ""),
        k_number=k,
    )


def candidate_from_udi(row: dict[str, Any], url: str) -> Candidate | None:
    """Candidate from a ``device/udi`` row."""
    codes = [c for c in row.get("product_codes") or [] if isinstance(c, dict)]
    ids = [str(i.get("id") or "") for i in row.get("identifiers") or [] if isinstance(i, dict)]
    key = str(row.get("public_device_record_key") or "") or (ids[0] if ids else "")
    if not key:
        return None
    first = codes[0] if codes else {}
    return Candidate(
        source="udi",
        record_id=key,
        owner=str(row.get("company_name") or ""),
        device_name=str(row.get("brand_name") or row.get("device_description") or ""),
        product_code=str(first.get("code") or ""),
        query_url=url,
        model_text=" ".join(
            str(row.get(k) or "")
            for k in ("version_or_model_number", "catalog_number", "brand_name")
        ),
        identifiers=[i for i in ids if i][:3],
    )


def candidate_from_listing(row: dict[str, Any], url: str) -> Candidate | None:
    """Candidate from a ``device/registrationlisting`` row."""
    reg = row.get("registration") or {}
    number = str(reg.get("registration_number") or "")
    if not number:
        return None
    owner = str((reg.get("owner_operator") or {}).get("firm_name") or reg.get("name") or "")
    products = [p for p in row.get("products") or [] if isinstance(p, dict)]
    prop = _first(row.get("proprietary_name"))
    dev = str((products[0].get("openfda") or {}).get("device_name") or "") if products else ""
    return Candidate(
        source="registrationlisting",
        record_id=number,
        owner=owner,
        device_name=" / ".join(x for x in (prop, dev) if x),
        product_code=str(products[0].get("product_code") or "") if products else "",
        query_url=url,
        model_text=" ".join(str(p) for p in (row.get("proprietary_name") or [])),
    )


def score_candidate(inp: LookupInputs, c: Candidate) -> Candidate:
    """Fill ``score``, ``matched``, ``not_matched``, ``manufacturer_match`` and ``keep``."""
    score = 0
    matched: list[str] = []
    missed: list[str] = []
    c.manufacturer_match = False

    if c.exact_id == "k_number" and inp.k_number:
        score += W_EXACT_ID
        matched.append(f"K-number {inp.k_number} you gave equals this record")
    if c.exact_id == "gtin" and inp.gtin:
        score += W_EXACT_ID
        matched.append(f"GTIN {inp.gtin} you gave is listed on this record")

    if inp.manufacturer and c.owner:
        label_core = _company_core(inp.manufacturer)
        owner_tokens = set(norm_company(c.owner).split())
        found = [t for t in label_core if t in owner_tokens]
        share = len(found) / len(label_core) if label_core else 0.0
        score += round(W_MANUFACTURER * share)
        if share == 1.0:
            c.manufacturer_match = True
            matched.append(f"manufacturer name matches '{inp.manufacturer}'")
        elif found:
            missed.append(
                f"manufacturer name only partly matches: {len(found)} of {len(label_core)} "
                f"words of '{inp.manufacturer}' are in '{c.owner}'"
            )
        else:
            kind = "owner" if c.source in ("udi", "registrationlisting") else "applicant"
            missed.append(f"{kind} differs: {c.owner} vs {inp.manufacturer} you gave")
    elif inp.manufacturer:
        missed.append(f"record has no maker to compare with '{inp.manufacturer}'")

    model_hit = False
    if inp.model and len(_alnum(inp.model)) >= 3:
        model_hit = _alnum(inp.model) in _alnum(c.model_text or c.device_name)
        where = {"510k": "the 510(k) device name", "udi": "the model / catalog field"}.get(
            c.source, "the listed product names"
        )
        if model_hit:
            score += W_MODEL
            matched.append(f"model {inp.model} appears in {where}")
        else:
            missed.append(f"model {inp.model} does not appear in {where}")

    name_share = 0.0
    label_words = _words(inp.device_name)
    if label_words:
        rec_words = set(_words(c.device_name))
        hit = [w for w in label_words if w in rec_words]
        name_share = len(hit) / len(label_words)
        score += round(W_NAME_WORDS * name_share)
        if hit:
            matched.append(f"device name shares {len(hit)} of {len(label_words)} words")
        if len(hit) < len(label_words):
            absent = [w for w in label_words if w not in rec_words]
            missed.append("device name words not in the record: " + ", ".join(absent))

    code_hit = False
    if inp.product_code:
        if c.product_code == inp.product_code:
            code_hit = True
            score += W_PRODUCT_CODE
            matched.append(f"product code {inp.product_code} equals this record")
        elif c.product_code:
            missed.append(f"product code differs: {c.product_code} vs {inp.product_code}")

    only_code = bool(inp.product_code) and not (
        inp.device_name or inp.model or inp.manufacturer or inp.k_number or inp.gtin
    )
    c.score = score
    c.matched = matched
    c.not_matched = missed
    c.keep = bool(
        c.exact_id
        or c.manufacturer_match
        or model_hit
        or name_share >= MIN_NAME_SHARE
        or (only_code and code_hit)
    )
    return c


def _rank_key(c: Candidate) -> tuple[int, int, int, str, str]:
    date_num = re.sub(r"\D", "", c.decision_date)
    return (
        0 if c.exact_id else 1,
        0 if c.manufacturer_match else 1,
        -c.score,
        "".join(chr(ord("9") - int(d)) for d in date_num),  # newest decision date first
        c.record_id,
    )


def rank_candidates(inp: LookupInputs, cands: Sequence[Candidate]) -> list[Candidate]:
    """Score, drop weak ones, de-duplicate and return at most :data:`MAX_MATCHES`."""
    seen: set[tuple[str, str, str]] = set()
    scored: list[Candidate] = []
    for c in cands:
        key = (c.source, c.record_id, c.device_name if c.source == "registrationlisting" else "")
        if key in seen:
            continue
        seen.add(key)
        score_candidate(inp, c)
        if c.keep:
            scored.append(c)
    return sorted(scored, key=_rank_key)[:MAX_MATCHES]


# ---------------------------------------------------------------------------
# The tool
# ---------------------------------------------------------------------------


def _clean(value: str) -> str:
    """Source text is passed on as it is, unless it holds a term this service does not repeat."""
    return value if is_clean(value) else "[text left out: open the link to read the source]"


def _opt(value: str) -> str | None:
    return _clean(value) if value else None


def _describe(c: Candidate) -> str:
    head = c.k_number or f"record {c.record_id}"
    parts = [head]
    if c.device_name:
        parts.append(_clean(c.device_name))
    if c.owner:
        parts.append(f"applicant {_clean(c.owner)}")
    if c.product_code:
        parts.append(f"product code {c.product_code}")
    if c.decision_date:
        parts.append(f"decision date {speak_date(c.decision_date)}")
    return ", ".join(parts)


def _change_text(check: LiveCheck) -> str:
    if check.window is None or check.as_of is None:
        return "no reports on openFDA in the last two years"
    changes = " and ".join(CHANGE_LABELS[t] for t in check.triggers) or check.change
    return f"{changes} as of {speak_date(check.as_of)}"


def lookup_device(
    *,
    device_name: str | None = None,
    model: str | None = None,
    manufacturer: str | None = None,
    k_number: str | None = None,
    udi: str | None = None,
    gtin: str | None = None,
    product_code: str | None = None,
    searcher: Searcher,
    live_checker: LiveChecker,
    now: Clock = utc_now,
) -> LookupAnswer:
    """Possible FDA records for a described device; a person confirms.

    Args:
        device_name: Name as read from a label or photo.
        model: Model, catalog or reference number.
        manufacturer: Maker named on the label.
        k_number: 510(k) number printed on the label (K plus six digits).
        udi: Printed UDI, such as ``(01)00380740000000(17)261231``.
        gtin: GTIN (8, 12, 13 or 14 digits).
        product_code: Three-letter FDA product code, if known.
        searcher: openFDA searcher (a fake in tests).
        live_checker: This week's change check (same as ``check_device_type``).
        now: Clock.

    Returns:
        A :class:`LookupAnswer`. ``confirmed`` is always ``None``.

    Raises:
        InvalidInputError: No usable input.
    """
    inp = clean_inputs(device_name, model, manufacturer, k_number, udi, gtin, product_code)
    started = now()
    log: list[tuple[str, bool]] = []  # (query label, ok)
    tried: list[str] = []
    notes: list[str] = list(inp.notes)

    def run(
        spec: QuerySpec, parse: Callable[[dict[str, Any], str], Candidate | None]
    ) -> list[Candidate]:
        tried.append(public_url(spec.endpoint, spec.search, spec.limit, spec.sort))
        try:
            ans = searcher.query(spec.endpoint, spec.search, limit=spec.limit, sort=spec.sort)
        except MaudeSignalError as exc:
            log.append((spec.label, False))
            reason = _ERROR_NAMES.get(type(exc), "could not be reached")
            notes.append(f"openFDA search '{spec.label}' failed: {reason}.")
            return []
        log.append((spec.label, True))
        return [c for r in ans.results if (c := parse(r, ans.url)) is not None]

    cands: list[Candidate] = []
    if inp.k_number:
        hits = run(
            QuerySpec("510k-k", "510k", f"k_number:{inp.k_number}", "510(k): K-number", 1),
            candidate_from_510k,
        )
        for c in hits:
            c.exact_id = "k_number"
        cands += hits
        if not hits:
            notes.append(f"No 510(k) record was found for K-number {inp.k_number}.")
    if inp.gtin:
        ids = {inp.gtin, inp.gtin.zfill(14)}
        search = "+OR+".join(f"identifiers.id:{_phrase(i)}" for i in sorted(ids))
        udi_hits = run(QuerySpec("udi-gtin", "udi", search, "UDI: GTIN", 10), candidate_from_udi)
        for c in udi_hits:
            if any(_strip_zeros(i) == _strip_zeros(inp.gtin) for i in c.identifiers):
                c.exact_id = "gtin"
        cands += udi_hits
    if not any(c.exact_id for c in cands):
        for spec in plan_queries(inp):
            parse = candidate_from_510k if spec.endpoint == "510k" else candidate_from_listing
            cands += run(spec, parse)
    ranked = rank_candidates(inp, cands)

    ok = sum(1 for _, good in log if good)
    failed = len(log) - ok
    status: LookupStatus
    if ranked:
        status = "needs_person_to_confirm"
    elif log and ok == 0:
        status = "search_failed"
    else:
        status = "no_match_found"

    matches: list[LookupMatch] = []
    facts: list[Fact] = []
    for i, c in enumerate(ranked, start=1):
        primary = links.k510_link(c.k_number) if c.k_number else c.query_url
        match_links = [LookupLink(label="openFDA record", url=primary)]
        if c.query_url != primary:
            match_links.append(LookupLink(label="openFDA search that found it", url=c.query_url))
        matches.append(
            LookupMatch(
                rank=i,
                source=c.source,
                record_id=c.record_id,
                k_number=c.k_number,
                device_name=_opt(c.device_name),
                applicant=_opt(c.owner),
                product_code=c.product_code or None,
                decision_date=c.decision_date or None,
                exact_id=c.exact_id,
                score=c.score,
                why_matched=[_clean(t) for t in c.matched],
                why_not_matched=[_clean(t) for t in c.not_matched],
                links=match_links,
            )
        )
        facts.append(
            Fact(
                text=f"Possible match {i}: {_describe(c)}.",
                link=primary,
                link_label="openFDA record",
            )
        )
        why = "; ".join(_clean(t) for t in c.matched) or "no field matched"
        text = f"Possible match {i} matched on: {why}."
        if c.not_matched:
            text += " Did not match on: " + "; ".join(_clean(t) for t in c.not_matched) + "."
        facts.append(Fact(text=text, link=c.query_url, link_label="openFDA search that found it"))

    device_types = _device_types(ranked, searcher, live_checker, started, facts, notes)

    if status == "needs_person_to_confirm":
        top = ranked[0]
        exact = " An id you gave equals this record." if top.exact_id else ""
        speak = [
            f"I found {plural(len(ranked), 'possible match', 'possible matches')} in FDA records.",
            f"The first possible match is {_describe(top)}.{exact}",
            "A person confirms which record, if any, is the device; nothing was chosen.",
        ]
        if failed:
            notes.append(f"{plural(failed, 'search')} failed, so there may be more records.")
    elif status == "search_failed":
        speak = [
            "openFDA could not be reached, so there are no possible matches to show.",
            "A person confirms the device once the search can run; nothing was chosen.",
            "Try again shortly.",
        ]
    else:
        speak = [
            "I found no possible matches in FDA records for what you gave.",
            "A person confirms the device from the label or the manufacturer; nothing was chosen.",
        ]
    if not facts:
        facts.append(
            Fact(
                text=(
                    "The openFDA search that was tried."
                    if tried
                    else "No search could be built from the inputs (a model needs 3 characters)."
                ),
                link=tried[-1] if tried else ENDPOINTS["510k"] + "?limit=1",
                link_label="openFDA search",
            )
        )
    note = " ".join(dict.fromkeys(notes)) or None
    answer = LookupAnswer(
        tool="lookup_device",
        speakable=compose(speak),
        facts=facts,
        provenance=Provenance(
            kind="live_openfda",
            source=(
                "openFDA device 510(k), registration & listing, UDI, recall and adverse-event "
                "endpoints (searches only; no model)"
            ),
            data_dates=f"recalls started {_recall_window(started)}",
            queried_at_utc=started.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            note="Possible matches only. " + LEGAL_NOTE,
        ),
        status=status,
        confirmed=None,
        note=note,
        searched_with=inp.used(),
        matches=matches,
        device_types=device_types,
    )
    screen(answer)
    return answer


def _recall_window(at: datetime) -> str:
    start = (at - timedelta(days=RECALL_WINDOW_DAYS)).date()
    return speak_range(start, at.date())


def _device_types(
    ranked: Sequence[Candidate],
    searcher: Searcher,
    live_checker: LiveChecker,
    at: datetime,
    facts: list[Fact],
    notes: list[str],
) -> list[LookupDeviceType]:
    """This week's change, recent recalls and report count for the top product code(s)."""
    codes: list[str] = []
    for c in ranked:
        if c.product_code and c.product_code not in codes:
            codes.append(c.product_code)
    out: list[LookupDeviceType] = []
    start = (at - timedelta(days=RECALL_WINDOW_DAYS)).date().isoformat()
    end = at.date().isoformat()
    window = _recall_window(at)
    for code in codes[:MAX_DEVICE_TYPES]:
        type_notes: list[str] = []
        type_name = ""
        try:
            cls = searcher.query("classification", f"product_code:{code}", limit=1)
            type_name = str(cls.results[0].get("device_name") or "") if cls.results else ""
            if type_name:
                type_name = _clean(type_name)
        except MaudeSignalError:
            type_notes.append("The device type name could not be read: openFDA was not reached.")
        change: str | None = None
        week_reports: int | None = None
        check_link: str | None = None
        try:
            check = live_checker(code)
            change = _change_text(check)
            week_reports = check.current_count if check.window else 0
            if check.window is not None:
                w = check.window
                cs, ce = w.current_start.strftime("%Y%m%d"), w.current_end.strftime("%Y%m%d")
                check_link = links.counts_link(code, cs, ce)
                facts.append(
                    Fact(
                        text=(
                            f"This week for {code}: {change}. There {were(check.current_count)} "
                            f"{plural(check.current_count, 'report')} received "
                            f"{speak_range(cs, ce)}."
                        ),
                        link=check_link,
                        link_label="openFDA: reports in this week",
                    )
                )
            else:
                check_link = links.counts_link(code, None, None)
                facts.append(
                    Fact(
                        text=f"This week for {code}: {change}.",
                        link=check_link,
                        link_label="openFDA: reports, all dates",
                    )
                )
        except MaudeSignalError:
            type_notes.append("This week's change could not be checked: openFDA was not reached.")
        recalls_n: int | None = None
        recalls_link: str | None = None
        try:
            ans = searcher.query(
                "recall",
                f"product_code:{code}+AND+event_date_initiated:[{start}+TO+{end}]",
                limit=1,
            )
            recalls_n, recalls_link = ans.total, ans.url
            facts.append(
                Fact(
                    text=(f"{plural(ans.total, 'recall record')} for {code} started {window}."),
                    link=ans.url,
                    link_label="openFDA: recent recalls",
                )
            )
        except MaudeSignalError:
            type_notes.append("Recent recalls could not be counted: openFDA was not reached.")
        reports_n: int | None = None
        reports_link: str | None = None
        try:
            rep = searcher.query("event", f"device.device_report_product_code:{code}", limit=1)
            reports_n, reports_link = rep.total, rep.url
            facts.append(
                Fact(
                    text=f"{plural(rep.total, 'report')} on openFDA for {code}, all dates.",
                    link=rep.url,
                    link_label="openFDA: reports, all dates",
                )
            )
        except MaudeSignalError:
            type_notes.append("The report count could not be read: openFDA was not reached.")
        out.append(
            LookupDeviceType(
                product_code=code,
                device_type_name=type_name or None,
                this_week_change=change,
                this_week_reports=week_reports,
                recent_recalls_count=recalls_n,
                recent_recalls_window=window,
                recent_recalls_link=recalls_link,
                report_count=reports_n,
                report_count_link=reports_link,
                check_link=check_link,
                note=" ".join(type_notes) or None,
            )
        )
        notes.extend(type_notes)
    return out
