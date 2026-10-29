"""Dashboard side of the live-call spend caps (see ``maudesignal.copilot.spend``).

HACKATHON-BUILT — Meta Global AI Developer Hackathon (Oct 26 – Nov 4, 2026).

One :class:`SpendGuard` per browser session (no login: the session is the user),
kept in ``st.session_state``; the daily cap is shared through the ledger file.
"""

from __future__ import annotations

import os
import uuid
from typing import Any

import streamlit as st

from maudesignal.copilot.spend import DailyLedger, GuardedClient, SpendCaps, SpendGuard
from maudesignal.storage.database import Database

_GUARD_KEY = "spend_guard"
_BASE_URL_DEFAULT = "https://api.meta.ai/v1"


def has_key() -> bool:
    """True when a Meta key is configured (live calls possible)."""
    return bool(os.environ.get("META_MODEL_API_KEY"))


def guard(db: Database | None = None) -> SpendGuard:
    """This browser session's guard (created on first use, caps read from the env)."""
    g = st.session_state.get(_GUARD_KEY)
    if not isinstance(g, SpendGuard):
        g = SpendGuard(
            session_id=uuid.uuid4().hex,
            caps=SpendCaps.from_env(),
            ledger=DailyLedger.from_env(),
            db=db,
        )
        st.session_state[_GUARD_KEY] = g
    elif db is not None and g.db is None:
        g.db = db
    return g


def guarded_client(db: Database | None = None) -> GuardedClient:
    """OpenAI-compatible Meta client whose chat calls count against the caps."""
    from openai import OpenAI

    client = OpenAI(
        api_key=os.environ["META_MODEL_API_KEY"],
        base_url=os.environ.get("META_MODEL_API_BASE_URL", _BASE_URL_DEFAULT),
    )
    return guard(db).wrap(client)


def sidebar_quota(db: Database | None = None) -> None:
    """Remaining live-call quota for this session and today (rendered in the sidebar slot).

    Shows nothing without a key: the keyless demo makes no live calls.
    """
    if not has_key():
        return
    g = guard(db)
    r = g.remaining()
    status = "reached — recorded answers shown" if r.exhausted else "available"
    st.caption(
        f"Live Meta quota ({status}): ${r.session_usd:.2f} of ${g.caps.session_usd:.2f} and "
        f"{r.session_calls} of {g.caps.session_calls} calls left this session · "
        f"${r.daily_usd:.2f} of ${g.caps.daily_usd:.2f} left today."
    )


def cap_notice(message: str) -> None:
    """Show why no live call was made."""
    st.warning(f"{message} No Meta call was made; showing the recorded demo answer instead.")


def recorded_fallback(question: str, transcripts: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Closest recorded answer, marked as a fallback for the renderer."""
    from maudesignal.copilot.spend import closest_recorded

    t = closest_recorded(question, transcripts)
    if t is None:
        return None
    return {**t, "fallback_for": question}
