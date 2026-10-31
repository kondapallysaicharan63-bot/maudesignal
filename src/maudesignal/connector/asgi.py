"""ASGI guard: refuse a key sent in the query string, and keep it out of access logs.

HACKATHON-BUILT — Meta Global AI Developer Hackathon (Oct 26 – Nov 4, 2026).

A key in a URL ends up in server access logs (uvicorn prints the full request line).
This middleware answers 400 to any request whose query names a key-like parameter and,
before answering, blanks ``scope["query_string"]`` so the access log of the same process
shows the path only. Keys belong in the ``X-API-Key`` header. It cannot reach a hosting
platform's own request log, which is why the docs also say to send the header only.
"""

from __future__ import annotations

import json
import re
from collections.abc import Awaitable, Callable, MutableMapping
from typing import Any
from urllib.parse import parse_qsl

Scope = MutableMapping[str, Any]
Receive = Callable[[], Awaitable[MutableMapping[str, Any]]]
Send = Callable[[MutableMapping[str, Any]], Awaitable[None]]
ASGIApp = Callable[[Scope, Receive, Send], Awaitable[None]]

_KEY_PARAM = re.compile(r"key|token|secret|auth", re.IGNORECASE)
_BODY = json.dumps(
    {
        "error": {
            "code": "key_in_url",
            "message": "Send the API key only in the X-API-Key header, never in the URL.",
        }
    }
).encode("utf-8")


def has_key_param(query_string: bytes) -> bool:
    """True when the query has a parameter that looks like an API key."""
    pairs = parse_qsl(query_string.decode("latin-1"), keep_blank_values=True)
    return any(_KEY_PARAM.search(name) for name, _ in pairs)


class RejectKeyInQuery:
    """Answer 400 (and blank the logged query) when a key-like parameter is in the URL."""

    def __init__(self, app: ASGIApp) -> None:
        """Wrap ``app``."""
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Handle one ASGI call."""
        if scope["type"] == "http" and has_key_param(scope.get("query_string", b"")):
            scope["query_string"] = b""  # the access log reads this same dict
            await send(
                {
                    "type": "http.response.start",
                    "status": 400,
                    "headers": [
                        (b"content-type", b"application/json"),
                        (b"content-length", str(len(_BODY)).encode("ascii")),
                    ],
                }
            )
            await send({"type": "http.response.body", "body": _BODY})
            return
        await self.app(scope, receive, send)
