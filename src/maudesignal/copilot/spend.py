"""Per-session and daily spend caps for live Meta Model API calls.

HACKATHON-BUILT — Meta Global AI Developer Hackathon (Oct 26 – Nov 4, 2026).

The public demo can hold a Meta key without letting one visitor (or a bot)
drain the $150 credit. There are no accounts: a "user" is one browser session.

* **Per session:** at most ``session_usd`` estimated spend AND at most
  ``session_calls`` Meta calls, whichever is reached first.
* **Per day (all sessions, UTC):** at most ``daily_usd`` estimated spend.

Caps are checked **before** every call, so no call starts once a cap is
reached; the call in flight when a cap is crossed can overshoot it by its own
cost (bounded by that call's ``max_tokens``). Costs are the same Standard-tier
list-price estimates the rest of the code uses, computed from the token usage
each response reports.

Every recorded call appends a ``meta.usage`` entry to the hash-chained audit
trail, and the first refusal in a session appends ``meta.cap_hit``. Caps are
read from the environment so they can be tuned without a code change:

``MAUDESIGNAL_CAP_SESSION_USD`` (default 1.00), ``MAUDESIGNAL_CAP_SESSION_CALLS``
(default 20), ``MAUDESIGNAL_CAP_DAILY_USD`` (default 10.00),
``MAUDESIGNAL_SPEND_LEDGER`` (default ``data/spend_ledger.json``).
"""

from __future__ import annotations

import json
import os
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, Protocol

from maudesignal.common.exceptions import MaudeSignalError
from maudesignal.copilot.meta_provider import SPARK_USD_PER_M_INPUT, SPARK_USD_PER_M_OUTPUT
from maudesignal.dossier.review import WONDER_USD_PER_M_INPUT, WONDER_USD_PER_M_OUTPUT
from maudesignal.storage.database import Database

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_LEDGER = PROJECT_ROOT / "data" / "spend_ledger.json"

DEFAULT_SESSION_USD = 1.00
DEFAULT_SESSION_CALLS = 20
DEFAULT_DAILY_USD = 10.00

#: Worst case of ONE live Spark call, used to keep a request's real spend at or under its
#: cap: the output cap every live agent/label call uses (``max_tokens=8000``) and a generous
#: prompt size. A guard with ``call_reserve_usd`` set refuses to start a call unless that much
#: of the session budget is still free, so the call in flight can never push past the cap.
WORST_CALL_OUTPUT_TOKENS = 8000
WORST_CALL_INPUT_TOKENS = 40000


def worst_case_call_usd() -> float:
    """Highest plausible cost of one live Spark call (8000 output + 40000 input tokens)."""
    return round(
        WORST_CALL_INPUT_TOKENS * SPARK_USD_PER_M_INPUT / 1e6
        + WORST_CALL_OUTPUT_TOKENS * SPARK_USD_PER_M_OUTPUT / 1e6,
        6,
    )


class ChatMeter(Protocol):
    """Runs one chat call under the daily per-call reservation (see ``connector.callcap``)."""

    def chat(self, create: Callable[..., Any], kwargs: dict[str, Any]) -> Any:
        """Reserve the call's worst case, call ``create(**kwargs)``, settle on success."""


class SpendLimitError(MaudeSignalError):
    """A cap was reached; the Meta call was not made."""

    def __init__(self, cap: str, message: str) -> None:
        """Create the error.

        Args:
            cap: ``"session_usd"``, ``"session_calls"`` or ``"daily_usd"``.
            message: Human-readable explanation shown in the UI.
        """
        super().__init__(message)
        self.cap = cap


@dataclass(frozen=True)
class SpendCaps:
    """The three caps."""

    session_usd: float = DEFAULT_SESSION_USD
    session_calls: int = DEFAULT_SESSION_CALLS
    daily_usd: float = DEFAULT_DAILY_USD
    #: Session budget that must still be free before a call may start (0 = off). Live routes
    #: set it to :func:`worst_case_call_usd` so real spend never exceeds ``session_usd``.
    call_reserve_usd: float = 0.0

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> SpendCaps:
        """Read caps from the environment; unset or invalid values keep the defaults.

        Args:
            env: Mapping to read (defaults to ``os.environ``).

        Returns:
            The caps.
        """
        e = os.environ if env is None else env

        def num(name: str, default: float) -> float:
            try:
                value = float(e.get(name, ""))
            except ValueError:
                return default
            return value if value >= 0 else default

        return cls(
            session_usd=num("MAUDESIGNAL_CAP_SESSION_USD", DEFAULT_SESSION_USD),
            session_calls=int(num("MAUDESIGNAL_CAP_SESSION_CALLS", DEFAULT_SESSION_CALLS)),
            daily_usd=num("MAUDESIGNAL_CAP_DAILY_USD", DEFAULT_DAILY_USD),
        )


class DailyLedger:
    """Spend per UTC day across every session, persisted to a small JSON file."""

    _lock = threading.Lock()

    def __init__(self, path: Path, *, today: Callable[[], date] | None = None) -> None:
        """Create a ledger.

        Args:
            path: JSON file (created on first write).
            today: Clock override (tests).
        """
        self._path = path
        self._today = today or (lambda: datetime.now(UTC).date())

    @classmethod
    def from_env(cls) -> DailyLedger:
        """Ledger at ``MAUDESIGNAL_SPEND_LEDGER`` or ``data/spend_ledger.json``."""
        return cls(Path(os.environ.get("MAUDESIGNAL_SPEND_LEDGER") or DEFAULT_LEDGER))

    def _read(self) -> dict[str, dict[str, float]]:
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return data if isinstance(data, dict) else {}

    def spent_today(self) -> float:
        """Estimated USD recorded today (UTC)."""
        with self._lock:
            return float(self._read().get(self._today().isoformat(), {}).get("usd", 0.0))

    def add(self, usd: float, calls: int) -> float:
        """Add spend for today and return today's new total."""
        with self._lock:
            data = self._read()
            day = data.setdefault(self._today().isoformat(), {"usd": 0.0, "calls": 0})
            day["usd"] = round(float(day.get("usd", 0.0)) + usd, 6)
            day["calls"] = int(day.get("calls", 0)) + calls
            self._path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._path.with_suffix(".tmp")
            tmp.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            tmp.replace(self._path)
            return float(day["usd"])


@dataclass(frozen=True)
class Remaining:
    """What is left before a cap is reached."""

    session_usd: float
    session_calls: int
    daily_usd: float

    @property
    def exhausted(self) -> bool:
        """True when any cap is reached."""
        return self.session_usd <= 0 or self.session_calls <= 0 or self.daily_usd <= 0


@dataclass
class SpendGuard:
    """Caps for one browser session, sharing a daily ledger with every other session."""

    session_id: str
    caps: SpendCaps
    ledger: DailyLedger
    db: Database | None = None
    session_usd: float = 0.0
    session_calls: int = 0
    cap_hit_logged: bool = False
    #: When set, every chat call made through :meth:`wrap` is reserved per call on the daily
    #: ledger before it is sent (the live website and the keyed ask tool set it).
    meter: ChatMeter | None = None
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def remaining(self) -> Remaining:
        """Quota left in this session and today."""
        return Remaining(
            session_usd=round(max(0.0, self.caps.session_usd - self.session_usd), 6),
            session_calls=max(0, self.caps.session_calls - self.session_calls),
            daily_usd=round(max(0.0, self.caps.daily_usd - self.ledger.spent_today()), 6),
        )

    def check(self, kind: str = "meta") -> None:
        """Raise before a call when any cap is reached.

        Args:
            kind: What was about to be called (logged with a refusal).

        Raises:
            SpendLimitError: A cap is reached; the call must not be made.
        """
        r = self.remaining()
        if r.session_calls <= 0:
            cap, msg = "session_calls", (
                f"This session used its {self.caps.session_calls} live Meta calls."
            )
        elif r.session_usd <= 0 or r.session_usd + 1e-9 < self.caps.call_reserve_usd:
            cap, msg = "session_usd", (
                f"This session reached its ${self.caps.session_usd:.2f} live-call budget."
            )
        elif r.daily_usd <= 0:
            cap, msg = "daily_usd", (
                f"Today's ${self.caps.daily_usd:.2f} live-call budget for the demo is used up."
            )
        else:
            return
        if self.db is not None and not self.cap_hit_logged:
            self.db.append_audit(
                actor="spend-guard",
                action="meta.cap_hit",
                entity_id=f"S-{self.session_id[:12]}",
                payload={"cap": cap, "refused": kind, **self._state()},
            )
            self.cap_hit_logged = True
        raise SpendLimitError(cap, msg)

    def record(self, *, kind: str, model: str, cost_usd: float, calls: int = 1) -> None:
        """Count one completed call (or ``calls`` billed units) and log it.

        Args:
            kind: e.g. ``"chat"``, ``"voice"``, ``"sam"``.
            model: Model id.
            cost_usd: Estimated cost of the call.
            calls: Meta calls this record covers.
        """
        with self._lock:
            self.session_usd = round(self.session_usd + cost_usd, 6)
            self.session_calls += calls
        today = self.ledger.add(cost_usd, calls)
        if self.db is not None:
            self.db.append_audit(
                actor="spend-guard",
                action="meta.usage",
                entity_id=f"S-{self.session_id[:12]}",
                payload={
                    "kind": kind,
                    "model": model,
                    "estimated_cost_usd": round(cost_usd, 6),
                    "calls": calls,
                    "daily_usd_after": today,
                    **self._state(),
                },
            )

    def _state(self) -> dict[str, Any]:
        return {
            "session_usd": self.session_usd,
            "session_calls": self.session_calls,
            "caps": {
                "session_usd": self.caps.session_usd,
                "session_calls": self.caps.session_calls,
                "daily_usd": self.caps.daily_usd,
            },
        }

    def wrap(self, client: Any) -> GuardedClient:
        """Return ``client`` with every ``chat.completions.create`` call guarded."""
        return GuardedClient(client, self)


def chat_cost_usd(model: str, input_tokens: int, output_tokens: int) -> float:
    """Estimated Standard-tier cost of one chat call.

    Args:
        model: Model id (``muse-wonder-*`` priced as Wonder, everything else as Spark).
        input_tokens: Prompt tokens reported by the response.
        output_tokens: Completion tokens reported by the response.

    Returns:
        USD.
    """
    if model.startswith("muse-wonder"):
        rates = (WONDER_USD_PER_M_INPUT, WONDER_USD_PER_M_OUTPUT)
    else:
        rates = (SPARK_USD_PER_M_INPUT, SPARK_USD_PER_M_OUTPUT)
    return round(input_tokens * rates[0] / 1e6 + output_tokens * rates[1] / 1e6, 6)


class _GuardedCompletions:
    def __init__(self, inner: Any, guard: SpendGuard) -> None:
        self._inner = inner
        self._guard = guard

    def create(self, **kwargs: Any) -> Any:
        self._guard.check("chat")
        meter = self._guard.meter
        resp = meter.chat(self._inner.create, kwargs) if meter else self._inner.create(**kwargs)
        usage = getattr(resp, "usage", None)
        tokens_in = int(getattr(usage, "prompt_tokens", 0) or 0)
        tokens_out = int(getattr(usage, "completion_tokens", 0) or 0)
        model = str(kwargs.get("model") or "")
        self._guard.record(
            kind="chat", model=model, cost_usd=chat_cost_usd(model, tokens_in, tokens_out)
        )
        return resp


class GuardedClient:
    """OpenAI-compatible client whose chat calls pass through a :class:`SpendGuard`.

    Only ``chat.completions.create`` is exposed: that is the one method the
    copilot, the vision reader and the dossier call, so nothing else can spend.
    """

    def __init__(self, client: Any, guard: SpendGuard) -> None:
        """Wrap ``client``; an SDK client that retries on its own is switched to no retries.

        One spend reservation covers exactly one HTTP request, so the SDK's silent retries
        (a billed first attempt followed by a cheaper second one) must never happen.
        """
        if getattr(client, "max_retries", 0) and hasattr(client, "with_options"):
            client = client.with_options(max_retries=0)
        completions = _GuardedCompletions(client.chat.completions, guard)
        self.chat = type("Chat", (), {"completions": completions})()


def closest_recorded(question: str, transcripts: list[dict[str, Any]]) -> dict[str, Any] | None:
    """The recorded demo answer whose question shares the most words with ``question``.

    Used when a cap is reached: the analyst still gets a real, gated answer that
    was recorded earlier, clearly labelled as such, and no Meta call is made.

    Args:
        question: What the visitor asked.
        transcripts: Recorded transcripts (``load_transcripts``).

    Returns:
        The best match, or None when there are no recordings.
    """

    def words(text: str) -> set[str]:
        return set("".join(c.lower() if c.isalnum() else " " for c in text).split())

    asked = words(question)
    best: dict[str, Any] | None = None
    best_score = -1
    for t in transcripts:
        score = len(asked & words(str(t.get("question", ""))))
        if score > best_score:
            best, best_score = t, score
    return best
