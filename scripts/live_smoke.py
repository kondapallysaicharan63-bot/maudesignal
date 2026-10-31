"""Live smoke test of the public Muse routes, in process, with a hard spend cap.

HACKATHON-BUILT — Meta Global AI Developer Hackathon (Oct 26 – Nov 4, 2026).

Runs the real app (``create_app``) through ``fastapi.testclient`` with the real Meta
clients, so it needs ``META_MODEL_API_KEY`` (a repository secret in Actions). It makes:

* 2 chat turns on ``/v1/live/ask`` (the second sends the first as ``history``),
* 1 spoken question on ``/v1/live/voice`` (``demo/voice/question.wav``, or ``question-c.wav``
  when that file is absent; resampled to 16 kHz mono PCM16 when it is not already),
* 1 photo on ``/v1/live/label`` (``demo/vision/labels/label-caresens-n.jpg``).

The total is capped at ``HARD_CAP_USD`` ($0.60): the app's own global cap is set to it and the
per-request caps are lower, and a step is skipped when the money spent so far plus that step's
cap would pass it. Nothing is run when there is no key.

It writes ``demo/live-smoke/result.json`` (mode, trace, cost, gate counts, what was heard,
match status). The file holds no key, no address and no uploaded bytes.

    python3 scripts/live_smoke.py [--out demo/live-smoke/result.json]

Exit code 0 when every step answered with HTTP 200, 1 when some did not, 2 with no key.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import wave
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from fastapi.testclient import TestClient  # noqa: E402

from maudesignal.connector.app import Settings, create_app  # noqa: E402
from maudesignal.connector.live import LiveConfig  # noqa: E402
from maudesignal.connector.store import ConnectorState  # noqa: E402

HARD_CAP_USD = 0.60
ASK_CAP, VOICE_CAP, LABEL_CAP = 0.12, 0.12, 0.15
QUESTIONS = (
    "What changed this week for LLZ?",
    "Which of those reports were not filed by the manufacturer?",
)
VOICE_FILES = ("question.wav", "question-c.wav")
LABEL_PHOTO = "demo/vision/labels/label-caresens-n.jpg"
OUT = ROOT / "demo" / "live-smoke" / "result.json"
TARGET_RATE = 16000


def to_16k_mono_pcm16(path: Path) -> bytes:
    """The WAV file as 16 kHz mono PCM16 bytes (resampled by linear interpolation if needed)."""
    with wave.open(str(path), "rb") as w:
        channels, width, rate = w.getnchannels(), w.getsampwidth(), w.getframerate()
        raw = w.readframes(w.getnframes())
    if width == 2 and channels == 1 and rate == TARGET_RATE:
        return path.read_bytes()
    dtype = {1: np.uint8, 2: np.int16, 4: np.int32}.get(width)
    if dtype is None:
        raise ValueError(f"unsupported sample width {width}")
    samples = np.frombuffer(raw, dtype=dtype).astype(np.float64)
    if width == 1:
        samples = (samples - 128.0) * 256.0
    elif width == 4:
        samples = samples / 65536.0
    if channels > 1:
        samples = samples.reshape(-1, channels).mean(axis=1)
    if rate != TARGET_RATE:
        n = round(len(samples) * TARGET_RATE / rate)
        samples = np.interp(np.linspace(0, len(samples) - 1, n), np.arange(len(samples)), samples)
    out = np.clip(np.round(samples), -32768, 32767).astype(np.int16)
    import io

    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(TARGET_RATE)
        w.writeframes(out.tobytes())
    return buf.getvalue()


def summarize(name: str, status: int, body: dict[str, Any]) -> dict[str, Any]:
    """The part of a response worth keeping: no key, no address, no uploaded bytes."""
    answer = body.get("answer") or {}
    out: dict[str, Any] = {
        "step": name,
        "http_status": status,
        "mode": body.get("mode"),
        "cost_usd": body.get("cost_usd"),
        "trace": body.get("trace"),
        "limits": body.get("limits"),
    }
    if answer:
        out["gate"] = {
            "passed_with_link": len(answer.get("speakable") or []),
            "withheld": len(answer.get("withheld") or []),
        }
        out["spoken_text"] = answer.get("spoken_text")
    if "heard" in body:
        out["heard"] = body["heard"]
    if "matches" in body:
        out["match_status"] = body["matches"].get("status")
        out["candidates"] = len(body["matches"].get("candidates") or [])
        out["confirmed"] = body.get("confirmed")
    if body.get("recorded_note"):
        out["recorded_note"] = body["recorded_note"]
    if status != 200:
        out["error_code"] = body.get("code")
    return out


def main(argv: list[str] | None = None) -> int:
    """Run the smoke test; returns the exit code."""
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--out", type=Path, default=OUT)
    args = ap.parse_args(argv)
    if not os.environ.get("META_MODEL_API_KEY"):
        print("META_MODEL_API_KEY is not set: nothing was run.")
        return 2
    # One process, its own in-memory per-call ledger (cap: HARD_CAP_USD minus one call's hold).
    os.environ.setdefault("MAUDESIGNAL_ALLOW_PER_INSTANCE_CAP", "1")
    cfg = LiveConfig(
        ask_per_day=10,
        voice_per_day=10,
        label_per_day=10,
        burst_per_min=100,
        daily_usd=HARD_CAP_USD,
        ask_usd=ASK_CAP,
        voice_usd=VOICE_CAP,
        label_usd=LABEL_CAP,
    )
    # Chat tiers off: this smoke exists to exercise the Muse Spark path (tier 4) itself.
    app = create_app(Settings(live_config=cfg, state=ConnectorState(), chat_tiers=False))
    client = TestClient(app, raise_server_exceptions=False)
    steps: list[dict[str, Any]] = []
    spent = 0.0

    def can_run(cap: float) -> bool:
        return spent + cap <= HARD_CAP_USD

    def record(name: str, resp: Any) -> dict[str, Any]:
        nonlocal spent
        body = resp.json()
        steps.append(summarize(name, resp.status_code, body))
        spent += float(body.get("cost_usd") or 0.0)
        print(
            f"{name}: HTTP {resp.status_code}, mode={body.get('mode')}, cost={body.get('cost_usd')}"
        )
        return dict(body)

    first: dict[str, Any] = {}
    if can_run(ASK_CAP):
        first = record("ask 1", client.post("/v1/live/ask", json={"question": QUESTIONS[0]}))
    if can_run(ASK_CAP):
        history = []
        if first.get("answer"):
            history = [{"question": QUESTIONS[0], "answer": first["answer"]["spoken_text"]}]
        record(
            "ask 2 (with history)",
            client.post("/v1/live/ask", json={"question": QUESTIONS[1], "history": history}),
        )
    wav_path = next(
        (
            ROOT / "demo" / "voice" / n
            for n in VOICE_FILES
            if (ROOT / "demo" / "voice" / n).exists()
        ),
        None,
    )
    if wav_path is not None and can_run(VOICE_CAP):
        wav = to_16k_mono_pcm16(wav_path)
        record("voice", client.post("/v1/live/voice", files={"audio": ("q.wav", wav, "audio/wav")}))
    photo = ROOT / LABEL_PHOTO
    if photo.exists() and can_run(LABEL_CAP):
        record(
            "label",
            client.post(
                "/v1/live/label", files={"image": (photo.name, photo.read_bytes(), "image/jpeg")}
            ),
        )
    result = {
        "kind": "live_smoke",
        "run_utc": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "hard_cap_usd": HARD_CAP_USD,
        "total_cost_usd": round(spent, 6),
        "voice_file": wav_path.name if wav_path else None,
        "steps": steps,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"total cost ${spent:.4f} (cap ${HARD_CAP_USD:.2f}); wrote {args.out}")
    return 0 if len(steps) == 4 and all(s["http_status"] == 200 for s in steps) else 1


if __name__ == "__main__":
    raise SystemExit(main())
