"""Vercel entry point: exports the read-only MaudeSignal connector API as ``app``.

HACKATHON-BUILT — Meta Global AI Developer Hackathon (Oct 26 – Nov 4, 2026).

Keys and caps come from environment variables set in the Vercel project (never in
git): MAUDESIGNAL_API_KEYS, MAUDESIGNAL_RATE_LIMIT_PER_MIN, MAUDESIGNAL_API_DAILY_USD,
META_MODEL_API_KEY (optional; without it ask() returns recorded answers).
"""

from __future__ import annotations

import sys
from pathlib import Path

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from fastapi import FastAPI  # noqa: E402

from maudesignal.connector.app import create_app  # noqa: E402

app: FastAPI = create_app()
