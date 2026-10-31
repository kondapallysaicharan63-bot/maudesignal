"""Probe of the Meta Model API built-in ``web_search`` tool (Track B, probe 2).

HACKATHON-BUILT — Meta Global AI Developer Hackathon (Oct 26 – Nov 4, 2026).

Runs only in GitHub Actions (``.github/workflows/research-probe.yml``, push to
``probe/research**``) with the repository secret ``META_MODEL_API_KEY``.

Probe 1 (run 41246131207) showed that ``muse-spark-1.3`` accepts ``web_search`` but made 7
searches and hit the 800-token output cap mid-reasoning, so no final message (and no
citations) came back. Probe 2 therefore:

* raises ``max_output_tokens`` to 3000 (reasoning counts toward it), reasoning effort ``low``;
* asks for at most 2 searches with ``max_tool_calls: 2``;
* asks for the retrieved sources with ``include: ["web_search_call.action.sources"]``;
* parses url citations from message annotations (``url_citation``: url, title, start/end)
  and sources from ``web_search_call.action.sources``, and prints per-search counts.

Hard limits: at most TWO HTTP requests. If the first is rejected with HTTP 400 naming
``max_tool_calls`` and/or ``include`` (or naming neither, in which case both are dropped),
ONE retry goes out without the rejected parameter(s). Any other failure stops the probe.
60 s timeout per request, no SDK retries, no streaming. The key is sent only in the
``Authorization`` header; neither the key nor any header is printed, and an error body is
printed truncated with the key redacted if it appears.

Cost uses only the repo's own price table (``copilot/meta_provider.py``, Muse Spark 1.3
Standard tier). The repo has no price for a web-search call, so that fee is "unknown".
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass, field
from typing import Any

import httpx

from maudesignal.copilot.meta_provider import SPARK_USD_PER_M_INPUT, SPARK_USD_PER_M_OUTPUT

DEFAULT_BASE_URL = "https://api.meta.ai/v1"
RESPONSES_PATH = "/responses"
PRIMARY_MODEL = "muse-spark-1.3"
MAX_OUTPUT_TOKENS = 3000
MAX_TOOL_CALLS = 2
INCLUDE_SOURCES = "web_search_call.action.sources"
TIMEOUT_S = 60.0
MAX_CALLS = 2
QUESTION = "Recent FDA safety communications about CT scanners: give titles, links and dates."

#: Input-token allowance for the cost estimate. Probe 1 used 24,256 input tokens for 7
#: searches; 40,000 covers that run again even if ``max_tool_calls`` is ignored.
ASSUMED_MAX_INPUT_TOKENS = 40_000
#: Only a successful reply is assumed to be billed (a 400 rejection is not), so at most ONE
#: request of a run is billed: the retry only follows a 400.
BILLED_CALLS_MAX = 1

#: Models with a price in the repo (USD per 1M input tokens, per 1M output tokens).
PRICES: dict[str, tuple[float, float]] = {
    PRIMARY_MODEL: (SPARK_USD_PER_M_INPUT, SPARK_USD_PER_M_OUTPUT),
}

#: Optional request parameters a 400 may reject (dropped on the single retry).
OPTIONAL_PARAMS = ("max_tool_calls", "include")

_TRUNC = 160
_DATE_KEYS = ("date", "published_date", "published_at", "publication_date", "page_age")


def build_request(model: str, drop: frozenset[str] = frozenset()) -> dict[str, Any]:
    """Return the JSON body of one Responses API request.

    Args:
        model: Model id.
        drop: Optional parameters to leave out (after a 400 rejected them).

    Returns:
        Request body.
    """
    body: dict[str, Any] = {
        "model": model,
        "input": QUESTION,
        "tools": [{"type": "web_search"}],
        "max_output_tokens": MAX_OUTPUT_TOKENS,
        "reasoning": {"effort": "low"},
        "stream": False,
        "max_tool_calls": MAX_TOOL_CALLS,
        "include": [INCLUDE_SOURCES],
    }
    for name in drop:
        body.pop(name, None)
    return body


def expected_max_cost_usd(model: str = PRIMARY_MODEL) -> float:
    """Worst-case token cost of a probe run at the repo's prices (search fee excluded).

    Args:
        model: Priced model id.

    Returns:
        USD: ``BILLED_CALLS_MAX`` x (assumed max input + the output cap).
    """
    rin, rout = PRICES[model]
    per_call = ASSUMED_MAX_INPUT_TOKENS * rin / 1e6 + MAX_OUTPUT_TOKENS * rout / 1e6
    return round(BILLED_CALLS_MAX * per_call, 6)


def _trunc(value: Any, limit: int = _TRUNC) -> str:
    text = " ".join(str(value).split())
    return text if len(text) <= limit else text[: limit - 3] + "..."


@dataclass
class Source:
    """One cited or retrieved source."""

    kind: str
    url: str
    title: str = ""
    date: str = ""
    start: int | None = None
    end: int | None = None


@dataclass
class SearchCall:
    """One ``web_search_call`` item."""

    status: str = ""
    action_type: str = ""
    queries: list[str] = field(default_factory=list)
    sources: int = 0


@dataclass
class ProbeResult:
    """What one Responses API reply says about the web_search tool."""

    status: str = ""
    incomplete_reason: str = ""
    searches: list[SearchCall] = field(default_factory=list)
    citations: list[Source] = field(default_factory=list)
    sources: list[Source] = field(default_factory=list)
    text: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    reasoning_tokens: int = 0
    cached_tokens: int = 0
    raw_usage: dict[str, Any] = field(default_factory=dict)
    output_types: list[str] = field(default_factory=list)

    @property
    def web_search_calls(self) -> int:
        """Number of ``web_search_call`` items."""
        return len(self.searches)

    @property
    def search_queries(self) -> list[str]:
        """Every query, in order."""
        return [q for s in self.searches for q in s.queries]


def _date_of(obj: dict[str, Any]) -> str:
    for key in _DATE_KEYS:
        if obj.get(key):
            return str(obj[key])
    return ""


def _int_or_none(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _source(kind: str, obj: dict[str, Any]) -> Source | None:
    url = obj.get("url") or obj.get("uri") or ""
    if not url:
        return None
    return Source(
        kind=kind,
        url=str(url),
        title=str(obj.get("title") or ""),
        date=_date_of(obj),
        start=_int_or_none(obj.get("start_index")),
        end=_int_or_none(obj.get("end_index")),
    )


def _search_call(item: dict[str, Any], res: ProbeResult) -> None:
    found = SearchCall(status=str(item.get("status") or ""))
    action = item.get("action") or {}
    if isinstance(action, dict):
        found.action_type = str(action.get("type") or "")
        queries = action.get("queries")
        if isinstance(queries, list):
            found.queries.extend(str(q) for q in queries if q)
        if action.get("query"):
            found.queries.append(str(action["query"]))
        for src in action.get("sources") or []:
            if isinstance(src, dict) and (s := _source("source", src)):
                res.sources.append(s)
                found.sources += 1
    res.searches.append(found)


def parse_response(body: dict[str, Any]) -> ProbeResult:
    """Pull searches, citations, sources, text and usage out of a Responses API reply.

    Args:
        body: Decoded JSON reply.

    Returns:
        The parsed result (fields stay empty when absent).
    """
    res = ProbeResult(status=str(body.get("status") or ""))
    details = body.get("incomplete_details")
    if isinstance(details, dict) and details.get("reason"):
        res.incomplete_reason = str(details["reason"])
    texts: list[str] = []
    for item in body.get("output") or []:
        if not isinstance(item, dict):
            continue
        kind = str(item.get("type") or "")
        res.output_types.append(kind)
        if kind == "web_search_call":
            _search_call(item, res)
        elif kind == "message":
            for part in item.get("content") or []:
                if not isinstance(part, dict):
                    continue
                if part.get("text"):
                    texts.append(str(part["text"]))
                for ann in part.get("annotations") or []:
                    if isinstance(ann, dict) and (s := _source(str(ann.get("type")), ann)):
                        res.citations.append(s)
    res.text = "\n".join(texts) or str(body.get("output_text") or "")
    usage = body.get("usage") or {}
    if isinstance(usage, dict):
        res.raw_usage = usage
        res.input_tokens = int(usage.get("input_tokens") or 0)
        res.output_tokens = int(usage.get("output_tokens") or 0)
        out_d = usage.get("output_tokens_details") or {}
        in_d = usage.get("input_tokens_details") or {}
        if isinstance(out_d, dict):
            res.reasoning_tokens = int(out_d.get("reasoning_tokens") or 0)
        if isinstance(in_d, dict):
            res.cached_tokens = int(in_d.get("cached_tokens") or 0)
    return res


def error_message(body: Any) -> str:
    """Return the error text of an error reply (``{"error": {"message": ...}}`` or raw)."""
    if isinstance(body, dict):
        err = body.get("error")
        if isinstance(err, dict):
            parts = [str(err.get(k)) for k in ("type", "code", "param", "message") if err.get(k)]
            return " | ".join(parts)
        if err:
            return str(err)
        return json.dumps(body)[:1000]
    return str(body)[:1000]


def rejected_params(status: int, message: str) -> frozenset[str]:
    """Optional parameters to drop on the single retry after a 400.

    Args:
        status: HTTP status.
        message: Error text from :func:`error_message`.

    Returns:
        The optional parameters the error names; both when a 400 names neither (the rest of
        the request is the shape probe 1 had accepted); empty (no retry) for any other status.
    """
    if status != 400:
        return frozenset()
    low = message.lower()
    named = frozenset(p for p in OPTIONAL_PARAMS if p in low)
    return named or frozenset(OPTIONAL_PARAMS)


def cost_line(model: str, res: ProbeResult) -> str:
    """Describe the cost of one reply using only prices that exist in the repo."""
    usage = (
        f"input={res.input_tokens} (cached {res.cached_tokens}), output={res.output_tokens} "
        f"(reasoning {res.reasoning_tokens}), web_search_calls={res.web_search_calls}"
    )
    rates = PRICES.get(model)
    if rates is None:
        return f"usage: {usage}; price unknown for {model} (no price in the repo)"
    usd = res.input_tokens * rates[0] / 1e6 + res.output_tokens * rates[1] / 1e6
    return (
        f"usage: {usage}; token cost ${usd:.6f} at ${rates[0]}/M in, ${rates[1]}/M out "
        f"(copilot/meta_provider.py); web_search tool fee: price unknown (none in the repo)"
    )


def redact(text: str, secret: str) -> str:
    """Remove the key from text, in case an error body echoes it."""
    return text.replace(secret, "[REDACTED]") if secret else text


def _span(s: Source) -> str:
    return f" | span {s.start}-{s.end}" if s.start is not None or s.end is not None else ""


def report(model: str, status: int, res: ProbeResult, sent: dict[str, Any]) -> list[str]:
    """Return the printable lines for one successful reply."""
    incomplete = f" (incomplete: {res.incomplete_reason})" if res.incomplete_reason else ""
    lines = [
        f"model: {model}",
        f"http_status: {status}",
        f"response_status: {res.status or '(none)'}{incomplete}",
        "web_search accepted: yes",
        f"max_tool_calls sent: {sent.get('max_tool_calls', 'no')}",
        f"include sent: {sent.get('include', 'no')}",
        f"output item types: {', '.join(res.output_types) or '(none)'}",
        f"web_search_call items: {res.web_search_calls}",
    ]
    for i, found in enumerate(res.searches, 1):
        queries = "; ".join(_trunc(q, 120) for q in found.queries) or "-"
        lines.append(
            f"  search {i}: status={found.status or '-'} action={found.action_type or '-'} "
            f"sources={found.sources} queries={queries}"
        )
    lines.append(f"url citations (message annotations with url): {len(res.citations)}")
    for c in res.citations[:12]:
        lines.append(
            f"  [{c.kind}] {_trunc(c.title, 100)} | {_trunc(c.url, 140)} | "
            f"date: {c.date or '-'}{_span(c)}"
        )
    lines.append(f"url sources (web_search_call.action.sources): {len(res.sources)}")
    for s in res.sources[:12]:
        lines.append(
            f"  [{s.kind}] {_trunc(s.title, 100)} | {_trunc(s.url, 140)} | date: {s.date or '-'}"
        )
    lines.append(f"answer text (truncated): {_trunc(res.text, 1500) or '(empty)'}")
    lines.append(cost_line(model, res))
    lines.append(f"raw usage: {_trunc(json.dumps(res.raw_usage, sort_keys=True), 600)}")
    return lines


def call(client: httpx.Client, url: str, key: str, body: dict[str, Any]) -> tuple[int, Any]:
    """Make ONE request; return (HTTP status, decoded body or raw text). Never raises on HTTP."""
    resp = client.post(
        url,
        json=body,
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        timeout=TIMEOUT_S,
    )
    try:
        return resp.status_code, resp.json()
    except ValueError:
        return resp.status_code, resp.text


def main() -> int:
    """Run the probe (at most two requests) and print the findings."""
    key = os.environ.get("META_MODEL_API_KEY", "")
    if not key:
        print("META_MODEL_API_KEY: MISSING; no request made.")
        return 2
    base = (os.environ.get("META_MODEL_API_BASE_URL") or DEFAULT_BASE_URL).rstrip("/")
    url = base + RESPONSES_PATH
    print(f"endpoint: POST {url}")
    print(f"question: {QUESTION}")
    print(
        f"model={PRIMARY_MODEL}, max_output_tokens={MAX_OUTPUT_TOKENS}, reasoning=low, "
        f"max_tool_calls={MAX_TOOL_CALLS}, include={INCLUDE_SOURCES}, timeout={TIMEOUT_S:.0f}s"
    )
    print(
        f"expected max token cost: ${expected_max_cost_usd():.4f} "
        f"({BILLED_CALLS_MAX} billed call x ({ASSUMED_MAX_INPUT_TOKENS} input + "
        f"{MAX_OUTPUT_TOKENS} output tokens)); web_search fee: price unknown"
    )
    drop: frozenset[str] = frozenset()
    calls = 0
    exit_code = 1
    with httpx.Client() as client:
        while calls < MAX_CALLS:
            body = build_request(PRIMARY_MODEL, drop)
            calls += 1
            print(f"\n--- call {calls} of max {MAX_CALLS} ---")
            try:
                status, reply = call(client, url, key, body)
            except httpx.HTTPError as exc:
                print(f"request failed: {type(exc).__name__} (no HTTP status)")
                break
            if 200 <= status < 300 and isinstance(reply, dict):
                res = parse_response(reply)
                print("\n".join(report(PRIMARY_MODEL, status, res, body)))
                exit_code = 0
                break
            msg = redact(error_message(reply), key)
            print(f"model: {PRIMARY_MODEL}\nhttp_status: {status}\nerror: {_trunc(msg, 800)}")
            retry_drop = rejected_params(status, msg) - drop
            if calls >= MAX_CALLS or not retry_drop:
                break
            drop = drop | retry_drop
            print(f"retrying once without: {', '.join(sorted(retry_drop))}")
    print(f"\nrequests made: {calls}")
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
