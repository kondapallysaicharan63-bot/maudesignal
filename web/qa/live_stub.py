"""A local stub of the live API (contract: web/DATA_CONTRACT.md, "Live API"). Used only by the Playwright runs.

It answers POST /v1/live/ask, /v1/live/voice and /v1/live/label with canned, clearly fake content, checks what the page
sent (the WAV header, the JPEG without EXIF, the history, the length limits) and logs every request so a test can read it
back at GET /__log. It stores nothing on disk and keeps the log in memory only. CORS: only the origins given, no credentials.

    from live_stub import Stub
    stub = Stub(port=8765, origins={"http://127.0.0.1:4173"}); stub.start()
"""

# ruff: noqa: E501, D102, D107
from __future__ import annotations

import json
import struct
import threading
from email.parser import BytesParser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

HEARD = "What changed this week?"
MAX_IMAGE_BYTES = 4 * 1024 * 1024  # the real server's limit for the image part
SEARCH_FAILED_NOTE = "openFDA could not be searched, so there is no match result for this photo."


def check_wav(data: bytes) -> dict[str, Any]:
    """Describe a WAV the way the real server must check it: RIFF/WAVE, PCM, mono, 16 kHz, 16-bit, data length."""
    info: dict[str, Any] = {"bytes": len(data), "valid": False}
    if len(data) < 44 or data[:4] != b"RIFF" or data[8:12] != b"WAVE" or data[12:16] != b"fmt ":
        return info
    fmt, ch, rate, _byte_rate, _align, bits = struct.unpack("<HHIIHH", data[20:36])
    info.update(format=fmt, channels=ch, sample_rate=rate, bits=bits)
    if data[36:40] == b"data":
        n = struct.unpack("<I", data[40:44])[0]
        info["data_bytes"] = n
        info["seconds"] = n / (rate * ch * bits // 8) if rate else 0
        info["valid"] = (fmt, ch, rate, bits) == (1, 1, 16000, 16) and n == len(data) - 44 and n > 0
    return info


def check_jpeg(data: bytes) -> dict[str, Any]:
    """Describe a JPEG: the magic bytes and whether any APP1 'Exif' segment is present."""
    info: dict[str, Any] = {
        "bytes": len(data),
        "jpeg": data[:3] == b"\xff\xd8\xff",
        "exif": b"Exif\x00\x00" in data[:65536],
    }
    # Width and height from the first SOFn segment, so a test can see the long side the page sent.
    i = 2
    while info["jpeg"] and i + 9 < len(data) and data[i] == 0xFF:
        marker = data[i + 1]
        if 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC):
            info["height"], info["width"] = struct.unpack(">HH", data[i + 5 : i + 9])
            break
        i += 2 + struct.unpack(">H", data[i + 2 : i + 4])[0]
    return info


class Stub:
    """The stub server. `mode` can be set at any time: "ok", "429", "500", "422_patient", "recorded".

    `label_mode`: "ok", "search_failed" (openFDA could not be searched), "no_match" (searched, nothing found).
    """

    def __init__(self, port: int = 8765, origins: set[str] | None = None) -> None:
        self.port = port
        self.origins = origins or set()
        self.log: list[dict[str, Any]] = []
        self.mode = "ok"
        self.label_mode = "ok"
        self.live_left = 20
        self.lookup_mode = "ok"  # "ok", "404" (the tool is not deployed)
        self.connect_mode = "ok"  # "ok" (a demo key is handed out), "no_key", "404"
        self.mentions_mode = "ok"  # "ok", "empty" (nothing found)
        self._server: ThreadingHTTPServer | None = None

    def start(self) -> None:
        stub = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, format: str, *args: object) -> None:  # noqa: A002
                pass

            def _cors(self) -> None:
                origin = self.headers.get("Origin", "")
                if origin in stub.origins:
                    self.send_header("Access-Control-Allow-Origin", origin)
                    self.send_header("Vary", "Origin")

            def _send(
                self, status: int, body: dict[str, Any], extra: dict[str, str] | None = None
            ) -> None:
                if (
                    "code" in body and "error" not in body
                ):  # the real API repeats code and message under "error"
                    body = {**body, "error": {"code": body["code"], "message": body["message"]}}
                raw = json.dumps(body).encode()
                self.send_response(status)
                self._cors()
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                for k, v in (extra or {}).items():
                    self.send_header(k, v)
                self.end_headers()
                self.wfile.write(raw)

            def do_OPTIONS(self) -> None:  # noqa: N802
                self.send_response(204)
                self._cors()
                self.send_header("Access-Control-Allow-Methods", "POST, GET, OPTIONS")
                self.send_header("Access-Control-Allow-Headers", "content-type, x-api-key")
                self.end_headers()

            def do_GET(self) -> None:  # noqa: N802
                if self.path == "/__log":
                    self._send(200, {"log": stub.log})
                elif self.path == "/v1/connect":
                    stub.log.append(
                        {
                            "path": self.path,
                            "method": "GET",
                            "origin": self.headers.get("Origin"),
                            "credentials_sent": "Cookie" in self.headers,
                        }
                    )
                    if stub.connect_mode == "404":
                        self._send(404, {"code": "not_found", "message": "no such path"})
                    else:
                        self._send(200, stub.connect())
                elif self.path.startswith("/v1/tools/lookup_device"):
                    # Make it yours: GET with the demo key in X-API-Key; only the K-number is sent.
                    q = self.path.partition("?")[2]
                    entry = {
                        "path": self.path,
                        "method": "GET",
                        "origin": self.headers.get("Origin"),
                        "key_sent": self.headers.get("X-API-Key") == "stub-demo-key-not-a-real-key",
                        "credentials_sent": "Cookie" in self.headers,
                        "query": q,
                    }
                    stub.log.append(entry)
                    if not entry["key_sent"]:
                        return self._send(401, {"code": "unauthorized", "message": "key needed"})
                    if stub.lookup_mode == "404":
                        return self._send(404, {"code": "not_found", "message": "no such path"})
                    if q == "k_number=K999999":
                        return self._send(200, {"found": False})
                    return self._send(
                        200,
                        {
                            "device": {
                                "k_number": q.partition("=")[2],
                                "device_name": "Stub looked-up device",
                                "applicant": "Stub Maker",
                                "product_code": "QIH",
                            }
                        },
                    )
                else:
                    self._send(404, {"code": "not_found", "message": "no such path"})

            def do_POST(self) -> None:  # noqa: N802
                n = int(self.headers.get("Content-Length", "0"))
                raw = self.rfile.read(n)
                ctype = self.headers.get("Content-Type", "")
                entry: dict[str, Any] = {
                    "path": self.path,
                    "content_type": ctype.split(";")[0],
                    "origin": self.headers.get("Origin"),
                    "credentials_sent": "Cookie" in self.headers,
                }
                stub.log.append(entry)
                if (
                    n > MAX_IMAGE_BYTES + 64 * 1024
                ):  # the real server caps the body at 4 MB plus multipart overhead
                    return self._send(413, {"code": "too_large", "message": "too large"})
                if stub.mode == "429":
                    return self._send(
                        429,
                        {
                            "code": "rate_limited",
                            "message": "Daily live limit reached.",
                            "retry_after_s": 3600,
                        },
                        {"Retry-After": "3600"},
                    )
                if stub.mode == "500":
                    return self._send(500, {"code": "server", "message": "boom"})
                if self.path == "/v1/live/mentions":
                    return stub.mentions_route(self, raw, entry)
                if self.path == "/v1/live/ask":
                    try:
                        body = json.loads(raw)
                    except ValueError:
                        return self._send(
                            422, {"code": "invalid_input", "message": "Body is not JSON."}
                        )
                    entry["body"] = body
                    if not isinstance(body, dict) or set(body) - {
                        "question",
                        "history",
                        "product_code",
                        "ref",
                    }:
                        return self._send(
                            422, {"code": "invalid_input", "message": "Invalid input: request."}
                        )
                    pc = body.get("product_code")
                    if pc is not None and not (
                        isinstance(pc, str) and len(pc) == 3 and pc.isalpha()
                    ):
                        return self._send(
                            422,
                            {"code": "invalid_input", "message": "Invalid input: product_code."},
                        )
                    q = body.get("question")
                    if not isinstance(q, str) or not 3 <= len(q.strip()) <= 500:
                        return self._send(
                            422,
                            {
                                "code": "invalid_input",
                                "message": "question must be 3 to 500 characters.",
                            },
                        )
                    hist = body.get("history", [])
                    if (
                        not isinstance(hist, list)
                        or len(hist) > 4
                        or any(len(h.get("answer", "")) > 20000 for h in hist)
                    ):
                        return self._send(
                            422,
                            {
                                "code": "invalid_input",
                                "message": "Invalid input: history.",
                            },
                        )
                    if (
                        "mrn" in q.lower()
                        or "patient name" in q.lower()
                        or stub.mode == "422_patient"
                    ):
                        return self._send(
                            422,
                            {
                                "code": "patient_data",
                                "message": "This looks like patient details, so it was not sent to the model. Remove them and ask again.",
                            },
                        )
                    return self._send(200, stub.answer(q, hist))
                if self.path == "/v1/live/voice":
                    msg = BytesParser().parsebytes(
                        b"Content-Type: " + ctype.encode() + b"\r\n\r\n" + raw
                    )
                    parts = {
                        p.get_param("name", header="content-disposition"): p.get_payload(
                            decode=True
                        )
                        for p in msg.walk()
                        if not p.is_multipart()
                    }
                    audio = parts.get("audio") or b""
                    info = check_wav(audio)
                    entry["audio"] = info
                    if "meta" in parts and parts["meta"]:
                        entry["meta"] = json.loads(parts["meta"])
                    if not info["valid"]:
                        return self._send(
                            422,
                            {
                                "code": "invalid_input",
                                "message": "audio must be WAV PCM16 mono 16000 Hz.",
                            },
                        )
                    return self._send(200, stub.answer(HEARD, [], heard=HEARD))
                if self.path == "/v1/live/label":
                    msg = BytesParser().parsebytes(
                        b"Content-Type: " + ctype.encode() + b"\r\n\r\n" + raw
                    )
                    parts = {
                        p.get_param("name", header="content-disposition"): p.get_payload(
                            decode=True
                        )
                        for p in msg.walk()
                        if not p.is_multipart()
                    }
                    img = parts.get("image") or b""
                    info = check_jpeg(img)
                    entry["image"] = info
                    if info["bytes"] > MAX_IMAGE_BYTES:
                        return self._send(
                            413, {"code": "too_large", "message": "The upload is too large."}
                        )
                    if not info["jpeg"] or info["exif"]:
                        return self._send(
                            422,
                            {
                                "code": "invalid_input",
                                "message": "image must be a JPEG without EXIF.",
                            },
                        )
                    return self._send(200, stub.label())
                self._send(404, {"code": "not_found", "message": "no such path"})

        self._server = ThreadingHTTPServer(("127.0.0.1", self.port), H)
        threading.Thread(target=self._server.serve_forever, daemon=True).start()

    def stop(self) -> None:
        if self._server:
            self._server.shutdown()
            self._server.server_close()

    def common(self, trace: list[dict[str, Any]], recorded: str | None = None) -> dict[str, Any]:
        """Fields every real live response has: mode, recorded_note (recorded only), trace, cost_usd, limits."""
        self.live_left = max(
            0, self.live_left - 1
        )  # every accepted request counts, live or recorded
        out: dict[str, Any] = {
            "mode": "live" if recorded is None else "recorded",
            "not_medical_advice": True,
            "trace": trace,
            "cost_usd": None,  # the real API sends null when nothing was spent
            "limits": {"remaining_today": self.live_left, "resets_utc": "2026-11-01T00:00:00Z"},
        }
        if recorded is not None:
            out["recorded_note"] = recorded
        return out

    def answer(self, q: str, hist: list[Any], heard: str | None = None) -> dict[str, Any]:
        n = len(hist)
        recorded = self.mode == "recorded"
        trace = (
            [
                {
                    "step": "Muse Spark answers from stored records",
                    "model": "muse-spark-1.3",
                    "ms": 0,
                    "status": "skipped",
                    "note": "No live model key is configured here.",
                },
                {"step": "Closest recorded answer", "model": None, "ms": 4, "status": "ok"},
            ]
            if recorded
            else [
                {
                    "step": "Muse Spark answers from stored records",
                    "model": "muse-spark-1.3",
                    "ms": 812,
                    "status": "ok",
                },
                {
                    "step": "Read-only tools and claim gate",
                    "model": None,
                    "ms": 6,
                    "status": "ok",
                    "note": "1 tool call(s): what_changed_this_week",
                },
            ]
        )
        if heard:
            trace.insert(
                0,
                {
                    "step": "Muse Voice Transcribe",
                    "model": "muse-voice-transcribe-1.0",
                    "ms": 540,
                    "status": "ok",
                },
            )
        sentences = [
            {
                "text": f"Stub answer {n + 1}: 33 reports were stored for the week.",
                "links": [
                    {
                        "label": "Report 50426770",
                        "url": "https://www.accessdata.fda.gov/scripts/cdrh/cfdocs/cfmaude/detail.cfm?mdrfoi__id=50426770",
                    }
                ],
            },
            {"text": "Two device types had more serious reports than usual.", "links": []},
        ]
        out = self.common(
            trace,
            (
                'No live model call was made. Shown instead: a recorded run that answered "What changed this week?" (recorded 2026-10-28).'
                if recorded
                else None
            ),
        )
        out["answer"] = {
            "speakable": sentences,
            "withheld": [{"reason": "a number did not match the stored data"}],
            "spoken_text": " ".join(s["text"] for s in sentences),
        }
        if heard:
            out["heard"] = heard
        return out

    def connect(self) -> dict[str, Any]:
        """GET /v1/connect with the real API body (ConnectInfo). The key is a fake string for the stub only."""
        base = "https://maudesignal-api.vercel.app"
        return {
            "mcp_url": f"{base}/mcp",
            "openapi_url": f"{base}/openapi.json",
            "docs_url": f"{base}/docs-page",
            "auth_header": "X-API-Key",
            "demo_key": None if self.connect_mode == "no_key" else "stub-demo-key-not-a-real-key",
            "demo_limits": {
                "per_minute": 10,
                "per_day": 200,
                "live_model": False,
                "note": "Read tools only. ask returns a recorded answer, labelled recorded.",
            },
            "steps": [
                f"Add {base}/mcp as a custom MCP connector.",
                "Send the key in the X-API-Key header.",
                "Call a tool, for example what_changed_this_week with product_code LLZ.",
            ],
        }

    def mentions_route(self, h: Any, raw: bytes, entry: dict[str, Any]) -> None:
        """POST /v1/live/mentions: check the body the way the real server must, then answer with canned, clearly fake mentions."""
        try:
            body = json.loads(raw)
        except ValueError:
            return h._send(422, {"code": "invalid_input", "message": "Body is not JSON."})
        entry["body"] = body
        if not isinstance(body, dict) or set(body) - {"product_code", "device_terms"}:
            return h._send(422, {"code": "invalid_input", "message": "Invalid input: request."})
        pc = body.get("product_code")
        if not (isinstance(pc, str) and len(pc) == 3 and pc.isalpha()):
            return h._send(
                422, {"code": "invalid_input", "message": "Invalid input: product_code."}
            )
        terms = body.get("device_terms", [])
        if (
            not isinstance(terms, list)
            or len(terms) > 5
            or any(not isinstance(t, str) for t in terms)
        ):
            return h._send(
                422, {"code": "invalid_input", "message": "Invalid input: device_terms."}
            )
        return h._send(200, self.mentions(pc.upper(), terms))

    def mentions(self, code: str, terms: list[str]) -> dict[str, Any]:
        """A mentions answer shaped like the contract. Content is fake (example.com) except one fda.gov address."""
        self.live_left = max(0, self.live_left - 1)
        empty = self.mentions_mode == "empty"
        found = (
            []
            if empty
            else [
                {
                    "source_name": "FDA press releases",
                    "source_kind": "official",
                    "date": "2026-10-20",
                    "url": "https://www.fda.gov/news-events/press-announcements/stub-announcement",
                    "quote": f"Stub sentence about {code} found on the fetched page.",
                    "why_matched": f"matched: {code}",
                    "badge": "Checked and approved by FDA",  # the page must ignore this and print its own fixed badge
                },
                {
                    "source_name": "Stub News",
                    "source_kind": "official",  # claims official but the address is not fda.gov: the page must show it as Public web
                    "date": "2026-10-21",
                    "url": "https://example.com/news/stub",
                    "quote": "Stub sentence from a news page about the device type.",
                    "why_matched": "matched: device type",
                    "badge": "x",
                },
                {
                    "source_name": "Stub Blog",
                    "source_kind": "web",
                    "date": None,
                    "url": "https://example.com/blog/stub",
                    "quote": "Dr. Smith said the device failed.",  # personal details: the page drops it and counts it
                    "why_matched": "matched: device",
                    "badge": "x",
                },
            ]
        )
        if empty:  # the real recorded LLZ zero result: failed rows and a MassDevice row the page must not show
            tried = [
                {"name": "GDELT DOC 2.0 (news index)", "url": "https://api.gdeltproject.org/api/v2/doc/doc", "status": "failed: ConnectTimeout", "n": 0},
                {"name": "FDA press releases (RSS)", "url": "https://www.fda.gov/about-fda/contact-fda/stay-informed/rss-feeds/press-releases/rss.xml", "status": "ok", "n": 0},
                {"name": "FDA recalls (RSS)", "url": "https://www.fda.gov/about-fda/contact-fda/stay-informed/rss-feeds/recalls/rss.xml", "status": "ok", "n": 0},
                {"name": "FDA warning letters (RSS)", "url": "https://www.fda.gov/about-fda/contact-fda/stay-informed/rss-feeds/warning-letters/rss.xml", "status": "failed: http 404", "n": 0},
                {"name": "MedTech Dive (RSS)", "url": "https://www.medtechdive.com/feeds/news/", "status": "ok", "n": 0},
                {"name": "MassDevice (RSS)", "url": "https://www.massdevice.com/feed/", "status": "failed: http 403", "n": 0},
                {"name": "Example Wire (RSS)", "url": "https://example.com/feed/", "status": "skipped: time", "n": 0},
            ]
            trace = [
                {"step": "Search: GDELT DOC 2.0 (news index)", "model": None, "ms": 6031, "status": "failed: ConnectTimeout"},
                {"step": "Search: FDA press releases (RSS)", "model": None, "ms": 277, "status": "ok"},
                {"step": "Search: FDA recalls (RSS)", "model": None, "ms": 352, "status": "ok"},
                {"step": "Search: FDA warning letters (RSS)", "model": None, "ms": 431, "status": "failed: http 404"},
                {"step": "Search: MedTech Dive (RSS)", "model": None, "ms": 228, "status": "ok"},
                {"step": "Search: MassDevice (RSS)", "model": None, "ms": 173, "status": "failed: http 403"},
                {"step": "Search: Example Wire (RSS)", "model": None, "ms": 0, "status": "skipped: time"},
                {"step": "Fetch pages and check each quote against the page text", "model": None, "ms": 0, "status": "0 page(s) tried"},
            ]
        else:
            tried = [
                {"name": "GDELT news search", "url": "https://api.gdeltproject.org/api/v2/doc/doc", "status": "ok", "n": 5},
                {"name": "FDA press releases", "url": "https://www.fda.gov/about-fda/contact-fda/stay-informed/rss-feeds/press-releases/rss.xml", "status": "ok", "n": 2},
            ]
            trace = [{"step": "Fetch and check pages", "model": None, "ms": 220, "status": "ok", "note": f"terms: {', '.join(terms) or 'none'}"}]
        return {
            "product_code": code,
            "searched_utc": "2026-10-31T12:00:00Z",
            "sources_tried": tried,
            "mentions": found,
            "dropped": {
                "quote_not_found": 0 if empty else 2,
                "personal_details": 0,
                "off_topic": 0 if empty else 1,
            },
            "trace": trace,
            "limits": {"remaining_today": self.live_left, "resets_utc": "2026-11-01T00:00:00Z"},
            "mode": "live",
        }

    def label(self) -> dict[str, Any]:
        """A label answer shaped like the real one (reading fields as the API names them, lot and serial withheld)."""
        failed = self.label_mode == "search_failed"
        trace = [
            {"step": "Re-encode photo, drop metadata", "model": None, "ms": 38, "status": "ok"},
            {"step": "SAM 3.1 crop", "model": "sam-3.1", "ms": 1400, "status": "ok"},
            {"step": "Muse Spark read", "model": "muse-spark-1.3", "ms": 4200, "status": "ok"},
            {
                "step": "openFDA search for possible matches",
                "model": None,
                "ms": 900,
                "status": "failed" if failed else "ok",
                "note": "2 openFDA search(es), 2 failed" if failed else "2 openFDA search(es)",
            },
        ]
        cands = (
            []
            if failed or self.label_mode == "no_match"
            else [
                {
                    "k_number": f"K00000{i}",
                    "device_name": f"Stub device {i}",
                    "applicant": f"Stub Maker {i}",
                    "product_code": "QIH",
                    "why_matched": [f"device name matches stub {i}"],
                    "why_not_matched": [] if i == 1 else ["model number differs"],
                    "links": [
                        {
                            "label": "510(k) record on openFDA",
                            "url": f"https://api.fda.gov/device/510k.json?search=k_number:K00000{i}",
                        }
                    ],
                }
                for i in (1, 2, 3)
            ]
        )
        matches: dict[str, Any] = {
            "status": "needs_person_to_confirm" if cands else "no_match_found",
            "candidates": cands,
        }
        if failed:
            matches["search_failed"] = True
            matches["note"] = SEARCH_FAILED_NOTE
        recorded = self.mode == "recorded"
        if recorded:
            trace = [
                {"step": "Re-encode photo, drop metadata", "model": None, "ms": 38, "status": "ok"},
                {
                    "step": "Muse Spark read",
                    "model": "muse-spark-1.3",
                    "ms": 0,
                    "status": "skipped",
                    "note": "No live model key is configured here.",
                },
            ]
        out = self.common(
            trace,
            (
                "No live model call was made. Shown instead: a recorded label run (stub sample)."
                if recorded
                else None
            ),
        )
        out["cost_usd"] = None if recorded else 0.0123  # fake figure for the stub only
        out.update(
            reading={
                "legibility": "partly_legible",
                "fields": {
                    "device_name": {"value": "Stub device", "legibility": "clear"},
                    "manufacturer": {"value": "Stub Maker", "legibility": "clear"},
                    "model": {"value": "", "legibility": "illegible"},
                    "k_number": {"value": "", "legibility": "illegible"},
                    "udi": {"value": "", "legibility": "illegible"},
                    "gtin": {"value": "", "legibility": "illegible"},
                },
                "values_withheld": ["lot", "serial"],
            },
            matches=matches,
            confirmed=None,
        )
        return out
