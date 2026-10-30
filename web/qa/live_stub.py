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
    return {
        "bytes": len(data),
        "jpeg": data[:3] == b"\xff\xd8\xff",
        "exif": b"Exif\x00\x00" in data[:65536],
    }


class Stub:
    """The stub server. `mode` can be set at any time: "ok", "429", "500", "422_patient"."""

    def __init__(self, port: int = 8765, origins: set[str] | None = None) -> None:
        self.port = port
        self.origins = origins or set()
        self.log: list[dict[str, Any]] = []
        self.mode = "ok"
        self.live_left = 20
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
                self.send_header("Access-Control-Allow-Headers", "content-type")
                self.end_headers()

            def do_GET(self) -> None:  # noqa: N802
                if self.path == "/__log":
                    self._send(200, {"log": stub.log})
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
                if n > 12 * 1024 * 1024:
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
                if self.path == "/v1/live/ask":
                    try:
                        body = json.loads(raw)
                    except ValueError:
                        return self._send(
                            422, {"code": "invalid_input", "message": "Body is not JSON."}
                        )
                    entry["body"] = body
                    q = body.get("question") if isinstance(body, dict) else None
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
                        or any(len(h.get("answer", "")) > 600 for h in hist)
                    ):
                        return self._send(
                            422,
                            {
                                "code": "invalid_input",
                                "message": "history is limited to 4 turns of 600 characters.",
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

    def common(self, trace: list[dict[str, Any]]) -> dict[str, Any]:
        self.live_left -= 1
        return {
            "mode": "live",
            "not_medical_advice": True,
            "trace": trace,
            "cost_usd": None,
            "limits": {"remaining_today": self.live_left, "resets_utc": "2026-11-01T00:00:00Z"},
        }

    def answer(self, q: str, hist: list[Any], heard: str | None = None) -> dict[str, Any]:
        n = len(hist)
        trace = [
            {
                "step": "Muse Spark reads the stored records",
                "model": "muse-spark-1.3",
                "ms": 812,
                "status": "ok",
            },
            {"step": "Claim gate checks every sentence", "model": None, "ms": 6, "status": "ok"},
        ]
        if heard:
            trace.insert(
                0,
                {
                    "step": "Transcribe the question",
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
        out = self.common(trace)
        out["answer"] = {
            "speakable": sentences,
            "withheld": [{"reason": "a number did not match the stored data"}],
            "spoken_text": " ".join(s["text"] for s in sentences),
        }
        if heard:
            out["heard"] = heard
        return out

    def label(self) -> dict[str, Any]:
        trace = [
            {"step": "SAM 3.1 finds the label", "model": "sam-3.1", "ms": 1400, "status": "ok"},
            {
                "step": "Muse Spark reads the label",
                "model": "muse-spark-1.3",
                "ms": 4200,
                "status": "ok",
            },
            {"step": "Search openFDA", "model": None, "ms": 900, "status": "ok"},
            {"step": "Claim gate checks the reading", "model": None, "ms": 5, "status": "ok"},
        ]
        cands = [
            {
                "k_number": f"K00000{i}",
                "device_name": f"Stub device {i}",
                "applicant": f"Stub Maker {i}",
                "product_code": "QIH",
                "why_matched": [f"device name matches stub {i}"],
                "why_not_matched": [] if i == 1 else ["model number differs"],
                "links": [
                    {
                        "label": "openFDA record",
                        "url": f"https://api.fda.gov/device/510k.json?search=k_number:K00000{i}",
                    }
                ],
            }
            for i in (1, 2, 3)
        ]
        out = self.common(trace)
        out.update(
            reading={
                "legibility": "partly_legible",
                "fields": {
                    "device_name": {"value": "Stub device", "legibility": "clear"},
                    "manufacturer": {"value": "Stub Maker", "legibility": "clear"},
                    "model": {"value": None, "legibility": "illegible"},
                    "k_number": {"value": None, "legibility": "illegible"},
                    "udi/gtin": {"value": None, "legibility": "illegible"},
                },
                "values_withheld": ["model", "k_number", "udi/gtin"],
            },
            matches={"status": "needs_person_to_confirm", "candidates": cands},
            confirmed=None,
        )
        return out
