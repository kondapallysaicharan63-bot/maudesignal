"""Audio helper for the live checks: a WAV file as 16 kHz mono 16-bit PCM (standard library).

HACKATHON-BUILT — Meta Global AI Developer Hackathon (Oct 26 – Nov 4, 2026).

The voice route accepts only 16 kHz mono PCM16 WAV. ``demo/voice/question-a.wav`` and other
recordings may use another rate, so they are resampled here by linear interpolation.
"""

from __future__ import annotations

import array
import io
import sys
import wave
from pathlib import Path

TARGET_RATE = 16000


def to_16k_mono_pcm16(data: bytes) -> bytes:
    """Return ``data`` (a WAV file's bytes) as a 16 kHz mono PCM16 WAV file's bytes.

    Raises:
        ValueError: The sample width is not 8, 16 or 32 bits.
    """
    with wave.open(io.BytesIO(data), "rb") as w:
        channels, width, rate = w.getnchannels(), w.getsampwidth(), w.getframerate()
        raw = w.readframes(w.getnframes())
    if width == 2 and channels == 1 and rate == TARGET_RATE:
        return data
    if width == 1:
        samples = [(b - 128) * 256.0 for b in raw]
    elif width == 2:
        arr = array.array("h")
        arr.frombytes(raw[: len(raw) - len(raw) % 2])
        if sys.byteorder == "big":
            arr.byteswap()
        samples = [float(s) for s in arr]
    elif width == 4:
        arr32 = array.array("i")
        arr32.frombytes(raw[: len(raw) - len(raw) % 4])
        if sys.byteorder == "big":
            arr32.byteswap()
        samples = [s / 65536.0 for s in arr32]
    else:
        raise ValueError(f"unsupported sample width {width}")
    if channels > 1:
        frames = len(samples) // channels
        samples = [
            sum(samples[i * channels : (i + 1) * channels]) / channels for i in range(frames)
        ]
    if rate != TARGET_RATE and samples:
        n = round(len(samples) * TARGET_RATE / rate)
        step = (len(samples) - 1) / max(1, n - 1)
        out = []
        for i in range(n):
            pos = i * step
            lo = int(pos)
            hi = min(lo + 1, len(samples) - 1)
            frac = pos - lo
            out.append(samples[lo] * (1 - frac) + samples[hi] * frac)
        samples = out
    pcm = array.array("h", [max(-32768, min(32767, round(s))) for s in samples])
    if sys.byteorder == "big":
        pcm.byteswap()
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(TARGET_RATE)
        w.writeframes(pcm.tobytes())
    return buf.getvalue()


def wav_info(data: bytes) -> dict[str, float | int]:
    """Channels, sample width in bytes, rate and seconds of a WAV file."""
    with wave.open(io.BytesIO(data), "rb") as w:
        return {
            "channels": w.getnchannels(),
            "width": w.getsampwidth(),
            "rate": w.getframerate(),
            "seconds": w.getnframes() / float(w.getframerate()),
        }


def load_voice(root: Path, names: tuple[str, ...]) -> tuple[str, bytes] | None:
    """The first of ``demo/voice/<name>`` that exists, resampled; ``None`` if none does."""
    for name in names:
        path = root / "demo" / "voice" / name
        if path.is_file():
            return name, to_16k_mono_pcm16(path.read_bytes())
    return None
