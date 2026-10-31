"""The one global daily cost cap shared by every live Muse call (names, defaults, margin).

HACKATHON-BUILT — Meta Global AI Developer Hackathon (Oct 26 – Nov 4, 2026).

``MAUDESIGNAL_LIVE_DAILY_USD`` (default 3.00) is the most the live website routes and the keyed
``ask`` tool may spend per UTC day together. Without Upstash the ledger is a set of small
objects in the private Blob store, one per request (see ``store.BlobLedger``): nothing is
read-modify-written, so no concurrent writer can erase another's hold or cost. A reserve writes
its hold and then lists the day's objects, so two simultaneous requests cannot both miss each
other. The cap enforced on that ledger is still ``daily - largest per-request cap``, which
leaves room for one request cap if a completed write were ever slow to appear in a listing.
"""

from __future__ import annotations

import os

#: Name of the one global ledger (Redis key part, or ``ledger/<name>/<day>.json`` in Blob).
LEDGER_ID = "live-global"
DAILY_USD_ENV = "MAUDESIGNAL_LIVE_DAILY_USD"
ASK_USD_ENV = "MAUDESIGNAL_LIVE_ASK_USD"
VOICE_USD_ENV = "MAUDESIGNAL_LIVE_VOICE_USD"
LABEL_USD_ENV = "MAUDESIGNAL_LIVE_LABEL_USD"
API_REQUEST_USD_ENV = "MAUDESIGNAL_API_REQUEST_USD"
DEFAULT_DAILY_USD = 3.00
DEFAULT_ASK_USD = 0.25
DEFAULT_VOICE_USD = 0.30
DEFAULT_LABEL_USD = 0.30
DEFAULT_API_REQUEST_USD = 0.25


def env_float(env: dict[str, str], name: str, default: float) -> float:
    """A non-negative float from ``env``; unset, invalid or negative gives ``default``."""
    try:
        value = float(env.get(name, ""))
    except ValueError:
        return default
    return value if value >= 0 else default


def largest_request_usd(env: dict[str, str] | None = None) -> float:
    """The biggest per-request cap among live ask, voice, label and the keyed ask tool."""
    e = dict(os.environ if env is None else env)
    return max(
        env_float(e, ASK_USD_ENV, DEFAULT_ASK_USD),
        env_float(e, VOICE_USD_ENV, DEFAULT_VOICE_USD),
        env_float(e, LABEL_USD_ENV, DEFAULT_LABEL_USD),
        env_float(e, API_REQUEST_USD_ENV, DEFAULT_API_REQUEST_USD),
    )


def global_daily_usd(env: dict[str, str] | None = None) -> float:
    """The configured global daily total (``MAUDESIGNAL_LIVE_DAILY_USD``, default 3.00)."""
    e = dict(os.environ if env is None else env)
    return env_float(e, DAILY_USD_ENV, DEFAULT_DAILY_USD)


def blob_enforced_cap(env: dict[str, str] | None = None) -> float:
    """Cap enforced on the Blob ledger: the daily total minus the largest request cap."""
    return max(0.0, round(global_daily_usd(env) - largest_request_usd(env), 6))
