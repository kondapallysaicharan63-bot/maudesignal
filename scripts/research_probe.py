"""One-shot probe of the Meta Model API built-in ``web_search`` tool (Track B, phase 1).

HACKATHON-BUILT — Meta Global AI Developer Hackathon (Oct 26 – Nov 4, 2026).

Runs only in GitHub Actions (``.github/workflows/research-probe.yml``, push to
``probe/research**``) with the repository secret ``META_MODEL_API_KEY``. It answers one
question: does a Responses API request with ``tools=[{"type": "web_search"}]`` work on
Muse Spark, and what comes back (citations, sources, usage)?

Hard limits:

* At most TWO HTTP requests in total. The first goes to ``muse-spark-1.3``. Only if that
  reply is an error saying the ``web_search`` tool is not supported does ONE more request go
  to the fallback model (``muse-spark-1.1`` by default; override with
  ``RESEARCH_PROBE_FALLBACK_MODEL``). Any other failure stops the probe.
* ``max_output_tokens`` = 800 (reasoning counts toward it), reasoning effort ``low``,
  60 s timeout per request, no retries, no streaming.
* The key is sent only in the ``Authorization`` header. Neither the key nor any header is
  ever printed; an error body is printed truncated, with the key redacted if it appears.

Cost is computed only from the repo's own price table (``copilot/meta_provider.py``,
Muse Spark 1.3 Standard tier). There is no price in the repo for any other model or for a
web-search tool call, so for those the probe prints the raw usage and says "price unknown".
"""

from __future__ import annotations

import json
import os
import re
import sys
from dataclasses import dataclass, field
from typing import Any

import httpx

from maudesignal.copilot.meta_provider import SPARK_USD_PER_M_INPUT, SPARK_USD_PER_M_OUTPUT

DEFAULT_BASE_URL = "https://api.meta.ai/v1"
RESPONSES_PATH = "/responses"
PRIMARY_MODEL = "muse-spark-1.3"
DEFAULT_FALLBACK_MODEL = "muse-spark-1.1"
MAX_OUTPUT_TOKENS = 800
TIMEOUT_S = 60.0
MAX_CALLS = 2
QUESTION = "Recent FDA safety communications about CT scanners: give titles, links and dates."

#: Models with a price in the repo (USD per 1M input tokens, per 1M output tokens).
PRICES: dict[str, tuple[float, float]] = {
    PRIMARY_MODEL: (SPARK_USD_PER_M_INPUT, SPARK_USD_PER_M_OUTPUT),
}

_TRUNC = 160
_DATE_KEYS = ("date", "published_date", "published_at", "publication_date", "page_age")
_UNSUPPORTED = re.compile(
    r"not\s+supported|unsupported|not\s+available|not\s+enabled|unknown|invalid|"
    r"not\s+allowed|does\s+not\s+support",
    re.IGNORECASE,
)


def build_request(model: str) -> dict[str, Any]:
    """Return the JSON body of the single Responses API request.

    Args:
        model: Model id.

    Returns:
        Request body.
    """
    return {
        "model": model,
        "input": QUESTION,
        "tools": [{"type": "web_search"}],
        "max_output_tokens": MAX_OUTPUT_TOKENS,
        "reasoning": {"effort": "low"},
        "stream": False,
    }


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


@dataclass
class ProbeResult:
    """What one Responses API reply says about the web_search tool."""

    status: str = ""
    web_search_calls: int = 0
    search_queries: list[str] = field(default_factory=list)
    citations: list[Source] = field(default_factory=list)
    sources: list[Source] = field(default_factory=list)
    text: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    reasoning_tokens: int = 0
    cached_tokens: int = 0
    raw_usage: dict[str, Any] = field(default_factory=dict)
    output_types: list[str] = field(default_factory=list)


def _date_of(obj: dict[str, Any]) -> str:
    for key in _DATE_KEYS:
        if obj.get(key):
            return str(obj[key])
    return ""


def _source(kind: str, obj: dict[str, Any]) -> Source | None:
    url = obj.get("url") or obj.get("uri") or ""
    if not url:
        return None
    return Source(kind=kind, url=str(url), title=str(obj.get("title") or ""), date=_date_of(obj))


def parse_response(body: dict[str, Any]) -> ProbeResult:
    """Pull tool use, citations, sources, text and usage out of a Responses API reply.

    Args:
        body: Decoded JSON reply.

    Returns:
        The parsed result (fields stay empty when absent).
    """
    res = ProbeResult(status=str(body.get("status") or ""))
    texts: list[str] = []
    for item in body.get("output") or []:
        if not isinstance(item, dict):
            continue
        kind = str(item.get("type") or "")
        res.output_types.append(kind)
        if kind == "web_search_call":
            res.web_search_calls += 1
            action = item.get("action") or {}
            if isinstance(action, dict):
                if action.get("query"):
                    res.search_queries.append(str(action["query"]))
                for src in action.get("sources") or []:
                    if isinstance(src, dict) and (s := _source("source", src)):
                        res.sources.append(s)
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
    for src in body.get("sources") or body.get("citations") or []:
        if isinstance(src, dict) and (s := _source("top_level", src)):
            res.sources.append(s)
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


def tool_unsupported(status: int, message: str) -> bool:
    """True when an error reply says the web_search tool is not supported for this model.

    Args:
        status: HTTP status.
        message: Error text from :func:`error_message`.

    Returns:
        Whether to try the fallback model.
    """
    if status not in (400, 404, 422):
        return False
    low = message.lower()
    mentions_tool = "web_search" in low or "tool" in low
    return mentions_tool and bool(_UNSUPPORTED.search(message))


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


def report(model: str, status: int, res: ProbeResult, accepted: bool) -> list[str]:
    """Return the printable lines for one successful reply."""
    lines = [
        f"model: {model}",
        f"http_status: {status}",
        f"response_status: {res.status or '(none)'}",
        f"web_search accepted: {'yes' if accepted else 'no'}",
        f"web_search_call items: {res.web_search_calls}",
        f"output item types: {', '.join(res.output_types) or '(none)'}",
    ]
    for q in res.search_queries[:5]:
        lines.append(f"  search query: {_trunc(q)}")
    lines.append(f"citations/annotations with url: {len(res.citations)}")
    for c in res.citations[:10]:
        lines.append(
            f"  [{c.kind}] {_trunc(c.title, 100)} | {_trunc(c.url, 140)} | date: {c.date or '-'}"
        )
    lines.append(f"url sources returned: {len(res.sources)}")
    for s in res.sources[:10]:
        lines.append(
            f"  [{s.kind}] {_trunc(s.title, 100)} | {_trunc(s.url, 140)} | date: {s.date or '-'}"
        )
    lines.append(f"answer text (truncated): {_trunc(res.text, 900) or '(empty)'}")
    lines.append(cost_line(model, res))
    lines.append(f"raw usage: {_trunc(json.dumps(res.raw_usage, sort_keys=True), 600)}")
    return lines


def call(client: httpx.Client, url: str, key: str, model: str) -> tuple[int, Any]:
    """Make ONE request; return (HTTP status, decoded body or raw text). Never raises on HTTP."""
    resp = client.post(
        url,
        json=build_request(model),
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
    fallback = os.environ.get("RESEARCH_PROBE_FALLBACK_MODEL") or DEFAULT_FALLBACK_MODEL
    url = base + RESPONSES_PATH
    print(f"endpoint: POST {url}")
    print(f"question: {QUESTION}")
    print(f"max_output_tokens={MAX_OUTPUT_TOKENS}, reasoning=low, timeout={TIMEOUT_S:.0f}s")
    models = [PRIMARY_MODEL]
    calls = 0
    exit_code = 1
    with httpx.Client() as client:
        while models and calls < MAX_CALLS:
            model = models.pop(0)
            calls += 1
            print(f"\n--- call {calls} of max {MAX_CALLS} ---")
            try:
                status, body = call(client, url, key, model)
            except httpx.HTTPError as exc:
                print(f"model: {model}\nrequest failed: {type(exc).__name__} (no HTTP status)")
                break
            if 200 <= status < 300 and isinstance(body, dict):
                res = parse_response(body)
                print("\n".join(report(model, status, res, accepted=True)))
                exit_code = 0
                break
            msg = redact(error_message(body), key)
            print(f"model: {model}\nhttp_status: {status}\nerror: {_trunc(msg, 800)}")
            if model == PRIMARY_MODEL and tool_unsupported(status, msg):
                print("web_search accepted: no (error says the tool is unsupported)")
                print(f"trying the fallback model once: {fallback}")
                models.append(fallback)
            else:
                print("web_search accepted: unknown (error is not a tool-unsupported error)")
    print(f"\nrequests made: {calls}")
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
