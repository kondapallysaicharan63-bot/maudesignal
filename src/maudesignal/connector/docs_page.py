"""The human-readable docs page (``GET /`` and ``GET /docs-page``), in the design-system look.

HACKATHON-BUILT — Meta Global AI Developer Hackathon (Oct 26 – Nov 4, 2026).

The page is ``api/docs.html`` with the design-system CSS (``design-system/tokens.css`` and
``maudesignal.css``) inlined and the example requests and responses from ``api/examples.json``
(captured from real local runs) rendered into it. The numbers on the page (rate limits, cost
cap) are the ones the running app uses, not copies. Nothing here needs a key or the network.
"""

from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any

from maudesignal.connector.data import PROJECT_ROOT
from maudesignal.connector.models import ADVISORY

TEMPLATE = PROJECT_ROOT / "api" / "docs.html"
EXAMPLES = PROJECT_ROOT / "api" / "examples.json"
CSS_FILES = (
    PROJECT_ROOT / "design-system" / "tokens.css",
    PROJECT_ROOT / "design-system" / "maudesignal.css",
)
SUPPORT_URL = "https://github.com/kondapallysaicharan63-bot/maudesignal/issues"

_FALLBACK = (
    "<!doctype html><html lang='en'><head><meta charset='utf-8'><title>MaudeSignal API</title>"
    "</head><body><h1>MaudeSignal connector API</h1><p>Read-only tools. "
    "The OpenAPI spec is at <a href='/openapi.json'>/openapi.json</a>.</p><p>{advisory}</p>"
    "<p><a href='{support}'>Support</a> | <a href='/privacy'>Privacy</a> | "
    "<a href='/terms'>Terms</a></p></body></html>"
)


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def _examples_html() -> str:
    try:
        items: list[dict[str, Any]] = json.loads(_read(EXAMPLES) or "[]")
    except ValueError:
        items = []
    out: list[str] = []
    for ex in items:
        body = json.dumps(ex.get("body"), indent=2, ensure_ascii=False)
        out.append(
            "<div class='ex'>"
            f"<h4>{html.escape(str(ex.get('title', '')))}</h4>"
            f"<pre class='req'>{html.escape(str(ex.get('request', '')))}</pre>"
            f"<p class='meta'>HTTP {html.escape(str(ex.get('status', '')))}</p>"
            f"<pre class='res'>{html.escape(body)}</pre></div>"
        )
    return "\n".join(out) or "<p>No captured examples are bundled with this build.</p>"


def render_docs_page(
    *,
    version: str,
    state_backend: str,
    rate_per_min: int,
    public_per_hour: int,
    daily_usd: float,
    request_usd: float,
) -> str:
    """The page as HTML text.

    Args:
        version: API version.
        state_backend: ``upstash_redis`` or ``in_memory_per_instance``.
        rate_per_min: Requests per key per minute.
        public_per_hour: Keyless checks per address per hour.
        daily_usd: Daily cost cap of ``ask`` per key.
        request_usd: Cost cap of one ``ask`` call.
    """
    template = _read(TEMPLATE)
    if not template:
        return _FALLBACK.format(advisory=html.escape(ADVISORY), support=SUPPORT_URL)
    shared = state_backend == "upstash_redis"
    scope = (
        "shared by every server instance (Upstash Redis)"
        if shared
        else "kept in each server instance's memory: per instance, reset on a cold start"
    )
    window = (
        " (counted in fixed one-minute windows, so a burst across a window edge"
        " can reach twice that)"
        if shared
        else " (sliding window, per server instance)"
    )
    values = {
        "WINDOW": html.escape(window),
        "STYLE": "\n".join(_read(p) for p in CSS_FILES),
        "VERSION": html.escape(version),
        "SCOPE": html.escape(scope),
        "RATE": str(rate_per_min),
        "PUBLIC_RATE": str(public_per_hour),
        "DAILY_USD": f"{daily_usd:.2f}",
        "REQUEST_USD": f"{request_usd:.2f}",
        "ADVISORY": html.escape(ADVISORY),
        "SUPPORT": SUPPORT_URL,
        "EXAMPLES": _examples_html(),
    }
    page = template
    for name, value in values.items():
        page = page.replace("{{" + name + "}}", value)
    return page
