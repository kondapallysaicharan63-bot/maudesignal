"""The ``ask`` tool: Muse Spark copilot behind the claim gate, with a recorded fallback.

HACKATHON-BUILT — Meta Global AI Developer Hackathon (Oct 26 – Nov 4, 2026).

Rules this module enforces:

* Only sentences the gate passed *and* that have an openFDA or record link go into
  ``speakable``. A withheld sentence is listed in ``withheld`` with the reason and is never
  spoken as fact; so is a passed sentence with no link (nothing to check it against).
* The copilot is read-only here: ``draft_capa`` and any other tool that writes is never
  offered to the model and never run (see ``readonly.py``).
* The live path needs ``META_MODEL_API_KEY``. Without it, or once the key's daily cost
  cap is reached, or if the model call fails, a *recorded* answer (a real, gated run stored
  in ``demo/transcripts``) is returned, labelled recorded, with the recorded question in the
  spoken lead. A recording is used only when it is about the same thing as the question.
* No forbidden term (``forbidden.py``) reaches a response.
* The model prompt lives in ``skills/safety-copilot`` (loaded by the copilot agent);
  nothing is prompted from here, and the copilot runs at temperature 0.
"""

from __future__ import annotations

import os
import re
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
from maudesignal.connector.forbidden import is_clean
from maudesignal.connector.models import Fact, Provenance, ToolAnswer, WithheldSentence
from maudesignal.connector.readonly import make_read_only
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
        "our", "its", "not", "but", "all", "fda",
    ]
)  # fmt: skip

_RECORDED = "this is a recorded answer to a different, similar question"
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
_UNLINKED_REASON = "passed the claim gate but has no openFDA or record link, so it is not spoken"
_FORBIDDEN_REASON = "contains a term this service does not use, so it is not spoken"
_MAX_QUOTED_Q = 140
_CODE_WORD = re.compile(r"\b[A-Za-z]{3}\b")

Item = tuple[str, list[tuple[str, str]], str | None]


def default_agent_factory(
    data: ConnectorData, guard: SpendGuard
) -> CopilotAgent:  # pragma: no cover
    """Real Muse Spark agent whose every chat call passes the spend guard (read-only tools)."""
    from maudesignal.copilot.meta_provider import MetaProvider

    provider = MetaProvider(
        api_key=os.environ["META_MODEL_API_KEY"],
        model=os.environ.get("META_MODEL_API_MODEL", ""),
        base_url=os.environ.get("META_MODEL_API_BASE_URL", "https://api.meta.ai/v1"),
    )
    model = os.environ.get("META_MODEL_API_MODEL", "muse-spark-1.3")
    agent = CopilotAgent(guard.wrap(provider.client), data.tool_context(), model=model)
    make_read_only(agent)
    return agent


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
        """The UTC-day spend ledger of one API key (kept apart per key).

        The ledger is a file on the server instance, so on serverless hosting it is per
        instance and resets on a cold start; see docs/hackathon/MUSE_CONNECTOR.md.
        """
        return DailyLedger(self.ledger_dir / f"{key_id}.json")


def _words(text: str) -> set[str]:
    cleaned = "".join(c.lower() if c.isalnum() else " " for c in text)
    return {w for w in cleaned.split() if len(w) >= 3 and w not in _STOP}


def _recorded_sentences(t: dict[str, Any]) -> list[dict[str, Any]]:
    return [s for s in (t.get("final") or {}).get("sentences") or [] if isinstance(s, dict)]


def _eligible(t: dict[str, Any]) -> bool:
    """A recording that may answer a stranger's question.

    Left out: voice-mode and greeting runs (they answer something else), unparsed runs,
    and runs whose question or sentences contain a term this service never uses.
    """
    label = str(t.get("label") or "").lower()
    if "voice" in label or t.get("parse_failed") or not t.get("question"):
        return False
    sentences = _recorded_sentences(t)
    texts = [str(t["question"])] + [str(s.get("text") or "") for s in sentences]
    return bool(sentences) and all(is_clean(x) for x in texts)


def _matches(question: str, t: dict[str, Any], known: set[str]) -> bool:
    """True when a recording is about what was asked.

    Every meaningful word of the question (one may be missing in a long question) must be
    in the recorded question or in the first sentence of its answer, and a product code in
    the question must be one of those texts' codes. So "for QIH" never gets the LLZ answer
    and "recalls" never gets a report count.
    """
    sentences = _recorded_sentences(t)
    first = next((str(s.get("text") or "") for s in sentences if s.get("status") == "pass"), "")
    haystack = f"{t.get('question') or ''} {first}"
    asked = _words(question)
    have = _words(haystack)
    if len(asked & have) < 2 or len(asked - have) > len(asked) // 5:
        return False
    codes = {w.upper() for w in _CODE_WORD.findall(question) if w.upper() in known}
    return codes <= {w.upper() for w in _CODE_WORD.findall(haystack)}


def _quoted(question: str) -> str:
    q = " ".join(question.split())
    if len(q) > _MAX_QUOTED_Q:
        q = q[:_MAX_QUOTED_Q].rsplit(" ", 1)[0] + " ..."
    q = re.sub(r"[.?!]+(?=\s|$)", lambda m: "," if m.end() < len(q) else "", q)
    return q.replace('"', "'")


def _speakable(lead: str | None, passed: list[str], withheld: int) -> str:
    room = MAX_SPEAKABLE_SENTENCES - (1 if lead else 0) - (1 if withheld else 0)
    parts: list[str] = [lead] if lead else []
    chosen = passed[: max(room, 1)] if passed else []
    parts += chosen or ["I could not verify an answer to that, so I am not stating one."]
    if withheld:
        parts.append(
            "One sentence was left out because it could not be verified or tied to a source."
            if withheld == 1
            else f"{withheld} sentences were left out because they could not be verified "
            "or tied to a source."
        )
    return compose(parts)


def _split(items: list[Item]) -> tuple[list[str], list[Fact], list[WithheldSentence]]:
    """Sort sentences into spoken (gate-passed, linked, clean) and left out.

    Each item is ``(text, links, withheld_reason)``. A spoken sentence is the text of at
    least one fact, so everything spoken has an openFDA or record link.
    """
    passed: list[str] = []
    facts: list[Fact] = []
    withheld: list[WithheldSentence] = []
    for text, found, reason in items:
        if reason is None and not is_clean(text):
            reason = _FORBIDDEN_REASON
        if reason is None and not found:
            reason = _UNLINKED_REASON
        if reason is not None:
            withheld.append(WithheldSentence(text=text, reason=reason))
            continue
        passed.append(text)
        for link, label in dict.fromkeys(found):
            facts.append(Fact(text=text, link=link, link_label=label))
    return passed, facts, withheld


def _from_live(res: CopilotResult, data: ConnectorData, now: datetime) -> ToolAnswer:
    items: list[Item] = []
    for s in res.report.sentences:
        if s.status != "pass":
            items.append((s.text, [], "; ".join(s.reasons) or "not verified"))
            continue
        found = [
            lk
            for cv in s.claim_verdicts
            if cv.status == "pass" and (lk := links.claim_link(cv.claim)) is not None
        ]
        items.append((s.text, found, None))
    passed, facts, withheld = _split(items)
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


def _digest_windows(data: ConnectorData) -> list[links.Window]:
    w = data.digest().get("window") or {}
    out: list[links.Window] = []
    for a, b in (("current_start", "current_end"), ("baseline_start", "baseline_end")):
        if w.get(a) and w.get(b):
            out.append((str(w[a]).replace("-", ""), str(w[b]).replace("-", "")))
    return out


def _from_recorded(t: dict[str, Any], reason: str, data: ConnectorData) -> ToolAnswer:
    windows = _digest_windows(data)
    items: list[Item] = []
    for s in _recorded_sentences(t):
        text = str(s.get("text") or "")
        if s.get("status") != "pass":
            reasons = [str(r) for r in s.get("reasons") or []]
            items.append((text, [], "; ".join(reasons) or "not verified"))
            continue
        claims = [c for c in s.get("claims") or [] if isinstance(c, dict)]
        found: list[tuple[str, str]] = []
        for claim in claims:
            lk = links.recorded_claim_link(claim) if claim.get("status") == "pass" else None
            if lk and claim.get("kind") != "count":
                found.append(lk)
        found += links.recover_count_links(text, claims, data.store, windows)
        items.append((text, found, None))
    passed, facts, withheld = _split(items)
    if not passed and all(w.reason in (_UNLINKED_REASON, _FORBIDDEN_REASON) for w in withheld):
        return _no_recording(reason)  # nothing here can be shown with a link: do not offer it
    through = speak_date(str(data.manifest().get("max_date_received") or ""))
    lead = (
        f'{_LEADS[reason]}: "{_quoted(str(t.get("question") or ""))}"'
        + (f", using stored reports through {through}" if through else "")
        + "."
    )
    return ToolAnswer(
        tool="ask",
        speakable=_speakable(lead, passed, len(withheld)),
        facts=facts,
        provenance=Provenance(
            kind="recorded_answer",
            source=(
                "Recorded run of the Muse Spark copilot; every sentence was checked by the "
                "claim gate when it was recorded"
            ),
            data_dates=f"recorded {str(t.get('recorded_at_utc') or '')[:10]}".strip(),
            note=_REASON_NOTES[reason],
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
            agent = runtime.agent_factory(data, guard)
            make_read_only(agent)  # whatever the factory built: no tool that writes
            res = agent.ask(q)
            if res.capa_ids or agent.context.created_capas:
                raise RuntimeError("a read-only ask wrote a record")  # never shown; falls back
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
    known = {r.product_code for r in data.store.records}
    related = [t for t in transcripts if _eligible(t) and _matches(q, t, known)]
    best = closest_recorded(q, related) if related else None
    if best is None:
        return _no_recording(reason)
    return _from_recorded(best, reason, data)
