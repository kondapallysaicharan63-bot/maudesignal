"""Names and defaults for the live cost limits (the daily total and the per-request caps).

HACKATHON-BUILT — Meta Global AI Developer Hackathon (Oct 26 – Nov 4, 2026).

``MAUDESIGNAL_LIVE_DAILY_USD`` (default 3.00) is the hard ceiling for everything the live
website routes and the keyed ``ask`` tool spend per UTC day together. It is enforced by ONE
rule, in ``callcap``: reserve each model call's worst case in the private Blob store before the
call, release it to the real cost only after a successful reply. The per-request caps below
(ask, voice, label, keyed ask) only bound one visitor's request; they hold nothing in the
daily ledger.
"""

from __future__ import annotations

import os

#: Non-secret id the live website routes use for their per-request guard.
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


def global_daily_usd(env: dict[str, str] | None = None) -> float:
    """The configured global daily total (``MAUDESIGNAL_LIVE_DAILY_USD``, default 3.00)."""
    e = dict(os.environ if env is None else env)
    return env_float(e, DAILY_USD_ENV, DEFAULT_DAILY_USD)
