"""Small HTTP helpers for the release scripts (standard library only).

HACKATHON-BUILT — Meta Global AI Developer Hackathon (Oct 26 – Nov 4, 2026).

``request`` never raises for an HTTP error status or a network failure: it returns a
``Response`` (status 0 when no HTTP answer arrived), so a check can assert on what happened.
It uses ``http.client`` so a test can send a body the server refuses early (a too-large
upload) and still read the refusal.
"""

from __future__ import annotations

import contextlib
import http.client
import json
import ssl
import time
import uuid
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlsplit


@dataclass
class Response:
    """What came back: status (0 = no answer), lower-cased headers, body, elapsed time."""

    status: int
    headers: dict[str, str] = field(default_factory=dict)
    body: bytes = b""
    elapsed_ms: int = 0
    error: str = ""

    @property
    def text(self) -> str:
        """The body decoded as UTF-8 (undecodable bytes replaced)."""
        return self.body.decode("utf-8", "replace")

    def json(self) -> Any:
        """The body parsed as JSON, or ``None`` when it is not JSON."""
        try:
            return json.loads(self.body)
        except ValueError:
            return None

    def error_code(self) -> str:
        """The API's error code (``{"code": ...}`` or ``{"error": {"code": ...}}``), else ''."""
        data = self.json()
        if not isinstance(data, dict):
            return ""
        err = data.get("error")
        if isinstance(err, dict) and isinstance(err.get("code"), str):
            return str(err["code"])
        return str(data["code"]) if isinstance(data.get("code"), str) else ""


def request(
    method: str,
    url: str,
    *,
    headers: dict[str, str] | None = None,
    body: bytes | None = None,
    json_body: Any = None,
    timeout: float = 30.0,
) -> Response:
    """Send one request and return the ``Response`` (see the module text)."""
    parts = urlsplit(url)
    host = parts.hostname or ""
    hdrs = {"User-Agent": "maudesignal-release-check/1", **(headers or {})}
    if json_body is not None:
        body = json.dumps(json_body).encode("utf-8")
        hdrs.setdefault("Content-Type", "application/json")
    path = parts.path or "/"
    if parts.query:
        path += "?" + parts.query
    started = time.monotonic()
    conn: http.client.HTTPConnection
    if parts.scheme == "https":
        conn = http.client.HTTPSConnection(
            host, parts.port or 443, timeout=timeout, context=ssl.create_default_context()
        )
    else:
        conn = http.client.HTTPConnection(host, parts.port or 80, timeout=timeout)
    try:
        # If the server answers early and closes (a refused upload), read its answer below.
        with contextlib.suppress(BrokenPipeError, ConnectionResetError):
            conn.request(method, path, body=body, headers=hdrs)
        resp = conn.getresponse()
        data = resp.read()
        return Response(
            resp.status,
            {k.lower(): v for k, v in resp.getheaders()},
            data,
            int((time.monotonic() - started) * 1000),
        )
    except (OSError, http.client.HTTPException) as exc:
        return Response(
            0, {}, b"", int((time.monotonic() - started) * 1000), f"{type(exc).__name__}: {exc}"
        )
    finally:
        conn.close()


def multipart(parts: dict[str, tuple[str, bytes, str]]) -> tuple[bytes, str]:
    """Encode ``{field: (filename, bytes, content_type)}``; returns ``(body, content_type)``."""
    boundary = "----release" + uuid.uuid4().hex
    out = bytearray()
    for name, (filename, data, ctype) in parts.items():
        out += f"--{boundary}\r\n".encode()
        out += (
            f'Content-Disposition: form-data; name="{name}"; filename="{filename}"\r\n'
            f"Content-Type: {ctype}\r\n\r\n"
        ).encode()
        out += data + b"\r\n"
    out += f"--{boundary}--\r\n".encode()
    return bytes(out), f"multipart/form-data; boundary={boundary}"


def percentile(values: list[float], pct: float) -> float:
    """Nearest-rank percentile (``pct`` 0-100) of ``values``; 0.0 for an empty list."""
    if not values:
        return 0.0
    ordered = sorted(values)
    rank = max(1, round(pct / 100 * len(ordered)))
    return float(ordered[min(rank, len(ordered)) - 1])
