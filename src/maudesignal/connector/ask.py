"""The ``ask`` tool: Muse Spark copilot behind the claim gate, with a recorded fallback.

HACKATHON-BUILT — Meta Global AI Developer Hackathon (Oct 26 – Nov 4, 2026).

Rules this module enforces:

* Only sentences the gate passed go into ``speakable``. A withheld sentence is listed in
  ``withheld`` with the gate's reason and is never spoken as fact.
* The live path needs ``META_MODEL_API_KEY``. Without it, or once the key's daily cost
  cap is reached, or if the model call fails, the closest *recorded* answer (a real,
  gated run stored in ``demo/transcripts``) is returned and labelled recorded.
* The model prompt lives in ``skills/safety-copilot`` (loaded by the copilot agent);
  nothing is prompted from here, and the copilot runs at temperature 0.
"""

from __future__ import annotations

import os
import tempfile
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from maudesignal.common.logging import get_logger
from maudesignal.connector import links
from maudesignal.connector.data import ConnectorData
from maudesignal.connector.errors import InvalidInputError, SourceUnavailableError
from maudesignal.connector.models import Fact, Provenance, ToolAnswer, WithheldSentence
from maudesignal.connector.speech import compose, speak_date
from maudesignal.connector.tools import Clock, _stamp, utc_now
from maudesignal.copilot.agent import CopilotAgent, CopilotResult
from maudesignal.copilot.spend import (
    DailyLedger,
    SpendCaps,
    SpendGuard,
    SpendLimitError,
    closest_recorded,
)

logger = get_logger(__name__)

MIN_QUESTION_CHARS = 3
MAX_QUESTION_CHARS = 500
DEFAULT_REQUEST_USD = 0.25
DEFAULT_DAILY_USD = 2.00
DEFAULT_REQUEST_CALLS = 20
MAX_SPEAKABLE_SENTENCES = 3

AgentFactory = Callable[[ConnectorData, SpendGuard], CopilotAgent]

_STOP = frozenset(
    [
        "the", "and", "what", "for", "this", "that", "with", "how", "are", "was", "any", "did",
        "does", "show", "give", "tell", "about", "from", "have", "has", "can", "you", "why",
        "who", "when", "which", "there", "their", "them", "into", "last", "please", "your",
        "our", "its", "not", "but", "all",
    ]
)  # fmt: skip

_RECORDED = "this is a recorded answer to a similar question."
_LEADS = {
    "cap": f"Today's live-answer budget is used up, so {_RECORDED}",
    "no_model": f"Live answers are not switched on here, so {_RECORDED}",
    "model_error": f"The live model is not available just now, so {_RECORDED}",
}
_REASON_NOTES = {
    "cap": "The daily cost cap for this key was reached, so no live model call was made.",
    "no_model": "No live model key is configured on this server, so no live model call was made.",
    "model_error": "The live model call failed, so no live answer is shown.",
}


def default_agent_factory(
    data: ConnectorData, guard: SpendGuard
) -> CopilotAgent:  # pragma: no cover
    """Real Muse Spark agent whose every chat call passes the spend guard."""
    from maudesignal.copilot.meta_provider import MetaProvider

    provider = MetaProvider(
        api_key=os.environ["META_MODEL_API_KEY"],
        model=os.environ.get("META_MODEL_API_MODEL", ""),
        base_url=os.environ.get("META_MODEL_API_BASE_URL", "https://api.meta.ai/v1"),
    )
    model = os.environ.get("META_MODEL_API_MODEL", "muse-spark-1.3")
    return CopilotAgent(guard.wrap(provider.client), data.tool_context(), model=model)


def _env_float(name: str, default: float) -> float:
    try:
        value = float(os.environ.get(name, ""))
    except ValueError:
        return default
    return value if value >= 0 else default


@dataclass
class AskRuntime:
    """Everything ``ask`` needs besides the stored data."""

    agent_factory: AgentFactory = default_agent_factory
    live_enabled: Callable[[], bool] = field(
        default=lambda: bool(os.environ.get("META_MODEL_API_KEY"))
    )
    caps: SpendCaps = field(
        default_factory=lambda: SpendCaps(
            session_usd=_env_float("MAUDESIGNAL_API_REQUEST_USD", DEFAULT_REQUEST_USD),
            session_calls=DEFAULT_REQUEST_CALLS,
            daily_usd=_env_float("MAUDESIGNAL_API_DAILY_USD", DEFAULT_DAILY_USD),
        )
    )
    ledger_dir: Path = field(
        default_factory=lambda: Path(
            os.environ.get("MAUDESIGNAL_API_LEDGER_DIR")
            or Path(tempfile.gettempdir()) / "maudesignal-api-spend"
        )
    )

    def ledger_for(self, key_id: str) -> DailyLedger:
        """The UTC-day spend ledger of one API key (kept apart per key)."""
        return DailyLedger(self.ledger_dir / f"{key_id}.json")


def _words(text: str) -> set[str]:
    cleaned = "".join(c.lower() if c.isalnum() else " " for c in text)
    return {w for w in cleaned.split() if len(w) >= 3 and w not in _STOP}


def _relevant(question: str, recorded_question: str) -> bool:
    asked = _words(question)
    shared = len(asked & _words(recorded_question))
    return shared >= 2 or (shared >= 1 and shared / max(len(asked), 1) >= 0.34)


def _speakable(lead: str | None, passed: list[str], withheld: int) -> str:
    room = MAX_SPEAKABLE_SENTENCES - (1 if lead else 0) - (1 if withheld else 0)
    parts: list[str] = [lead] if lead else []
    chosen = passed[: max(room, 1)] if passed else []
    parts += chosen or ["I could not verify an answer to that, so I am not stating one."]
    if withheld:
        parts.append(
            "One sentence was withheld because it could not be verified."
            if withheld == 1
            else f"{withheld} sentences were withheld because they could not be verified."
        )
    return compose(parts)


def _from_live(res: CopilotResult, data: ConnectorData, now: datetime) -> ToolAnswer:
    passed: list[str] = []
    facts: list[Fact] = []
    withheld: list[WithheldSentence] = []
    for s in res.report.sentences:
        if s.status != "pass":
            withheld.append(
                WithheldSentence(text=s.text, reason="; ".join(s.reasons) or "not verified")
            )
            continue
        passed.append(s.text)
        for cv in s.claim_verdicts:
            found = links.claim_link(cv.claim) if cv.status == "pass" else None
            if found:
                facts.append(Fact(text=s.text, link=found[0], link_label=found[1]))
                break
    latest = str(data.manifest().get("max_date_received") or "")
    return ToolAnswer(
        tool="ask",
        speakable=_speakable(None, passed, len(withheld)),
        facts=facts,
        provenance=Provenance(
            kind="live_model",
            source=(
                "Muse Spark copilot over the stored demo snapshot; every sentence was checked "
                "by the claim gate before it appears here"
            ),
            data_dates=(
                f"stored reports received through {speak_date(latest)}" if latest else None
            ),
            queried_at_utc=_stamp(now),
            note=f"Model {res.model}; temperature 0.",
        ),
        withheld=withheld,
    )


def _from_recorded(t: dict[str, Any], reason: str) -> ToolAnswer:
    sentences = (t.get("final") or {}).get("sentences") or []
    passed: list[str] = []
    facts: list[Fact] = []
    withheld: list[WithheldSentence] = []
    for s in sentences:
        text = str(s.get("text") or "")
        if s.get("status") != "pass":
            reasons = [str(r) for r in s.get("reasons") or []]
            withheld.append(
                WithheldSentence(text=text, reason="; ".join(reasons) or "not verified")
            )
            continue
        passed.append(text)
        for claim in s.get("claims") or []:
            found = links.recorded_claim_link(claim) if claim.get("status") == "pass" else None
            if found:
                facts.append(Fact(text=text, link=found[0], link_label=found[1]))
                break
    recorded_q = str(t.get("question") or "")
    return ToolAnswer(
        tool="ask",
        speakable=_speakable(_LEADS[reason], passed, len(withheld)),
        facts=facts,
        provenance=Provenance(
            kind="recorded_answer",
            source=(
                "Recorded run of the Muse Spark copilot; every sentence was checked by the "
                "claim gate when it was recorded"
            ),
            data_dates=f"recorded {str(t.get('recorded_at_utc') or '')[:10]}".strip(),
            note=f'{_REASON_NOTES[reason]} Closest recorded question: "{recorded_q}"',
        ),
        withheld=withheld,
    )


def _no_recording(reason: str) -> ToolAnswer:
    return ToolAnswer(
        tool="ask",
        speakable=compose(
            [
                "I have no verified answer to that question right now.",
                "Try the what changed, device check, report or recalls tools instead.",
            ]
        ),
        facts=[],
        provenance=Provenance(
            kind="recorded_answer",
            source="No recorded answer matches this question",
            note=_REASON_NOTES[reason],
        ),
    )


def ask(
    data: ConnectorData,
    question: str,
    *,
    key_id: str,
    runtime: AskRuntime,
    now: Clock = utc_now,
) -> ToolAnswer:
    """Answer a question through the copilot and the claim gate, or from a recorded run.

    Args:
        data: Stored data.
        question: The caller's question (3 to 500 characters).
        key_id: Non-secret id of the calling API key (hash prefix), for its cost ledger.
        runtime: Live-model settings.
        now: Clock (tests).

    Raises:
        InvalidInputError: The question is empty or too long.
        SourceUnavailableError: No live answer and nothing recorded exists at all.
    """
    q = " ".join(question.split())
    if not (MIN_QUESTION_CHARS <= len(q) <= MAX_QUESTION_CHARS):
        raise InvalidInputError(
            f"Ask a question of {MIN_QUESTION_CHARS} to {MAX_QUESTION_CHARS} characters."
        )
    reason = "no_model"
    if runtime.live_enabled():
        guard = SpendGuard(
            session_id=f"api-{key_id}",
            caps=runtime.caps,
            ledger=runtime.ledger_for(key_id),
            db=data.db,
        )
        try:
            guard.check("connector.ask")
            res = runtime.agent_factory(data, guard).ask(q)
            return _from_live(res, data, now())
        except SpendLimitError:
            reason = "cap"
        except (
            Exception
        ) as exc:  # noqa: BLE001 - any model/network failure falls back to a recording
            logger.warning("connector_ask_live_failed", error_type=type(exc).__name__)
            reason = "model_error"
    transcripts = data.transcripts()
    if not transcripts:
        raise SourceUnavailableError(
            "No live answer is available and no recorded answers are stored."
        )
    related = [t for t in transcripts if _relevant(q, str(t.get("question") or ""))]
    best = closest_recorded(q, related) if related else None
    if best is None:
        return _no_recording(reason)
    return _from_recorded(best, reason)
