"""Tests for the public live Muse routes (HACKATHON-BUILT). No network, no model key.

Spark, Voice Transcribe, SAM and openFDA are replaced by fakes. Covers: the response
contract, per-address daily limits and their reset, the global cost cap, the recorded
fallbacks, the patient-data guard, upload limits, EXIF removal, CORS and "nothing stored".
"""

from __future__ import annotations

import base64
import io
import json
import tempfile
import wave
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402
from PIL import Image  # noqa: E402

from maudesignal.connector import live as live_module  # noqa: E402
from maudesignal.connector.app import Settings, create_app  # noqa: E402
from maudesignal.connector.ask import AgentFactory  # noqa: E402
from maudesignal.connector.blob_store import MemoryStore  # noqa: E402
from maudesignal.connector.data import ConnectorData  # noqa: E402
from maudesignal.connector.forbidden import forbidden_in  # noqa: E402
from maudesignal.connector.live import (  # noqa: E402
    LiveBackends,
    LiveConfig,
    UploadError,
    check_audio,
    clean_image,
    parse_multipart,
)
from maudesignal.connector.security import KeyStore, RateLimiter  # noqa: E402
from maudesignal.connector.store import ConnectorState, DailyCounter  # noqa: E402
from maudesignal.copilot.agent import CopilotAgent  # noqa: E402
from maudesignal.copilot.spend import SpendGuard  # noqa: E402
from maudesignal.copilot.voice import Transcript, VoiceTranscribeError  # noqa: E402
from maudesignal.vision.sam import SamClient  # noqa: E402
from tests.unit.test_connector import GOOD, KEY, SCRIPT, fake_check  # noqa: E402
from tests.unit.test_connector_store import FakeRedis, make_state  # noqa: E402
from tests.unit.test_label_match import FakeSearcher  # noqa: E402


@pytest.fixture(autouse=True)
def _per_instance_cap_accepted(monkeypatch: pytest.MonkeyPatch) -> None:
    """Most tests use a MemoryStore (no shared ledger); the operator override lets them run."""
    monkeypatch.setenv("MAUDESIGNAL_ALLOW_PER_INSTANCE_CAP", "1")


from tests.unit.test_vision import (  # noqa: E402
    LABEL_BOX,
    LABEL_PNG,
    FakeClient,
    label_payload,
    sam_transport,
)

ORIGIN = "https://app.example.com"
NOW = datetime(2026, 10, 30, 12, 0, 0, tzinfo=UTC)
QUESTION = "What changed this week for LLZ?"
PATH_ASK, PATH_VOICE, PATH_LABEL = "/v1/live/ask", "/v1/live/voice", "/v1/live/label"
MODELS = {"muse-spark-1.3", "muse-voice-transcribe-1.0", "sam-3.1", None}


# --- fakes -------------------------------------------------------------------------------


class Clock:
    """A settable wall clock (for the daily reset) and a monotonic clock for time budgets."""

    def __init__(self) -> None:
        self.now = NOW
        self.mono = 1000.0

    def wall(self) -> datetime:
        return self.now

    def advance(self, seconds: float) -> None:
        self.mono += seconds


class RecordingSpark:
    """Scripted Muse Spark chat client that keeps every request it receives."""

    def __init__(self, content: str = SCRIPT) -> None:
        self.content = content
        self.requests: list[dict[str, Any]] = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kwargs: Any) -> Any:
        self.requests.append(kwargs)
        return SimpleNamespace(
            model="muse-spark-1.3",
            choices=[
                SimpleNamespace(message=SimpleNamespace(content=self.content, tool_calls=None))
            ],
            usage=SimpleNamespace(prompt_tokens=100, completion_tokens=50),
        )


class FakeTranscriber:
    def __init__(self, text: str = "What changed this week for LLZ?", fail: bool = False) -> None:
        self.text, self.fail = text, fail
        self.received: list[bytes] = []

    def transcribe_bytes(self, data: bytes, *, filename: str = "audio.wav") -> Transcript:
        self.received.append(data)
        if self.fail:
            raise VoiceTranscribeError("Voice Transcribe HTTP 500", status_code=500)
        return Transcript(text=self.text, language="English", duration_s=1.0)


def openfda_rows(endpoint: str, search: str) -> list[dict[str, Any]]:
    row = {
        "k_number": "K990001",
        "applicant": "Fictional Devices Test Co.",
        "device_name": "DemoScan AI Viewer",
        "product_code": "QIH",
        "decision_date": "2026-01-02",
    }
    if endpoint == "510k":
        return [row]
    if endpoint == "classification":
        return [{"product_code": "QIH", "device_name": "Radiological CAD", "device_class": "2"}]
    return []


class Env:
    """One app under test with its fakes, so a test can look at what the fakes received."""

    def __init__(
        self,
        tmp_path: Path,
        *,
        live: bool = True,
        config: LiveConfig | None = None,
        spark: RecordingSpark | None = None,
        transcriber: FakeTranscriber | None = None,
        searcher: FakeSearcher | None = None,
        state: ConnectorState | None = None,
        origins: tuple[str, ...] = (ORIGIN,),
        store: Any = None,
        fetcher: Any = None,
        mentions_dir: Path | None = None,
    ) -> None:
        self.clock = Clock()
        self.spark = spark or RecordingSpark()
        self.label_spark = FakeClient([label_payload() for _ in range(8)])
        self.transcriber = transcriber or FakeTranscriber()
        self.searcher = searcher or FakeSearcher(openfda_rows)
        self.sam_seen: list[dict[str, Any]] = []
        self.store = store if store is not None else MemoryStore()
        self.live_on = live
        self.state = state or ConnectorState()

        def agent_factory(_deadline: float, _clock: Callable[[], float]) -> AgentFactory:
            def factory(d: ConnectorData, guard: SpendGuard) -> CopilotAgent:
                return CopilotAgent(guard.wrap(self.spark), d.tool_context())

            return factory

        self.backends = LiveBackends(
            live_enabled=lambda: self.live_on,
            agent_factory=agent_factory,
            transcriber=lambda _t: self.transcriber,
            spark_client=lambda _d, _c: self.label_spark,
            sam=lambda _t: SamClient(
                "k", transport=sam_transport({"label": LABEL_BOX}, self.sam_seen)
            ),
            searcher=lambda _t: self.searcher,
            clock=lambda: self.clock.mono,
            sleep=lambda _s: None,
        )
        if fetcher is not None:
            self.backends.mentions_fetcher = lambda: fetcher
        self.backends.mentions_dir = mentions_dir or (tmp_path / "no-mentions")
        settings = Settings(
            keys=KeyStore.from_env({"MAUDESIGNAL_API_KEYS": KEY}),
            limiter=RateLimiter(100),
            data=ConnectorData(work_dir=tmp_path / "work"),
            live_checker=fake_check,
            now=self.clock.wall,
            state=self.state,
            web_origins=origins,
            feedback_store=self.store,
            live=self.backends,
            live_config=config or LiveConfig(daily_usd=3.0, burst_per_min=1000),
        )
        self.client = TestClient(create_app(settings), raise_server_exceptions=False)

    def ask(self, question: str = QUESTION, **extra: Any) -> Any:
        return self.client.post(PATH_ASK, json={"question": question, **extra})

    def voice(self, wav: bytes | None = None, meta: dict[str, Any] | None = None) -> Any:
        files: dict[str, Any] = {
            "audio": ("q.wav", make_wav() if wav is None else wav, "audio/wav")
        }
        if meta is not None:
            files["meta"] = (None, json.dumps(meta), "application/json")
        return self.client.post(PATH_VOICE, files=files)

    def label(self, image: bytes | None = None, ctype: str = "image/png") -> Any:
        data = image if image is not None else LABEL_PNG.read_bytes()
        return self.client.post(PATH_LABEL, files={"image": ("l.png", data, ctype)})


def make_wav(seconds: float = 1.0, rate: int = 16000, channels: int = 1, width: int = 2) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(width)
        w.setframerate(rate)
        w.writeframes(
            b"\x01\x00" * channels * int(seconds * rate)
            if width == 2
            else b"\x01" * int(seconds * rate)
        )
    return buf.getvalue()


def jpeg_with_exif(size: tuple[int, int] = (900, 600), orientation: int = 1) -> bytes:
    img = Image.new("RGB", size, (200, 200, 200))
    exif = Image.Exif()
    exif[0x010F] = "SECRETCAM"  # camera make
    exif[0x0110] = "MODEL-SECRET-9"
    exif[0x0112] = orientation
    exif.get_ifd(0x8825)[1] = "N"  # a GPS block
    buf = io.BytesIO()
    img.save(buf, format="JPEG", exif=exif.tobytes())
    return buf.getvalue()


def assert_contract(body: dict[str, Any]) -> None:
    """Fields every live response shares."""
    assert body["mode"] in ("live", "recorded")
    assert body["not_medical_advice"] is True
    assert (body["mode"] == "recorded") == ("recorded_note" in body)
    assert body["cost_usd"] is None or isinstance(body["cost_usd"], int | float)
    lim = body["limits"]
    assert isinstance(lim["remaining_today"], int) and lim["resets_utc"].endswith("Z")
    assert body["trace"], "every response has a trace"
    for step in body["trace"]:
        assert step["model"] in MODELS and isinstance(step["ms"], int) and step["ms"] >= 0
        assert step["status"] in ("ok", "skipped", "failed") and step["step"]
    assert forbidden_in(json.dumps(body)) == []


def assert_answer(body: dict[str, Any]) -> None:
    a = body["answer"]
    assert a["spoken_text"].strip() and a["speakable"]
    for s in a["speakable"]:
        assert s["text"].strip()
        for lk in s["links"]:
            assert lk["url"].startswith("https://") and lk["label"]
    for w in a["withheld"]:
        assert set(w) == {"reason"}  # a left-out sentence's text is never returned


# --- ask -----------------------------------------------------------------------------------


def test_live_ask_contract_gate_and_trace(tmp_path: Path) -> None:
    env = Env(tmp_path)
    r = env.ask()
    assert r.status_code == 200, r.text
    body = r.json()
    assert_contract(body)
    assert_answer(body)
    assert body["mode"] == "live" and "recorded_note" not in body
    assert body["cost_usd"] and body["cost_usd"] > 0
    assert body["answer"]["speakable"][0]["links"], "a spoken sentence has a link"
    assert len(body["answer"]["withheld"]) == 1  # the 99-report sentence the gate blocked
    assert "99" not in json.dumps(body["answer"])
    models = [s["model"] for s in body["trace"]]
    assert "muse-spark-1.3" in models
    assert body["limits"]["remaining_today"] == 29  # 30 a day by default, one used
    assert body["limits"]["resets_utc"] == "2026-10-31T00:00:00Z"
    assert len(env.spark.requests) >= 1 and all(q["temperature"] == 0.0 for q in env.spark.requests)


def test_ask_history_is_context_and_answers_are_cut_to_600(tmp_path: Path) -> None:
    env = Env(tmp_path)
    hist = [{"question": "Earlier question about QIH?", "answer": "A" * 900}]
    r = env.ask("And what about LLZ?", history=hist)
    assert r.status_code == 200 and r.json()["mode"] == "live"
    msgs = env.spark.requests[0]["messages"]
    assistant = [m for m in msgs if m["role"] == "assistant"]
    assert assistant and assistant[0]["content"] == "A" * 600
    users = [m["content"] for m in msgs if m["role"] == "user"]
    assert users[0] == "Earlier question about QIH?" and "LLZ" in users[1]
    assert any(m["content"] == "Earlier question about QIH?" for m in msgs)


def test_ask_product_code_is_added_to_a_question_without_one(tmp_path: Path) -> None:
    env = Env(tmp_path)
    assert env.ask("What changed this week?", product_code="qih").status_code == 200
    users = [m["content"] for m in env.spark.requests[0]["messages"] if m["role"] == "user"]
    assert users[0].endswith("(device type QIH)")


def test_ask_without_a_model_key_gives_a_labelled_recording(tmp_path: Path) -> None:
    env = Env(tmp_path, live=False)
    body = env.ask().json()
    assert_contract(body)
    assert body["mode"] == "recorded"
    assert (
        "No live model key" in body["recorded_note"] or "not switched on" in body["recorded_note"]
    )
    assert "What changed this week" in body["recorded_note"]  # the recorded question is named
    assert "recorded answer" in body["answer"]["spoken_text"]
    assert env.spark.requests == [], "no model call without a key"
    assert body["cost_usd"] is None


def test_ask_model_error_falls_back_and_never_shows_a_fake_live_answer(tmp_path: Path) -> None:
    env = Env(tmp_path)

    def boom(**_: Any) -> Any:
        raise RuntimeError(f"upstream said bad key {KEY}")

    env.spark.chat.completions.create = boom  # type: ignore[assignment]
    r = env.ask()
    body = r.json()
    assert r.status_code == 200 and body["mode"] == "recorded"
    assert "failed" in body["recorded_note"] and KEY not in r.text
    assert body["trace"][0]["status"] == "failed"


def test_global_cost_cap_gives_recorded_and_no_model_call(tmp_path: Path) -> None:
    # An empty ledger lets the first answer through; once the day's counted total leaves no
    # room for one more call's worst case, the next request is answered from a recording.
    from tests.unit.test_connector_batch_o import FakeBlobStore

    one_call = json.dumps(
        {
            "sentences": [
                {"text": "LLZ had 33 reports from August 25 to August 31, 2026.", "claims": [GOOD]}
            ]
        }
    )
    store = FakeBlobStore()
    env = Env(
        tmp_path,
        spark=RecordingSpark(one_call),
        store=store,
        config=LiveConfig(daily_usd=3.0, burst_per_min=99),
    )
    first = env.ask().json()
    assert first["mode"] == "live"
    calls = len(env.spark.requests)
    store.seed_ledger(2.89, NOW.date())  # the Env clock's day; the enforced cap is 2.90
    second = env.ask().json()
    assert second["mode"] == "recorded" and "cost cap" in second["recorded_note"]
    assert len(env.spark.requests) == calls, "no live call once the cap is reached"
    assert second["trace"][0]["status"] == "skipped"


def test_request_cap_is_checked_per_call(tmp_path: Path) -> None:
    env = Env(tmp_path, config=LiveConfig(ask_usd=0.0, burst_per_min=99))
    body = env.ask().json()
    assert body["mode"] == "recorded"  # a request budget of 0 never starts a call


def test_live_config_reads_the_environment_and_keeps_defaults_for_bad_values() -> None:
    assert LiveConfig.from_env({}).daily_usd == 3.0 and LiveConfig.from_env({}).ask_per_day == 30
    env = {
        "MAUDESIGNAL_LIVE_DAILY_USD": "5",
        "MAUDESIGNAL_LIVE_ASK_PER_DAY": "7",
        "MAUDESIGNAL_LIVE_VOICE_PER_DAY": "x",
        "MAUDESIGNAL_LIVE_LABEL_PER_DAY": "-2",
    }
    got = LiveConfig.from_env(env)
    assert (got.daily_usd, got.ask_per_day) == (5.0, 7)
    assert (got.voice_per_day, got.label_per_day) == (10, 5)  # invalid values keep defaults


def test_shared_ledger_and_counters_when_upstash_is_configured(tmp_path: Path) -> None:
    fake = FakeRedis()
    env = Env(tmp_path, state=make_state(fake), config=LiveConfig(ask_per_day=2, burst_per_min=99))
    assert env.ask().json()["mode"] == "live"
    assert env.ask().json()["mode"] == "live"
    assert env.ask().status_code == 429  # the daily count lives in Redis
    keys = list(fake.kv)
    assert any(":daily:live-ask:" in k for k in keys)
    assert not any("live-global" in k for k in keys), "no global ledger in Redis"
    assert not any("testclient" in k for k in keys), "the raw address is never a Redis key"


def test_per_ip_daily_limit_resets_at_utc_midnight(tmp_path: Path, monkeypatch: Any) -> None:
    monkeypatch.setenv("MAUDESIGNAL_TRUST_FORWARDED", "1")
    env = Env(tmp_path, live=False, config=LiveConfig(ask_per_day=2, burst_per_min=99))
    a = {"X-Forwarded-For": "203.0.113.7"}
    b = {"X-Forwarded-For": "203.0.113.8"}

    def go(h: dict[str, str]) -> Any:
        return env.client.post(PATH_ASK, json={"question": QUESTION}, headers=h)

    assert go(a).status_code == 200
    second = go(a)
    assert second.status_code == 200 and second.json()["limits"]["remaining_today"] == 0
    third = go(a)
    assert third.status_code == 429
    body = third.json()
    assert body["code"] == "rate_limited" and body["retry_after_s"] == 12 * 3600
    assert third.headers["retry-after"] == str(12 * 3600)
    assert go(b).status_code == 200, "another address has its own count"
    env.clock.now = NOW + timedelta(hours=13)  # past midnight UTC
    assert go(a).status_code == 200


def test_burst_limit_per_minute(tmp_path: Path) -> None:
    env = Env(tmp_path, live=False, config=LiveConfig(burst_per_min=2))
    assert env.ask().status_code == 200 and env.ask().status_code == 200
    r = env.ask()
    assert r.status_code == 429 and r.json()["code"] == "rate_limited"
    assert r.json()["retry_after_s"] >= 1


def test_the_address_is_only_a_peppered_hash(tmp_path: Path, monkeypatch: Any) -> None:
    monkeypatch.setenv("MAUDESIGNAL_TRUST_FORWARDED", "1")
    seen: list[str] = []
    real = DailyCounter.hit

    def spy(self: DailyCounter, who: str) -> tuple[bool, int]:
        seen.append(who)
        return real(self, who)

    monkeypatch.setattr(DailyCounter, "hit", spy)
    env = Env(tmp_path, live=False)
    env.client.post(
        PATH_ASK, json={"question": QUESTION}, headers={"X-Forwarded-For": "198.51.100.23"}
    )
    assert seen and all(s.startswith("live:") and "198.51.100.23" not in s for s in seen)


def test_requests_are_logged_without_address_text_or_bytes(
    tmp_path: Path, monkeypatch: Any
) -> None:
    events: list[tuple[str, dict[str, Any]]] = []

    class Spy:
        def info(self, event: str, **kw: Any) -> None:
            events.append((event, kw))

        warning = error = info

    monkeypatch.setattr(live_module, "logger", Spy())
    monkeypatch.setenv("MAUDESIGNAL_TRUST_FORWARDED", "1")
    env = Env(tmp_path)
    env.client.post(
        PATH_ASK,
        json={"question": "UNIQUE-QUESTION-TEXT about LLZ?"},
        headers={"X-Forwarded-For": "198.51.100.23"},
    )
    env.voice(make_wav())
    env.label()
    assert {e for e, _ in events} >= {"live_request"}
    dump = json.dumps(events, default=str)
    assert "198.51.100.23" not in dump and "UNIQUE-QUESTION-TEXT" not in dump
    assert "testclient" not in dump and "What changed this week" not in dump


# --- patient data, input shape -------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "Patient jane.doe@example.com had a problem with LLZ",
        "Call 555-123-4567 about LLZ reports",
        "MRN 8837261 had an LLZ event",
        "Born 1961-04-02 and the LLZ device failed",
        "Mrs. Jane Smith, age 67, died after LLZ",
        "A 67-year-old had an LLZ event",
        "LLZ event in a 71 y/o",
    ],
)
def test_patient_data_in_a_question_is_refused(tmp_path: Path, text: str) -> None:
    env = Env(tmp_path)
    r = env.ask(text)
    assert r.status_code == 422 and r.json()["code"] == "patient_data"
    assert env.spark.requests == []


def test_ordinary_device_questions_are_not_mistaken_for_patient_data(tmp_path: Path) -> None:
    env = Env(tmp_path)
    for q in (QUESTION, "Show recalls for QIH since January"):
        assert env.ask(q).status_code == 200


def test_patient_data_in_history_is_refused(tmp_path: Path) -> None:
    env = Env(tmp_path)
    r = env.ask(QUESTION, history=[{"question": "Fine?", "answer": "Call 555-123-4567"}])
    assert r.status_code == 422 and r.json()["code"] == "patient_data"


@pytest.mark.parametrize(
    "body",
    [
        {"question": 5},
        {"question": "hi"},
        {"question": "x" * 501},
        {"question": QUESTION, "extra": 1},
        {"question": QUESTION, "product_code": "TOOLONG"},
        {"question": QUESTION, "history": [{"question": "q", "answer": "a"}] * 5},
        {"question": QUESTION, "history": "nope"},
        {"question": QUESTION, "history": [{"question": 1, "answer": "a"}]},
        ["not", "an", "object"],
        None,
    ],
)
def test_ask_wrong_shapes_are_422(tmp_path: Path, body: Any) -> None:
    env = Env(tmp_path)
    r = env.client.post(PATH_ASK, json=body)
    assert r.status_code == 422 and r.json()["code"] == "invalid_input"
    assert env.spark.requests == []


def test_ask_not_json_is_422_and_oversize_is_413(tmp_path: Path) -> None:
    env = Env(tmp_path)
    r = env.client.post(PATH_ASK, content=b"{nope", headers={"content-type": "application/json"})
    assert r.status_code == 422 and r.json()["code"] == "invalid_input"
    big = env.client.post(PATH_ASK, json={"question": "x" * 70_000})
    assert big.status_code == 413
    # no content-length (chunked): the stream itself is capped
    chunks = (b"x" * 10_000 for _ in range(10))
    chunked = env.client.post(
        PATH_ASK, content=chunks, headers={"content-type": "application/json"}
    )
    assert chunked.status_code == 413
    assert env.spark.requests == []


def test_invalid_requests_do_not_use_the_daily_count(tmp_path: Path) -> None:
    env = Env(tmp_path, live=False, config=LiveConfig(ask_per_day=1, burst_per_min=99))
    assert env.client.post(PATH_ASK, json={"question": 5}).status_code == 422
    assert env.ask().status_code == 200


# --- uploads: audio ----------------------------------------------------------------------------


def test_voice_live_shows_what_was_heard_and_answers_through_the_gate(tmp_path: Path) -> None:
    env = Env(tmp_path)
    wav = make_wav(2.0)
    r = env.voice(wav, meta={"product_code": "llz"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert_contract(body)
    assert_answer(body)
    assert body["mode"] == "live" and body["heard"] == "What changed this week for LLZ?"
    assert env.transcriber.received == [wav], "the clip goes to the transcriber, nothing else"
    models = [s["model"] for s in body["trace"]]
    assert models[0] == "muse-voice-transcribe-1.0" and "muse-spark-1.3" in models
    assert body["cost_usd"] > 0
    assert "99" not in json.dumps(body["answer"])
    # the audio never reaches the chat model
    assert all("audio" not in json.dumps(q["messages"]).lower() for q in env.spark.requests)
    assert body["limits"]["remaining_today"] == 9  # 10 voice questions a day


def _slow_voice_env(
    tmp_path: Path, transcribe_s: float, spark_s: float, real_deadline: bool = True
) -> Env:
    """Voice app whose fake transcriber and fake Spark advance the fake clock."""
    from maudesignal.connector.live import DeadlineClient

    env = Env(tmp_path)
    clock = env.clock
    inner_transcriber = env.transcriber
    spark = env.spark

    class SlowTranscriber:
        def transcribe_bytes(self, data: bytes, *, filename: str = "audio.wav") -> Transcript:
            clock.advance(transcribe_s)
            return inner_transcriber.transcribe_bytes(data)

    def make_slow(timeout: float) -> Any:
        def slow_create(**kwargs: Any) -> Any:
            # like a real client: a call longer than its timeout stops at the timeout and fails
            clock.advance(min(spark_s, timeout))
            if spark_s > timeout:
                raise TimeoutError("request timed out")
            return spark._create(**kwargs)

        return SimpleNamespace(
            chat=SimpleNamespace(completions=SimpleNamespace(create=slow_create))
        )

    slow = make_slow(1e9)
    slow.with_options = lambda timeout, max_retries: make_slow(timeout)  # type: ignore[attr-defined]

    def agent_factory(deadline: float, ck: Callable[[], float]) -> AgentFactory:
        def factory(d: ConnectorData, guard: SpendGuard) -> CopilotAgent:
            client = DeadlineClient(slow, deadline, ck) if real_deadline else slow
            return CopilotAgent(guard.wrap(client), d.tool_context())

        return factory

    env.backends.transcriber = lambda _t: SlowTranscriber()  # type: ignore[assignment,return-value]
    env.backends.agent_factory = agent_factory
    return env


def test_voice_slow_transcription_and_slow_spark_end_recorded_inside_the_vercel_limit(
    tmp_path: Path,
) -> None:
    # transcription takes its 15 s, then every Spark call takes 24 s: before the single request
    # deadline this took 63 s of fake time; now the answer is recorded, with a note, under 55 s.
    env = _slow_voice_env(tmp_path, transcribe_s=15, spark_s=24)
    started = env.clock.mono
    body = env.voice().json()
    assert env.clock.mono - started < 55
    assert_contract(body)
    assert body["mode"] == "recorded" and body["recorded_note"]
    assert body["heard"] == "What changed this week for LLZ?" or "heard" not in body


def test_voice_with_no_time_left_after_transcription_skips_spark(tmp_path: Path) -> None:
    env = _slow_voice_env(tmp_path, transcribe_s=50, spark_s=1)
    started = env.clock.mono
    body = env.voice().json()
    assert env.clock.mono - started < 55
    assert_contract(body)
    assert body["mode"] == "recorded" and "time limit" in body["recorded_note"]
    assert env.spark.requests == [], "no Spark call starts with under 3 s left"
    assert body["heard"] == "What changed this week for LLZ?"
    assert any(s["status"] == "skipped" and s["model"] == "muse-spark-1.3" for s in body["trace"])
    assert_answer(body)


def test_voice_fast_path_still_answers_live_with_the_remaining_time(tmp_path: Path) -> None:
    env = _slow_voice_env(tmp_path, transcribe_s=3, spark_s=2)
    body = env.voice().json()
    assert body["mode"] == "live" and body["heard"]


def test_voice_without_a_key_returns_a_recorded_voice_run(tmp_path: Path) -> None:
    env = Env(tmp_path, live=False)
    body = env.voice().json()
    assert_contract(body)
    assert_answer(body)
    assert body["mode"] == "recorded" and "heard" not in body
    assert "recorded run" in body["recorded_note"]
    assert "recorded answer" in body["answer"]["spoken_text"]
    assert env.transcriber.received == [], "no transcription without a key"
    assert body["trace"][0]["status"] == "skipped"


def test_voice_transcription_failure_returns_the_recorded_voice_run(tmp_path: Path) -> None:
    env = Env(tmp_path, transcriber=FakeTranscriber(fail=True))
    body = env.voice().json()
    assert_contract(body)
    assert body["mode"] == "recorded" and "heard" not in body
    assert "could not be turned into text" in body["answer"]["spoken_text"]
    assert body["trace"][0]["status"] == "failed" and "HTTP 500" not in json.dumps(body)


def test_voice_transcript_with_patient_data_is_refused_and_not_echoed(tmp_path: Path) -> None:
    env = Env(tmp_path, transcriber=FakeTranscriber("Her MRN 4482910 and the LLZ failed"))
    r = env.voice()
    assert r.status_code == 422 and r.json()["code"] == "patient_data"
    assert "4482910" not in r.text and env.spark.requests == []


def test_voice_empty_transcript_is_422(tmp_path: Path) -> None:
    env = Env(tmp_path, transcriber=FakeTranscriber("   "))
    r = env.voice()
    assert r.status_code == 422 and r.json()["code"] == "invalid_input"


def test_voice_daily_limit(tmp_path: Path) -> None:
    env = Env(tmp_path, live=False, config=LiveConfig(voice_per_day=1, burst_per_min=99))
    assert env.voice().status_code == 200
    assert env.voice().status_code == 429


@pytest.mark.parametrize(
    ("wav", "status"),
    [
        (b"", 422),
        (b"this is not a wav file", 422),
        (make_wav(rate=24000), 422),  # right type, wrong rate
        (make_wav(channels=2), 422),
        (make_wav(width=1), 422),
        (make_wav(seconds=61), 422),  # over 60 s
        (b"RIFF" + b"\x00" * 100, 422),
        (make_wav(seconds=132), 413),  # 4.22 MB: over 4 MiB
    ],
    ids=["empty", "text", "24k", "stereo", "8bit", "61s", "riff-stub", "over-4mb"],
)
def test_audio_is_checked_before_any_model_call(tmp_path: Path, wav: bytes, status: int) -> None:
    env = Env(tmp_path)
    r = env.voice(wav)
    assert r.status_code == status, r.text
    assert r.json()["code"] in ("invalid_input", "too_large")
    assert env.transcriber.received == [] and env.spark.requests == []


def test_a_60_second_clip_is_accepted() -> None:
    assert check_audio(make_wav(60.0)) == pytest.approx(60.0)
    with pytest.raises(UploadError) as e:
        check_audio(make_wav(60.5))
    assert e.value.status == 422


def test_voice_wrong_request_types_are_422(tmp_path: Path) -> None:
    env = Env(tmp_path)
    r1 = env.client.post(PATH_VOICE, json={"audio": "x"})
    r2 = env.client.post(PATH_VOICE, files={"other": ("x.txt", b"hi", "text/plain")})
    r3 = env.client.post(
        PATH_VOICE,
        content=b"--b\r\nbroken",
        headers={"content-type": "multipart/form-data; boundary=b"},
    )
    r4 = env.client.post(PATH_VOICE, content=b"x", headers={"content-type": "multipart/form-data"})
    assert [r.status_code for r in (r1, r2, r3, r4)] == [422, 422, 422, 422]
    bad_meta = env.client.post(
        PATH_VOICE,
        files={"audio": ("a.wav", make_wav(), "audio/wav"), "meta": (None, "{nope", "text/plain")},
    )
    assert bad_meta.status_code == 422
    bad_meta2 = env.voice(meta={"history": "x"})
    assert bad_meta2.status_code == 422
    assert env.transcriber.received == []


def test_voice_oversize_request_is_413_before_reading(tmp_path: Path) -> None:
    env = Env(tmp_path)
    r = env.client.post(
        PATH_VOICE, files={"audio": ("a.wav", b"\x00" * (5 * 1024 * 1024), "audio/wav")}
    )
    assert r.status_code == 413 and r.json()["code"] == "too_large"


# --- uploads: image --------------------------------------------------------------------------


def test_exif_is_really_removed_before_any_model_sees_the_photo(tmp_path: Path) -> None:
    original = jpeg_with_exif()
    assert b"SECRETCAM" in original and b"Exif" in original
    env = Env(tmp_path)
    r = env.label(original, "image/jpeg")
    assert r.status_code == 200, r.text
    assert env.sam_seen, "SAM received the photo"
    for seen in env.sam_seen:
        url = seen["body"]["input"][0]["content"][1]["image_url"]
        raw = base64.b64decode(url.split(",", 1)[1])
        assert b"Exif" not in raw and b"SECRETCAM" not in raw and b"MODEL-SECRET" not in raw
        assert not Image.open(io.BytesIO(raw)).getexif()
    for call in env.label_spark.calls:
        for part in call["messages"][1]["content"]:
            if part.get("type") == "image_url":
                raw = base64.b64decode(part["image_url"]["url"].split(",", 1)[1])
                assert b"SECRETCAM" not in raw and b"Exif" not in raw
    assert "SECRETCAM" not in r.text


def test_clean_image_drops_metadata_and_keeps_the_photo_upright() -> None:
    cleaned, size = clean_image(jpeg_with_exif((200, 100)), "image/jpeg")
    img = Image.open(io.BytesIO(cleaned))
    assert img.format == "JPEG" and not img.getexif() and "exif" not in img.info
    assert "icc_profile" not in img.info and size == (200, 100)
    assert b"SECRETCAM" not in cleaned and b"Exif" not in cleaned


def test_clean_image_orientation_rotates_a_wide_photo() -> None:
    cleaned, size = clean_image(jpeg_with_exif((200, 100), orientation=6), "image/jpeg")
    assert size == (100, 200) and Image.open(io.BytesIO(cleaned)).size == (100, 200)


def test_png_is_accepted_and_reencoded_as_jpeg() -> None:
    cleaned, _ = clean_image(LABEL_PNG.read_bytes(), "image/png")
    assert cleaned.startswith(b"\xff\xd8\xff")


@pytest.mark.parametrize(
    ("data", "ctype", "status"),
    [
        (b"", "image/jpeg", 422),
        (b"GIF89a" + b"\x00" * 50, "image/gif", 422),
        (b"hello this is text", "image/jpeg", 422),  # right claim, wrong bytes
        (jpeg_with_exif()[:200], "image/jpeg", 422),  # truncated
        (jpeg_with_exif(), "text/plain", 422),
        (jpeg_with_exif(), "image/webp", 422),
        (b"\xff\xd8\xff" + b"\x00" * (4 * 1024 * 1024 + 10), "image/jpeg", 413),
    ],
    ids=["empty", "gif", "text-as-jpeg", "truncated", "text-type", "webp-type", "over-4mb"],
)
def test_images_are_checked_before_any_model_call(
    tmp_path: Path, data: bytes, ctype: str, status: int
) -> None:
    env = Env(tmp_path)
    r = env.label(data, ctype)
    assert r.status_code == status, r.text
    assert env.sam_seen == [] and env.label_spark.calls == []


def test_too_many_pixels_and_tiny_images_are_refused() -> None:
    big = io.BytesIO()
    Image.new("L", (7000, 7000)).save(big, format="PNG")  # 49 MP of flat grey, small file
    with pytest.raises(UploadError) as e:
        clean_image(big.getvalue(), "image/png")
    assert e.value.status == 413
    tiny = io.BytesIO()
    Image.new("RGB", (8, 8)).save(tiny, format="PNG")
    with pytest.raises(UploadError) as e2:
        clean_image(tiny.getvalue(), "image/png")
    assert e2.value.status == 422


def test_label_missing_part_and_oversize_request(tmp_path: Path) -> None:
    env = Env(tmp_path)
    assert (
        env.client.post(PATH_LABEL, files={"photo": ("x.png", b"x", "image/png")}).status_code
        == 422
    )
    big = env.client.post(
        PATH_LABEL,
        files={"image": ("x.jpg", b"\xff\xd8\xff" + b"0" * (9 * 1024 * 1024), "image/jpeg")},
    )
    assert big.status_code == 413


# --- label ----------------------------------------------------------------------------------


def test_label_live_reading_matches_and_trace(tmp_path: Path) -> None:
    env = Env(tmp_path)
    r = env.label()
    assert r.status_code == 200, r.text
    body = r.json()
    assert_contract(body)
    assert body["mode"] == "live" and body["confirmed"] is None
    fields = body["reading"]["fields"]
    assert set(fields) == {"device_name", "manufacturer", "model", "k_number", "udi", "gtin"}
    assert fields["device_name"]["value"] == "DemoScan AI Viewer"
    assert fields["model"]["value"] == "DSV-100"
    m = body["matches"]
    assert m["status"] == "needs_person_to_confirm" and 1 <= len(m["candidates"]) <= 3
    c = m["candidates"][0]
    assert c["k_number"] == "K990001" and c["product_code"] == "QIH"
    assert c["why_matched"] and isinstance(c["why_not_matched"], list)
    assert all(lk["url"].startswith("https://") for lk in c["links"]) and c["links"]
    steps = {s["step"]: s for s in body["trace"]}
    assert steps["SAM 3.1 crop"]["model"] == "sam-3.1"
    assert steps["Muse Spark read"]["model"] == "muse-spark-1.3"
    assert steps["Re-encode photo, drop metadata"]["model"] is None
    assert body["cost_usd"] > 0 and body["limits"]["remaining_today"] == 4  # 5 labels a day


def test_label_never_returns_lot_or_serial(tmp_path: Path) -> None:
    env = Env(tmp_path)
    body = env.label().json()
    text = json.dumps(body)
    assert "TESTLOT1" not in text, "the lot printed on the label is never returned"
    assert "lot" not in body["reading"]["fields"] and "serial" not in body["reading"]["fields"]
    assert body["reading"]["values_withheld"] == ["lot"]
    assert fields_udi(body) == "(01)00812345678901(17)270101"


def fields_udi(body: dict[str, Any]) -> str:
    return str(body["reading"]["fields"]["udi"]["value"])


def test_label_with_no_match_says_so(tmp_path: Path) -> None:
    env = Env(tmp_path, searcher=FakeSearcher(lambda e, s: []))
    body = env.label().json()
    assert body["mode"] == "live" and body["matches"] == {
        "status": "no_match_found",
        "candidates": [],
    }


def test_label_openfda_failure_is_reported_in_the_trace(tmp_path: Path) -> None:
    env = Env(
        tmp_path,
        searcher=FakeSearcher(
            openfda_rows, fail={"510k", "udi", "classification", "registrationlisting", "recall"}
        ),
    )
    body = env.label().json()
    assert body["mode"] == "live" and body["matches"]["status"] == "no_match_found"
    assert body["matches"]["search_failed"] is True
    assert "could not be searched" in body["matches"]["note"]
    step = next(s for s in body["trace"] if s["step"].startswith("openFDA"))
    assert step["status"] == "failed"


def test_label_openfda_past_deadline_is_reported_as_not_searched(tmp_path: Path) -> None:
    env = Env(tmp_path)
    inner = env.searcher

    class Slow:
        def query(self, endpoint: str, search: str, **kw: Any) -> Any:
            env.clock.advance(46)  # the first call uses the whole openFDA window
            raise TimeoutError("slow")

    env.backends.searcher = lambda _t: Slow()  # type: ignore[assignment,return-value]
    body = env.label().json()
    assert body["mode"] == "live" and inner is not None
    assert body["matches"]["search_failed"] is True and body["matches"]["note"]


def test_label_a_real_search_that_finds_nothing_is_not_marked_failed(tmp_path: Path) -> None:
    env = Env(tmp_path, searcher=FakeSearcher(lambda e, s: []))
    body = env.label().json()
    assert body["matches"]["status"] == "no_match_found" and "search_failed" not in body["matches"]


def test_a_dripping_openfda_call_is_cut_at_the_wall_clock_limit(monkeypatch: Any) -> None:
    import time

    from maudesignal.common.exceptions import OpenFDAUnavailableError
    from maudesignal.connector import live
    from maudesignal.connector.live import _DeadlineSearcher

    monkeypatch.setattr(live, "OPENFDA_CALL_WALL_S", 0.2)

    class Drip:
        def query(self, endpoint: str, search: str, **kw: Any) -> Any:
            time.sleep(1.0)

    started = time.monotonic()
    with pytest.raises(OpenFDAUnavailableError):
        _DeadlineSearcher(Drip(), 1e12, lambda: 0.0).query("510k", "x", limit=1)  # type: ignore[arg-type]
    assert time.monotonic() - started < 0.8


def test_missing_pepper_with_shared_state_logs_a_warning(tmp_path: Path, monkeypatch: Any) -> None:
    from maudesignal.connector import live

    seen: list[str] = []
    monkeypatch.setattr(
        live.logger, "warning", lambda event, **kw: seen.append(event), raising=False
    )

    class SharedState(ConnectorState):
        @property
        def shared(self) -> bool:
            return True

    Env(tmp_path, state=SharedState())
    assert "live_pepper_missing" in seen
    seen.clear()
    Env(tmp_path)  # not shared: nothing to warn about
    assert "live_pepper_missing" not in seen


def test_label_without_a_key_returns_a_stored_run_labelled_recorded(tmp_path: Path) -> None:
    env = Env(tmp_path, live=False)
    body = env.label().json()
    assert_contract(body)
    assert body["mode"] == "recorded" and "not your photo" in body["recorded_note"]
    assert body["confirmed"] is None and "image_file" not in body
    assert env.sam_seen == [] and env.label_spark.calls == []
    assert body["trace"][1]["status"] == "skipped"
    assert body["matches"]["status"] in ("needs_person_to_confirm", "no_match_found")
    assert body["matches"]["candidates"], "a stored match result with candidates is shown"


def test_label_model_failure_falls_back_to_the_stored_run(tmp_path: Path) -> None:
    env = Env(tmp_path)
    env.label_spark = FakeClient([RuntimeError("secret upstream detail")])
    body = env.label().json()
    assert body["mode"] == "recorded" and "secret upstream detail" not in json.dumps(body)
    assert body["trace"][-1]["status"] == "failed"


def test_label_timeout_ends_within_budget_and_says_so(tmp_path: Path) -> None:
    env = Env(tmp_path)
    started = env.clock.mono

    def slow(**_: Any) -> Any:
        env.clock.advance(52)  # the Spark call used the whole budget, then timed out
        raise TimeoutError("budget")

    env.label_spark = SimpleNamespace(  # type: ignore[assignment]
        chat=SimpleNamespace(completions=SimpleNamespace(create=slow))
    )
    env.backends.spark_client = lambda _d, _c: env.label_spark
    body = env.label().json()
    assert body["mode"] == "recorded" and "longer than the time limit" in body["recorded_note"]
    assert env.clock.mono - started < 55


def test_label_slow_openfda_stops_at_the_deadline(tmp_path: Path) -> None:
    env = Env(tmp_path)
    started = env.clock.mono
    inner = env.searcher

    class Slow:
        def query(self, endpoint: str, search: str, **kw: Any) -> Any:
            env.clock.advance(6)  # every openFDA call "takes" its full 6 s timeout
            return inner.query(endpoint, search, **kw)

    env.backends.searcher = lambda _t: Slow()  # type: ignore[assignment,return-value]
    body = env.label().json()
    assert body["mode"] == "live"
    assert env.clock.mono - started < 55, "no openFDA query starts after the deadline"
    assert any(s["step"].startswith("openFDA") for s in body["trace"])


def test_deadline_wrappers_refuse_new_work_after_the_deadline() -> None:
    from maudesignal.common.exceptions import OpenFDAUnavailableError
    from maudesignal.connector.live import _DeadlineSam, _DeadlineSearcher
    from maudesignal.vision.sam import SamError

    t = {"now": 0.0}
    inner = FakeSearcher(openfda_rows)
    searcher = _DeadlineSearcher(inner, 10.0, lambda: t["now"])
    assert searcher.query("510k", "k_number:K1", limit=1)
    t["now"] = 11.0
    with pytest.raises(OpenFDAUnavailableError):
        searcher.query("510k", "k_number:K1", limit=1)
    assert len(inner.calls) == 1
    sam = _DeadlineSam(SamClient("k", transport=sam_transport({})), 10.0, lambda: t["now"])
    with pytest.raises(SamError):
        sam.segment(None, "label")  # type: ignore[arg-type]


def test_label_daily_limit(tmp_path: Path) -> None:
    env = Env(tmp_path, live=False, config=LiveConfig(label_per_day=1, burst_per_min=99))
    assert env.label().status_code == 200
    assert env.label().status_code == 429


# --- CORS, headers, storage -------------------------------------------------------------------


def test_cors_allowed_origin_preflight_and_post(tmp_path: Path) -> None:
    env = Env(tmp_path, live=False)
    for path in (PATH_ASK, PATH_VOICE, PATH_LABEL):
        pre = env.client.options(
            path,
            headers={"Origin": ORIGIN, "Access-Control-Request-Method": "POST"},
        )
        assert pre.status_code == 204
        assert pre.headers["access-control-allow-origin"] == ORIGIN
        assert pre.headers["access-control-allow-methods"] == "POST, OPTIONS"
        assert pre.headers["access-control-allow-headers"] == "Content-Type"
        assert "access-control-allow-credentials" not in pre.headers
    post = env.client.post(PATH_ASK, json={"question": QUESTION}, headers={"Origin": ORIGIN})
    assert post.status_code == 200
    assert post.headers["access-control-allow-origin"] == ORIGIN
    assert "access-control-allow-credentials" not in post.headers
    assert post.headers["vary"] == "Origin" and post.headers["cache-control"] == "no-store"


def test_cors_denied_origin_is_refused_and_gets_no_headers(tmp_path: Path) -> None:
    env = Env(tmp_path)
    evil = {"Origin": "https://evil.example.com"}
    r = env.client.post(PATH_ASK, json={"question": QUESTION}, headers=evil)
    assert r.status_code == 403 and "access-control-allow-origin" not in r.headers
    pre = env.client.options(PATH_LABEL, headers=evil | {"Access-Control-Request-Method": "POST"})
    assert pre.status_code == 204 and "access-control-allow-origin" not in pre.headers
    assert env.spark.requests == []
    none_listed = Env(tmp_path / "n", origins=())
    r2 = none_listed.client.post(PATH_ASK, json={"question": QUESTION}, headers={"Origin": ORIGIN})
    assert r2.status_code == 403
    wild = Env(tmp_path / "w", origins=("*",))  # a wildcard is not an origin
    r3 = wild.client.post(PATH_ASK, json={"question": QUESTION}, headers={"Origin": ORIGIN})
    assert r3.status_code == 403


def test_nothing_is_written_to_the_store_or_disk(tmp_path: Path, monkeypatch: Any) -> None:
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(scratch))
    env = Env(tmp_path)
    before = sorted(p.name for p in scratch.rglob("*"))
    assert env.ask().status_code == 200
    assert env.voice().status_code == 200
    assert env.label(jpeg_with_exif(), "image/jpeg").status_code == 200
    assert env.label().status_code == 200
    assert (
        env.voice(make_wav(), meta={"history": [{"question": "q1", "answer": "a1"}]}).status_code
        == 200
    )
    assert env.store.list_prefix("") == [], "no feedback, visit or live record is stored"
    assert sorted(p.name for p in scratch.rglob("*")) == before, "no temporary file was made"
    # no ledger file either: cost accounting is in memory unless Redis is configured
    assert not list((tmp_path / "work").glob("*.json"))
    # the audit trail of the copilot holds a question hash, never the text
    db_text = "".join(p.read_bytes().decode("latin-1") for p in (tmp_path / "work").glob("*.db"))
    assert "What changed this week for LLZ" not in db_text


# --- helpers ----------------------------------------------------------------------------------


def test_parse_multipart_basics() -> None:
    body = (
        b'--B\r\nContent-Disposition: form-data; name="a"; filename="x.bin"\r\n'
        b"Content-Type: application/octet-stream\r\n\r\n\x00\x01--notB\r\n"
        b'--B\r\nContent-Disposition: form-data; name="b"\r\n\r\nhello\r\n--B--\r\n'
    )
    parts = parse_multipart(body, "multipart/form-data; boundary=B")
    assert parts == {"a": ("application/octet-stream", b"\x00\x01--notB"), "b": ("", b"hello")}
    dup = body.replace(b'name="b"', b'name="a"')
    assert parse_multipart(dup, "multipart/form-data; boundary=B") is None
    assert parse_multipart(body, "application/json") is None
    assert parse_multipart(body, "multipart/form-data") is None
    assert parse_multipart(b"", "multipart/form-data; boundary=B") is None


def test_daily_counter_counts_per_id_and_per_day() -> None:
    day = {"d": NOW.date()}
    c = DailyCounter(2, today=lambda: day["d"])
    assert c.hit("a") == (True, 1) and c.hit("a") == (True, 0) and c.hit("a") == (False, 0)
    assert c.hit("b") == (True, 1)
    day["d"] = NOW.date() + timedelta(days=1)
    assert c.hit("a") == (True, 1)


def test_the_model_key_never_appears_in_any_response_or_log(
    tmp_path: Path, monkeypatch: Any
) -> None:
    secret = "meta-key-NOT-REAL-0123456789abcdef"
    monkeypatch.setenv("META_MODEL_API_KEY", secret)
    logged: list[str] = []

    class Spy:
        def info(self, event: str, **kw: Any) -> None:
            logged.append(json.dumps([event, kw], default=str))

        warning = error = info

    monkeypatch.setattr(live_module, "logger", Spy())
    env = Env(tmp_path, transcriber=FakeTranscriber(fail=True))

    def boom(**_: Any) -> Any:
        raise RuntimeError(f"401 for key {secret}")

    env.spark.chat.completions.create = boom  # type: ignore[assignment]
    env.label_spark = FakeClient([RuntimeError(f"bad {secret}")])
    env.backends.spark_client = lambda _d, _c: env.label_spark
    responses = [env.ask(), env.voice(), env.label()]
    assert all(r.status_code == 200 and r.json()["mode"] == "recorded" for r in responses)
    assert secret not in "".join(r.text for r in responses) + "".join(logged)


def test_live_routes_are_not_in_the_public_openapi_document(tmp_path: Path) -> None:
    env = Env(tmp_path)
    spec = env.client.get("/openapi.json")
    assert "/v1/live" not in spec.text


def test_errors_are_not_cached_and_keep_the_older_envelope_too(tmp_path: Path) -> None:
    env = Env(tmp_path)
    r = env.client.post(PATH_ASK, json={"question": 5})
    assert r.status_code == 422 and r.headers["cache-control"] == "no-store"
    assert r.json()["code"] == "invalid_input"
    assert r.json()["error"]["code"] == "invalid_input"


def test_live_fails_closed_without_a_shared_ledger(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Model key set, but no Upstash and no Blob store: recorded answers, no model call."""
    monkeypatch.delenv("MAUDESIGNAL_ALLOW_PER_INSTANCE_CAP", raising=False)
    env = Env(tmp_path)
    assert not env.state.has_call_ledger
    r = env.ask()
    assert r.status_code == 200 and r.json()["mode"] == "recorded"
    assert env.spark.requests == [], "the model was never called"
    v = env.voice()
    assert v.status_code == 200 and v.json()["mode"] == "recorded"
    assert env.spark.requests == []
    monkeypatch.setenv("MAUDESIGNAL_ALLOW_PER_INSTANCE_CAP", "1")
    assert Env(tmp_path).ask().json()["mode"] == "live"
