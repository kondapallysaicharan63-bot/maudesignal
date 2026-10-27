"""Segment Anything Model 3.1 (``sam-3.1``) over the Meta Model API Responses endpoint.

HACKATHON-BUILT — Meta Global AI Developer Hackathon (Oct 26 – Nov 4, 2026).

Request and output format as documented (read 2026-10-27):

* https://dev.meta.ai/docs/sam/overview — ``POST /v1/responses`` with model
  ``sam-3.1``; one user message holding an ``input_text`` noun phrase and one
  ``input_image``; streaming SSE ``response.output_text.delta`` events, ending on
  ``response.completed``; zero matches = empty ``output_text`` (not an error).
* https://dev.meta.ai/docs/sam/segmenting — ``image_url`` is "a public URL or a
  base64 data URL (data:image/png;base64,...)"; ``metadata.include_confidence``
  must be the STRING ``"true"``; a 400 is permanent for that request.
* https://dev.meta.ai/docs/sam/reading-segmentation — the grammar parsed below::

    line    ::= FRAME record ( "," record )*
    record  ::= OBJECT_ID box mask
    box     ::= "<|box;x1=" INT ";y1=" INT ";x2=" INT ";y2=" INT ";w=" INT ";h=" INT [CONF] "|>"
    mask    ::= "<|mask;x=0;y=0" [CONF] ";data=" H "," W "," ENC PAYLOAD "|>"
    CONF    ::= ";c=" DECIMAL
    FRAME   ::= "<" INT "f>"
    ENC     ::= "~" (lossless) | "!" (one_bit); PAYLOAD is base85 and may contain ! or ~

  Boxes are in source pixels with inclusive x2/y2; ``w``/``h`` repeat the source
  size. Object ids are stable but not dense. Mask payloads are kept but not
  decoded (only boxes are needed to crop a label).
* https://dev.meta.ai/docs/pricing-rate-limits — image segmentation $2.50 per
  1,000 images.

The key is sent only in the ``Authorization`` header and never logged.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

import httpx

from maudesignal.common.exceptions import MaudeSignalError
from maudesignal.vision.images import EncodedImage

DEFAULT_BASE_URL = "https://api.meta.ai/v1"
RESPONSES_PATH = "/responses"
DEFAULT_SAM_MODEL = "sam-3.1"
SAM_USD_PER_IMAGE = 2.50 / 1000
EVENT_DELTA = "response.output_text.delta"
EVENT_DONE = "response.completed"
EVENT_ERRORS = frozenset({"error", "response.failed", "response.incomplete"})
RETRYABLE_STATUS = frozenset({429, 500, 502, 503})

_FRAME = re.compile(r"<(\d+)f>")
_RECORD = re.compile(
    r"(?:^|,)(\d+)<\|box;(?P<box>[^|]*)\|><\|mask;(?P<mask>.*?)\|>(?=,\d+<\|box;|\s*$)",
    re.DOTALL,
)


class SamError(MaudeSignalError):
    """Segmentation failed (HTTP error, stream error, or unparseable output)."""

    def __init__(
        self, message: str, *, status_code: int | None = None, retryable: bool = False
    ) -> None:
        """Create the error (message never contains the API key)."""
        super().__init__(message)
        self.status_code = status_code
        self.retryable = retryable


@dataclass(frozen=True)
class SamBox:
    """A box in source pixels (x2, y2 inclusive)."""

    x1: int
    y1: int
    x2: int
    y2: int
    w: int
    h: int
    confidence: float | None = None

    @property
    def area(self) -> int:
        """Box area in pixels."""
        return max(0, self.x2 - self.x1 + 1) * max(0, self.y2 - self.y1 + 1)

    def as_tuple(self) -> tuple[int, int, int, int]:
        """``(x1, y1, x2, y2)``."""
        return (self.x1, self.y1, self.x2, self.y2)

    def scaled_to(self, width: int, height: int) -> SamBox:
        """The same box in an image of a different size (e.g. the display copy)."""
        sx = width / self.w if self.w else 1.0
        sy = height / self.h if self.h else 1.0
        return SamBox(
            round(self.x1 * sx),
            round(self.y1 * sy),
            round(self.x2 * sx),
            round(self.y2 * sy),
            width,
            height,
            self.confidence,
        )


@dataclass(frozen=True)
class SamMask:
    """A mask token (payload kept encoded)."""

    height: int
    width: int
    encoding: str  # "lossless" | "one_bit"
    payload: str
    confidence: float | None = None


@dataclass(frozen=True)
class SamRecord:
    """One object on one frame."""

    frame: int
    object_id: int
    box: SamBox
    mask: SamMask | None


def _kv(fields: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for part in fields.split(";"):
        if "=" in part:
            k, v = part.split("=", 1)
            out[k.strip()] = v
    return out


def _parse_box(fields: str) -> SamBox:
    kv = _kv(fields)
    try:
        conf = float(kv["c"]) if "c" in kv else None
        return SamBox(
            int(kv["x1"]),
            int(kv["y1"]),
            int(kv["x2"]),
            int(kv["y2"]),
            int(kv["w"]),
            int(kv["h"]),
            conf,
        )
    except (KeyError, ValueError) as exc:
        raise SamError(f"malformed box token: {fields[:80]!r}") from exc


def _parse_mask(fields: str) -> SamMask | None:
    head, sep, data = fields.partition("data=")
    if not sep:
        return None
    kv = _kv(head)
    m = re.match(r"(\d+),(\d+),(.)", data, re.DOTALL)
    if not m:
        return None
    enc = {"~": "lossless", "!": "one_bit"}.get(m.group(3), m.group(3))
    conf = float(kv["c"]) if "c" in kv and re.fullmatch(r"[0-9.]+", kv["c"]) else None
    return SamMask(int(m.group(1)), int(m.group(2)), enc, data[m.end() :], conf)


def parse_segmentation(text: str) -> list[SamRecord]:
    """Parse SAM special-token output (one line per frame) into records.

    Fields are read by key, so a token parses the same with or without ``c``.
    Empty text (zero matches) returns an empty list.

    Raises:
        SamError: Non-empty text that does not follow the documented grammar.
    """
    records: list[SamRecord] = []
    text = (text or "").strip()
    if not text:
        return records
    for frame, body in _frames(text):
        found = list(_RECORD.finditer(body))
        if not found:
            raise SamError(f"frame <{frame}f> has no parseable record")
        for r in found:
            records.append(
                SamRecord(
                    frame=frame,
                    object_id=int(r.group(1)),
                    box=_parse_box(r.group("box")),
                    mask=_parse_mask(r.group("mask")),
                )
            )
    return records


def _frames(text: str) -> list[tuple[int, str]]:
    """Split output into (frame, records) pairs.

    Each frame is its own line, so a frame marker is only trusted at the start of a
    line (a base85 mask payload could contain ``<`` digits ``f>``). Text that does
    not start every line with a marker falls back to splitting on every marker.
    """
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    heads = [_FRAME.match(ln) for ln in lines]
    if all(heads):
        return [
            (int(m.group(1)), ln[m.end() :].strip())
            for m, ln in zip(heads, lines, strict=True)
            if m is not None
        ]
    markers = list(_FRAME.finditer(text))
    if not markers:
        raise SamError("segmentation output has no <Nf> frame marker")
    out: list[tuple[int, str]] = []
    for i, m in enumerate(markers):
        end = markers[i + 1].start() if i + 1 < len(markers) else len(text)
        body = text[m.end() : end].strip()
        if body:
            out.append((int(m.group(1)), body))
    return out


def best_record(records: list[SamRecord]) -> SamRecord | None:
    """Highest confidence first, then largest box; None for no records."""
    if not records:
        return None
    return max(
        records,
        key=lambda r: (r.box.confidence if r.box.confidence is not None else -1.0, r.box.area),
    )


@dataclass
class SamResult:
    """What one segmentation request returned."""

    prompt: str
    records: list[SamRecord]
    raw_text: str
    images_billed: int = 1
    usage: dict[str, Any] = field(default_factory=dict)

    @property
    def cost_usd(self) -> float:
        """Estimated cost at $2.50 per 1,000 images."""
        return round(self.images_billed * SAM_USD_PER_IMAGE, 6)


def _error_message(resp: httpx.Response) -> str:
    try:
        body = resp.json()
    except ValueError:
        return resp.text[:200]
    err = body.get("error") if isinstance(body, dict) else None
    if isinstance(err, dict):
        parts = [str(err.get("code") or ""), str(err.get("message") or "")]
        return " ".join(p for p in parts if p)[:300]
    return json.dumps(body)[:200]


def read_sse_text(lines: list[str]) -> tuple[str, dict[str, Any]]:
    """Accumulate ``response.output_text.delta`` payloads from SSE ``data:`` lines.

    Returns:
        The output text and the ``usage`` block of ``response.completed`` (if any).

    Raises:
        SamError: An error event in the stream.
    """
    chunks: list[str] = []
    usage: dict[str, Any] = {}
    for line in lines:
        if not line.startswith("data:"):
            continue
        data = line[5:].strip()
        if not data or data == "[DONE]":
            continue
        try:
            event = json.loads(data)
        except ValueError:
            continue
        etype = event.get("type") if isinstance(event, dict) else None
        if etype == EVENT_DELTA:
            delta = event.get("delta")
            if isinstance(delta, str):
                chunks.append(delta)
        elif etype == EVENT_DONE:
            resp = event.get("response") or {}
            if isinstance(resp, dict) and isinstance(resp.get("usage"), dict):
                usage = resp["usage"]
            break
        elif etype in EVENT_ERRORS:
            detail = event.get("error") or event.get("response") or {}
            msg = detail.get("message") if isinstance(detail, dict) else None
            raise SamError(f"SAM stream reported {etype}: {msg or 'no message'}")
    # One line per frame: keep frame boundaries even if a delta lacks a newline.
    return "\n".join(c.strip("\n") for c in chunks), usage


class SamClient:
    """Client for SAM 3.1 image segmentation (streamed Responses API)."""

    def __init__(
        self,
        api_key: str,
        *,
        base_url: str = DEFAULT_BASE_URL,
        model: str = DEFAULT_SAM_MODEL,
        include_confidence: bool = True,
        timeout_s: float = 60.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        """Create a SAM client.

        Args:
            api_key: Meta Model API key (same key as chat). Never logged.
            base_url: API base URL.
            model: SAM model id.
            include_confidence: Ask for per-record confidence (``metadata``).
            timeout_s: Request timeout.
            transport: Injected HTTP transport (tests).

        Raises:
            SamError: Empty key.
        """
        if not api_key:
            raise SamError("Meta Model API key is empty")
        self._api_key = api_key
        self._url = base_url.rstrip("/") + RESPONSES_PATH
        self._model = model
        self._include_confidence = include_confidence
        self._client = httpx.Client(
            timeout=httpx.Timeout(timeout_s, connect=min(10.0, timeout_s)), transport=transport
        )

    def __repr__(self) -> str:
        """Representation without the key."""
        return f"SamClient(url={self._url!r}, model={self._model!r})"

    def close(self) -> None:
        """Close the HTTP client."""
        self._client.close()

    def __enter__(self) -> SamClient:
        """Context-manager entry."""
        return self

    def __exit__(self, *exc: object) -> None:
        """Close on exit."""
        self.close()

    def request_body(self, image: EncodedImage, prompt: str) -> dict[str, Any]:
        """JSON body for one image + one noun-phrase prompt."""
        body: dict[str, Any] = {
            "model": self._model,
            "stream": True,
            "input": [
                {
                    "type": "message",
                    "role": "user",
                    "content": [
                        {"type": "input_text", "text": prompt},
                        {"type": "input_image", "image_url": image.data_url},
                    ],
                }
            ],
        }
        if self._include_confidence:
            body["metadata"] = {"include_confidence": "true"}
        return body

    def segment(self, image: EncodedImage, prompt: str) -> SamResult:
        """Segment every instance of ``prompt`` in ``image``.

        Raises:
            SamError: HTTP / stream error or output outside the grammar.
        """
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
        }
        try:
            with self._client.stream(
                "POST", self._url, json=self.request_body(image, prompt), headers=headers
            ) as resp:
                if resp.status_code >= 400:
                    resp.read()
                    raise SamError(
                        f"SAM HTTP {resp.status_code}: {_error_message(resp)}",
                        status_code=resp.status_code,
                        retryable=resp.status_code in RETRYABLE_STATUS,
                    )
                lines = list(resp.iter_lines())
        except httpx.TimeoutException as exc:
            raise SamError(f"SAM timed out ({type(exc).__name__})", retryable=True) from exc
        except httpx.HTTPError as exc:
            raise SamError(f"SAM request failed ({type(exc).__name__})", retryable=True) from exc
        text, usage = read_sse_text(lines)
        return SamResult(
            prompt=prompt, records=parse_segmentation(text), raw_text=text, usage=usage
        )
