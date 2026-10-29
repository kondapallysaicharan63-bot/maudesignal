"""Tests for the voice-query surface (HACKATHON-BUILT).

Meta Voice Transcribe is faked with ``httpx.MockTransport`` and Muse Spark with a
scripted OpenAI-compatible client, so these tests make no network calls.
"""

from __future__ import annotations

import hashlib
import io
import json
import wave
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
import pytest

from maudesignal.copilot.agent import CopilotAgent
from maudesignal.copilot.tools import ToolContext
from maudesignal.copilot.transcript import load_transcripts, result_to_dict, save_transcript
from maudesignal.copilot.voice import (
    DEFAULT_VOICE_MODEL,
    MAX_BODY_BYTES,
    AudioValidationError,
    MetaTranscriber,
    Transcript,
    VoiceTranscribeError,
    ask_by_voice,
    estimate_cost_usd,
    validate_audio,
)
from maudesignal.gate.loader import store_from_database
from maudesignal.storage.database import Database

KEY = "sk-test-not-a-real-key-123"
QUESTION = "What came in overnight? Is anything worsening?"


def _wav(seconds: float = 1.0, rate: int = 16000, channels: int = 1, width: int = 2) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(width)
        w.setframerate(rate)
        w.writeframes(b"\x00" * int(seconds * rate) * channels * width)
    return buf.getvalue()


class Recorder:
    """MockTransport handler that records requests and returns a canned response."""

    def __init__(self, response: httpx.Response | Exception) -> None:
        self.response = response
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        request.read()
        self.requests.append(request)
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


def _ok(text: str = QUESTION, ms: int = 3220) -> httpx.Response:
    return httpx.Response(
        200, json={"sessionId": "s-1", "transcript": text, "audioDurationMs": ms, "turns": []}
    )


def _tr(handler: Recorder, **kw: Any) -> MetaTranscriber:
    return MetaTranscriber(KEY, transport=httpx.MockTransport(handler), **kw)


# ---------------------------------------------------------------------------
# Transcriber
# ---------------------------------------------------------------------------


def test_transcribe_success_sends_documented_request() -> None:
    rec = Recorder(_ok())
    with _tr(rec) as tr:
        t = tr.transcribe_bytes(_wav(3.2), filename="q.wav")
    assert t.text == QUESTION and t.duration_s == 3.22 and t.session_id == "s-1"
    assert t.language == "English"  # the single languageBias sent; API reports none
    assert t.raw["turns"] == []
    req = rec.requests[0]
    assert req.method == "POST" and str(req.url) == "https://api.meta.ai/v1/asr/transcribe"
    assert req.headers["authorization"] == f"Bearer {KEY}"
    assert req.headers["accept"] == "application/json"
    assert req.headers["content-type"].startswith("multipart/form-data")
    body = req.content
    assert b'name="request"' in body and b'name="audio"; filename="q.wav"' in body
    assert b"Content-Type: audio/wav" in body
    settings_part = body.split(b'name="request"')[1].split(b"\r\n\r\n", 1)[1].split(b"\r\n--")[0]
    settings = json.loads(settings_part)
    assert settings["model"] == DEFAULT_VOICE_MODEL == "muse-voice-transcribe-1.0"
    assert settings["audioEncoding"] == "WAV" and settings["mode"] == "PUSH_TO_TALK"
    assert "MAUDE" in settings["keywords"] and settings["languageBias"] == ["English"]


def test_no_bias_means_unknown_language_and_custom_base_url() -> None:
    rec = Recorder(_ok())
    tr = _tr(rec, language_bias=None, keywords=None, base_url="https://example.test/v1/")
    t = tr.transcribe_bytes(_wav())
    assert t.language is None
    assert str(rec.requests[0].url) == "https://example.test/v1/asr/transcribe"
    assert "languageBias" not in tr.request_settings() and "keywords" not in tr.request_settings()


@pytest.mark.parametrize(
    ("status", "retryable"), [(400, False), (401, False), (413, False), (429, True), (503, True)]
)
def test_http_errors_raise_without_leaking_key(status: int, retryable: bool) -> None:
    body = {"error": {"message": "bad thing", "type": "invalid_request_error", "code": "x1"}}
    tr = _tr(Recorder(httpx.Response(status, json=body)))
    with pytest.raises(VoiceTranscribeError) as ei:
        tr.transcribe_bytes(_wav())
    err = ei.value
    assert err.status_code == status and err.retryable is retryable
    assert "bad thing" in str(err) and "code=x1" in str(err)
    assert KEY not in str(err) and KEY not in repr(tr)


def test_server_error_with_text_body() -> None:
    tr = _tr(Recorder(httpx.Response(500, text="upstream exploded")))
    with pytest.raises(VoiceTranscribeError, match="HTTP 500: upstream exploded") as ei:
        tr.transcribe_bytes(_wav())
    assert ei.value.retryable


def test_timeout_and_transport_errors_are_wrapped() -> None:
    tr = _tr(Recorder(httpx.ReadTimeout("slow")))
    with pytest.raises(VoiceTranscribeError, match="timed out") as ei:
        tr.transcribe_bytes(_wav())
    assert ei.value.retryable and ei.value.status_code is None
    tr2 = _tr(Recorder(httpx.ConnectError("refused")))
    with pytest.raises(VoiceTranscribeError, match="request failed"):
        tr2.transcribe_bytes(_wav())


@pytest.mark.parametrize(
    "resp",
    [
        httpx.Response(200, text="not json"),
        httpx.Response(200, json={"sessionId": "s"}),
        httpx.Response(200, json=["transcript"]),
    ],
)
def test_malformed_success_response(resp: httpx.Response) -> None:
    with pytest.raises(VoiceTranscribeError):
        _tr(Recorder(resp)).transcribe_bytes(_wav())


def test_missing_duration_is_none() -> None:
    t = _tr(Recorder(httpx.Response(200, json={"transcript": " hi "}))).transcribe_bytes(_wav())
    assert t.text == "hi" and t.duration_s is None and t.cost_usd == 0.0


def test_empty_key_refused() -> None:
    with pytest.raises(VoiceTranscribeError):
        MetaTranscriber("")


# ---------------------------------------------------------------------------
# Local validation (nothing is uploaded)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("data", "name", "match"),
    [
        (_wav(), "q.mp3", "unsupported file type"),
        (_wav(), "q", "unsupported file type"),
        (b"", "q.wav", "empty"),
        (b"RIFF0000garbage", "q.wav", "not a readable"),
        (_wav(channels=2), "q.wav", "mono"),
        (_wav(width=1), "q.wav", "16-bit"),
        (_wav(rate=44100), "q.wav", "sample rate"),
        (_wav(seconds=0), "q.wav", "no samples"),
        (_wav(seconds=601, rate=16000), "q.wav", "limit is 600 s"),
    ],
)
def test_validation_rejects_before_upload(data: bytes, name: str, match: str) -> None:
    rec = Recorder(_ok())
    with pytest.raises(AudioValidationError, match=match):
        _tr(rec).transcribe_bytes(data, filename=name)
    assert rec.requests == []


def test_oversize_file_rejected_before_upload() -> None:
    rec = Recorder(_ok())
    with pytest.raises(AudioValidationError, match="limit is 32 MB"):
        _tr(rec).transcribe_bytes(b"\x00" * (MAX_BODY_BYTES + 1), filename="big.wav")
    assert rec.requests == []


def test_validate_accepts_24k_and_transcribe_file(tmp_path: Path) -> None:
    assert validate_audio(_wav(2.0, rate=24000)).seconds == 2.0
    p = tmp_path / "q.WAV"
    p.write_bytes(_wav(1.0))
    assert _tr(Recorder(_ok())).transcribe_file(p).text == QUESTION
    with pytest.raises(AudioValidationError, match="cannot read"):
        _tr(Recorder(_ok())).transcribe_file(tmp_path / "missing.wav")


def test_cost_estimate() -> None:
    assert estimate_cost_usd(3600) == 0.18
    assert estimate_cost_usd(59.9) == estimate_cost_usd(59) == round(59 * 0.18 / 3600, 6)
    assert estimate_cost_usd(-1) == 0.0
    t = Transcript(text="x", language=None, duration_s=600.0)
    assert t.cost_usd == 0.03


# ---------------------------------------------------------------------------
# End to end: voice → transcript → gated copilot answer → recorded transcript
# ---------------------------------------------------------------------------


def _ctx(tmp_path: Path) -> ToolContext:
    db = Database(tmp_path / "v.db")
    for i, et in enumerate(["Malfunction", "Malfunction", "Injury"], start=1):
        rid = f"1111111-2026-0000{i}"
        db.upsert_raw_report(
            maude_report_id=rid,
            product_code="QIH",
            date_received=f"2026082{i + 4}",
            date_of_event=None,
            raw_payload={"report_number": rid},
        )
        db.upsert_normalized_event(
            maude_report_id=rid,
            product_code="QIH",
            event_type=et,
            event_date=None,
            narrative="Triage alert was not sent after a server update.",
            mfr_narrative=None,
            manufacturer="Acme",
            brand_name="Acme Triage",
        )
    return ToolContext(db=db, store=store_from_database(db))


def _msg(content: str | None = None, tool_calls: list[Any] | None = None) -> Any:
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content, tool_calls=tool_calls))],
        usage=SimpleNamespace(prompt_tokens=100, completion_tokens=50),
    )


class FakeClient:
    """Scripted OpenAI-compatible client (same pattern as test_copilot_agent)."""

    def __init__(self, script: list[Any]) -> None:
        self.script = list(script)
        self.calls: list[dict[str, Any]] = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kwargs: Any) -> Any:
        self.calls.append({**kwargs, "messages": list(kwargs["messages"])})
        return self.script.pop(0)


def test_ask_by_voice_end_to_end(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path)
    call = SimpleNamespace(
        id="c1",
        function=SimpleNamespace(name="product_summary", arguments='{"product_code": "QIH"}'),
    )
    answer = json.dumps(
        {
            "sentences": [
                {
                    "text": "QIH has 3 reports.",
                    "claims": [{"kind": "count", "product_code": "QIH", "value": 3}],
                }
            ]
        }
    )
    # tool round, tool-free draft, then the schema-constrained final-answer call
    client = FakeClient([_msg(tool_calls=[call]), _msg(answer), _msg(answer)])
    agent = CopilotAgent(client, ctx)
    wav = tmp_path / "question.wav"
    wav.write_bytes(_wav(3.2))
    rec = Recorder(_ok())

    ans = ask_by_voice(_tr(rec), agent, wav)

    assert ans.transcript.text == QUESTION
    assert ans.result.question == QUESTION and ans.result.report.passed == 1
    # Only text reaches the chat model — never audio.
    user_msgs = [m for m in client.calls[0]["messages"] if m["role"] == "user"]
    assert user_msgs[-1]["content"] == QUESTION
    assert all(isinstance(m.get("content"), str) for m in client.calls[0]["messages"])
    assert ans.cost_usd == round(ans.transcript.cost_usd + ans.result.cost_usd, 6)

    # Audit: what was heard is chained before the answer and points at it.
    trail = ctx.db.list_audit()
    assert [a.action for a in trail] == ["voice.transcribed", "copilot.answer"]
    heard, answered = trail
    payload = json.loads(heard.payload_json)
    assert heard.actor == "voice:muse-voice-transcribe-1.0"
    assert payload["transcript_text"] == QUESTION
    assert payload["audio_sha256"] == hashlib.sha256(wav.read_bytes()).hexdigest()
    assert heard.entity_id == f"V-{payload['audio_sha256'][:16]}"
    assert payload["audio_seconds"] == 3.22
    assert payload["question_entity_id"] == answered.entity_id
    assert ctx.db.verify_audit_chain() == (True, None)

    voice = ans.transcript.to_voice_block()
    assert voice == {"transcript_text": QUESTION, "language": "English", "audio_seconds": 3.22}
    d = result_to_dict(ans.result, label="00-voice", voice=voice)
    assert d["voice"]["transcript_text"] == QUESTION
    assert "voice" not in result_to_dict(ans.result)  # text-only shape unchanged
    save_transcript(ans.result, tmp_path / "t", label="00-voice", voice=voice)
    (loaded,) = load_transcripts(tmp_path / "t")
    assert loaded["voice"]["audio_seconds"] == 3.22


def test_ask_by_voice_bytes_and_silence_skips_model(tmp_path: Path) -> None:
    client = FakeClient([])
    ctx = _ctx(tmp_path)
    agent = CopilotAgent(client, ctx)
    with pytest.raises(VoiceTranscribeError, match="no speech"):
        ask_by_voice(_tr(Recorder(_ok(text="  "))), agent, _wav())
    assert client.calls == []  # nothing heard → no model call, no cost
    (rejected,) = ctx.db.list_audit()
    assert rejected.action == "voice.rejected"
    assert "model was not called" in json.loads(rejected.payload_json)["reason"]


def test_voice_html_shows_what_was_heard() -> None:
    from maudesignal.dashboard.copilot_pages import _voice_html

    out = _voice_html(
        {"transcript_text": "Is <LLZ> worsening?", "language": "English", "audio_seconds": 2.5}
    )
    assert "Heard:" in out and "&lt;LLZ&gt;" in out and "2.5 s" in out and "English" in out
    assert "Meta Voice Transcribe" in _voice_html({"transcript_text": "hi", "language": None})


def test_audit_export_roundtrip_and_tamper_detection(tmp_path: Path) -> None:
    from maudesignal.copilot.audit_export import export_audit, load_exports

    ctx = _ctx(tmp_path)
    ctx.db.append_audit(actor="voice:m", action="voice.transcribed", entity_id="V-1", payload={})
    ctx.db.append_audit(actor="copilot:x", action="copilot.answer", entity_id="Q-1", payload={})
    out = tmp_path / "t"
    export_audit(ctx.db, out / "audit-00-voice.json", run_label="00-voice")
    (doc,) = load_exports(out)
    assert doc["run_label"] == "00-voice" and doc["verified"] == (True, None)
    assert [e["action"] for e in doc["entries"]] == ["voice.transcribed", "copilot.answer"]

    doc["entries"][0]["payload_json"] = '{"transcript_text": "edited"}'
    (out / "audit-00-voice.json").write_text(json.dumps(doc), encoding="utf-8")
    (tampered,) = load_exports(out)
    assert tampered["verified"] == (False, 1)
