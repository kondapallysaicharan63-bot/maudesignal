"""Research mode: public web links next to the FDA-records answer (behind ``MAUDESIGNAL_RESEARCH``).

HACKATHON-BUILT — Meta Global AI Developer Hackathon (Oct 26 – Nov 4, 2026).

One function, :func:`run_research`, used by the website route (``POST /v1/live/ask`` with
``research: true``) and by the connector tool. It sends at most ONE Responses API request to
Muse Spark 1.3 with the built-in ``web_search`` tool and turns the reply into a research
block::

    {"status": "ok" | "news_only" | "unavailable",
     "label": "Web research — not FDA records, not verified by the gate",
     "items": [{"title", "url", "date" | null, "source"}],   # http(s) only, deduped, <= 8
     "summary_text": null, "cost_usd": float, "note": str | null}

``summary_text`` is always ``null``: only title, link, date and source are shown.

SWITCH ON ONLY AFTER probe 2 (``scripts/research_probe.py``) has shown that Meta honours
``max_tool_calls`` and once the per-search fee is known. ``MAUDESIGNAL_RESEARCH`` is off by
default (``1`` / ``true`` / ``on`` turns it on); when off nothing here runs.

Rules:

* The block is never mixed into the gated answer: it is built here, from the web reply only,
  and the route puts it next to the answer. Nothing in it goes through or past the claim
  gate, and it is never counted as a MAUDE fact. The instructions come from the
  ``web-research`` Skill; no prompt text lives in Python.
* Request: ``reasoning.effort`` low, ``max_output_tokens`` 3000 (reasoning included),
  ``max_tool_calls`` 2, ``include: ["web_search_call.action.sources"]``, 45 s timeout, no SDK
  retries and NO retry of any kind. A 400 that names ``max_tool_calls`` or ``include`` switches
  web research off for this process (later questions skip the paid call) and the GDELT news
  index answers instead.
* Spend, worst case per request (the hold, reserved in the daily per-call ledger before the
  request is sent): ``RESEARCH_INPUT_TOKENS`` 15,000 input tokens x $1.25/M + 3,000 output
  tokens x $4.25/M + the search-fee allowance ``MAUDESIGNAL_RESEARCH_SEARCH_FEE_USD`` (default
  $0.05 per search; Meta's fee is NOT known to this repo, so this is a deliberately high
  stand-in) x max(``MAX_SEARCHES``, 2) = $0.01875 + $0.01275 + $0.10 = $0.1315. Probe 2 used
  5,411 input / 1,589 output tokens with ``max_tool_calls`` 2, so 15,000 input tokens is
  about 2.8x what was seen; a reply above it (or above any other limit the hold assumes) is
  flagged as an overshoot below. The hold is above the $0.10 per-call limit of the other
  routes, so Research has its own per-call limit ``MAUDESIGNAL_RESEARCH_HOLD_USD`` (default and
  ceiling $0.14) and reserves against a lower cap: the enforced cap minus (research limit -
  $0.10), 2.90 - 0.04 = 2.86 with the defaults, i.e. 3.00 - 0.14. With list-after-put
  visibility the later of two concurrent reservations sees the earlier one; if it did not,
  the day total is still at most min(2.90 + 0.14, 2.86 + 0.10) = 2.96 for a research call
  racing another call, and 2.86 + 0.14 = 3.00 for two research calls racing. In addition only
  ONE research request may be in flight at a time (``exclusive``), so overshoots cannot stack.
* Research-only daily dollar cap ``MAUDESIGNAL_RESEARCH_DAY_USD`` (default $0.30): the day's
  counted total of research ledger objects (``research-<uuid>.json``: settled at their real
  cost, unsettled or failed at their hold), this request's hold included, may not go above
  it; checked inside the same reservation as the global cap. With the defaults that is 2
  requests a day at their holds (2 x 0.1315 = 0.263; a third would make 0.3945), more only
  when earlier requests settled cheaper. Once reached, research is refused and the GDELT news
  path (or a clear note) answers, as for the global cap. It only ever lowers spend, so the
  $3.00 bound above is unchanged.
* After each reply: if it made more than ``MAX_SEARCHES`` searches, used more than
  ``MAX_OUTPUT_TOKENS`` output tokens or more than the 15,000 input-token allowance, or its
  real cost is above the hold, web research is switched off for this process AND for the rest
  of the UTC day in the ledger (flag ``research``), with a warning; the real cost is still
  settled. A request that fails or times out after it was sent (Meta may still bill it) also
  raises the day flag, and stays counted at its hold.
* Failure gives ``status: "unavailable"`` (or ``news_only`` when GDELT answers) and
  ``cost_usd`` = what the ledger counts for this request, so no partial cost is hidden.
* Items: url citations of the final message first, then ``web_search_call.action.sources``.
  Dates only from a date field the API returns (``null`` otherwise). A title holding a
  forbidden word (``connector.forbidden``) is replaced by the domain.
"""

from __future__ import annotations

import contextlib
import os
import re
import threading
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import quote_plus, urlparse

import httpx

from maudesignal.common.logging import get_logger
from maudesignal.connector.callcap import MAX_CALL_HOLD_USD, CallLedger, CallRefusedError
from maudesignal.connector.forbidden import is_clean
from maudesignal.connector.mentions import SOURCES as MENTION_SOURCES
from maudesignal.connector.mentions import Fetcher, parse_gdelt
from maudesignal.copilot.meta_provider import SPARK_USD_PER_M_INPUT, SPARK_USD_PER_M_OUTPUT
from maudesignal.extraction.skill_loader import SkillLoader

logger = get_logger(__name__)

RESEARCH_ENV = "MAUDESIGNAL_RESEARCH"
SEARCH_FEE_ENV = "MAUDESIGNAL_RESEARCH_SEARCH_FEE_USD"
PER_DAY_ENV = "MAUDESIGNAL_RESEARCH_PER_DAY"
SAVE_PER_DAY_ENV = "MAUDESIGNAL_RESEARCH_SAVE_PER_DAY"
HOLD_CAP_ENV = "MAUDESIGNAL_RESEARCH_HOLD_USD"
DAY_USD_ENV = "MAUDESIGNAL_RESEARCH_DAY_USD"
KILL_FLAG = "research"

LABEL = "Web research — not FDA records, not verified by the gate"
GDELT_SOURCE = "GDELT news index"
SKILL_NAME = "web-research"
INSTRUCTIONS_HEADING = "## Instructions (sent to the model)"

MODEL = "muse-spark-1.3"
RESPONSES_PATH = "/responses"
DEFAULT_BASE_URL = "https://api.meta.ai/v1"
MAX_OUTPUT_TOKENS = 3000
MAX_SEARCHES = 2
INCLUDE_SOURCES = "web_search_call.action.sources"
TIMEOUT_S = 45.0
MAX_REQUESTS = 1
#: Input-token allowance for the hold. Search results are added to the input by the API, so
#: the prompt size says nothing about it. Probe 1 used 24,256 input tokens for 7 searches
#: (no ``max_tool_calls``); probe 2 used 5,411 with ``max_tool_calls`` 2 (about 2,700 per
#: search plus the prompt). 15,000 is about 2.8x probe 2; a reply above it is an overshoot
#: (research is switched off for the day, the real cost is still settled).
RESEARCH_INPUT_TOKENS = 15_000
#: Per-search fee allowance (Meta's fee is not published to this repo): deliberately high.
DEFAULT_SEARCH_FEE_USD = 0.05
#: Research's own per-call hold limit (default and ceiling); see the module docstring.
DEFAULT_HOLD_CAP_USD = 0.14
MAX_HOLD_CAP_USD = 0.14
#: Research-only daily dollar cap (counted from the ledger's research objects).
DEFAULT_DAY_USD = 0.30
#: Ceiling of ``MAUDESIGNAL_RESEARCH_DAY_USD`` and of any caller-passed day cap.
MAX_DAY_USD = 0.50
DEFAULT_PER_DAY = 5
DEFAULT_SAVE_PER_DAY = 20
MAX_ITEMS = 8
MAX_SUMMARY_CHARS = 1500
MAX_TITLE_CHARS = 300
MAX_URL_CHARS = 2000
MAX_DATE_CHARS = 40
GDELT_TIMEOUT_S = 15.0

OPTIONAL_PARAMS = ("max_tool_calls", "include")
_DATE_KEYS = ("date", "published_date", "published_at", "publication_date", "page_age")
_TRUE = {"1", "true", "yes", "on"}

NOTE_LIMIT = "Daily limit of {n} web research requests reached. It resets at 00:00 UTC."
NOTE_UNAVAILABLE = "Web research is not available right now."
NOTE_NEWS_ONLY = "Web search was not available; showing news links from the GDELT news index."
NOTE_CAP = "Today's live-call budget is used up, so web search was not run."
NOTE_OFF = "Web search is switched off for now; showing news links only."
NOTE_DAY_CAP = "Today's web research budget is used up, so web search was not run."


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------


@contextlib.contextmanager
def research_forced_off() -> Iterator[None]:
    """Hide ``MAUDESIGNAL_RESEARCH`` while the committed API files are generated.

    The OpenAPI spec and MCP manifest in ``api/`` always describe the default deployment
    (Research off), whatever the generating shell has set.
    """
    saved = os.environ.pop(RESEARCH_ENV, None)
    try:
        yield
    finally:
        if saved is not None:
            os.environ[RESEARCH_ENV] = saved


def research_enabled(env: dict[str, str] | None = None) -> bool:
    """True when ``MAUDESIGNAL_RESEARCH`` turns Research mode on (default off)."""
    e = os.environ if env is None else env
    return str(e.get(RESEARCH_ENV, "")).strip().lower() in _TRUE


def _num_env(env: dict[str, str] | None, name: str, default: float) -> float:
    e = os.environ if env is None else env
    try:
        value = float(str(e.get(name, "")).strip())
    except ValueError:
        return default
    return value if value >= 0 and value == value else default


def search_fee_usd(env: dict[str, str] | None = None) -> float:
    """Per-search fee allowance (``MAUDESIGNAL_RESEARCH_SEARCH_FEE_USD``, default $0.05)."""
    return _num_env(env, SEARCH_FEE_ENV, DEFAULT_SEARCH_FEE_USD)


def per_day(env: dict[str, str] | None = None) -> int:
    """Research requests per visitor per UTC day (default 5)."""
    return max(1, int(_num_env(env, PER_DAY_ENV, DEFAULT_PER_DAY)))


def hold_cap_usd(env: dict[str, str] | None = None) -> float:
    """Research's per-call hold limit (``MAUDESIGNAL_RESEARCH_HOLD_USD``; default/ceiling 0.14)."""
    return min(MAX_HOLD_CAP_USD, _num_env(env, HOLD_CAP_ENV, DEFAULT_HOLD_CAP_USD))


def clamp_day_usd(value: float) -> float:
    """A research day cap held to ``0 .. MAX_DAY_USD`` (a non-finite value gives the default)."""
    if value != value or value in (float("inf"), float("-inf")):
        return DEFAULT_DAY_USD
    return max(0.0, min(MAX_DAY_USD, value))


def research_day_usd(env: dict[str, str] | None = None) -> float:
    """Research-only daily cap (``MAUDESIGNAL_RESEARCH_DAY_USD``): default $0.30, max $0.50."""
    return clamp_day_usd(_num_env(env, DAY_USD_ENV, DEFAULT_DAY_USD))


def save_per_day(env: dict[str, str] | None = None) -> int:
    """Saved links per visitor per UTC day (default 20)."""
    return max(1, int(_num_env(env, SAVE_PER_DAY_ENV, DEFAULT_SAVE_PER_DAY)))


def token_cost_usd(input_tokens: int, output_tokens: int) -> float:
    """Spark 1.3 Standard-tier token cost (prices in ``copilot/meta_provider.py``)."""
    return input_tokens * SPARK_USD_PER_M_INPUT / 1e6 + output_tokens * SPARK_USD_PER_M_OUTPUT / 1e6


def hold_usd(fee_per_search: float) -> float:
    """Worst-case cost of one research request (reserved before it is sent)."""
    return round(
        token_cost_usd(RESEARCH_INPUT_TOKENS, MAX_OUTPUT_TOKENS)
        + fee_per_search * max(MAX_SEARCHES, 2),
        6,
    )


# ---------------------------------------------------------------------------
# Skill
# ---------------------------------------------------------------------------


def _skills_root() -> Path:
    return Path(__file__).resolve().parents[3] / "skills"


def load_instructions(skills_root: Path | None = None) -> str:
    """The "Instructions (sent to the model)" section of the ``web-research`` Skill."""
    skill = SkillLoader(skills_root or _skills_root()).load(SKILL_NAME)
    text = skill.system_prompt
    start = text.find(INSTRUCTIONS_HEADING)
    if start < 0:
        raise ValueError("web-research SKILL.md has no instructions section")
    body = text[start + len(INSTRUCTIONS_HEADING) :]
    end = body.find("\n## ")
    return " ".join((body if end < 0 else body[:end]).split())


# ---------------------------------------------------------------------------
# Request and reply
# ---------------------------------------------------------------------------


def build_request(
    question: str,
    product_code: str | None,
    instructions: str,
    drop: frozenset[str] = frozenset(),
) -> dict[str, Any]:
    """The Responses API body (optional parameters in ``drop`` are left out)."""
    text = question.strip()
    if product_code:
        text += f"\nDevice type (FDA product code): {product_code.upper()}."
    body: dict[str, Any] = {
        "model": MODEL,
        "instructions": instructions,
        "input": text,
        "tools": [{"type": "web_search"}],
        "max_output_tokens": MAX_OUTPUT_TOKENS,
        "reasoning": {"effort": "low"},
        "stream": False,
        "max_tool_calls": MAX_SEARCHES,
        "include": [INCLUDE_SOURCES],
    }
    for name in drop:
        body.pop(name, None)
    return body


def domain_of(url: str) -> str:
    """The link's host without ``www.``."""
    host = (urlparse(url).hostname or "").lower()
    return host[4:] if host.startswith("www.") else host


def clean_url(raw: Any) -> str | None:
    """An http(s) URL with a host, at most 2000 characters, or ``None``."""
    if not isinstance(raw, str):
        return None
    url = raw.strip()
    if not url or len(url) > MAX_URL_CHARS or any(c.isspace() for c in url):
        return None
    try:
        parts = urlparse(url)
    except ValueError:
        return None
    if parts.scheme not in ("http", "https") or not parts.hostname:
        return None
    return url


def _date_of(obj: dict[str, Any]) -> str | None:
    for key in _DATE_KEYS:
        value = obj.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()[:MAX_DATE_CHARS]
    return None


def safe_title(raw: Any, url: str) -> str:
    """The title cut to 300 characters, or the domain when empty or holding a forbidden word."""
    title = " ".join(str(raw or "").split())[:MAX_TITLE_CHARS]
    return title if title and is_clean(title) else domain_of(url)


def _dedupe_key(url: str) -> str:
    parts = urlparse(url)
    host = domain_of(url)
    path = parts.path.rstrip("/")
    return f"{host}{path}?{parts.query}"


@dataclass
class ParsedReply:
    """What one Responses API reply holds for Research mode."""

    items: list[dict[str, Any]] = field(default_factory=list)
    summary_text: str | None = None
    searches: int = 0
    input_tokens: int | None = None
    output_tokens: int | None = None


def _add(items: list[dict[str, Any]], seen: set[str], obj: dict[str, Any], source: str) -> None:
    url = clean_url(obj.get("url"))
    if url is None or len(items) >= MAX_ITEMS:
        return
    key = _dedupe_key(url)
    if key in seen:
        return
    seen.add(key)
    items.append(
        {
            "title": safe_title(obj.get("title"), url),
            "url": url,
            "date": _date_of(obj),
            "source": source or domain_of(url),
        }
    )


def parse_reply(body: dict[str, Any]) -> ParsedReply:
    """Items (citations first, then search sources), summary text, searches made and usage."""
    out = ParsedReply()
    citations: list[dict[str, Any]] = []
    sources: list[dict[str, Any]] = []
    texts: list[str] = []
    for item in body.get("output") or []:
        if not isinstance(item, dict):
            continue
        kind = item.get("type")
        if kind == "web_search_call":
            out.searches += 1
            action = item.get("action")
            if isinstance(action, dict):
                sources.extend(s for s in action.get("sources") or [] if isinstance(s, dict))
        elif kind == "message":
            for part in item.get("content") or []:
                if not isinstance(part, dict):
                    continue
                if isinstance(part.get("text"), str):
                    texts.append(part["text"])
                for ann in part.get("annotations") or []:
                    if isinstance(ann, dict) and ann.get("type") == "url_citation":
                        citations.append(ann)
    seen: set[str] = set()
    for obj in citations + sources:
        _add(out.items, seen, obj, "")
    # summary_text stays None: Research mode shows title, link, date and source only.
    usage = body.get("usage")
    if isinstance(usage, dict):
        tin, tout = usage.get("input_tokens"), usage.get("output_tokens")
        if isinstance(tin, int) and isinstance(tout, int):
            out.input_tokens, out.output_tokens = tin, tout
    return out


def error_text(body: Any) -> str:
    """The error text of an error reply (never holds the key: it is never in the body)."""
    if isinstance(body, dict):
        err = body.get("error")
        if isinstance(err, dict):
            return " | ".join(str(err.get(k)) for k in ("param", "message") if err.get(k))
        return str(err or "")[:500]
    return str(body)[:500]


def rejected_params(status: int, message: str) -> frozenset[str]:
    """Optional parameters a 400 names (web research is then switched off; never retried)."""
    if status != 400:
        return frozenset()
    low = message.lower()
    return frozenset(p for p in OPTIONAL_PARAMS if p in low)


# ---------------------------------------------------------------------------
# Transport
# ---------------------------------------------------------------------------


class ResearchTransport(Protocol):
    """One Responses API request: returns ``(HTTP status, decoded JSON or text)``."""

    def post(self, body: dict[str, Any]) -> tuple[int, Any]:
        """Send ``body``; raises on a network failure or timeout."""


class HttpResearchTransport:
    """Real transport: httpx, Bearer key in the header only, 45 s timeout, no retries."""

    def __init__(
        self, api_key: str, *, base_url: str = DEFAULT_BASE_URL, timeout_s: float = TIMEOUT_S
    ) -> None:
        """Create the transport (the key is never logged)."""
        self._key = api_key
        self._url = base_url.rstrip("/") + RESPONSES_PATH
        self._timeout = timeout_s

    def post(self, body: dict[str, Any]) -> tuple[int, Any]:  # pragma: no cover - network
        """POST one request."""
        with httpx.Client(timeout=self._timeout) as client:
            resp = client.post(
                self._url,
                json=body,
                headers={"Authorization": f"Bearer {self._key}"},
            )
        try:
            return resp.status_code, resp.json()
        except ValueError:
            return resp.status_code, resp.text[:500]


#: Why web research is switched off in this process (empty: it is on).
_DISABLED: list[str] = []
_DISABLED_LOCK = threading.Lock()


def disable_for_process(reason: str) -> None:
    """Switch the paid web search off for this process (later questions get GDELT only)."""
    with _DISABLED_LOCK:
        if not _DISABLED:
            _DISABLED.append(reason)
    logger.warning("research_disabled_for_process", reason=reason)


def disabled_reason() -> str | None:
    """Why web research is off in this process, or ``None``."""
    with _DISABLED_LOCK:
        return _DISABLED[0] if _DISABLED else None


def reset_rejected() -> None:
    """Switch web research back on for this process (tests)."""
    with _DISABLED_LOCK:
        _DISABLED.clear()


def overshoot(parsed: ParsedReply) -> str | None:
    """Why a reply went past the limits the hold assumes, or ``None``."""
    if parsed.searches > MAX_SEARCHES:
        return f"{parsed.searches} searches (limit {MAX_SEARCHES})"
    if parsed.output_tokens is not None and parsed.output_tokens > MAX_OUTPUT_TOKENS:
        return "output tokens above max_output_tokens"
    if parsed.input_tokens is not None and parsed.input_tokens > RESEARCH_INPUT_TOKENS:
        return "input tokens above the hold's allowance"
    return None


# ---------------------------------------------------------------------------
# GDELT backup (news only)
# ---------------------------------------------------------------------------

_WORD = re.compile(r"[A-Za-z][A-Za-z0-9-]{3,}")
_STOP = frozenset(
    {"what", "when", "which", "with", "about", "from", "have", "this", "that", "there", "were"}
    | {"recent", "give", "show", "tell", "list", "links", "dates", "titles", "does", "their"}
)


def gdelt_terms(question: str, product_code: str | None) -> list[str]:
    """Up to four search words from the question (no stop words), plus the product code."""
    words = [w for w in _WORD.findall(question) if w.lower() not in _STOP]
    terms = list(dict.fromkeys(words))[:4]
    if product_code:
        terms.insert(0, product_code.upper())
    return terms


def gdelt_items(
    question: str, product_code: str | None, fetcher: Fetcher, timeout_s: float = GDELT_TIMEOUT_S
) -> list[dict[str, Any]] | None:
    """News links from the GDELT news index, or ``None`` when GDELT could not be read."""
    terms = gdelt_terms(question, product_code)
    if not terms:
        return []
    gdelt = next(s for s in MENTION_SOURCES if s.style == "gdelt")
    query = quote_plus(" ".join(f'"{t}"' if " " in t else t for t in terms) + " sourcelang:english")
    try:
        status, text = fetcher.get(gdelt.url.replace("{query}", query), timeout_s)
        if status != 200:
            return None
        cands = parse_gdelt(text, gdelt)
    except Exception as exc:  # noqa: BLE001 - the backup failing only means no items
        logger.warning("research_gdelt_failed", error_type=type(exc).__name__)
        return None
    items: list[dict[str, Any]] = []
    seen: set[str] = set()
    for c in cands:
        _add(items, seen, {"url": c.url, "title": c.title, "date": c.date or None}, GDELT_SOURCE)
    return items


# ---------------------------------------------------------------------------
# The one entry point
# ---------------------------------------------------------------------------


def block(
    status: str,
    items: list[dict[str, Any]],
    summary_text: str | None,
    cost_usd: float,
    note: str | None,
) -> dict[str, Any]:
    """The research block in its fixed shape."""
    return {
        "status": status,
        "label": LABEL,
        "items": items[:MAX_ITEMS],
        "summary_text": summary_text,
        "cost_usd": round(max(0.0, cost_usd), 6),
        "note": note,
    }


def limit_block(limit: int) -> dict[str, Any]:
    """The block shown when the visitor's daily research limit is used up (no call made)."""
    return block("unavailable", [], None, 0.0, NOTE_LIMIT.format(n=limit))


def run_research(
    question: str,
    product_code: str | None,
    *,
    transport: ResearchTransport | None,
    ledger: CallLedger | None,
    fee_per_search: float = DEFAULT_SEARCH_FEE_USD,
    news_fetcher: Callable[[], Fetcher] | None = None,
    instructions: str | None = None,
    hold_cap: float = DEFAULT_HOLD_CAP_USD,
    day_cap: float | None = None,
) -> dict[str, Any]:
    """Run Research mode for one question and return the research block.

    Args:
        question: The visitor's question (already checked for patient data).
        product_code: Optional three-letter product code.
        transport: Responses API transport; ``None`` when there is no model key.
        ledger: The daily per-call ledger; ``None`` means no shared ledger, so no call is made.
        fee_per_search: Search-fee allowance in USD (see the module docstring).
        news_fetcher: Factory for the GDELT backup's HTTP fetcher (``None``: no backup).
        instructions: Instructions text (tests); read from the Skill when omitted.
        hold_cap: Research's per-call hold limit (at most ``MAX_HOLD_CAP_USD``).
        day_cap: Research-only daily dollar cap; ``None`` reads ``MAUDESIGNAL_RESEARCH_DAY_USD``.

    Returns:
        The research block. Never raises for a model, network or ledger failure.
    """
    counted = 0.0
    note: str | None = NOTE_UNAVAILABLE
    if disabled_reason() is not None:
        note = NOTE_OFF
    elif transport is not None and ledger is not None:
        result = _web_search(
            question,
            product_code,
            transport,
            ledger,
            fee_per_search,
            instructions,
            hold_cap,
            research_day_usd() if day_cap is None else clamp_day_usd(day_cap),
        )
        if isinstance(result, dict):
            return result
        counted, note = result
    if news_fetcher is not None:
        news = gdelt_items(question, product_code, news_fetcher())
        if news:
            return block("news_only", news, None, counted, NOTE_NEWS_ONLY)
    return block("unavailable", [], None, counted, note)


def _web_search(
    question: str,
    product_code: str | None,
    transport: ResearchTransport,
    ledger: CallLedger,
    fee_per_search: float,
    instructions: str | None,
    hold_cap: float,
    day_cap: float,
) -> dict[str, Any] | tuple[float, str]:
    """The one paid request: the ``ok`` block, or ``(counted_usd, note)`` when it failed."""
    try:
        text = instructions if instructions is not None else load_instructions()
    except Exception as exc:  # noqa: BLE001 - a broken Skill file means no research
        logger.error("research_skill_unreadable", error_type=type(exc).__name__)
        return 0.0, NOTE_UNAVAILABLE
    cap_limit = min(max(hold_cap, 0.0), MAX_HOLD_CAP_USD)
    hold = hold_usd(fee_per_search)
    reply: dict[str, Any] = {}
    body = build_request(question, product_code, text)

    def call() -> ParsedReply:
        status, data = transport.post(body)
        reply["status"], reply["data"] = status, data
        if not 200 <= status < 300 or not isinstance(data, dict):
            if rejected_params(status, error_text(data)):
                # Switched off before the hold is released, so no request slips in between.
                disable_for_process("a 400 rejected max_tool_calls or include")
            raise RuntimeError(f"research http {status}")
        return parse_reply(data)

    def actual(parsed: ParsedReply) -> float | None:
        if parsed.input_tokens is None or parsed.output_tokens is None:
            return None
        return round(
            token_cost_usd(parsed.input_tokens, parsed.output_tokens)
            + parsed.searches * fee_per_search,
            6,
        )

    def checked_cost(parsed: ParsedReply) -> float | None:
        """The real cost; a reply past the hold's limits first switches research off."""
        why = overshoot(parsed)
        if why is not None:  # before the settle, so no request is reserved in between
            disable_for_process(why)
            ledger.set_flag(KILL_FLAG, why)
        return actual(parsed)

    try:
        parsed: ParsedReply = ledger.metered(
            hold,
            call,
            checked_cost,
            kill_flag=KILL_FLAG,
            max_hold_usd=cap_limit,
            cap_usd=research_cap(ledger.cap_usd, cap_limit),
            kind=KILL_FLAG,
            exclusive=True,
            blocked_by=KILL_FLAG,
            kind_cap_usd=day_cap,
        )
    except CallRefusedError as exc:
        if exc.cap == "flag":
            return 0.0, NOTE_OFF
        if exc.cap == "kind_cap":
            return 0.0, NOTE_DAY_CAP
        return 0.0, NOTE_CAP if exc.cap == "cap" else NOTE_UNAVAILABLE
    except Exception as exc:  # noqa: BLE001 - the request was sent: its hold counts
        status = int(reply.get("status") or 0)
        logger.warning("research_call_failed", error_type=type(exc).__name__, http_status=status)
        return hold, NOTE_UNAVAILABLE
    cost = actual(parsed)
    return block("ok", parsed.items, None, hold if cost is None else cost, None)


def research_cap(enforced_cap_usd: float, hold_cap: float) -> float:
    """The cap research reserves against: the enforced cap minus (its limit - the $0.10 limit)."""
    return round(enforced_cap_usd - max(0.0, hold_cap - MAX_CALL_HOLD_USD), 6)


#: What a saved link records as its saver: never an identity (a typed ref is not one).
SAVED_BY = "unverified visitor"


def save_payload(
    url: str,
    title: str,
    date: str | None,
    saved_at: str,
    *,
    visitor: str,
    ref: str | None = None,
) -> dict[str, Any]:
    """The audit payload of one saved link (no question text, ever).

    ``visitor`` is the peppered one-way hash the live limits use; ``ref`` the referral code
    the visitor's link carried, if any. Neither identifies a person.
    """
    return {
        "url": url,
        "title": title,
        "date": date,
        "saved_by": SAVED_BY,
        "visitor": visitor,
        "ref": ref,
        "saved_at": saved_at,
    }


__all__ = [
    "LABEL",
    "RESEARCH_ENV",
    "HttpResearchTransport",
    "ResearchTransport",
    "block",
    "hold_usd",
    "limit_block",
    "parse_reply",
    "research_day_usd",
    "research_enabled",
    "run_research",
]
