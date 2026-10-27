"""Day 1 smoke test: Meta Model API connection + streaming.

HACKATHON-BUILT — Meta Global AI Developer Hackathon, Oct 26, 2026.

Usage:
    META_MODEL_API_KEY=... META_MODEL_API_BASE_URL=... \\
        META_MODEL_API_MODEL=... python test_meta_connection.py

The key comes from the environment only. Never paste a key into this file,
never commit a .env file. See .env.example for the variable names.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, "src")

from maudesignal.copilot import MetaProvider, SafetyCopilot


def main() -> int:
    api_key = os.environ.get("META_MODEL_API_KEY", "")
    base_url = os.environ.get("META_MODEL_API_BASE_URL", "")
    model = os.environ.get("META_MODEL_API_MODEL", "")
    missing = [
        name
        for name, value in (
            ("META_MODEL_API_KEY", api_key),
            ("META_MODEL_API_BASE_URL", base_url),
            ("META_MODEL_API_MODEL", model),
        )
        if not value
    ]
    if missing:
        print(f"MISSING env vars: {', '.join(missing)}")
        print("Copy .env.example to .env and fill in your values (do not commit .env).")
        return 2

    from openai import OpenAI

    ids = sorted(m.id for m in OpenAI(api_key=api_key, base_url=base_url).models.list())
    print(f"models.list OK: {len(ids)} models; {model} available: {model in ids}")
    print(f"models.list ids: {', '.join(ids)}")
    # Every model id the hackathon features call; a missing one 404s at run time.
    for needed in (
        "muse-spark-1.3",
        "muse-wonder-1.0",
        "muse-image-1.0",
        "muse-voice-transcribe-1.0",
        "sam-3.1",
    ):
        print(f"  {needed}: {'listed' if needed in ids else 'NOT LISTED'}")

    provider = MetaProvider(api_key=api_key, model=model, base_url=base_url)
    copilot = SafetyCopilot(provider)
    print(f"Model: {provider.model} | Provider: {provider.provider_name}")
    print("Streaming test answer:")
    for delta in copilot.ask_stream(
        "In one sentence, what is postmarket surveillance for medical devices?"
    ):
        print(delta, end="", flush=True)
    print("\nSTREAM OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
