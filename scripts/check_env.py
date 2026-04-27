"""One-shot env check."""

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(".env"))

KEYS = [
    "GEMINI_API_KEY",
    "GEMINI_API_KEY_2",
    "GEMINI_API_KEY_3",
    "GROQ_API_KEY",
    "GROQ_API_KEY_2",
    "OPENFDA_API_KEY",
]
missing = []
for k in KEYS:
    v = os.environ.get(k, "")
    print(f"{k}: {'SET (' + str(len(v)) + ' chars)' if v else 'MISSING'}")
    if not v:
        missing.append(k)
print(f"PROVIDER_FALLBACK_ORDER: {os.environ.get('PROVIDER_FALLBACK_ORDER', '')!r}")
if missing:
    print(f"\nMISSING: {missing}")
    raise SystemExit(1)
print("\nALL KEYS PRESENT")
