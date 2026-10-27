"""Ask the copilot by voice: Meta Voice Transcribe → transcript text → ``CopilotAgent.ask``.

HACKATHON-BUILT — Meta Global AI Developer Hackathon (Oct 26 – Nov 4, 2026).

Second Meta AI surface. Audio is NEVER sent to the chat model: Muse Spark's audio
input is degraded, so the clip is transcribed first with Muse Voice Transcribe
(file endpoint ``POST /v1/asr/transcribe``) and only the text reaches the agent.
The transcript is returned with the answer so the analyst sees exactly what was
heard before trusting what was answered.

Request/response format as documented at https://dev.meta.ai/docs/speech-to-text
and https://dev.meta.ai/docs/api-reference/voice/transcribe (read 2026-10-27; see
``docs/hackathon/VOICE_API_NOTES.md``). Every wire-level name is a module constant
so a doc change is a one-line edit.

The API key is passed to the constructor, sent only in the ``Authorization``
header, and never logged, stored or included in an exception message.
"""

from __future__ import annotations

import io
import json
import math
import wave
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

import httpx

from maudesignal.common.exceptions import MaudeSignalError

if TYPE_CHECKING:  # pragma: no cover
    from maudesignal.copilot.agent import CopilotAgent, CopilotResult

# --- Wire format (documented; see module docstring) --------------------------------
DEFAULT_BASE_URL = "https://api.meta.ai/v1"
TRANSCRIBE_PATH = "/asr/transcribe"
DEFAULT_VOICE_MODEL = "muse-voice-transcribe-1.0"
FIELD_REQUEST = "request"  # multipart part: JSON settings (application/json)
FIELD_AUDIO = "audio"  # multipart part: the WAV clip (audio/wav)
AUDIO_ENCODING = "WAV"  # only documented value of ``audioEncoding``
MODE = "PUSH_TO_TALK"  # documented default; one utterance, ``turns`` is empty
RESPONSE_TEXT = "transcript"
RESPONSE_DURATION_MS = "audioDurationMs"
RESPONSE_SESSION = "sessionId"

# --- Documented limits ---------------------------------------------------------------
MAX_BODY_BYTES = 32 * 1000 * 1000  # "32 MB" (413 above); decimal MB is the safe reading
MAX_AUDIO_SECONDS = 600.0  # 10 minutes (400 above)
SUPPORTED_SAMPLE_RATES = (16000, 24000)
SUPPORTED_EXTENSIONS = (".wav",)
RETRYABLE_STATUS = frozenset({429, 500, 503})

# --- Pricing ------------------------------------------------------------------------
# "$0.18 per hour" of audio, billed in whole seconds, rounded down (speech-to-text page).
VOICE_USD_PER_AUDIO_HOUR = 0.18

# Recognition hints (ASR vocabulary bias, not an LLM prompt): domain terms an analyst
# will say that a general model may mis-spell.
DEFAULT_KEYWORDS: tuple[str, ...] = ("MAUDE", "MDR", "CAPA", "510(k)", "CFR", "openFDA")
DEFAULT_LANGUAGE_BIAS: tuple[str, ...] = ("English",)


class VoiceTranscribeError(MaudeSignalError):
    """Transcription failed (HTTP error, timeout, bad response, or nothing heard)."""

    def __init__(
        self, message: str, *, status_code: int | None = None, retryable: bool = False
    ) -> None:
        """Create the error.

        Args:
            message: Client-safe description (never contains the API key).
            status_code: HTTP status, when the server answered.
            retryable: True for 429/500/503 and timeouts (docs: retry with backoff).
        """
        super().__init__(message)
        self.status_code = status_code
        self.retryable = retryable


class AudioValidationError(VoiceTranscribeError):
    """The clip was rejected locally, before any upload (and before any cost)."""


@dataclass(frozen=True)
class WavInfo:
    """Header facts about a WAV clip."""

    channels: int
    sample_width: int
    sample_rate: int
    seconds: float


@dataclass(frozen=True)
class Transcript:
    """What Muse Voice Transcribe heard."""

    text: str
    language: str | None
    duration_s: float | None
    session_id: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def cost_usd(self) -> float:
        """Estimated transcription cost (0.0 when the duration is unknown)."""
        return estimate_cost_usd(self.duration_s or 0.0)

    def to_voice_block(self) -> dict[str, Any]:
        """The ``voice`` block stored in a copilot transcript JSON."""
        return {
            "transcript_text": self.text,
            "language": self.language,
            "audio_seconds": self.duration_s,
        }


@dataclass(frozen=True)
class VoiceAnswer:
    """A spoken question: what was heard plus the copilot's gated answer."""

    transcript: Transcript
    result: CopilotResult

    @property
    def cost_usd(self) -> float:
        """Transcription + Muse Spark cost."""
        return round(self.transcript.cost_usd + self.result.cost_usd, 6)


def estimate_cost_usd(audio_seconds: float) -> float:
    """Estimated Voice Transcribe cost for a clip.

    Args:
        audio_seconds: Clip duration; billing rounds down to whole seconds.

    Returns:
        USD at the documented $0.18 per audio hour.
    """
    billed = max(0, math.floor(audio_seconds))
    return round(billed * VOICE_USD_PER_AUDIO_HOUR / 3600.0, 6)


def inspect_wav(data: bytes) -> WavInfo:
    """Read a WAV header.

    Raises:
        AudioValidationError: Not a readable RIFF/WAVE PCM file.
    """
    try:
        with wave.open(io.BytesIO(data), "rb") as w:
            rate = w.getframerate()
            return WavInfo(
                channels=w.getnchannels(),
                sample_width=w.getsampwidth(),
                sample_rate=rate,
                seconds=w.getnframes() / rate if rate else 0.0,
            )
    except (wave.Error, EOFError) as exc:
        raise AudioValidationError(f"not a readable PCM WAV file: {exc}") from exc


def validate_audio(data: bytes, filename: str = "audio.wav") -> WavInfo:
    """Check a clip against the documented limits before uploading it.

    The endpoint accepts mono 16-bit PCM WAV at 16 or 24 kHz, at most 10 minutes,
    in a body of at most 32 MB. Rejecting locally saves a round trip and is free.

    Args:
        data: The clip bytes.
        filename: Original file name (extension is checked).

    Returns:
        Header facts for the clip.

    Raises:
        AudioValidationError: The clip would be rejected by the API.
    """
    if not filename.lower().endswith(SUPPORTED_EXTENSIONS):
        raise AudioValidationError(
            f"unsupported file type {Path(filename).suffix or '(none)'!r}; record or convert "
            "to WAV: ffmpeg -i in.m4a -ac 1 -ar 16000 -c:a pcm_s16le out.wav"
        )
    if not data:
        raise AudioValidationError("audio clip is empty")
    if len(data) > MAX_BODY_BYTES:
        raise AudioValidationError(
            f"audio is {len(data) / 1e6:.1f} MB; the limit is {MAX_BODY_BYTES / 1e6:.0f} MB"
        )
    info = inspect_wav(data)
    if info.channels != 1:
        raise AudioValidationError(f"audio must be mono (got {info.channels} channels)")
    if info.sample_width != 2:
        raise AudioValidationError(f"audio must be 16-bit PCM (got {8 * info.sample_width}-bit)")
    if info.sample_rate not in SUPPORTED_SAMPLE_RATES:
        raise AudioValidationError(
            f"sample rate must be 16000 or 24000 Hz (got {info.sample_rate})"
        )
    if info.seconds <= 0:
        raise AudioValidationError("audio clip has no samples")
    if info.seconds > MAX_AUDIO_SECONDS:
        raise AudioValidationError(
            f"audio is {info.seconds:.0f} s; the limit is {MAX_AUDIO_SECONDS:.0f} s"
        )
    return info


def _error_message(resp: httpx.Response) -> str:
    """Pull the documented ``{"error": {"message", "type", "code"}}`` detail, if present."""
    try:
        body = resp.json()
    except ValueError:
        return resp.text[:200]
    err = body.get("error") if isinstance(body, dict) else None
    if isinstance(err, dict):
        parts = [str(err.get("type") or ""), str(err.get("message") or "")]
        if err.get("code"):
            parts.append(f"code={err['code']}")
        return " ".join(p for p in parts if p)[:300]
    return json.dumps(body)[:200]


class MetaTranscriber:
    """Client for Meta Voice Transcribe (file endpoint)."""

    def __init__(
        self,
        api_key: str,
        *,
        base_url: str = DEFAULT_BASE_URL,
        model: str = DEFAULT_VOICE_MODEL,
        timeout_s: float = 60.0,
        language_bias: tuple[str, ...] | None = DEFAULT_LANGUAGE_BIAS,
        keywords: tuple[str, ...] | None = DEFAULT_KEYWORDS,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        """Create a transcriber.

        Args:
            api_key: Meta Model API key (same key as the chat API). Never logged.
            base_url: API base URL, ``https://api.meta.ai/v1`` by default.
            model: Voice model id.
            timeout_s: Total request timeout in seconds (connect is capped at 10 s).
            language_bias: Languages to bias toward; ``None`` lets the model detect.
            keywords: Domain terms to bias recognition toward; ``None`` for none.
            transport: Injected HTTP transport (``httpx.MockTransport`` in tests).

        Raises:
            VoiceTranscribeError: Empty key.
        """
        if not api_key:
            raise VoiceTranscribeError("Meta Model API key is empty")
        self._api_key = api_key
        self._url = base_url.rstrip("/") + TRANSCRIBE_PATH
        self._model = model
        self._language_bias = language_bias
        self._keywords = keywords
        self._client = httpx.Client(
            timeout=httpx.Timeout(timeout_s, connect=min(10.0, timeout_s)),
            transport=transport,
        )

    def __repr__(self) -> str:
        """Representation without the key."""
        return f"MetaTranscriber(url={self._url!r}, model={self._model!r})"

    def __enter__(self) -> MetaTranscriber:
        """Context-manager entry."""
        return self

    def __exit__(self, *exc: object) -> None:
        """Close the HTTP client."""
        self.close()

    def close(self) -> None:
        """Close the HTTP client."""
        self._client.close()

    @property
    def model(self) -> str:
        """Voice model id."""
        return self._model

    def request_settings(self) -> dict[str, Any]:
        """JSON body of the ``request`` multipart part."""
        settings: dict[str, Any] = {
            "model": self._model,
            "audioEncoding": AUDIO_ENCODING,
            "mode": MODE,
        }
        if self._language_bias:
            settings["languageBias"] = list(self._language_bias)
        if self._keywords:
            settings["keywords"] = list(self._keywords)
        return settings

    def transcribe_file(self, path: Path | str) -> Transcript:
        """Transcribe a WAV file on disk."""
        p = Path(path)
        try:
            data = p.read_bytes()
        except OSError as exc:
            raise AudioValidationError(f"cannot read audio file {p.name}: {exc}") from exc
        return self.transcribe_bytes(data, filename=p.name)

    def transcribe_bytes(self, data: bytes, *, filename: str = "audio.wav") -> Transcript:
        """Validate and upload one clip; return what was heard.

        Raises:
            AudioValidationError: Clip rejected locally (no upload, no cost).
            VoiceTranscribeError: HTTP error, timeout, or malformed response.
        """
        validate_audio(data, filename)
        files: dict[str, tuple[str | None, bytes | str, str]] = {
            FIELD_REQUEST: (None, json.dumps(self.request_settings()), "application/json"),
            FIELD_AUDIO: (filename, data, "audio/wav"),
        }
        headers = {"Authorization": f"Bearer {self._api_key}", "Accept": "application/json"}
        try:
            resp = self._client.post(self._url, files=files, headers=headers)
        except httpx.TimeoutException as exc:
            raise VoiceTranscribeError(
                f"Voice Transcribe timed out ({type(exc).__name__})", retryable=True
            ) from exc
        except httpx.HTTPError as exc:
            raise VoiceTranscribeError(
                f"Voice Transcribe request failed ({type(exc).__name__})", retryable=True
            ) from exc
        if resp.status_code >= 400:
            raise VoiceTranscribeError(
                f"Voice Transcribe HTTP {resp.status_code}: {_error_message(resp)}",
                status_code=resp.status_code,
                retryable=resp.status_code in RETRYABLE_STATUS,
            )
        return self._parse(resp)

    def _parse(self, resp: httpx.Response) -> Transcript:
        try:
            body = resp.json()
        except ValueError as exc:
            raise VoiceTranscribeError("Voice Transcribe returned non-JSON") from exc
        if not isinstance(body, dict) or not isinstance(body.get(RESPONSE_TEXT), str):
            raise VoiceTranscribeError(f"Voice Transcribe response has no {RESPONSE_TEXT!r}")
        ms = body.get(RESPONSE_DURATION_MS)
        duration = round(float(ms) / 1000.0, 3) if isinstance(ms, int | float) else None
        # The API does not report a detected language (documented). Use one if a future
        # response carries it; otherwise report the single bias we sent, if any.
        language = body.get("language")
        if not isinstance(language, str):
            bias = self._language_bias or ()
            language = bias[0] if len(bias) == 1 else None
        session = body.get(RESPONSE_SESSION)
        return Transcript(
            text=body[RESPONSE_TEXT].strip(),
            language=language,
            duration_s=duration,
            session_id=session if isinstance(session, str) else None,
            raw=body,
        )


def ask_by_voice(
    transcriber: MetaTranscriber,
    agent: CopilotAgent,
    audio: Path | str | bytes,
    *,
    filename: str = "question.wav",
) -> VoiceAnswer:
    """Transcribe a spoken question, then ask the copilot the transcript text.

    Args:
        transcriber: Voice Transcribe client.
        agent: The copilot (text only — audio never reaches the chat model).
        audio: Path to a WAV file, or the WAV bytes (e.g. from ``st.audio_input``).
        filename: Name used for validation/upload when ``audio`` is bytes.

    Returns:
        The transcript (shown to the analyst) and the gated copilot result.

    Raises:
        AudioValidationError: Clip rejected locally.
        VoiceTranscribeError: Transcription failed or nothing intelligible was heard
            (the model is not called in either case).
    """
    if isinstance(audio, bytes):
        transcript = transcriber.transcribe_bytes(audio, filename=filename)
    else:
        transcript = transcriber.transcribe_file(audio)
    if not transcript.text:
        raise VoiceTranscribeError("no speech was recognised in the recording")
    return VoiceAnswer(transcript=transcript, result=agent.ask(transcript.text))
