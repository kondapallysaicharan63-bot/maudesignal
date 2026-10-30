"""Device label reading -> possible openFDA matches -> device-type view.

HACKATHON-BUILT — Meta Global AI Developer Hackathon (Oct 26 – Nov 4, 2026).

The agentic next step after :mod:`maudesignal.vision.label` has read a photo:

1. **Search openFDA** with what was read. A printed K-number goes to ``device/510k``; a
   UDI / GTIN goes to ``device/udi``; otherwise the model number, device name and
   manufacturer go to ``device/510k``, ``device/registrationlisting`` and
   ``device/classification``. All searches are deterministic; no model is called here.
2. **Rank up to 3 possible matches** with a documented score (:data:`SCORING_RULES`).
   Each match says why it matched and what did NOT match. Records from the maker printed
   on the label rank first; a record from a different maker is shown with the mismatch,
   never as a maker match. Nothing is auto-picked: the result has ``confirmed = None``
   and ``status = "needs_person_to_confirm"`` until :func:`confirm` records a person.
3. **Precompute the device-type view** for each distinct product code among the matches
   (reports, recalls, 510(k) records, this week's change) so the UI can show it right
   after a person confirms. Every fact is a sentence that either passes the claim-level
   gate (:mod:`maudesignal.gate`) or is recomputed from the stored openFDA answer; one
   that fails is withheld and its text is never stored.
4. **Trace every step** (SAM 3.1 crop, Muse Spark read, each openFDA query, gate check,
   done) with timings measured by ``time.perf_counter``. A step that was not run in this
   process has ``elapsed_ms = None`` and ``timing = "not recorded"``.

Lot and serial numbers are never read into, or stored by, this module.
This is a search aid for a person; it does not identify a device and is not medical advice.
"""

from __future__ import annotations

import copy
import re
import time
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from fractions import Fraction
from types import SimpleNamespace
from typing import Any, Protocol, cast
from urllib.parse import quote

import httpx

from maudesignal.common.exceptions import (
    MaudeSignalError,
    OpenFDAAPIError,
    OpenFDAForbiddenError,
    OpenFDARateLimitError,
    OpenFDAUnavailableError,
)
from maudesignal.gate import (
    Claim,
    DeviceClaim,
    DeviceRef,
    EvidenceStore,
    RecallClaim,
    RecallCountClaim,
    RecallRef,
    verify_sentence,
)
from maudesignal.ingestion.openfda_client import USER_AGENT, OpenFDAClient
from maudesignal.monitor.deterioration import (
    BASELINE_WEEKS,
    SEVERITY_ESCALATION_PP,
    SPIKE_MIN_REPORTS,
    SPIKE_MULTIPLIER,
)
from maudesignal.monitor.digest import CHANGE_LABELS
from maudesignal.monitor.live_check import LiveCheck, check_product_code
from maudesignal.vision.fda_pdf import normalize_k_number
from maudesignal.vision.label import (
    SESSION_ONLY_FIELDS,
    LabelResult,
    gtin_check_digit_ok,
    parse_udi,
    read_device_label,
)
from maudesignal.vision.sam import SamClient
from maudesignal.vision.spark import DEFAULT_VISION_MODEL
from maudesignal.vision.verify import norm_company, norm_text

SCHEMA_VERSION = "1.0"
MAX_MATCHES = 3
RECALL_FETCH_LIMIT = 100  # openFDA rows fetched per device type; larger totals are recomputed
STATUS_NEEDS_PERSON = "needs_person_to_confirm"
STATUS_NO_MATCH = "no_match_found"
STATUS_CONFIRMED = "confirmed_by_person"
NOT_RECORDED = "not recorded"
DISCLAIMER = (
    "Possible matches for a person to confirm. This is a search of public openFDA records, "
    "not an identification of the device, and not medical advice."
)

ENDPOINTS: dict[str, str] = {
    "510k": "https://api.fda.gov/device/510k.json",
    "udi": "https://api.fda.gov/device/udi.json",
    "registrationlisting": "https://api.fda.gov/device/registrationlisting.json",
    "classification": "https://api.fda.gov/device/classification.json",
    "recall": "https://api.fda.gov/device/recall.json",
}

#: How a candidate is scored (shown to the reader; the numbers below are the code's).
W_EXACT_ID = 100
W_MANUFACTURER = 40
W_MODEL = 25
W_NAME_WORDS = 25
MIN_NAME_SHARE = 0.5
SCORING_RULES: tuple[str, ...] = (
    f"Exact K-number or GTIN printed on the label equals the record: {W_EXACT_ID} points.",
    f"Manufacturer: up to {W_MANUFACTURER} points, in proportion to the label's maker words "
    "found in the record's applicant / owner. A maker match needs all of them.",
    f"Model number found in the record's device name or model field: {W_MODEL} points.",
    f"Device name: up to {W_NAME_WORDS} points, in proportion to the label's name words "
    "found in the record.",
    "A record is kept only if it has an exact id, a maker match, a model match, or at least "
    f"{int(MIN_NAME_SHARE * 100)}% of the label's name words.",
    "Order: exact id first, then maker match, then score, then newest decision date, then id.",
    "At most 3 are shown. None is chosen for the person.",
)

_GENERIC_COMPANY = frozenset(
    (  # noqa: SIM905
        "usa us america americas international intl group holdings holding company technology "
        "technologies medical healthcare health systems system products product"
    ).split()
)
_STOP_WORDS = frozenset("a an and of the for with by in to or".split())  # noqa: SIM905
_TERM_CLEAN = re.compile(r"[^A-Za-z0-9 .\-]")
_SAFE = '+:"()[]*-.'


# ---------------------------------------------------------------------------
# openFDA search (injectable)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Answer:
    """One openFDA answer: the public URL, the match total, the rows, and the measured time."""

    url: str
    total: int
    results: tuple[dict[str, Any], ...]
    started_utc: str
    elapsed_ms: float | None


class Searcher(Protocol):
    """What :func:`match_label` needs from openFDA (tests inject a fake)."""

    def query(
        self, endpoint: str, search: str, *, limit: int = 25, sort: str | None = None
    ) -> Answer:
        """Run one search on ``ENDPOINTS[endpoint]``; ``search`` uses openFDA ``+`` syntax."""
        ...


CheckFn = Callable[[str], LiveCheck]


def utc_now() -> str:
    """Current UTC time, second precision."""
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def public_url(endpoint: str, search: str, limit: int, sort: str | None = None) -> str:
    """The openFDA URL a reader can open (never contains an API key)."""
    url = f"{ENDPOINTS[endpoint]}?search={quote(search, safe=_SAFE)}&limit={limit}"
    if sort:
        url += f"&sort={quote(sort, safe=_SAFE + ',')}"
    return url


class OpenFdaSearcher:
    """Real openFDA searches (User-Agent sent, key from the caller, 403 / 429 handled)."""

    def __init__(
        self,
        api_key: str | None = None,
        *,
        transport: httpx.BaseTransport | None = None,
        timeout_s: float = 30.0,
    ) -> None:
        """Create the searcher; ``api_key`` raises the rate limit and is never stored."""
        self._api_key = api_key
        self._client = httpx.Client(
            timeout=timeout_s, transport=transport, headers={"User-Agent": USER_AGENT}
        )

    def close(self) -> None:
        """Close the HTTP client."""
        self._client.close()

    def __enter__(self) -> OpenFdaSearcher:
        """Context-manager entry."""
        return self

    def __exit__(self, *exc: object) -> None:
        """Close on exit."""
        self.close()

    def query(
        self, endpoint: str, search: str, *, limit: int = 25, sort: str | None = None
    ) -> Answer:
        """Run one search; a 404 means no matches."""
        url = public_url(endpoint, search, limit, sort)
        request_url = url + (f"&api_key={quote(self._api_key, safe='')}" if self._api_key else "")
        started = utc_now()
        t0 = time.perf_counter()
        try:
            resp = self._client.get(request_url)
        except httpx.HTTPError as exc:
            raise OpenFDAAPIError(f"HTTP error contacting openFDA ({type(exc).__name__})") from exc
        elapsed = round((time.perf_counter() - t0) * 1000, 1)
        if resp.status_code == 404:
            return Answer(url, 0, (), started, elapsed)
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
        return Answer(url, total, rows, started, elapsed)


# ---------------------------------------------------------------------------
# Step trace (timings are measured, never written by hand)
# ---------------------------------------------------------------------------


@dataclass
class Trace:
    """Ordered steps; a step run here is timed with ``time.perf_counter``."""

    steps: list[dict[str, Any]] = field(default_factory=list)

    @contextmanager
    def step(self, name: str, model: str, **extra: Any) -> Iterator[dict[str, Any]]:
        """Time the body; the yielded dict can be updated with count / url / note."""
        entry: dict[str, Any] = {
            "step": name,
            "model": model,
            "started_utc": utc_now(),
            "elapsed_ms": None,
            "timing": NOT_RECORDED,
            **extra,
        }
        t0 = time.perf_counter()
        try:
            yield entry
        finally:
            entry["elapsed_ms"] = round((time.perf_counter() - t0) * 1000, 1)
            entry["timing"] = "measured"
            self.steps.append(entry)

    def add_answer(self, name: str, answer: Answer | None, error: str | None = None) -> None:
        """Record an openFDA answer already timed by the searcher."""
        self.steps.append(
            {
                "step": name,
                "model": "openFDA",
                "started_utc": answer.started_utc if answer else utc_now(),
                "elapsed_ms": answer.elapsed_ms if answer else None,
                "timing": "measured" if answer and answer.elapsed_ms is not None else NOT_RECORDED,
                "count": answer.total if answer else None,
                "url": answer.url if answer else None,
                **({"error": error} if error else {}),
            }
        )


def not_recorded_read_steps(reason: str) -> list[dict[str, Any]]:
    """SAM / Spark steps for a stored reading that was not re-run in this process."""
    return [
        {
            "step": "SAM 3.1 crop",
            "model": "SAM 3.1",
            "started_utc": None,
            "elapsed_ms": None,
            "timing": NOT_RECORDED,
            "note": reason,
        },
        {
            "step": "Muse Spark read",
            "model": "Muse Spark",
            "started_utc": None,
            "elapsed_ms": None,
            "timing": NOT_RECORDED,
            "note": reason,
        },
    ]


class _TimedSam:
    """Wraps a SAM client and measures each ``segment`` call."""

    def __init__(self, inner: SamClient) -> None:
        self._inner = inner
        self.calls: list[tuple[str, float]] = []
        self.prompts: list[str] = []

    def segment(self, image: Any, prompt: str) -> Any:
        if not self.calls:
            self.first_started = utc_now()
        t0 = time.perf_counter()
        try:
            return self._inner.segment(image, prompt)
        finally:
            self.calls.append((prompt, (time.perf_counter() - t0) * 1000))
            self.prompts.append(prompt)

    first_started: str = ""


class _TimedCompletions:
    """Measures ``create``; ``calls`` holds ``(started_utc, elapsed_ms)`` per call."""

    def __init__(self, inner: Any) -> None:
        self._inner = inner
        self.calls: list[tuple[str, float]] = []

    def create(self, *args: Any, **kwargs: Any) -> Any:
        started = utc_now()
        t0 = time.perf_counter()
        try:
            return self._inner.create(*args, **kwargs)
        finally:
            self.calls.append((started, (time.perf_counter() - t0) * 1000))


class _TimedClient:
    """Wraps an OpenAI-compatible client and measures ``chat.completions.create``."""

    def __init__(self, inner: Any) -> None:
        self.completions = _TimedCompletions(inner.chat.completions)
        self.chat = SimpleNamespace(completions=self.completions)

    @property
    def calls(self) -> list[tuple[str, float]]:
        return self.completions.calls


def read_label_timed(
    image_bytes: bytes,
    *,
    client: Any,
    sam: SamClient | None,
    model: str = DEFAULT_VISION_MODEL,
) -> tuple[LabelResult, list[dict[str, Any]]]:
    """Run SAM 3.1 + Muse Spark on a photo (``read_device_label``) and time each step.

    openFDA is not called here (``openfda=None``): the search is :func:`match_label`'s job.
    Used by ``scripts/record_label_matches.py`` and by the API's ``POST /v1/label``.

    Returns:
        ``(reading, [SAM step, Spark step])`` with measured ``elapsed_ms`` values.
    """
    timed_sam = _TimedSam(sam) if sam is not None else None
    timed_client = _TimedClient(client)
    result = read_device_label(
        image_bytes,
        client=timed_client,
        sam=cast(SamClient, timed_sam) if timed_sam else None,
        openfda=None,
        model=model,
    )
    if timed_sam is not None and timed_sam.calls:
        sam_step: dict[str, Any] = {
            "step": "SAM 3.1 crop",
            "model": "SAM 3.1",
            "started_utc": timed_sam.first_started,
            "elapsed_ms": round(sum(ms for _, ms in timed_sam.calls), 1),
            "timing": "measured",
            "note": (
                f"prompts tried: {', '.join(timed_sam.prompts)}; "
                f"{result.sam_note or 'crop used'}"
            ),
            "cost_usd": result.sam_cost_usd,
        }
    else:
        sam_step = not_recorded_read_steps("SAM was not configured or not called")[0]
    if timed_client.calls:
        started, ms = timed_client.calls[-1]
        spark_step: dict[str, Any] = {
            "step": "Muse Spark read",
            "model": "Muse Spark",
            "started_utc": started,
            "elapsed_ms": round(ms, 1),
            "timing": "measured",
            "input_tokens": result.input_tokens,
            "output_tokens": result.output_tokens,
            "cost_usd": result.spark_cost_usd,
        }
    else:
        spark_step = not_recorded_read_steps("Muse Spark was not called")[1]
    return result, [sam_step, spark_step]


# ---------------------------------------------------------------------------
# Reading helpers
# ---------------------------------------------------------------------------


def _field(reading: Mapping[str, Any], name: str) -> str:
    """The field's value when it was read (fully or partly), else ''."""
    raw = (reading.get("fields") or {}).get(name) or {}
    if raw.get("legibility") in ("not_present", "illegible"):
        return ""
    return str(raw.get("value") or "").strip()


# GS1 application identifiers kept from a printed UDI: GTIN (01), production date (11) and
# expiry (17). Everything else (lot 10, serial 21, and any other per-unit AI) is dropped.
_UDI_KEEP_AIS = ("01", "11", "17")


def sanitize_udi(udi: str) -> str:
    """Rebuild a human-readable UDI keeping only AIs 01 / 11 / 17 (never lot or serial)."""
    parsed = parse_udi(udi)
    return "".join(f"({ai}){parsed[ai]}" for ai in _UDI_KEEP_AIS if parsed.get(ai))


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


@dataclass(frozen=True)
class LabelInputs:
    """What the search uses, taken from the reading (lot / serial are never included)."""

    k_number: str | None
    k_number_printed: str
    gtin: str | None
    model_number: str
    device_name: str
    manufacturer: str

    def to_dict(self) -> dict[str, Any]:
        """JSON form (only what was read)."""
        return {
            "k_number": self.k_number,
            "gtin": self.gtin,
            "model_number": self.model_number or None,
            "device_name": self.device_name or None,
            "manufacturer": self.manufacturer or None,
        }


def inputs_from_reading(reading: Mapping[str, Any]) -> LabelInputs:
    """Pull the search inputs out of a label reading dict."""
    printed = _field(reading, "k_number")
    k: str | None
    try:
        k = normalize_k_number(printed) if printed else None
    except ValueError:
        k = None
    gtin_raw = _field(reading, "gtin")
    digits = re.sub(r"\D", "", gtin_raw)
    if not digits:
        udi = _field(reading, "udi")
        digits = re.sub(r"\D", "", parse_udi(udi).get("01", "")) if udi else ""
    gtin = digits if digits and gtin_check_digit_ok(digits) else None
    return LabelInputs(
        k_number=k,
        k_number_printed=printed,
        gtin=gtin,
        model_number=_field(reading, "model_number"),
        device_name=_field(reading, "device_name"),
        manufacturer=_field(reading, "manufacturer"),
    )


# ---------------------------------------------------------------------------
# Query plan
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class QuerySpec:
    """One planned openFDA search."""

    id: str
    endpoint: str
    search: str
    label: str
    limit: int = 25


def plan_queries(inp: LabelInputs) -> list[QuerySpec]:
    """The name / model / manufacturer searches (used when no id lookup answers).

    The maker-restricted searches come first; the name-only search is last and its
    results are scored down when the maker differs.
    """
    out: list[QuerySpec] = []
    core = _company_core(inp.manufacturer) if inp.manufacturer else []
    maker = f"applicant:{_phrase(' '.join(core))}" if core else ""
    firm = f"registration.owner_operator.firm_name:{_phrase(' '.join(core))}" if core else ""
    name_words = _words(inp.device_name)
    noun = name_words[-1] if name_words else ""
    model = inp.model_number
    model_ok = len(_alnum(model)) >= 3

    if maker and model_ok:
        out.append(
            QuerySpec(
                "510k-maker-model",
                "510k",
                f"{maker}+AND+device_name:{_phrase(model)}",
                "510(k): maker + model number",
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
            QuerySpec("510k-model", "510k", f"device_name:{_phrase(model)}", "510(k): model number")
        )
    if firm and model_ok:
        out.append(
            QuerySpec(
                "rl-maker-model",
                "registrationlisting",
                f"{firm}+AND+proprietary_name:{_phrase(model)}",
                "Registration & listing: maker + model number",
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
                "Registration & listing: model number",
            )
        )
    seen: set[tuple[str, str]] = set()
    unique: list[QuerySpec] = []
    for q in out:
        if (q.endpoint, q.search) not in seen:
            seen.add((q.endpoint, q.search))
            unique.append(q)
    return unique


def classification_by_name_query(inp: LabelInputs) -> QuerySpec | None:
    """Device-type search by name (used only when no record matched)."""
    if not inp.device_name:
        return None
    return QuerySpec(
        "class-name",
        "classification",
        f"device_name:{_phrase(inp.device_name)}",
        "Classification: device name",
        limit=10,
    )


# ---------------------------------------------------------------------------
# Candidates and scoring
# ---------------------------------------------------------------------------


@dataclass
class Candidate:
    """One openFDA record that may be the device on the label."""

    source: str  # 510k | udi | registrationlisting | classification
    record_id: str
    owner: str
    device_name: str
    product_code: str
    query_url: str
    model_text: str = ""
    decision_date: str = ""
    extra: dict[str, Any] = field(default_factory=dict)
    device_type_name: str = ""
    exact_id: str | None = None  # "k_number" | "gtin"
    score: int = 0
    manufacturer_match: bool = False
    manufacturer_partial: bool = False
    matched: list[str] = field(default_factory=list)
    not_matched: list[str] = field(default_factory=list)
    keep: bool = False

    def to_dict(self) -> dict[str, Any]:
        """JSON form."""
        return {
            "source": self.source,
            "record_id": self.record_id,
            "owner": self.owner or None,
            "device_name": self.device_name or None,
            "product_code": self.product_code or None,
            "device_type_name": self.device_type_name or None,
            "decision_date": self.decision_date or None,
            "query_url": self.query_url,
            "score": self.score,
            "manufacturer_match": self.manufacturer_match,
            "why_matched": list(self.matched),
            "why_not_matched": list(self.not_matched),
            **self.extra,
        }


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
        extra={"k_number": k},
    )


def candidate_from_udi(row: dict[str, Any], url: str) -> Candidate | None:
    """Candidate from a ``device/udi`` row."""
    codes = [c for c in row.get("product_codes") or [] if isinstance(c, dict)]
    ids = [str(i.get("id") or "") for i in row.get("identifiers") or [] if isinstance(i, dict)]
    key = str(row.get("public_device_record_key") or "") or (ids[0] if ids else "")
    if not key:
        return None
    first = codes[0] if codes else {}
    type_name = str(first.get("name") or (first.get("openfda") or {}).get("device_name") or "")
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
        device_type_name=type_name,
        extra={"identifiers": [i for i in ids if i][:3]},
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
        extra={"listing_name": prop or None, "fei_number": reg.get("fei_number")},
    )


def candidate_from_classification(row: dict[str, Any], url: str) -> Candidate | None:
    """Device-type candidate from a ``device/classification`` row (no maker)."""
    code = str(row.get("product_code") or "")
    if not code:
        return None
    name = str(row.get("device_name") or "")
    return Candidate(
        source="classification",
        record_id=code,
        owner="",
        device_name=name,
        product_code=code,
        query_url=url,
        device_type_name=name,
        extra={
            "regulation_number": row.get("regulation_number"),
            "device_class": row.get("device_class"),
        },
    )


def score_candidate(inp: LabelInputs, c: Candidate) -> Candidate:
    """Fill ``score``, ``matched``, ``not_matched``, ``manufacturer_match``, ``keep``."""
    score = 0
    matched: list[str] = []
    missed: list[str] = []
    c.manufacturer_match = False
    c.manufacturer_partial = False

    if c.exact_id == "k_number" and inp.k_number:
        score += W_EXACT_ID
        matched.append(f"K-number {inp.k_number} printed on the label equals this record")
    if c.exact_id == "gtin" and inp.gtin:
        score += W_EXACT_ID
        matched.append(f"GTIN {inp.gtin} on the label is listed on this record")

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
            c.manufacturer_partial = True
            missed.append(
                f"manufacturer name only partly matches: {len(found)} of {len(label_core)} "
                f"words of '{inp.manufacturer}' are in '{c.owner}'"
            )
        else:
            kind = "owner" if c.source in ("udi", "registrationlisting") else "applicant"
            missed.append(f"{kind} differs: {c.owner} vs {inp.manufacturer} on the label")
    elif inp.manufacturer and c.source != "classification":
        missed.append(f"record has no maker to compare with '{inp.manufacturer}'")

    model_hit = False
    if inp.model_number and len(_alnum(inp.model_number)) >= 3 and c.source != "classification":
        model_hit = _alnum(inp.model_number) in _alnum(c.model_text or c.device_name)
        where = {"510k": "the 510(k) device name", "udi": "the model / catalog field"}.get(
            c.source, "the listed product names"
        )
        if model_hit:
            score += W_MODEL
            matched.append(f"model {inp.model_number} appears in {where}")
        else:
            missed.append(f"model {inp.model_number} does not appear in {where}")

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

    c.score = score
    c.matched = matched
    c.not_matched = missed
    c.keep = bool(c.exact_id or c.manufacturer_match or model_hit or name_share >= MIN_NAME_SHARE)
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


def rank_candidates(inp: LabelInputs, cands: Sequence[Candidate]) -> list[Candidate]:
    """Score, drop weak ones, de-duplicate and return at most :data:`MAX_MATCHES`."""
    seen: set[tuple[str, str, str]] = set()
    scored: list[Candidate] = []
    for c in cands:
        key = (c.source, c.record_id, str(c.extra.get("listing_name") or ""))
        if key in seen:
            continue
        seen.add(key)
        score_candidate(inp, c)
        if c.keep:
            scored.append(c)
    return sorted(scored, key=_rank_key)[:MAX_MATCHES]


# ---------------------------------------------------------------------------
# Device-type view: facts through the gate or recomputed
# ---------------------------------------------------------------------------


@dataclass
class FactDraft:
    """A sentence about a device type, before it is checked."""

    id: str
    topic: str
    text: str
    query_url: str | None
    data: dict[str, Any]
    claims: list[Claim] = field(default_factory=list)
    recheck: Callable[[], bool] | None = None
    # "recomputed": the recheck applies the detector's rules again to stored counts.
    # "direct": the figure is the stored openFDA total / row itself (the recheck is only a
    # consistency test), so it is labelled as taken directly, not as independently checked.
    check_kind: str = "recomputed"
    query_urls: list[str] = field(default_factory=list)


WITHHELD_REASON = "could not be verified against the stored openFDA answer"


def check_facts(drafts: Sequence[FactDraft], store: EvidenceStore) -> list[dict[str, Any]]:
    """Gate (when the draft has claims) or recompute each draft; withhold failures.

    A withheld fact keeps only its id, topic, check kind, query link and a fixed reason:
    its sentence and figures are dropped and never stored.
    """
    out: list[dict[str, Any]] = []
    for d in drafts:
        if d.claims:
            check = "gate"
            ok = verify_sentence(d.text, d.claims, store).status == "pass"
        elif d.recheck is not None:
            check = d.check_kind
            ok = bool(d.recheck())
        else:
            check, ok = "none", False
        if ok:
            out.append(
                {
                    "id": d.id,
                    "topic": d.topic,
                    "status": "pass",
                    "check": check,
                    "text": d.text,
                    "data": d.data,
                    "query_url": d.query_url,
                    **({"query_urls": list(d.query_urls)} if d.query_urls else {}),
                }
            )
        else:
            out.append(
                {
                    "id": d.id,
                    "topic": d.topic,
                    "status": "withheld",
                    "check": check,
                    "text": None,
                    "data": None,
                    "reason": WITHHELD_REASON,
                    "query_url": d.query_url,
                    **({"query_urls": list(d.query_urls)} if d.query_urls else {}),
                }
            )
    return out


def _iso(ymd: str) -> str:
    return f"{ymd[:4]}-{ymd[4:6]}-{ymd[6:]}" if re.fullmatch(r"\d{8}", ymd) else ymd


def recompute_change(lc: LiveCheck) -> str:
    """Re-apply the detector's four rules to the figures stored in ``lc``."""
    if lc.as_of is None:
        return "stable"
    cur, base, prior = lc.current_count, lc.baseline_count, lc.prior_report_count
    triggers: list[str] = []
    if cur and (not prior or lc.new_event_types):
        triggers.append("new_signal")
    if cur and base:
        delta = Fraction(lc.current_severe_count, cur) - Fraction(lc.baseline_severe_count, base)
        if delta * 100 >= SEVERITY_ESCALATION_PP:
            triggers.append("severity_escalation")
    mean = Fraction(base, BASELINE_WEEKS)
    if cur >= SPIKE_MIN_REPORTS and cur >= SPIKE_MULTIPLIER * mean:
        triggers.append("spike")
    for name in ("new_signal", "severity_escalation", "spike"):
        if name in triggers:
            return name
    return "stable"


def live_query_entries(lc: LiveCheck) -> list[dict[str, Any]]:
    """One entry per LiveCheck query: its label, URL and the stored figure it produced."""
    figures: list[int | None] = [
        None,  # reports per day: a list of days, not one figure
        lc.current_count,
        lc.baseline_count,
        lc.prior_report_count,
        lc.prior_report_count,
    ]
    return [
        {"query": label, "url": url, "count": figures[i] if i < len(figures) else None}
        for i, (label, url) in enumerate(lc.queries)
    ]


def _same_total(value: int, answer: Answer) -> Callable[[], bool]:
    """Recheck: the figure still equals the stored answer's openFDA total."""
    return lambda: value == answer.total


def _row_code(row: dict[str, Any]) -> str:
    return str(row.get("product_code") or "")


def build_view_drafts(
    code: str,
    *,
    classification: Answer | None,
    clearances: Answer | None,
    recalls: Answer | None,
    live: LiveCheck | None,
    live_error: str | None,
) -> tuple[list[FactDraft], EvidenceStore, list[dict[str, Any]]]:
    """Compose the fact sentences for one product code from the stored answers."""
    drafts: list[FactDraft] = []
    unavailable: list[dict[str, Any]] = []

    def na(topic: str, why: str) -> None:
        unavailable.append(
            {
                "id": f"{code}:{topic}",
                "topic": topic,
                "status": "unavailable",
                "check": "none",
                "text": None,
                "data": None,
                "reason": why,
                "query_url": None,
            }
        )

    # --- device type name (recomputed from the classification answer) ---
    cls_row = None
    if classification is not None:
        cls_row = next((r for r in classification.results if _row_code(r) == code), None)
    if cls_row is not None and classification is not None:
        name = str(cls_row.get("device_name") or "")
        klass = cls_row.get("device_class")
        reg = cls_row.get("regulation_number")

        def re_cls(
            name: str = name, rows: tuple[dict[str, Any], ...] = classification.results
        ) -> bool:
            return any(
                _row_code(r) == code and str(r.get("device_name") or "") == name for r in rows
            )

        drafts.append(
            FactDraft(
                f"{code}:device_type",
                "device_type",
                f"Product code {code} is the device type '{name}' in the FDA classification "
                "database.",
                classification.url,
                {"device_type_name": name, "device_class": klass, "regulation_number": reg},
                recheck=re_cls,
                check_kind="direct",
            )
        )
    else:
        na("device_type", "no classification record was returned for this product code")

    # --- 510(k) records (count recomputed; latest through the gate) ---
    if clearances is not None:
        total = clearances.total
        drafts.append(
            FactDraft(
                f"{code}:clearances_total",
                "clearances_total",
                f"openFDA lists {total} 510(k) records under product code {code}.",
                clearances.url,
                {"total": total},
                recheck=_same_total(total, clearances),
                check_kind="direct",
            )
        )
        if clearances.results:
            r = clearances.results[0]
            k = str(r.get("k_number") or "")
            applicant = str(r.get("applicant") or "")
            decided = str(r.get("decision_date") or "")
            drafts.append(
                FactDraft(
                    f"{code}:clearances_latest",
                    "clearances_latest",
                    f"Most recent 510(k) under {code} on openFDA: {k} ({applicant}, decided "
                    f"{decided}).",
                    clearances.url,
                    {"k_number": k, "applicant": applicant, "decision_date": decided},
                    claims=[DeviceClaim(k_number=k, product_code=code)],
                )
            )
    else:
        na("clearances_total", "the openFDA 510(k) search failed")

    # --- recalls ---
    if recalls is not None:
        rtotal = recalls.total
        rows = recalls.results
        if rtotal <= len(rows):  # every row was fetched, so the gate can recount them
            drafts.append(
                FactDraft(
                    f"{code}:recalls_total",
                    "recalls_total",
                    f"openFDA lists {rtotal} recalls under product code {code}.",
                    recalls.url,
                    {"total": rtotal},
                    claims=[RecallCountClaim(product_code=code, value=rtotal)],
                )
            )
        else:
            drafts.append(
                FactDraft(
                    f"{code}:recalls_total",
                    "recalls_total",
                    f"openFDA lists {rtotal} recalls under product code {code}.",
                    recalls.url,
                    {"total": rtotal},
                    recheck=_same_total(rtotal, recalls),
                    check_kind="direct",
                )
            )
        if rows:
            r0 = rows[0]
            num = str(r0.get("product_res_number") or "")
            firm = str(r0.get("recalling_firm") or "")
            started = str(r0.get("event_date_initiated") or "")
            if num:
                drafts.append(
                    FactDraft(
                        f"{code}:recalls_latest",
                        "recalls_latest",
                        f"Most recent recall under {code} on openFDA: {num} ({firm}, started "
                        f"{started}).",
                        recalls.url,
                        {"recall_number": num, "firm": firm, "date_initiated": started},
                        claims=[RecallClaim(recall_number=num, product_code=code)],
                    )
                )
    else:
        na("recalls_total", "the openFDA recall search failed")

    # --- MAUDE reports and this week's change (recomputed from the stored counts) ---
    if live is not None:
        lc = live
        if lc.as_of is None:
            drafts.append(
                FactDraft(
                    f"{code}:reports_total",
                    "reports_total",
                    f"openFDA has no MAUDE reports for {code} in the last two years; "
                    f"{lc.prior_report_count} reports exist before that.",
                    lc.queries[0][1] if lc.queries else None,
                    {"total": lc.prior_report_count, "as_of": None},
                    recheck=lambda: lc.current_count == 0,
                    check_kind="direct",
                )
            )
        else:
            as_of = lc.as_of.isoformat()
            win = lc.to_dict()["window"]
            qurl = lc.queries[1][1] if len(lc.queries) > 1 else None
            prior_url = lc.queries[3][1] if len(lc.queries) > 3 else None
            drafts.append(
                FactDraft(
                    f"{code}:reports_total",
                    "reports_total",
                    f"MAUDE holds {lc.all_dates_total} reports for {code} up to {as_of}, the "
                    f"latest report date on openFDA: {lc.prior_report_count} before the 7 days "
                    f"ending {as_of} plus {lc.current_count} in them.",
                    prior_url,
                    {
                        "total": lc.all_dates_total,
                        "as_of": as_of,
                        "before_this_week": lc.prior_report_count,
                        "this_week": lc.current_count,
                    },
                    recheck=lambda: lc.all_dates_total == lc.prior_report_count + lc.current_count,
                    check_kind="direct",
                    query_urls=[u for u in (prior_url, qurl) if u],
                )
            )
            drafts.append(
                FactDraft(
                    f"{code}:reports_window",
                    "reports_window",
                    f"In the 7 days ending {as_of}, openFDA has {lc.current_count} reports for "
                    f"{code}; the 4 weeks before averaged {lc.baseline_weekly_mean:g} per week.",
                    qurl,
                    {
                        "count": lc.current_count,
                        "from": _iso(win["current_start"]),
                        "to": _iso(win["current_end"]),
                        "baseline_weekly_mean": lc.baseline_weekly_mean,
                    },
                    recheck=lambda: (
                        lc.baseline_weekly_mean == lc.baseline_count / BASELINE_WEEKS
                        and lc.current_count == sum(n for _, n in lc.current_event_type_counts)
                    ),
                    check_kind="direct",
                )
            )
        drafts.append(
            FactDraft(
                f"{code}:this_week_change",
                "this_week_change",
                f"This week's change for {code}: {lc.change}.",
                lc.queries[1][1] if len(lc.queries) > 1 else None,
                {
                    "change": lc.change,
                    "classification": lc.classification,
                    "triggers": list(lc.triggers),
                    "as_of": lc.as_of.isoformat() if lc.as_of else None,
                    "rules": [
                        "new kind of problem: reports this week and none before, or an event "
                        "type not seen before",
                        f"more serious than usual: Injury/Death share up {SEVERITY_ESCALATION_PP} "
                        f"points or more vs the 4 weeks before",
                        f"reports suddenly increased: at least {SPIKE_MIN_REPORTS} reports and "
                        f"{SPIKE_MULTIPLIER} times the 4-week weekly average",
                    ],
                },
                recheck=lambda: (
                    recompute_change(lc) == lc.classification
                    and CHANGE_LABELS[lc.classification] == lc.change
                ),
            )
        )
    else:
        na("reports_total", live_error or "the MAUDE count check did not run")

    store = EvidenceStore.from_iterables(
        [],
        clearances=[
            DeviceRef(
                k_number=str(r.get("k_number") or ""),
                product_code=_row_code(r),
                device_name=str(r.get("device_name") or ""),
                company_name=str(r.get("applicant") or "") or None,
                decision_date=str(r.get("decision_date") or "") or None,
            )
            for r in (clearances.results if clearances else ())
            if r.get("k_number")
        ],
        recalls=[
            RecallRef(
                recall_number=str(r.get("product_res_number") or ""),
                product_code=_row_code(r),
                event_number=str(r.get("res_event_number") or "") or None,
                recalling_firm=str(r.get("recalling_firm") or "") or None,
                product_description=str(r.get("product_description") or ""),
                reason_for_recall=str(r.get("reason_for_recall") or ""),
                recall_status=str(r.get("recall_status") or "") or None,
                date_initiated=re.sub(r"\D", "", str(r.get("event_date_initiated") or "")) or None,
            )
            for r in (recalls.results if recalls else ())
            if r.get("product_res_number")
        ],
    )
    return drafts, store, unavailable


# ---------------------------------------------------------------------------
# The whole step
# ---------------------------------------------------------------------------


def _error_name(exc: Exception) -> str:
    return type(exc).__name__


def match_label(
    reading: Mapping[str, Any],
    *,
    searcher: Searcher,
    check_fn: CheckFn | None = None,
    read_steps: Sequence[dict[str, Any]] | None = None,
    image_file: str | None = None,
    model_info: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Search openFDA from a label reading, rank possible matches, build device-type views.

    Args:
        reading: A label reading dict (``LabelResult.to_dict()`` or a stored
            ``demo/vision/label-*.json``). Lot / serial fields are ignored if present.
        searcher: openFDA searcher (:class:`OpenFdaSearcher`, or a fake in tests).
        check_fn: ``product code -> LiveCheck`` for the MAUDE counts and this week's
            change. None skips them (those facts are marked unavailable).
        read_steps: The SAM / Spark trace steps from :func:`read_label_timed`, or
            :func:`not_recorded_read_steps` for a stored reading.
        image_file: Photo file name to record.
        model_info: ``{"model", "skill_version", "input_tokens", "output_tokens",
            "cost_usd"}`` of the reading, copied through.

    Returns:
        The ``label-match`` dict: ``matches`` (at most 3), ``confirmed = None``,
        ``status``, ``device_type_views``, ``trace``. Nothing is auto-confirmed.
    """
    trace = Trace()
    trace.steps.extend(copy.deepcopy(list(read_steps or not_recorded_read_steps(NOT_RECORDED))))
    inp = inputs_from_reading(reading)
    queries_log: list[dict[str, Any]] = []
    cands: list[Candidate] = []
    basis = "none"

    def run(
        spec: QuerySpec, parse: Callable[[dict[str, Any], str], Candidate | None]
    ) -> list[Candidate]:
        try:
            ans = searcher.query(spec.endpoint, spec.search, limit=spec.limit)
        except MaudeSignalError as exc:
            queries_log.append(
                {
                    "id": spec.id,
                    "label": spec.label,
                    "url": public_url(spec.endpoint, spec.search, spec.limit),
                    "count": None,
                    "ok": False,
                    "error": _error_name(exc),
                }
            )
            trace.steps.append(
                {
                    "step": f"openFDA search: {spec.label}",
                    "model": "openFDA",
                    "started_utc": utc_now(),
                    "elapsed_ms": None,
                    "timing": NOT_RECORDED,
                    "count": None,
                    "url": public_url(spec.endpoint, spec.search, spec.limit),
                    "error": _error_name(exc),
                }
            )
            return []
        queries_log.append(
            {"id": spec.id, "label": spec.label, "url": ans.url, "count": ans.total, "ok": True}
        )
        trace.add_answer(f"openFDA search: {spec.label}", ans)
        found = [parse(r, ans.url) for r in ans.results]
        return [c for c in found if c is not None]

    # 1) exact ids first
    if inp.k_number:
        basis = "k_number"
        hits = run(
            QuerySpec("510k-k", "510k", f"k_number:{inp.k_number}", "510(k): K-number", 1),
            candidate_from_510k,
        )
        for c in hits:
            c.exact_id = "k_number"
        cands += hits
    if not cands and inp.gtin:
        basis = "gtin"
        ids = {inp.gtin, inp.gtin.zfill(14)}
        search = "+OR+".join(f"identifiers.id:{_phrase(i)}" for i in sorted(ids))
        hits = run(QuerySpec("udi-gtin", "udi", search, "UDI: GTIN", 10), candidate_from_udi)
        for c in hits:
            if any(
                _strip_zeros(i) == _strip_zeros(inp.gtin) for i in c.extra.get("identifiers", [])
            ):
                c.exact_id = "gtin"
        cands += hits
    # 2) model + name + manufacturer
    if not cands:
        basis = "model_name_manufacturer" if (inp.device_name or inp.model_number) else "none"
        for spec in plan_queries(inp):
            parse = {
                "510k": candidate_from_510k,
                "registrationlisting": candidate_from_listing,
            }[spec.endpoint]
            cands += run(spec, parse)
    ranked = rank_candidates(inp, cands)
    # 3) a device type only, when no record matched
    if not ranked and basis == "model_name_manufacturer":
        spec_c = classification_by_name_query(inp)
        if spec_c is not None:
            ranked = rank_candidates(inp, run(spec_c, candidate_from_classification))

    # device-type names for the matched product codes (one classification query)
    codes: list[str] = []
    for c in ranked:
        if c.product_code and c.product_code not in codes:
            codes.append(c.product_code)
    cls_answer: Answer | None = None
    if codes:
        spec_t = QuerySpec(
            "class-codes",
            "classification",
            "+OR+".join(f"product_code:{c}" for c in codes),
            "Classification: device type of the matched product codes",
            limit=len(codes) * 3,
        )
        try:
            cls_answer = searcher.query(spec_t.endpoint, spec_t.search, limit=spec_t.limit)
            queries_log.append(
                {
                    "id": spec_t.id,
                    "label": spec_t.label,
                    "url": cls_answer.url,
                    "count": cls_answer.total,
                    "ok": True,
                }
            )
            trace.add_answer(f"openFDA search: {spec_t.label}", cls_answer)
        except MaudeSignalError as exc:
            queries_log.append(
                {
                    "id": spec_t.id,
                    "label": spec_t.label,
                    "url": public_url(spec_t.endpoint, spec_t.search, spec_t.limit),
                    "count": None,
                    "ok": False,
                    "error": _error_name(exc),
                }
            )
            trace.add_answer(f"openFDA search: {spec_t.label}", None, _error_name(exc))
    if cls_answer is not None:
        names = {_row_code(r): str(r.get("device_name") or "") for r in cls_answer.results}
        for c in ranked:
            if not c.device_type_name:
                c.device_type_name = names.get(c.product_code, "")

    # device-type views
    all_drafts: list[tuple[str, list[FactDraft], EvidenceStore, list[dict[str, Any]]]] = []
    for code in codes:
        cls_one = None
        if cls_answer is not None:
            rows = tuple(r for r in cls_answer.results if _row_code(r) == code)
            cls_one = Answer(
                cls_answer.url, len(rows), rows, cls_answer.started_utc, cls_answer.elapsed_ms
            )
        kans = _safe_query(
            searcher,
            trace,
            queries_log,
            QuerySpec(
                f"510k-{code}", "510k", f"product_code:{code}", f"510(k) records for {code}", 3
            ),
            sort="decision_date:desc",
        )
        rans = _safe_query(
            searcher,
            trace,
            queries_log,
            QuerySpec(
                f"recall-{code}",
                "recall",
                f"product_code:{code}",
                f"Recalls for {code}",
                RECALL_FETCH_LIMIT,
            ),
            sort="event_date_initiated:desc",
        )
        live: LiveCheck | None = None
        live_err: str | None = None
        if check_fn is not None:
            with trace.step(
                f"openFDA search: MAUDE counts and this week's change for {code}", "openFDA"
            ) as st:
                try:
                    live = check_fn(code)
                    st["count"] = live.all_dates_total
                    st["url"] = live.queries[0][1] if live.queries else None
                    st["urls"] = [u for _, u in live.queries]
                    st["note"] = (
                        f"covers {len(live.queries)} openFDA queries; elapsed_ms is the combined "
                        "time of the whole check"
                    )
                    st["queries"] = live_query_entries(live)
                    queries_log.append(
                        {
                            "id": f"maude-{code}",
                            "label": f"MAUDE counts for {code}",
                            "url": st["url"],
                            "count": live.all_dates_total,
                            "ok": True,
                        }
                    )
                except MaudeSignalError as exc:
                    live_err = "the MAUDE count check failed"
                    st["error"] = _error_name(exc)
                    queries_log.append(
                        {
                            "id": f"maude-{code}",
                            "label": f"MAUDE counts for {code}",
                            "url": None,
                            "count": None,
                            "ok": False,
                            "error": _error_name(exc),
                        }
                    )
        all_drafts.append(
            (
                code,
                *build_view_drafts(
                    code,
                    classification=cls_one,
                    clearances=kans,
                    recalls=rans,
                    live=live,
                    live_error=live_err,
                ),
            )
        )

    views: dict[str, Any] = {}
    withheld_total = passed_total = 0
    with trace.step("Gate check", "gate") as gate_step:
        for code, drafts, store, unavailable in all_drafts:
            facts = check_facts(drafts, store) + unavailable
            passed_total += sum(1 for f in facts if f["status"] == "pass")
            withheld_total += sum(1 for f in facts if f["status"] == "withheld")
            views[code] = {
                "product_code": code,
                "device_type_name": next(
                    (
                        f["data"]["device_type_name"]
                        for f in facts
                        if f["topic"] == "device_type" and f["status"] == "pass"
                    ),
                    None,
                ),
                "facts": facts,
                "summary": {f["topic"]: f["data"] for f in facts if f["status"] == "pass"},
            }
        gate_step["count"] = passed_total
        gate_step["note"] = f"{passed_total} facts passed, {withheld_total} withheld"
    measured = [s["elapsed_ms"] for s in trace.steps if s.get("elapsed_ms") is not None]
    trace.steps.append(
        {
            "step": "Done",
            "model": "gate",
            "started_utc": utc_now(),
            "elapsed_ms": round(sum(measured), 1) if measured else None,
            "timing": "sum of the measured steps above" if measured else NOT_RECORDED,
        }
    )

    matches = [c.to_dict() for c in ranked]
    maker_found = any(c.manufacturer_match for c in ranked)
    if not ranked:
        status, note = STATUS_NO_MATCH, _no_match_note(inp, queries_log)
    else:
        status, note = STATUS_NEEDS_PERSON, _match_note(inp, ranked, maker_found)
    label_fields = {
        k: {
            "value": sanitize_udi(str(v.get("value", ""))) if k == "udi" else v.get("value", ""),
            "legibility": v.get("legibility", ""),
        }
        for k, v in (reading.get("fields") or {}).items()
        if k not in SESSION_ONLY_FIELDS
    }
    mi = dict(model_info or {})
    return {
        "kind": "device_label_match",
        "schema_version": SCHEMA_VERSION,
        "image_file": image_file,
        "generated_utc": utc_now(),
        "label": {
            "fields": label_fields,
            "session_fields_omitted": True,
            "overall_legibility": reading.get("overall_legibility", ""),
        },
        "search_basis": basis,
        "search_inputs": inp.to_dict(),
        "queries": queries_log,
        "matches": matches,
        "manufacturer_match_found": maker_found,
        "note": note,
        "status": status,
        "confirmed": None,
        "device_type_views": views,
        "trace": trace.steps,
        "scoring_rules": list(SCORING_RULES),
        "reading": {
            "model": mi.get("model") or reading.get("model") or None,
            "skill_version": mi.get("skill_version") or reading.get("skill_version") or None,
            "input_tokens": mi.get("input_tokens", reading.get("input_tokens")),
            "output_tokens": mi.get("output_tokens", reading.get("output_tokens")),
            "cost_usd": mi.get("cost_usd", reading.get("cost_usd")),
        },
        "disclaimer": DISCLAIMER,
    }


def _safe_query(
    searcher: Searcher,
    trace: Trace,
    log: list[dict[str, Any]],
    spec: QuerySpec,
    sort: str | None = None,
) -> Answer | None:
    try:
        ans = searcher.query(spec.endpoint, spec.search, limit=spec.limit, sort=sort)
    except MaudeSignalError as exc:
        url = public_url(spec.endpoint, spec.search, spec.limit, sort)
        log.append(
            {
                "id": spec.id,
                "label": spec.label,
                "url": url,
                "count": None,
                "ok": False,
                "error": _error_name(exc),
            }
        )
        trace.steps.append(
            {
                "step": f"openFDA search: {spec.label}",
                "model": "openFDA",
                "started_utc": utc_now(),
                "elapsed_ms": None,
                "timing": NOT_RECORDED,
                "count": None,
                "url": url,
                "error": _error_name(exc),
            }
        )
        return None
    log.append({"id": spec.id, "label": spec.label, "url": ans.url, "count": ans.total, "ok": True})
    trace.add_answer(f"openFDA search: {spec.label}", ans)
    return ans


def _no_match_note(inp: LabelInputs, log: list[dict[str, Any]]) -> str:
    if not (inp.k_number or inp.gtin or inp.device_name or inp.model_number):
        return (
            "The label reading has no K-number, UDI, model number or device name, so there was "
            "nothing to search openFDA with."
        )
    if log and not any(q["ok"] for q in log):
        return "openFDA could not be reached, so no search result is shown."
    return "No openFDA record matched what was read from this label."


def _match_note(inp: LabelInputs, ranked: Sequence[Candidate], maker_found: bool) -> str:
    if ranked[0].exact_id:
        return "A record matches an id printed on the label. A person must confirm it."
    if inp.manufacturer and not maker_found and any(c.manufacturer_partial for c in ranked):
        return (
            f"Records below partly match the maker name '{inp.manufacturer}' (some of its words "
            "are in the record's maker); none matches it fully. What differs is shown with each "
            "record. A person must confirm one, or none."
        )
    if inp.manufacturer and not maker_found:
        return (
            f"No record from '{inp.manufacturer}' was found; the records below are from other "
            "makers and are shown with what differs. A person must confirm one, or none."
        )
    return "These are possible matches. A person must confirm one, or none."


# ---------------------------------------------------------------------------
# Person confirms
# ---------------------------------------------------------------------------


def confirm(
    result: Mapping[str, Any], choice_index: int | None, person: str, *, when_utc: str | None = None
) -> dict[str, Any]:
    """Record which match a named person confirmed (returns a copy; nothing is auto-picked).

    Args:
        result: A :func:`match_label` result.
        choice_index: Index into ``result["matches"]``, or None for "none of these".
        person: Who confirmed (required; shown in the audit trail).
        when_utc: Override the timestamp (tests).

    Raises:
        ValueError: Empty person, or an index outside the matches.
    """
    who = " ".join((person or "").split())
    if not who:
        raise ValueError("a person's name is required to confirm a match")
    matches = result.get("matches") or []
    out = copy.deepcopy(dict(result))
    stamp = when_utc or utc_now()
    if choice_index is None:
        out["confirmed"] = {
            "index": None,
            "none_of_these": True,
            "person": who[:120],
            "confirmed_utc": stamp,
        }
    else:
        if not 0 <= choice_index < len(matches):
            raise ValueError(f"choice {choice_index} is not one of the {len(matches)} matches")
        m = matches[choice_index]
        out["confirmed"] = {
            "index": choice_index,
            "none_of_these": False,
            "source": m["source"],
            "record_id": m["record_id"],
            "product_code": m.get("product_code"),
            "person": who[:120],
            "confirmed_utc": stamp,
        }
    out["status"] = STATUS_CONFIRMED
    return out


def confirmed_view(result: Mapping[str, Any]) -> dict[str, Any] | None:
    """The device-type view of the confirmed match, or None until a person confirms one."""
    conf = result.get("confirmed")
    if not conf or conf.get("none_of_these"):
        return None
    code = conf.get("product_code")
    view = (result.get("device_type_views") or {}).get(code)
    return cast("dict[str, Any] | None", view)


def default_check_fn(api_key: str | None, today: date | None = None) -> CheckFn:
    """``product code -> LiveCheck`` using the existing client (same four rules as the detector)."""

    def run(code: str) -> LiveCheck:
        with OpenFDAClient(api_key) as client:
            return check_product_code(client, code, today or datetime.now(UTC).date())

    return run
