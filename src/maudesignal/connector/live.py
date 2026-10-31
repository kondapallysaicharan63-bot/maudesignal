"""Public live Muse routes for the website: ask, voice and label photo (no connector key).

HACKATHON-BUILT — Meta Global AI Developer Hackathon (Oct 26 – Nov 4, 2026).

Routes (hidden from the public OpenAPI document, keyless, browser origin must be listed in
``MAUDESIGNAL_WEB_ORIGINS``)::

    POST /v1/live/ask    JSON {question, history?, product_code?, ref?}
    POST /v1/live/voice  multipart: "audio" (WAV PCM16 mono 16 kHz, <= 60 s, <= 4 MB), "meta"?
    POST /v1/live/label  multipart: "image" (JPEG or PNG, <= 8 MB)

What this module adds on top of the existing pieces (it reuses, and does not copy, them):

* ``connector.ask.ask_detailed`` answers a question with Muse Spark behind the claim gate
  (read-only tools, temperature 0, prompt in ``skills/safety-copilot``), or from a recorded
  run, labelled as recorded with the recorded question named.
* ``copilot.voice.MetaTranscriber`` turns a spoken question into text first (audio never
  reaches the chat model); the transcript is returned with the answer.
* ``vision.label_match`` reads a label photo (SAM 3.1 crop, Muse Spark read) and searches
  openFDA for up to three possible matches. Nothing is picked for the person.

Rules enforced here:

* Per-address daily limits (ask 30, voice 10, label 5 by default) plus a per-minute burst
  limit. The address is only ever a peppered HMAC id, in memory or in Upstash; it is never
  stored in a record or logged.
* One daily cost rule for every Meta call (``callcap``): each model call (every Spark
  completion, each Voice Transcribe, each SAM call) reserves its worst case in the private
  Blob store before it is sent and is released to the real cost only after a successful reply;
  a failed or timed-out call stays counted at its worst case. Hard ceiling
  ``MAUDESIGNAL_LIVE_DAILY_USD`` (3.00); calls normally stop at that minus one call's hold.
* No model key, a cap reached, or a model error gives a recorded answer, labelled recorded.
  A recorded answer is never presented as live.
* Uploads are checked (size, type, duration, pixels) before any model call and held in
  memory only. Images are decoded and re-encoded, so EXIF and every other metadata block is
  dropped. Audio and image bytes are never written to disk or Blob and never logged. Lot and
  serial numbers are never returned.
* A question or a voice transcript that looks like patient data is refused with 422.
* The whole label request is built to end in under 55 s: each step has a timeout and a
  deadline; on a timeout the recorded fallback answers with a note.
"""

from __future__ import annotations

import hashlib
import hmac
import io
import json
import os
import re
import secrets
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse
from PIL import Image, ImageOps
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator
from starlette.concurrency import run_in_threadpool
from starlette.requests import ClientDisconnect

from maudesignal.common.logging import get_logger
from maudesignal.connector import chat, links
from maudesignal.connector.answer_cache import AnswerCache
from maudesignal.connector.ask import (
    _REASON_NOTES,
    AgentFactory,
    AskOutcome,
    AskRuntime,
    ask_detailed,
    recorded_voice_answer,
)
from maudesignal.connector.callcap import CallMeter, CallRefusedError, enforced_cap
from maudesignal.connector.data import PROJECT_ROOT, ConnectorData
from maudesignal.connector.direct import answer as direct_answer
from maudesignal.connector.errors import InvalidInputError, SourceUnavailableError
from maudesignal.connector.feedback import clean_ref, looks_like_phi
from maudesignal.connector.forbidden import is_clean
from maudesignal.connector.globalcap import (
    ASK_USD_ENV,
    DAILY_USD_ENV,
    DEFAULT_ASK_USD,
    DEFAULT_DAILY_USD,
    DEFAULT_LABEL_USD,
    DEFAULT_VOICE_USD,
    LABEL_USD_ENV,
    LEDGER_ID,
    VOICE_USD_ENV,
)
from maudesignal.connector.mentions import (
    LABEL,
    Fetcher,
    HttpFetcher,
    empty_recorded,
    load_recorded,
    search_mentions,
)
from maudesignal.connector.models import ToolAnswer
from maudesignal.connector.readonly import make_read_only
from maudesignal.connector.security import RateLimiter
from maudesignal.connector.store import ConnectorState, MemoryLedger
from maudesignal.connector.tiers import cacheable
from maudesignal.copilot.agent import CopilotAgent
from maudesignal.copilot.spend import (
    DailyLedger,
    SpendCaps,
    SpendGuard,
    SpendLimitError,
    worst_case_call_usd,
)
from maudesignal.copilot.voice import (
    AudioValidationError,
    Transcript,
    VoiceTranscribeError,
    estimate_cost_usd,
    validate_audio,
)
from maudesignal.vision.images import fit
from maudesignal.vision.label import LabelResult
from maudesignal.vision.label_match import (
    OpenFdaSearcher,
    Searcher,
    match_label,
    read_label_timed,
    sanitize_udi,
)
from maudesignal.vision.sam import SamClient, SamError
from maudesignal.vision.spark import DEFAULT_VISION_MODEL

logger = get_logger(__name__)

ASK_PATH = "/v1/live/ask"
VOICE_PATH = "/v1/live/voice"
LABEL_PATH = "/v1/live/label"
MENTIONS_PATH = "/v1/live/mentions"
LIVE_PATHS = (ASK_PATH, VOICE_PATH, LABEL_PATH, MENTIONS_PATH)

# Environment names (all optional).
ASK_PER_DAY_ENV = "MAUDESIGNAL_LIVE_ASK_PER_DAY"
VOICE_PER_DAY_ENV = "MAUDESIGNAL_LIVE_VOICE_PER_DAY"
LABEL_PER_DAY_ENV = "MAUDESIGNAL_LIVE_LABEL_PER_DAY"
MENTIONS_PER_DAY_ENV = "MAUDESIGNAL_LIVE_MENTIONS_PER_DAY"
BURST_PER_MIN_ENV = "MAUDESIGNAL_LIVE_PER_MIN"
PEPPER_ENV = "MAUDESIGNAL_KEY_PEPPER"

DEFAULT_ASK_PER_DAY = 30
DEFAULT_VOICE_PER_DAY = 10
DEFAULT_LABEL_PER_DAY = 5
DEFAULT_MENTIONS_PER_DAY = 10
DEFAULT_BURST_PER_MIN = 10

# Upload and body limits.
MAX_JSON_BYTES = 64 * 1024
MAX_AUDIO_BYTES = 4 * 1024 * 1024
MAX_IMAGE_BYTES = 4 * 1024 * 1024  # Vercel rejects bodies over 4.5 MB before the app runs
MAX_META_BYTES = 16 * 1024
MULTIPART_OVERHEAD = 64 * 1024
MAX_AUDIO_SECONDS = 60.0
AUDIO_SAMPLE_RATE = 16000
MAX_IMAGE_PIXELS = 40_000_000
MIN_IMAGE_SIDE = 32
IMAGE_MAX_SIDE = 1600
MAX_HISTORY = 4
MAX_HISTORY_ANSWER_CHARS = 600
MAX_QUESTION_CHARS = 500
MAX_CANDIDATES = 3

# Time budgets in seconds (the label request must end in under 55 s).
LABEL_BUDGET_S = 50.0
SAM_PROMPT_DEADLINE_S = 12.0
SAM_CALL_TIMEOUT_S = 10.0
OPENFDA_DEADLINE_S = 45.0
OPENFDA_CALL_TIMEOUT_S = 6.0
#: Hard wall-clock cap per openFDA call (an httpx timeout applies per phase, not per call).
OPENFDA_CALL_WALL_S = 8.0
ASK_BUDGET_S = 50.0
VOICE_TRANSCRIBE_TIMEOUT_S = 15.0
#: One deadline for the whole voice request (transcription plus answer), under Vercel's 60 s.
VOICE_REQUEST_BUDGET_S = 52.0
MIN_CALL_BUDGET_S = 3.0
CALL_TIMEOUT_S = 25.0

VOICE_MODEL = "muse-voice-transcribe-1.0"
SAM_MODEL = "sam-3.1"
SPARK_MODEL = DEFAULT_VISION_MODEL
IMAGE_TYPES = ("image/jpeg", "image/png")
_JPEG = b"\xff\xd8\xff"
_PNG = b"\x89PNG\r\n\x1a\n"
_PRODUCT_CODE = r"^[A-Za-z]{3}$"

PHI_MESSAGE = (
    "Please remove patient details (names, ages, email addresses, phone numbers, ID or "
    "record numbers, dates of birth) and send again. Nothing was answered or kept."
)
NOT_MEDICAL_ADVICE = True


# ---------------------------------------------------------------------------
# Settings and backends
# ---------------------------------------------------------------------------


def _int_env(env: dict[str, str], name: str, default: int, *, minimum: int = 1) -> int:
    try:
        value = int(env.get(name, ""))
    except ValueError:
        return default
    return value if value >= minimum else default


def _float_env(env: dict[str, str], name: str, default: float) -> float:
    try:
        value = float(env.get(name, ""))
    except ValueError:
        return default
    return value if value >= 0 else default


@dataclass(frozen=True)
class LiveConfig:
    """Limits and caps of the live routes (environment-driven)."""

    ask_per_day: int = DEFAULT_ASK_PER_DAY
    voice_per_day: int = DEFAULT_VOICE_PER_DAY
    label_per_day: int = DEFAULT_LABEL_PER_DAY
    burst_per_min: int = DEFAULT_BURST_PER_MIN
    daily_usd: float = DEFAULT_DAILY_USD
    ask_usd: float = DEFAULT_ASK_USD
    voice_usd: float = DEFAULT_VOICE_USD
    label_usd: float = DEFAULT_LABEL_USD
    mentions_per_day: int = DEFAULT_MENTIONS_PER_DAY

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> LiveConfig:
        """Read the limits; unset or invalid values keep the defaults."""
        e = dict(os.environ if env is None else env)
        return cls(
            ask_per_day=_int_env(e, ASK_PER_DAY_ENV, DEFAULT_ASK_PER_DAY),
            voice_per_day=_int_env(e, VOICE_PER_DAY_ENV, DEFAULT_VOICE_PER_DAY),
            label_per_day=_int_env(e, LABEL_PER_DAY_ENV, DEFAULT_LABEL_PER_DAY),
            burst_per_min=_int_env(e, BURST_PER_MIN_ENV, DEFAULT_BURST_PER_MIN),
            daily_usd=_float_env(e, DAILY_USD_ENV, DEFAULT_DAILY_USD),
            ask_usd=_float_env(e, ASK_USD_ENV, DEFAULT_ASK_USD),
            voice_usd=_float_env(e, VOICE_USD_ENV, DEFAULT_VOICE_USD),
            label_usd=_float_env(e, LABEL_USD_ENV, DEFAULT_LABEL_USD),
            mentions_per_day=_int_env(e, MENTIONS_PER_DAY_ENV, DEFAULT_MENTIONS_PER_DAY),
        )


class Transcriber:
    """What the voice route needs from a transcription client."""

    def transcribe_bytes(self, data: bytes, *, filename: str = "audio.wav") -> Transcript:
        """Transcribe one WAV clip."""
        raise NotImplementedError


def _key() -> str:
    return os.environ.get("META_MODEL_API_KEY", "")


def default_agent_factory(deadline: float, clock: Callable[[], float]) -> AgentFactory:
    """Real Muse Spark agent whose model calls stop at ``deadline`` (read-only tools)."""

    def factory(data: ConnectorData, guard: SpendGuard) -> CopilotAgent:  # pragma: no cover
        from maudesignal.copilot.meta_provider import MetaProvider

        provider = MetaProvider(
            api_key=_key(),
            model=os.environ.get("META_MODEL_API_MODEL", ""),
            base_url=os.environ.get("META_MODEL_API_BASE_URL", "https://api.meta.ai/v1"),
        )
        model = os.environ.get("META_MODEL_API_MODEL", SPARK_MODEL)
        client = DeadlineClient(provider.client, deadline, clock)
        agent = CopilotAgent(guard.wrap(client), data.tool_context(), model=model)
        make_read_only(agent)
        return agent

    return factory


def default_transcriber(timeout_s: float) -> Transcriber:  # pragma: no cover
    """Real Muse Voice Transcribe client."""
    from maudesignal.copilot.voice import MetaTranscriber

    return MetaTranscriber(  # type: ignore[return-value]
        _key(),
        base_url=os.environ.get("META_MODEL_API_BASE_URL", "https://api.meta.ai/v1"),
        timeout_s=timeout_s,
    )


def default_spark_client(deadline: float, clock: Callable[[], float]) -> Any:  # pragma: no cover
    """Real Muse Spark chat client whose calls stop at ``deadline``."""
    from maudesignal.copilot.meta_provider import MetaProvider

    provider = MetaProvider(
        api_key=_key(),
        model=os.environ.get("META_MODEL_API_MODEL", ""),
        base_url=os.environ.get("META_MODEL_API_BASE_URL", "https://api.meta.ai/v1"),
    )
    return DeadlineClient(provider.client, deadline, clock)


def default_sam(timeout_s: float) -> SamClient | None:  # pragma: no cover
    """Real SAM 3.1 client (None when no key)."""
    if not _key():
        return None
    return SamClient(
        _key(),
        base_url=os.environ.get("META_MODEL_API_BASE_URL", "https://api.meta.ai/v1"),
        timeout_s=timeout_s,
    )


def default_searcher(timeout_s: float) -> Searcher:  # pragma: no cover
    """Real openFDA searcher (the optional ``OPENFDA_API_KEY`` is never stored)."""
    return OpenFdaSearcher(os.environ.get("OPENFDA_API_KEY") or None, timeout_s=timeout_s)


@dataclass
class LiveBackends:
    """Everything the live routes call out to (tests inject fakes for all of it)."""

    live_enabled: Callable[[], bool] = field(default=lambda: bool(_key()))
    agent_factory: Callable[[float, Callable[[], float]], AgentFactory] = default_agent_factory
    transcriber: Callable[[float], Transcriber] = default_transcriber
    spark_client: Callable[[float, Callable[[], float]], Any] = default_spark_client
    sam: Callable[[float], SamClient | None] = default_sam
    searcher: Callable[[float], Searcher] = default_searcher
    clock: Callable[[], float] = time.monotonic
    sleep: Callable[[float], None] = time.sleep  # waits between feed retries
    vision_dir: Path = field(default_factory=lambda: PROJECT_ROOT / "demo" / "vision")
    mentions_fetcher: Callable[[], Fetcher] = HttpFetcher
    mentions_dir: Path = field(default_factory=lambda: PROJECT_ROOT / "demo" / "mentions")


class DeadlineClient:
    """Wraps an OpenAI-style client: each call gets the time left; none starts after the end."""

    def __init__(self, inner: Any, deadline: float, clock: Callable[[], float]) -> None:
        """Wrap ``inner``; ``deadline`` is a reading of ``clock``."""
        self._inner, self._deadline, self._clock = inner, deadline, clock
        completions = _DeadlineCompletions(self)
        self.chat = type("Chat", (), {"completions": completions})()

    def left(self) -> float:
        """Seconds until the deadline."""
        return self._deadline - self._clock()

    def create(self, **kwargs: Any) -> Any:
        """One chat call with a timeout of at most the time left."""
        left = self.left()
        if left < MIN_CALL_BUDGET_S:
            raise TimeoutError("the live time budget for this request is used up")
        client = self._inner
        if hasattr(client, "with_options"):
            client = client.with_options(timeout=min(left, CALL_TIMEOUT_S), max_retries=0)
        return client.chat.completions.create(**kwargs)


class _DeadlineCompletions:
    def __init__(self, owner: DeadlineClient) -> None:
        self._owner = owner

    def create(self, **kwargs: Any) -> Any:
        return self._owner.create(**kwargs)


class _DeadlineSam:
    """SAM client that starts no new prompt after ``deadline`` (the full photo is read then)."""

    def __init__(self, inner: SamClient, deadline: float, clock: Callable[[], float]) -> None:
        self._inner, self._deadline, self._clock = inner, deadline, clock

    def segment(self, image: Any, prompt: str) -> Any:
        if self._clock() > self._deadline:
            raise SamError("SAM time budget used up")
        return self._inner.segment(image, prompt)


class _DeadlineSearcher:
    """openFDA searcher that runs no query after ``deadline``."""

    def __init__(self, inner: Searcher, deadline: float, clock: Callable[[], float]) -> None:
        self._inner, self._deadline, self._clock = inner, deadline, clock

    def query(self, endpoint: str, search: str, *, limit: int = 25, sort: str | None = None) -> Any:
        from concurrent.futures import ThreadPoolExecutor
        from concurrent.futures import TimeoutError as FutureTimeout

        from maudesignal.common.exceptions import OpenFDAUnavailableError

        if self._clock() > self._deadline:
            raise OpenFDAUnavailableError("openFDA time budget used up")
        # A slowly dripping response must not outlast the call limit: wait at most that long.
        pool = ThreadPoolExecutor(max_workers=1)
        future = pool.submit(self._inner.query, endpoint, search, limit=limit, sort=sort)
        try:
            return future.result(timeout=OPENFDA_CALL_WALL_S)
        except FutureTimeout as exc:
            raise OpenFDAUnavailableError("openFDA call took longer than its time limit") from exc
        finally:
            pool.shutdown(wait=False)


@dataclass
class LiveAskRuntime(AskRuntime):
    """``AskRuntime`` whose Meta calls all go through the one per-call daily ledger."""

    live_ledger: DailyLedger = field(default_factory=MemoryLedger)

    def ledger_for(self, key_id: str) -> DailyLedger:
        """A throwaway per-request ledger: the live routes keep no per-key daily total."""
        return self.live_ledger


class _MeteredSam:
    """SAM client whose every segmentation call reserves its worst case first."""

    def __init__(self, inner: Any, meter: CallMeter) -> None:
        self._inner, self._meter = inner, meter

    def segment(self, image: Any, prompt: str) -> Any:
        return self._meter.sam(lambda: self._inner.segment(image, prompt))


# ---------------------------------------------------------------------------
# Request validation
# ---------------------------------------------------------------------------


class HistoryItem(BaseModel):
    """One earlier question and its answer, sent back by the browser as context."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    question: str = Field(min_length=1, max_length=MAX_QUESTION_CHARS)
    answer: str = Field(default="", max_length=20_000)


class _CommonIn(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    history: list[HistoryItem] = Field(default_factory=list, max_length=MAX_HISTORY)
    product_code: str | None = Field(default=None, pattern=_PRODUCT_CODE)

    @field_validator("product_code", mode="after")
    @classmethod
    def _upper(cls, value: str | None) -> str | None:
        return value.upper() if value else None


#: Shortest typed message: two characters, so "hi" gets its canned reply (tier 1).
MIN_MESSAGE_CHARS = 2


class AskIn(_CommonIn):
    """Body of ``POST /v1/live/ask``."""

    question: str = Field(min_length=MIN_MESSAGE_CHARS, max_length=MAX_QUESTION_CHARS)
    ref: str | None = Field(default=None, max_length=200)

    @field_validator("ref", mode="before")
    @classmethod
    def _ref(cls, value: Any) -> Any:
        return clean_ref(value)  # never kept or logged; only accepted


class MetaIn(_CommonIn):
    """The optional ``meta`` part of ``POST /v1/live/voice``."""


class MentionsIn(BaseModel):
    """Body of ``POST /v1/live/mentions``."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    product_code: str = Field(pattern=_PRODUCT_CODE)
    device_terms: list[str] = Field(default_factory=list, max_length=5)

    @field_validator("product_code", mode="after")
    @classmethod
    def _upper_code(cls, value: str) -> str:
        return value.upper()

    @field_validator("device_terms", mode="after")
    @classmethod
    def _terms(cls, value: list[str]) -> list[str]:
        if any(not 2 <= len(t.strip()) <= 60 for t in value):
            raise ValueError("each term must have 2 to 60 characters")
        return [t.strip() for t in value]


_MENTIONS_NOTES = {
    "unreachable": "None of the public sources could be reached just now.",
}


def with_code(question: str, code: str | None) -> str:
    """Add the chosen device type to a question that does not name one."""
    if code and not re.search(rf"\b{code}\b", question, re.IGNORECASE):
        return f"{question} (device type {code})"
    return question


#: Extra patterns for the live routes, whose text goes to an external model: a patient title
#: with a name ("Mrs. Jane Smith") and an age ("age 67", "67-year-old", "67 y/o").
_PATIENT_NAME = re.compile(r"\b(?:Mr|Mrs|Ms|Miss|Mx)\.?\s+[A-Z][a-z]+")
_PATIENT_AGE = re.compile(
    r"\b(?:aged?\s*:?\s*\d{1,3}\b|\d{1,3}\s*-?\s*(?:year|yr)s?\s*-?\s*old\b|\d{1,3}\s*y/?o\b)",
    re.IGNORECASE,
)


def phi_in(texts: list[str]) -> bool:
    """True when any text looks like patient details (a guard, not a guarantee)."""
    return any(
        looks_like_phi(t) or _PATIENT_NAME.search(t) or _PATIENT_AGE.search(t) for t in texts
    )


def history_texts(history: list[HistoryItem]) -> list[str]:
    """Every free-text field of a history list."""
    return [t for h in history for t in (h.question, h.answer)]


def history_pairs(history: list[HistoryItem]) -> list[tuple[str, str]]:
    """History as ``(question, answer)`` with each answer cut to 600 characters."""
    return [(h.question, h.answer[:MAX_HISTORY_ANSWER_CHARS]) for h in history]


def parse_multipart(body: bytes, content_type: str) -> dict[str, tuple[str, bytes]] | None:
    """Split a ``multipart/form-data`` body held in memory into ``{name: (type, bytes)}``.

    Returns None when the body is not well-formed multipart (or has duplicate or too many
    parts). Nothing is written to disk: the standard form parsers spool large parts to
    temporary files, which uploads here must never be.
    """
    if not content_type.lower().startswith("multipart/form-data"):
        return None
    m = re.search(r'boundary="?([^";\s]{1,200})"?', content_type, re.IGNORECASE)
    if not m:
        return None
    delimiter = b"--" + m.group(1).encode("latin-1", "ignore")
    chunks = body.split(delimiter)
    parts: dict[str, tuple[str, bytes]] = {}
    for chunk in chunks[1:]:
        if chunk.startswith(b"--"):
            break
        chunk = chunk[2:] if chunk.startswith(b"\r\n") else chunk
        head, sep, data = chunk.partition(b"\r\n\r\n")
        if not sep:
            return None
        if data.endswith(b"\r\n"):
            data = data[:-2]
        name: str | None = None
        ctype = ""
        for line in head.split(b"\r\n"):
            key, _, value = line.partition(b":")
            lower = key.strip().lower()
            if lower == b"content-disposition":
                nm = re.search(rb'(?:^|[;\s])name="([^"]{1,64})"', value)
                name = nm.group(1).decode("latin-1") if nm else None
            elif lower == b"content-type":
                ctype = value.strip().decode("latin-1").lower()
        if name is None or name in parts or len(parts) >= 4:
            return None
        parts[name] = (ctype, data)
    return parts or None


class UploadError(Exception):
    """An upload was refused before any model call."""

    def __init__(self, status: int, code: str, message: str) -> None:
        """Create the error."""
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


def check_audio(data: bytes) -> float:
    """Check a clip against the live limits; returns its length in seconds.

    Raises:
        UploadError: Too large (413) or not a mono 16-bit 16 kHz WAV of at most 60 s (422).
    """
    if len(data) > MAX_AUDIO_BYTES:
        raise UploadError(413, "too_large", "Audio is too large (4 MB at most).")
    if not data:
        raise UploadError(422, "invalid_input", "The audio part is empty.")
    try:
        info = validate_audio(data, "audio.wav")
    except AudioValidationError as exc:
        raise UploadError(422, "invalid_input", f"Audio not accepted: {exc}") from None
    if info.sample_rate != AUDIO_SAMPLE_RATE:
        raise UploadError(422, "invalid_input", "Audio must be WAV PCM16 mono at 16000 Hz.")
    if info.seconds > MAX_AUDIO_SECONDS:
        raise UploadError(422, "invalid_input", "Audio must be 60 seconds or shorter.")
    return info.seconds


def clean_image(data: bytes, content_type: str) -> tuple[bytes, tuple[int, int]]:
    """Decode a photo and re-encode it as a plain JPEG: EXIF and all other metadata are gone.

    The pixels are copied into a fresh image, so no EXIF, GPS, ICC profile or comment block of
    the original can survive. EXIF orientation is applied first so the photo stays upright.

    Returns:
        ``(jpeg_bytes, (width, height))``.

    Raises:
        UploadError: Too large (413), or not a decodable JPEG or PNG (422).
    """
    if len(data) > MAX_IMAGE_BYTES:
        raise UploadError(413, "too_large", "Image is too large (8 MB at most).")
    if content_type not in IMAGE_TYPES:
        raise UploadError(422, "invalid_input", "Image must be JPEG or PNG.")
    if not (data.startswith(_JPEG) or data.startswith(_PNG)):
        raise UploadError(422, "invalid_input", "Image must be JPEG or PNG.")
    try:
        with Image.open(io.BytesIO(data)) as img:
            if img.format not in ("JPEG", "PNG"):
                raise UploadError(422, "invalid_input", "Image must be JPEG or PNG.")
            width, height = img.size
            if width * height > MAX_IMAGE_PIXELS:
                raise UploadError(413, "too_large", "Image has too many pixels.")
            if min(width, height) < MIN_IMAGE_SIDE:
                raise UploadError(422, "invalid_input", "Image is too small to read.")
            img.load()
            upright = ImageOps.exif_transpose(img).convert("RGB")
            fresh = Image.frombytes("RGB", upright.size, upright.tobytes())
    except UploadError:
        raise
    except Exception:  # noqa: BLE001 - Pillow raises many types for broken files
        raise UploadError(422, "invalid_input", "Image could not be decoded.") from None
    fresh = fit(fresh, IMAGE_MAX_SIDE)
    out = io.BytesIO()
    fresh.save(out, format="JPEG", quality=90)  # no exif=, icc_profile= or comment: none kept
    return out.getvalue(), fresh.size


# ---------------------------------------------------------------------------
# Response shaping
# ---------------------------------------------------------------------------


def _step(
    step: str, model: str | None, ms: float, status: str, note: str | None = None
) -> dict[str, Any]:
    out: dict[str, Any] = {"step": step, "model": model, "ms": int(round(ms)), "status": status}
    if note:
        out["note"] = note
    return out


def _safe_text(text: str) -> str:
    return text if is_clean(text) else "[text removed]"


def answer_block(answer: ToolAnswer) -> dict[str, Any]:
    """The contract's ``answer``: gated sentences with their links, left-out reasons only."""
    grouped: dict[str, list[dict[str, str]]] = {}
    for f in answer.facts:
        if is_clean(f.text):
            grouped.setdefault(f.text, []).append({"label": f.link_label, "url": f.link})
    speakable = [{"text": t, "links": ls} for t, ls in grouped.items()]
    spoken = _safe_text(answer.speakable)
    if not speakable:
        speakable = [{"text": spoken, "links": []}]
    return {
        "speakable": speakable,
        "withheld": [{"reason": _safe_text(w.reason)} for w in answer.withheld],
        "spoken_text": spoken,
    }


def recorded_note(outcome: AskOutcome) -> str:
    """Why a recording is shown, and which recorded run it is."""
    note = _REASON_NOTES.get(outcome.reason or "", "No live model call was made.")
    if outcome.recorded_question:
        when = (outcome.recorded_at or "")[:10]
        note += f' Shown instead: a recorded run that answered "{outcome.recorded_question}"' + (
            f" (recorded {when})." if when else "."
        )
    else:
        note += " No recorded answer matches this question."
    return _safe_text(note)


def ask_trace(outcome: AskOutcome) -> list[dict[str, Any]]:
    """Trace steps of an ask: model time and tool/gate time are measured, never typed in."""
    if outcome.live:
        tools = ", ".join(dict.fromkeys(outcome.tool_names)) or "no tools"
        model_ms = outcome.model_ms or 0.0
        return [
            _step("Muse Spark answers from stored records", SPARK_MODEL, model_ms, "ok"),
            _step(
                "Read-only tools and claim gate",
                None,
                max(0.0, outcome.total_ms - model_ms),
                "ok",
                f"{len(outcome.tool_names)} tool call(s): {tools}",
            ),
        ]
    skipped = outcome.reason in ("no_model", "live_off", "cap", "no_transcript")
    note = _REASON_NOTES.get(outcome.reason or "", "")
    found = outcome.recorded_question is not None
    return [
        _step(
            "Muse Spark answers from stored records",
            SPARK_MODEL,
            outcome.attempt_ms,
            "skipped" if skipped else "failed",
            note,
        ),
        _step(
            "Closest recorded answer",
            None,
            max(0.0, outcome.total_ms - outcome.attempt_ms),
            "ok" if found else "failed",
            None if found else "no recorded answer matches",
        ),
    ]


def reset_time(today: date) -> datetime:
    """Next UTC midnight after ``today``."""
    return datetime.combine(today + timedelta(days=1), datetime.min.time(), tzinfo=UTC)


def _iso(moment: datetime) -> str:
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


def _cost(total: float) -> float | None:
    return round(total, 6) if total > 0 else None


# ---------------------------------------------------------------------------
# Label payload
# ---------------------------------------------------------------------------

_FIELD_MAP = (
    ("device_name", "device_name"),
    ("manufacturer", "manufacturer"),
    ("model", "model_number"),
    ("k_number", "k_number"),
    ("udi", "udi"),
    ("gtin", "gtin"),
)


def _scrub(value: Any) -> Any:
    if isinstance(value, str):
        return _safe_text(value)
    if isinstance(value, list):
        return [_scrub(v) for v in value]
    if isinstance(value, dict):
        return {k: _scrub(v) for k, v in value.items()}
    return value


def _reading_block(reading: dict[str, Any], withheld: list[str]) -> dict[str, Any]:
    fields = reading.get("fields") or {}
    out: dict[str, Any] = {}
    for name, source in _FIELD_MAP:
        f = fields.get(source) or {}
        value = str(f.get("value") or "")
        if name == "udi":
            value = sanitize_udi(value)  # keep AIs 01 / 11 / 17 only: never a lot or serial
        out[name] = {"value": value, "legibility": str(f.get("legibility") or "")}
    block: dict[str, Any] = {
        "legibility": str(reading.get("overall_legibility") or ""),
        "fields": out,
    }
    if withheld:
        block["values_withheld"] = withheld
    return _scrub(block)  # type: ignore[no-any-return]


def _candidate(c: dict[str, Any]) -> dict[str, Any]:
    k = c.get("k_number") or (c.get("record_id") if c.get("source") == "510k" else None)
    found: list[dict[str, str]] = []
    if k:
        found.append({"label": "510(k) record on openFDA", "url": links.k510_link(str(k))})
    url = c.get("query_url")
    if isinstance(url, str) and url.startswith("https://"):
        found.append({"label": "openFDA search that found it", "url": url})
    return {
        "k_number": k,
        "device_name": c.get("device_name"),
        "applicant": c.get("owner") or c.get("applicant"),
        "product_code": c.get("product_code"),
        "why_matched": list(c.get("why_matched") or []),
        "why_not_matched": list(c.get("why_not_matched") or []),
        "links": found,
    }


SEARCH_FAILED_NOTE = "openFDA could not be searched, so there is no match result for this photo."


def _matches_block(matches: list[dict[str, Any]], *, search_failed: bool = False) -> dict[str, Any]:
    """Up to three candidates; a person must confirm one. None is ever picked here.

    ``search_failed`` is true when no openFDA search ran or every one failed: the empty list then
    means "not searched", and the block says so instead of claiming nothing matched.
    """
    cands = [_candidate(m) for m in matches[:MAX_CANDIDATES]]
    block: dict[str, Any] = {
        "status": "needs_person_to_confirm" if cands else "no_match_found",
        "candidates": _scrub(cands),
    }
    if search_failed and not cands:
        block["search_failed"] = True
        block["note"] = SEARCH_FAILED_NOTE
    return block


def _stored_to_candidates(d: dict[str, Any]) -> list[dict[str, Any]]:
    """Candidates of a stored reading (older shape: openFDA 510(k) rows from the name search)."""
    basis = str(d.get("match_basis") or "none")
    out: list[dict[str, Any]] = []
    for c in d.get("candidates") or []:
        if not isinstance(c, dict):
            continue
        out.append(
            {
                "source": "510k",
                "k_number": c.get("k_number"),
                "record_id": c.get("k_number"),
                "owner": c.get("applicant"),
                "device_name": c.get("device_name"),
                "product_code": c.get("product_code"),
                "why_matched": [f"found by the recorded name search ({basis})"],
                "why_not_matched": [],
            }
        )
    return out


def recorded_label(vision_dir: Path) -> tuple[dict[str, Any], dict[str, Any], str] | None:
    """The stored label run to show when the live read cannot run.

    Prefers a stored match result (``label-match-*.json``); otherwise a stored reading that
    has candidates. Returns ``(reading_like, matches_block, image_file)`` or None.
    """
    if not vision_dir.is_dir():
        return None
    for path in sorted(vision_dir.glob("label-match-*.json")):
        try:
            d = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(d, dict) and d.get("matches"):
            reading = {
                "fields": (d.get("label") or {}).get("fields") or {},
                "overall_legibility": (d.get("label") or {}).get("overall_legibility"),
            }
            return reading, _matches_block(list(d["matches"])), str(d.get("image_file") or "")
    best: tuple[int, str, dict[str, Any]] | None = None
    for path in sorted(vision_dir.glob("label-*.json")):
        if path.name.startswith("label-match-"):
            continue
        try:
            d = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(d, dict) or d.get("kind") != "device_label_reading":
            continue
        rank = len(d.get("candidates") or [])
        if best is None or rank > best[0]:
            best = (rank, path.name, d)
    if best is None:
        return None
    d = best[2]
    return d, _matches_block(_stored_to_candidates(d)), str(d.get("image_file") or best[1])


# ---------------------------------------------------------------------------
# Mounting
# ---------------------------------------------------------------------------


def _err(
    status: int,
    code: str,
    message: str,
    headers: dict[str, str] | None = None,
    **extra: Any,
) -> Response:
    body: dict[str, Any] = {
        "code": code,
        "message": message,
        "error": {"code": code, "message": message},
    } | extra
    return JSONResponse(
        status_code=status, content=body, headers={"Cache-Control": "no-store", **(headers or {})}
    )


def mount_live(
    app: FastAPI,
    *,
    data: ConnectorData,
    state: ConnectorState,
    web_origins: frozenset[str],
    client_address: Callable[[Request], str],
    make_limiter: Callable[[str, int, float], RateLimiter],
    backends: LiveBackends | None = None,
    config: LiveConfig | None = None,
    now: Callable[[], datetime] | None = None,
    env: dict[str, str] | None = None,
    tiers: bool = True,
) -> None:
    """Add the three live routes and their CORS handling to ``app``.

    Args:
        app: The connector app.
        data: Stored data (recorded answers, evidence, tool context).
        state: Shared state (Upstash when configured, memory otherwise).
        web_origins: Exact browser origins allowed (``MAUDESIGNAL_WEB_ORIGINS``).
        client_address: Returns the caller address (honours ``TRUST_FORWARDED``).
        make_limiter: ``(name, limit, window_seconds)`` factory for the burst limiter.
        backends: Model, speech, SAM and openFDA clients (fakes in tests).
        config: Limits; read from the environment when omitted.
        now: UTC clock (tests).
        env: Environment (tests).
        tiers: Chat tiers for typed questions (canned, direct, cache before Muse Spark).
            Tiers 1 to 3 cost nothing, use no daily live-question allowance and never touch
            the per-call spend ledger.
    """
    be = backends or LiveBackends()
    cfg = config or LiveConfig.from_env(env)
    clock_now = now or (lambda: datetime.now(UTC))
    today: Callable[[], date] = lambda: clock_now().date()  # noqa: E731
    # Fail closed: every Meta call reserves its worst case in the private Blob store first, so
    # with no such store no live call is made (unless the local-only per-process override is
    # set, which keeps the same ledger in this process's memory).
    per_instance_ok = (env if env is not None else os.environ).get(
        "MAUDESIGNAL_ALLOW_PER_INSTANCE_CAP", ""
    ).strip() == "1"
    call_ledger = state.call_ledger(
        today=today, allow_memory=per_instance_ok, cap_usd=enforced_cap(cfg.daily_usd)
    )
    no_shared_ledger = call_ledger is None
    meter = CallMeter(call_ledger) if call_ledger is not None else None
    burst = make_limiter("live-burst", cfg.burst_per_min, 60.0)
    counters = {
        "ask": state.daily_counter("live-ask", cfg.ask_per_day, today=today),
        "voice": state.daily_counter("live-voice", cfg.voice_per_day, today=today),
        "label": state.daily_counter("live-label", cfg.label_per_day, today=today),
        "mentions": state.daily_counter("live-mentions", cfg.mentions_per_day, today=today),
    }
    pepper_src = (env if env is not None else os.environ).get(PEPPER_ENV)
    if not pepper_src and state.shared:
        logger.warning(
            "live_pepper_missing",
            detail=f"{PEPPER_ENV} is not set: each instance hashes addresses differently, "
            "so the shared per-address daily limits are multiplied by the number of instances",
        )
    pepper = (pepper_src or secrets.token_hex(16)).encode("utf-8")
    live_cache = AnswerCache(state, "live", now=clock_now)

    def who(request: Request) -> str:
        """Peppered HMAC of the caller address: all the limiters and counters ever see."""
        mac = hmac.new(pepper, client_address(request).encode("utf-8"), hashlib.sha256)
        return "live:" + mac.hexdigest()[:24]

    def runtime(request_usd: float, budget_s: float) -> LiveAskRuntime:
        """Ask settings for one request: its cost cap and the time its model calls may take."""
        return LiveAskRuntime(
            agent_factory=be.agent_factory(be.clock() + budget_s, be.clock),
            live_enabled=lambda: be.live_enabled() and not no_shared_ledger,
            caps=SpendCaps(
                session_usd=request_usd,
                session_calls=20,
                daily_usd=cfg.daily_usd,
                call_reserve_usd=worst_case_call_usd(),
            ),
            state=state,
            live_ledger=MemoryLedger(today=today),
            meter=meter,
        )

    def limits(remaining: int) -> dict[str, Any]:
        return {"remaining_today": remaining, "resets_utc": _iso(reset_time(today()))}

    @app.middleware("http")
    async def _live_cors(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        """CORS for the live routes: exact origins from the environment, no credentials."""
        if request.url.path not in LIVE_PATHS:
            return await call_next(request)
        origin = request.headers.get("origin", "").rstrip("/")
        allowed = bool(origin) and origin in web_origins
        response: Response
        if request.method == "OPTIONS":
            response = Response(status_code=204)
            if allowed:
                response.headers["Access-Control-Allow-Methods"] = "POST, OPTIONS"
                response.headers["Access-Control-Allow-Headers"] = "Content-Type"
                response.headers["Access-Control-Max-Age"] = "600"
        elif origin and not allowed:
            response = _err(403, "origin_not_allowed", "Origin not allowed.")
        else:
            response = await call_next(request)
        response.headers["Vary"] = "Origin"
        if allowed:
            response.headers["Access-Control-Allow-Origin"] = origin
            response.headers["Access-Control-Expose-Headers"] = "Retry-After"
        return response

    def burst_refusal(request: Request) -> Response | None:
        ok, _remaining, retry = burst.check(who(request))
        if ok:
            return None
        return _err(
            429,
            "rate_limited",
            f"Too many requests. Retry in {retry} seconds.",
            {"Retry-After": str(retry)},
            retry_after_s=retry,
        )

    def daily_refusal(request: Request, endpoint: str) -> tuple[Response | None, int]:
        ok, remaining = counters[endpoint].hit(who(request))
        if ok:
            return None, remaining
        reset = reset_time(today())
        retry = max(1, int((reset - clock_now()).total_seconds()))
        limit = counters[endpoint].limit
        return (
            _err(
                429,
                "rate_limited",
                f"Daily limit of {limit} {endpoint} requests reached. Resets at {_iso(reset)}.",
                {"Retry-After": str(retry)},
                retry_after_s=retry,
            ),
            0,
        )

    async def read_capped(request: Request, cap: int) -> bytes | Response:
        declared = request.headers.get("content-length", "")
        if declared.isdigit() and int(declared) > cap:
            return _err(413, "too_large", "The upload is too large.")
        chunks: list[bytes] = []
        size = 0
        try:
            async for chunk in request.stream():
                size += len(chunk)
                if size > cap:
                    return _err(413, "too_large", "The upload is too large.")
                chunks.append(chunk)
        except ClientDisconnect:
            return Response(status_code=400)
        return b"".join(chunks)

    def invalid(exc: ValidationError) -> Response:
        where = ", ".join(sorted({str(x["loc"][-1]) for x in exc.errors() if x.get("loc")}))
        return _err(422, "invalid_input", f"Invalid input: {where or 'request'}.")

    def room_for_live() -> str | None:
        """Why no live call can start (``None`` when one can)."""
        if not be.live_enabled():
            return "live_off" if _key() else "no_model"
        if no_shared_ledger:
            return "live_off"
        return None

    def log(
        endpoint: str, mode: str, started: float, status: int = 200, tier: str | None = None
    ) -> None:
        """One line per request: no address, no text, no bytes."""
        logger.info(
            "live_request",
            endpoint=endpoint,
            mode=mode,
            tier=tier,
            status=status,
            ms=int((be.clock() - started) * 1000),
        )

    def free_answer(body: AskIn) -> dict[str, Any] | None:
        """A tier 1, 2 or 3 answer (no model, $0), or None when Muse Spark must answer."""
        t0 = be.clock()
        r = chat.route_for(data, body.question, body.product_code, has_history=bool(body.history))
        if r.tier == "canned":
            return chat.canned_body(r, (be.clock() - t0) * 1000.0)
        if r.tier == "direct":
            found = direct_answer(data, r)
            return chat.direct_body(found, (be.clock() - t0) * 1000.0)
        if cacheable(body.question, r, has_history=bool(body.history)):
            hit = live_cache.get(body.question, body.product_code)
            if hit is not None:
                return chat.cached_body(hit, (be.clock() - t0) * 1000.0)
        return None

    # --- ask ---------------------------------------------------------------------------

    def do_ask(body: AskIn) -> AskOutcome:
        return ask_detailed(
            data,
            with_code(body.question, body.product_code),
            key_id=LEDGER_ID,
            runtime=runtime(cfg.ask_usd, ASK_BUDGET_S),
            history=history_pairs(body.history),
        )

    @app.post(ASK_PATH, include_in_schema=False)
    async def live_ask(request: Request) -> Response:
        started = be.clock()
        if (blocked := burst_refusal(request)) is not None:
            return blocked
        raw = await read_capped(request, MAX_JSON_BYTES)
        if isinstance(raw, Response):
            return raw
        try:
            payload = json.loads(raw)
            body = AskIn.model_validate(payload)
        except ValueError as exc:
            if isinstance(exc, ValidationError):
                return invalid(exc)
            return _err(422, "invalid_input", "Body must be a JSON object.")
        if phi_in([body.question, *history_texts(body.history)]):
            return _err(422, "patient_data", PHI_MESSAGE)
        if tiers:
            free = await run_in_threadpool(free_answer, body)
            if free is not None:
                free["limits"] = limits(counters["ask"].peek(who(request)))
                log("ask", free["mode"], started, tier=free["tier"])
                return JSONResponse(free, headers={"Cache-Control": "no-store"})
        refused, remaining = daily_refusal(request, "ask")
        if refused is not None:
            return refused
        try:
            outcome = await run_in_threadpool(do_ask, body)
        except InvalidInputError as exc:
            return _err(422, "invalid_input", str(exc))
        except SourceUnavailableError:
            return _err(503, "unavailable", "No answer is available right now.")
        response = _ask_response(outcome, limits(remaining))
        if tiers and outcome.live:
            r = chat.route_for(
                data, body.question, body.product_code, has_history=bool(body.history)
            )
            if cacheable(body.question, r, has_history=bool(body.history)):
                live_cache.put(body.question, body.product_code, chat.cache_entry(response))
        log("ask", response["mode"], started, tier="live")
        return JSONResponse(response, headers={"Cache-Control": "no-store"})

    # --- outside mentions (no model; free public sources; inside the global cost cap) -------

    def do_mentions(body: MentionsIn) -> tuple[dict[str, Any], str | None]:
        """``(body_without_limits, recorded_reason)``; the reason is None for a live result."""
        # No Meta call is made and nothing costs money, so the spend ledger is not used.
        found = search_mentions(
            body.product_code,
            body.device_terms,
            be.mentions_fetcher(),
            clock=be.clock,
            now=clock_now,
            sleep=be.sleep,
        )
        if found.network_ok:
            return found.as_dict() | {"label": LABEL, "mode": "live"}, None
        reason = "unreachable"
        stored = load_recorded(be.mentions_dir, body.product_code) or empty_recorded(
            body.product_code, clock_now()
        )
        note = _MENTIONS_NOTES[reason]
        if not stored.get("searched_utc"):
            note += " No stored mentions exist for this product code."
        else:
            note += f" Shown instead: the stored search of {str(stored['searched_utc'])[:10]}."
        return stored | {"label": LABEL, "mode": "recorded", "recorded_note": note}, reason

    @app.post(MENTIONS_PATH, include_in_schema=False)
    async def live_mentions(request: Request) -> Response:
        started = be.clock()
        if (blocked := burst_refusal(request)) is not None:
            return blocked
        raw = await read_capped(request, MAX_JSON_BYTES)
        if isinstance(raw, Response):
            return raw
        try:
            body = MentionsIn.model_validate(json.loads(raw))
        except ValueError as exc:
            if isinstance(exc, ValidationError):
                return invalid(exc)
            return _err(422, "invalid_input", "Body must be a JSON object.")
        if phi_in(body.device_terms):
            return _err(422, "patient_data", PHI_MESSAGE)
        refused, remaining = daily_refusal(request, "mentions")
        if refused is not None:
            return refused
        out, reason = await run_in_threadpool(do_mentions, body)
        out["limits"] = limits(remaining)
        log("mentions", "recorded" if reason else "live", started)
        return JSONResponse(out, headers={"Cache-Control": "no-store"})

    def _ask_response(outcome: AskOutcome, lim: dict[str, Any]) -> dict[str, Any]:
        out: dict[str, Any] = {
            "mode": "live" if outcome.live else "recorded",
            "tier": "live",
            "not_medical_advice": NOT_MEDICAL_ADVICE,
            "answer": answer_block(outcome.answer),
            "trace": ask_trace(outcome),
            "cost_usd": _cost(outcome.cost_usd),
            "limits": lim,
        }
        if not outcome.live:
            out["recorded_note"] = recorded_note(outcome)
        return out

    # --- voice -------------------------------------------------------------------------

    def do_voice(
        wav: bytes, seconds: float, meta: MetaIn, deadline: float
    ) -> tuple[dict[str, Any], int | None, str | None]:
        """Transcribe and answer within ``deadline``.

        ``deadline`` is a reading of the backend clock for the whole request. Returns
        ``(response_without_limits, http_status, code)``.
        """
        trace: list[dict[str, Any]] = []
        pairs = history_pairs(meta.history)
        reason = room_for_live()
        heard: str | None = None
        transcribe_cost = 0.0
        if reason is None and deadline - be.clock() < MIN_CALL_BUDGET_S * 2:
            reason = "timeout"
        if reason is None and meter is not None:
            t0 = be.clock()
            try:
                transcriber = be.transcriber(min(VOICE_TRANSCRIBE_TIMEOUT_S, deadline - be.clock()))
                transcript = meter.transcribe(seconds, lambda: transcriber.transcribe_bytes(wav))
                ms = (be.clock() - t0) * 1000
                transcribe_cost = estimate_cost_usd(seconds)
                heard = transcript.text.strip()
                trace.append(_step("Muse Voice Transcribe", VOICE_MODEL, ms, "ok"))
            except CallRefusedError:
                reason = "cap"
            except VoiceTranscribeError as exc:
                reason = "no_transcript"
                trace.append(
                    _step(
                        "Muse Voice Transcribe",
                        VOICE_MODEL,
                        (be.clock() - t0) * 1000,
                        "failed",
                        f"transcription failed ({type(exc).__name__})",
                    )
                )
            except Exception as exc:  # noqa: BLE001 - never fail the visitor on this
                logger.warning("live_voice_transcribe_failed", error_type=type(exc).__name__)
                reason = "no_transcript"
                trace.append(
                    _step(
                        "Muse Voice Transcribe",
                        VOICE_MODEL,
                        (be.clock() - t0) * 1000,
                        "failed",
                        f"transcription failed ({type(exc).__name__})",
                    )
                )
        if heard is None:
            if not trace:  # no transcription was tried: say why
                trace.append(
                    _step(
                        "Muse Voice Transcribe",
                        VOICE_MODEL,
                        0,
                        "skipped",
                        _REASON_NOTES.get(reason or "", ""),
                    )
                )
            outcome = recorded_voice_answer(data, reason or "no_model")
            trace.extend(ask_trace(outcome))
            return (
                {
                    "mode": "recorded",
                    "not_medical_advice": NOT_MEDICAL_ADVICE,
                    "recorded_note": recorded_note(outcome),
                    "answer": answer_block(outcome.answer),
                    "trace": trace,
                    "cost_usd": _cost(transcribe_cost),
                },
                None,
                None,
            )
        if not heard:
            return {}, 422, "no_speech"
        if phi_in([heard]):
            return {}, 422, "patient_data"
        question = with_code(heard, meta.product_code)
        left = deadline - be.clock()
        if left < MIN_CALL_BUDGET_S:
            # No time left for the answer: the words were heard, a recorded run answers.
            outcome = recorded_voice_answer(data, "timeout")
            trace.append(
                _step(
                    "Muse Spark answers from stored records",
                    SPARK_MODEL,
                    0,
                    "skipped",
                    _REASON_NOTES["timeout"],
                )
            )
            trace.extend(ask_trace(outcome)[1:])
            return (
                {
                    "mode": "recorded",
                    "not_medical_advice": NOT_MEDICAL_ADVICE,
                    "heard": heard,
                    "recorded_note": recorded_note(outcome),
                    "answer": answer_block(outcome.answer),
                    "trace": trace,
                    "cost_usd": _cost(transcribe_cost),
                },
                None,
                None,
            )
        rt = runtime(max(cfg.voice_usd - transcribe_cost, 0.01), left)
        outcome = ask_detailed(
            data, question, key_id=LEDGER_ID, runtime=rt, history=pairs, spoken=True
        )
        trace.extend(ask_trace(outcome))
        resp: dict[str, Any] = {
            "mode": "live" if outcome.live else "recorded",
            "not_medical_advice": NOT_MEDICAL_ADVICE,
            "heard": heard,
            "answer": answer_block(outcome.answer),
            "trace": trace,
            "cost_usd": _cost(transcribe_cost + outcome.cost_usd),
        }
        if not outcome.live:
            resp["recorded_note"] = recorded_note(outcome)
        return resp, None, None

    @app.post(VOICE_PATH, include_in_schema=False)
    async def live_voice(request: Request) -> Response:
        started = be.clock()
        if (blocked := burst_refusal(request)) is not None:
            return blocked
        raw = await read_capped(request, MAX_AUDIO_BYTES + MAX_META_BYTES + MULTIPART_OVERHEAD)
        if isinstance(raw, Response):
            return raw
        parts = parse_multipart(raw, request.headers.get("content-type", ""))
        if parts is None or "audio" not in parts:
            return _err(422, "invalid_input", "Send multipart/form-data with an audio part.")
        wav = parts["audio"][1]
        del raw
        try:
            seconds = check_audio(wav)
        except UploadError as exc:
            return _err(exc.status, exc.code, exc.message)
        meta = MetaIn()
        if "meta" in parts:
            if len(parts["meta"][1]) > MAX_META_BYTES:
                return _err(413, "too_large", "The meta part is too large.")
            try:
                meta = MetaIn.model_validate(json.loads(parts["meta"][1]))
            except ValidationError as exc:
                return invalid(exc)
            except ValueError:
                return _err(422, "invalid_input", "The meta part must be a JSON object.")
        if phi_in(history_texts(meta.history)):
            return _err(422, "patient_data", PHI_MESSAGE)
        refused, remaining = daily_refusal(request, "voice")
        if refused is not None:
            return refused
        try:
            response, status, code = await run_in_threadpool(
                do_voice, wav, seconds, meta, started + VOICE_REQUEST_BUDGET_S
            )
        except SourceUnavailableError:
            return _err(503, "unavailable", "No answer is available right now.")
        except InvalidInputError as exc:
            return _err(422, "invalid_input", str(exc))
        if status is not None:
            if code == "patient_data":
                return _err(422, "patient_data", PHI_MESSAGE)
            return _err(422, "invalid_input", "No speech was heard in the recording. Try again.")
        response["limits"] = limits(remaining)
        log("voice", response["mode"], started)
        return JSONResponse(response, headers={"Cache-Control": "no-store"})

    # --- label -------------------------------------------------------------------------

    def recorded_label_response(
        reason: str, note: str, trace: list[dict[str, Any]], cost: float
    ) -> dict[str, Any]:
        stored = recorded_label(be.vision_dir)
        if stored is None:
            raise SourceUnavailableError("No recorded label run is stored.")
        reading, matches, image_file = stored
        text = (
            f"{note} Shown instead: a stored run on a sample photo"
            + (f" ({image_file})." if image_file else ".")
            + " It is not your photo."
        )
        return {
            "mode": "recorded",
            "not_medical_advice": NOT_MEDICAL_ADVICE,
            "recorded_note": _safe_text(text),
            "reading": _reading_block(reading, []),
            "matches": matches,
            "confirmed": None,
            "trace": trace,
            "cost_usd": _cost(cost),
        }

    def do_label(jpeg: bytes, re_encode_ms: float) -> dict[str, Any]:
        t_start = be.clock()
        trace: list[dict[str, Any]] = [
            _step("Re-encode photo, drop metadata", None, re_encode_ms, "ok")
        ]
        reason = room_for_live()
        if reason is not None:
            trace.append(_step("SAM 3.1 crop", SAM_MODEL, 0, "skipped", _REASON_NOTES[reason]))
            trace.append(_step("Muse Spark read", SPARK_MODEL, 0, "skipped", _REASON_NOTES[reason]))
            return recorded_label_response(reason, _REASON_NOTES[reason], trace, 0.0)
        cost = 0.0
        guard = SpendGuard(
            session_id="live-label",
            caps=SpendCaps(
                session_usd=cfg.label_usd,
                session_calls=4,
                daily_usd=cfg.daily_usd,
                call_reserve_usd=worst_case_call_usd(),
            ),
            ledger=MemoryLedger(today=today),
            db=None,
            meter=meter,
        )
        deadline = t_start + LABEL_BUDGET_S
        sam = be.sam(SAM_CALL_TIMEOUT_S)
        result: LabelResult | None = None
        steps: list[dict[str, Any]] = []
        failure: str | None = None
        try:
            client = guard.wrap(be.spark_client(deadline, be.clock))
            metered_sam: Any = None
            if sam is not None and meter is not None:
                metered_sam = _DeadlineSam(
                    _MeteredSam(sam, meter),  # type: ignore[arg-type]
                    t_start + SAM_PROMPT_DEADLINE_S,
                    be.clock,
                )
            result, steps = read_label_timed(
                jpeg, client=client, sam=metered_sam, model=SPARK_MODEL
            )
        except SpendLimitError:
            failure = _REASON_NOTES["cap"]
        except Exception as exc:  # noqa: BLE001 - any model failure falls back to a recording
            logger.warning("live_label_read_failed", error_type=type(exc).__name__)
            timed_out = be.clock() >= deadline - MIN_CALL_BUDGET_S or "TimeoutError" in str(exc)
            if "SpendLimitError" in str(exc) or "CallRefused" in str(exc):
                failure = _REASON_NOTES["cap"]
            elif timed_out:
                failure = "The live read took longer than the time limit."
            else:
                failure = _REASON_NOTES["model_error"]
        if result is not None:
            cost = result.cost_usd
        if result is None or failure:
            trace.append(
                _step(
                    "Muse Spark read",
                    SPARK_MODEL,
                    (be.clock() - t_start) * 1000,
                    "failed",
                    failure,
                )
            )
            return recorded_label_response(
                "model_error", failure or _REASON_NOTES["model_error"], trace, cost
            )
        trace.extend(_label_read_steps(steps))
        withheld = [n for n in ("lot", "serial") if result.fields.get(n) and result.fields[n].value]
        reading = result.to_dict()
        search_info = {
            "model": result.model,
            "skill_version": result.skill_version,
            "input_tokens": result.input_tokens,
            "output_tokens": result.output_tokens,
            "cost_usd": result.cost_usd,
        }
        searcher = _DeadlineSearcher(
            be.searcher(OPENFDA_CALL_TIMEOUT_S), t_start + OPENFDA_DEADLINE_S, be.clock
        )
        t_search = be.clock()
        matched = match_label(
            reading, searcher=searcher, check_fn=None, read_steps=[], model_info=search_info
        )
        trace.append(_openfda_step(matched, (be.clock() - t_search) * 1000))
        return {
            "mode": "live",
            "not_medical_advice": NOT_MEDICAL_ADVICE,
            "reading": _reading_block(reading, withheld),
            "matches": _matches_block(
                list(matched.get("matches") or []),
                search_failed=_search_failed(
                    matched, deadline_passed=be.clock() > t_start + OPENFDA_DEADLINE_S
                ),
            ),
            "confirmed": None,
            "trace": trace,
            "cost_usd": _cost(cost),
        }

    @app.post(LABEL_PATH, include_in_schema=False)
    async def live_label(request: Request) -> Response:
        started = be.clock()
        if (blocked := burst_refusal(request)) is not None:
            return blocked
        raw = await read_capped(request, MAX_IMAGE_BYTES + MULTIPART_OVERHEAD)
        if isinstance(raw, Response):
            return raw
        parts = parse_multipart(raw, request.headers.get("content-type", ""))
        if parts is None or "image" not in parts:
            return _err(422, "invalid_input", "Send multipart/form-data with an image part.")
        ctype, image = parts["image"]
        del raw
        t0 = be.clock()
        try:
            jpeg, _size = clean_image(image, ctype)
        except UploadError as exc:
            return _err(exc.status, exc.code, exc.message)
        re_encode_ms = (be.clock() - t0) * 1000
        del image, parts
        refused, remaining = daily_refusal(request, "label")
        if refused is not None:
            return refused
        try:
            response = await run_in_threadpool(do_label, jpeg, re_encode_ms)
        except SourceUnavailableError:
            return _err(503, "unavailable", "No answer is available right now.")
        response["limits"] = limits(remaining)
        log("label", response["mode"], started)
        return JSONResponse(response, headers={"Cache-Control": "no-store"})


def _label_read_steps(steps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Map ``read_label_timed`` steps (SAM, Spark) to the contract's trace."""
    out: list[dict[str, Any]] = []
    for s in steps:
        measured = s.get("timing") == "measured" and s.get("elapsed_ms") is not None
        is_sam = "SAM" in str(s.get("step"))
        out.append(
            _step(
                "SAM 3.1 crop" if is_sam else "Muse Spark read",
                SAM_MODEL if is_sam else SPARK_MODEL,
                float(s.get("elapsed_ms") or 0.0),
                "ok" if measured else "skipped",
                str(s.get("note")) if s.get("note") else None,
            )
        )
    return out


def _search_failed(matched: dict[str, Any], *, deadline_passed: bool) -> bool:
    """True when openFDA could not be searched: every query failed, or the deadline stopped them.

    A label with nothing to search for (no queries planned, time left) is a real "no match".
    """
    queries = list(matched.get("queries") or [])
    if queries:
        return all(not q.get("ok") for q in queries)
    return deadline_passed


def _openfda_step(matched: dict[str, Any], wall_ms: float) -> dict[str, Any]:
    queries = list(matched.get("queries") or [])
    failed = sum(1 for q in queries if not q.get("ok"))
    note = f"{len(queries)} openFDA search(es)" + (f", {failed} failed" if failed else "")
    status = "failed" if queries and failed == len(queries) else "ok"
    return _step("openFDA search for possible matches", None, wall_ms, status, note)


__all__ = [
    "ASK_PATH",
    "LABEL_PATH",
    "LIVE_PATHS",
    "VOICE_PATH",
    "LiveBackends",
    "LiveConfig",
    "mount_live",
]
