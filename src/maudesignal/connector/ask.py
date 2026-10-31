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
* No forbidden term (``forbidden.py``) reaches a response: left-out sentences and reasons
  are screened too. In live answers a left-out sentence's text is never returned.
* The model prompt lives in ``skills/safety-copilot`` (loaded by the copilot agent);
  nothing is prompted from here, and the copilot runs at temperature 0.
"""

from __future__ import annotations

import os
import re
import tempfile
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from maudesignal.common.logging import get_logger
from maudesignal.connector import links
from maudesignal.connector.callcap import CallMeter
from maudesignal.connector.data import ConnectorData
from maudesignal.connector.errors import InvalidInputError, SourceUnavailableError
from maudesignal.connector.forbidden import is_clean
from maudesignal.connector.models import Fact, Provenance, ToolAnswer, WithheldSentence
from maudesignal.connector.readonly import make_read_only
from maudesignal.connector.speech import compose, plural, speak_date
from maudesignal.connector.store import ConnectorState
from maudesignal.connector.tools import Clock, _stamp, utc_now
from maudesignal.copilot.agent import CopilotAgent, CopilotResult
from maudesignal.copilot.spend import (
    DailyLedger,
    SpendCaps,
    SpendGuard,
    SpendLimitError,
    closest_recorded,
    worst_case_call_usd,
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
    "live_off": f"Live answers are switched off on this server, so {_RECORDED}",
    "model_error": f"The live model is not available just now, so {_RECORDED}",
    "timeout": f"This request ran out of time, so {_RECORDED}",
    "demo_key": f"The public demo key never starts a live model call, so {_RECORDED}",
    "no_transcript": (
        "Your recording could not be turned into text, so this is a recorded answer to a "
        "different spoken question"
    ),
}
_REASON_NOTES = {
    "cap": "The daily cost cap for this key was reached, so no live model call was made.",
    "no_model": "No live model key is configured on this server, so no live model call was made.",
    "live_off": (
        "Live model calls are switched off on this server (limits are per instance), "
        "so no live model call was made."
    ),
    "model_error": "The live model call failed, so no live answer is shown.",
    "no_transcript": "The recording could not be transcribed, so no live model call was made.",
    "timeout": "The time limit for this request was used up, so no live model call was made.",
    "demo_key": "The public demo key never starts a live model call, so this is a recorded answer.",
}
_UNLINKED_REASON = "passed the claim gate but has no openFDA or record link, so it is not spoken"
_FORBIDDEN_REASON = "contains a term this service does not use, so it is not spoken"
_FORBIDDEN_TEXT = "Sentence left out: it contains a term this service does not use."
_GATE_TEXT = "Sentence left out by the claim gate."
_GENERIC_REASON = "could not be verified"
#: Live answers: the only reason texts ever returned. Fixed per claim kind, never built from
#: gate reason strings, which can carry text the model wrote into a claim field.
_LIVE_REASONS = {
    "quote": "quote: not found verbatim in the cited record",
    "count": "count: number does not match stored records",
    "share": "share: percentage does not match stored records",
    "device": "device: not found in stored records",
    "record": "record: not in the evidence store",
    "regulation": "regulation: section not in the curated CFR list",
    "recall": "recall: not found in stored recall data",
    "recall_count": "recall_count: number does not match stored recall data",
    "source_count": "source_count: number does not match the cited source",
    "literature": "literature: reference could not be verified",
    "ungrounded": "ungrounded: number or citation without a claim",
}
_KINDS = frozenset(_LIVE_REASONS)
_RUN = 20  # a shared run of this many characters counts as quoting the sentence
_MAX_QUOTED_Q = 140
_CODE_WORD = re.compile(r"\b[A-Za-z]{3}\b")

Item = tuple[str, list[tuple[str, str]], str | None, list[str]]


def _quotes(reason: str, text: str) -> bool:
    """True when ``reason`` repeats a run of ``_RUN`` or more characters of ``text``."""
    a, b = " ".join(reason.lower().split()), " ".join(text.lower().split())
    return any(b[i : i + _RUN] in a for i in range(max(len(b) - _RUN + 1, 0)))


def _safe_reason(reason: str, text: str) -> str:
    """The gate's reason with any part that quotes the sentence or a banned term dropped."""
    kept: list[str] = []
    for part in reason.split("; "):
        if _quotes(part, text) or not is_clean(part):
            head = part.split(":", 1)[0].strip() if ":" in part else ""
            part = f"{head}: {_GENERIC_REASON}" if head in _KINDS else _GENERIC_REASON
        kept.append(part)
    return "; ".join(dict.fromkeys(kept)) or _GENERIC_REASON


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
    from maudesignal.connector.live import CALL_TIMEOUT_S

    # No SDK retries and a bounded wait: one reservation covers exactly one HTTP request.
    client = provider.client.with_options(max_retries=0, timeout=CALL_TIMEOUT_S)
    agent = CopilotAgent(guard.wrap(client), data.tool_context(), model=model)
    make_read_only(agent)
    return agent


ALLOW_PER_INSTANCE_ENV = "MAUDESIGNAL_ALLOW_PER_INSTANCE_CAP"


def live_mode_allowed() -> bool:
    """True only when the model key is set AND a per-call spend ledger can be kept.

    Every Meta call reserves its worst-case cost in the private Blob store first (see
    ``callcap``). Without that store the daily total cannot be kept across serverless
    instances, so live Muse Spark calls need the explicit local-only override
    ``MAUDESIGNAL_ALLOW_PER_INSTANCE_CAP=1`` (an in-memory ledger of this one process). A model
    key alone returns recorded answers.
    """
    return bool(os.environ.get("META_MODEL_API_KEY")) and (
        bool(os.environ.get("BLOB_READ_WRITE_TOKEN", "").strip())
        or os.environ.get(ALLOW_PER_INSTANCE_ENV, "").strip() == "1"
    )


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
    live_enabled: Callable[[], bool] = field(default=live_mode_allowed)
    caps: SpendCaps = field(
        default_factory=lambda: SpendCaps(
            session_usd=_env_float("MAUDESIGNAL_API_REQUEST_USD", DEFAULT_REQUEST_USD),
            session_calls=DEFAULT_REQUEST_CALLS,
            daily_usd=_env_float("MAUDESIGNAL_API_DAILY_USD", DEFAULT_DAILY_USD),
            call_reserve_usd=worst_case_call_usd(),
        )
    )
    ledger_dir: Path = field(
        default_factory=lambda: Path(
            os.environ.get("MAUDESIGNAL_API_LEDGER_DIR")
            or Path(tempfile.gettempdir()) / "maudesignal-api-spend"
        )
    )
    state: ConnectorState | None = None
    #: An explicit per-call reservation (tests, and the live website routes).
    meter: CallMeter | None = None
    #: Cheaper tier-4 settings (compact prompt, low reasoning effort, two tool rounds).
    lean: bool = True

    def call_meter(self) -> CallMeter | None:
        """The per-call reservation every Meta call goes through (``None``: live is off)."""
        if self.meter is not None:
            return self.meter
        if self.state is None:
            return None
        local = os.environ.get(ALLOW_PER_INSTANCE_ENV, "").strip() == "1"
        ledger = self.state.call_ledger(allow_memory=local)
        return CallMeter(ledger) if ledger is not None else None

    def ledger_for(self, key_id: str) -> DailyLedger:
        """The UTC-day spend ledger of one API key (kept apart per key; a per-key cap only).

        With a shared store the ledger is in Redis. Otherwise it is a file on the server
        instance, so on serverless hosting it is per instance and resets on a cold start;
        see docs/hackathon/MUSE_CONNECTOR.md.
        """
        shared = self.state.ledger(key_id) if self.state else None
        return shared or DailyLedger(self.ledger_dir / f"{key_id}.json")


#: Tier-4 limits (see ``apply_lean``). Output tokens include reasoning tokens.
LEAN_MAX_TOOL_ROUNDS = 2
LEAN_MAX_TOKENS = 3000
LEAN_MAX_TOKENS_COMPARE = 5000
LEAN_TOOL_RESULT_CHARS = 6000
_COMPARE = re.compile(
    r"\bcompare\b|\bcomparison\b|\bversus\b|\bvs\.?\b|\bdifference\b|\bside by side\b"
    r"|\bwhich (?:one|of)\b|\bbetween\b",
    re.IGNORECASE,
)


def is_comparison(question: str) -> bool:
    """True when the question compares things (then reasoning effort ``medium``)."""
    return _COMPARE.search(question) is not None


def apply_lean(agent: CopilotAgent, question: str) -> None:
    """Cheaper tier-4 settings: compact prompt, ``low`` effort (``medium`` to compare)."""
    compare = is_comparison(question)
    agent.configure_lean(
        reasoning_effort="medium" if compare else "low",
        max_tool_rounds=LEAN_MAX_TOOL_ROUNDS,
        max_tokens=LEAN_MAX_TOKENS_COMPARE if compare else LEAN_MAX_TOKENS,
        max_tool_result_chars=LEAN_TOOL_RESULT_CHARS,
    )


def _words(text: str) -> set[str]:
    cleaned = "".join(c.lower() if c.isalnum() else " " for c in text)
    return {w for w in cleaned.split() if len(w) >= 3 and w not in _STOP}


def _recorded_sentences(t: dict[str, Any]) -> list[dict[str, Any]]:
    return [s for s in (t.get("final") or {}).get("sentences") or [] if isinstance(s, dict)]


def _eligible(t: dict[str, Any], *, voice: bool = False) -> bool:
    """A recording that may answer a stranger's question.

    Left out: voice-mode and greeting runs (they answer something else; kept only when
    ``voice`` is set, for a spoken question), unparsed runs, and runs whose question or
    sentences contain a term this service never uses.
    """
    label = str(t.get("label") or "").lower()
    if ("voice" in label) != voice or t.get("parse_failed") or not t.get("question"):
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


_CONNECTIVE_START = re.compile(
    r"^(?:here(?:'s| is| are)|below|sure|certainly|of course|okay|ok|hi|hello|hey|thanks"
    r"|thank you|let me|i (?:checked|looked|searched|found|reviewed|used|can help)"
    r"|based on (?:the |my )?(?:stored |available )?(?:records|data|tools?|results?)"
    r"|in summary|to summari[sz]e|overall|in short|please note|note that|happy to help"
    r"|(?:good|great) question)\b",
    re.IGNORECASE,
)
_ADVISORY = re.compile(
    r"\b(?:a (?:named )?(?:human|person)|qualified (?:person|reviewer)|your team)\b.*\breview"
    r"|\bnot medical advice\b|\bnothing (?:is|was) filed\b",
    re.IGNORECASE,
)
MAX_CONNECTIVE_WORDS = 14
NO_FACTS_LINE = (
    "I have nothing checked to add to that. Ask about a product code, a report, a recall or "
    "what changed this week."
)


def is_connective(text: str) -> bool:
    """True for a sentence that states no fact: a greeting, a transition, an advisory line.

    Used only for sentences that carry no claim and passed the gate. Such a sentence is
    neither shown as a fact nor listed as held back. Anything with a digit, or longer than
    a short transition, is not connective.
    """
    t = " ".join(text.split())
    if not t or any(c.isdigit() for c in t):
        return False
    if _ADVISORY.search(t):
        return True
    return len(t.split()) <= MAX_CONNECTIVE_WORDS and _CONNECTIVE_START.search(t) is not None


def _speakable(lead: str | None, passed: list[str], withheld: int, *, factual: bool = True) -> str:
    room = MAX_SPEAKABLE_SENTENCES - (1 if lead else 0) - (1 if withheld else 0)
    parts: list[str] = [lead] if lead else []
    chosen = passed[: max(room, 1)] if passed else []
    empty = (
        "I could not verify an answer to that, so I am not stating one."
        if factual or withheld
        else NO_FACTS_LINE
    )
    parts += chosen or [empty]
    if withheld:
        parts.append(
            "One sentence was left out because it could not be verified or tied to a source."
            if withheld == 1
            else f"{plural(withheld, 'sentence')} were left out because they could not be verified "
            "or tied to a source."
        )
    return compose(parts)


def _live_reason(s: Any) -> str:
    """Fixed-template reason for a blocked live sentence (no model-controlled text)."""
    parts = [
        _LIVE_REASONS.get(str(cv.claim.kind), _GENERIC_REASON)
        for cv in s.claim_verdicts
        if cv.status != "pass"
    ]
    if s.ungrounded:
        parts.append(_LIVE_REASONS["ungrounded"])
    return "; ".join(dict.fromkeys(parts)) or _GENERIC_REASON


def _split(
    items: list[Item], *, hide_withheld_text: bool
) -> tuple[list[str], list[Fact], list[WithheldSentence]]:
    """Sort sentences into spoken (gate-passed, linked, clean) and left out.

    Each item is ``(text, links, withheld_reason, claim_kinds)``. A spoken sentence is the
    text of at least one fact, so everything spoken has an openFDA or record link. With
    ``hide_withheld_text`` (live answers) a left-out sentence is replaced by a neutral
    placeholder whatever the reason; a sentence with a banned term is always replaced.
    Every left-out text and reason is screened with the banned-term list.
    """
    passed: list[str] = []
    facts: list[Fact] = []
    withheld: list[WithheldSentence] = []
    for text, found, reason, kinds in items:
        if reason is None and not found and not kinds and is_clean(text) and is_connective(text):
            continue  # a transition or greeting: not a fact, and not "held back" either
        if reason is None and not is_clean(text):
            reason = _FORBIDDEN_REASON
        if reason is None and not found:
            reason = _UNLINKED_REASON
        if reason is not None:
            shown = text
            if not is_clean(text):
                shown = _FORBIDDEN_TEXT
            elif hide_withheld_text:
                shown = _GATE_TEXT
            if hide_withheld_text:
                pass  # live: reasons are fixed templates built by _live_reason
            elif reason not in (_UNLINKED_REASON, _FORBIDDEN_REASON):
                reason = _safe_reason(reason, text)
            if not is_clean(shown):  # defensive: the screen has the last word
                shown = _FORBIDDEN_TEXT
            if not is_clean(reason):
                reason = _GENERIC_REASON
            withheld.append(
                WithheldSentence(text=shown, reason=reason, claim_kinds=sorted(set(kinds)))
            )
            continue
        passed.append(text)
        for link, label in dict.fromkeys(found):
            facts.append(Fact(text=text, link=link, link_label=label))
    return passed, facts, withheld


def _from_live(res: CopilotResult, data: ConnectorData, now: datetime) -> ToolAnswer:
    items: list[Item] = []
    for s in res.report.sentences:
        if s.status != "pass":
            kinds: list[str] = [cv.claim.kind for cv in s.claim_verdicts if cv.status != "pass"]
            items.append((s.text, [], _live_reason(s), kinds))
            continue
        found = [
            lk
            for cv in s.claim_verdicts
            if cv.status == "pass" and (lk := links.claim_link(cv.claim)) is not None
        ]
        items.append((s.text, found, None, [str(cv.claim.kind) for cv in s.claim_verdicts]))
    passed, facts, withheld = _split(items, hide_withheld_text=True)
    latest = str(data.manifest().get("max_date_received") or "")
    factual = any(kinds for _t, _l, _r, kinds in items) or any(
        not is_connective(t) for t, _l, _r, _k in items
    )
    return ToolAnswer(
        tool="ask",
        speakable=_speakable(None, passed, len(withheld), factual=factual),
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
            kinds = [str(c.get("kind")) for c in s.get("claims") or [] if isinstance(c, dict)]
            items.append((text, [], "; ".join(reasons) or "not verified", kinds))
            continue
        claims = [c for c in s.get("claims") or [] if isinstance(c, dict)]
        found: list[tuple[str, str]] = []
        for claim in claims:
            lk = links.recorded_claim_link(claim) if claim.get("status") == "pass" else None
            if lk and claim.get("kind") != "count":
                found.append(lk)
        found += links.recover_count_links(text, claims, data.store, windows)
        items.append((text, found, None, [str(c.get("kind")) for c in claims]))
    passed, facts, withheld = _split(items, hide_withheld_text=False)
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


@dataclass
class AskOutcome:
    """An ``ask`` answer plus what the live API reports about how it was made."""

    answer: ToolAnswer
    live: bool
    #: Why a recording was used (``cap``, ``no_model``, ``live_off``, ``model_error``,
    #: ``no_transcript``), or None for a live answer.
    reason: str | None = None
    cost_usd: float = 0.0
    model: str | None = None
    model_ms: float | None = None  # time inside model calls (measured)
    total_ms: float = 0.0  # whole ask, models + read-only tools + claim gate (measured)
    tool_names: list[str] = field(default_factory=list)
    recorded_question: str | None = None
    recorded_at: str | None = None
    #: When a recording was used after a live attempt failed: time spent on the attempt.
    attempt_ms: float = 0.0


class _TimedCompletions:
    def __init__(self, inner: Any, owner: _TimedClient) -> None:
        self._inner, self._owner = inner, owner

    def create(self, **kwargs: Any) -> Any:
        t0 = time.perf_counter()
        try:
            return self._inner.create(**kwargs)
        finally:
            self._owner.ms += (time.perf_counter() - t0) * 1000.0


class _TimedClient:
    """Adds up the time spent inside ``chat.completions.create`` (the model calls)."""

    def __init__(self, inner: Any) -> None:
        self.ms = 0.0
        completions = _TimedCompletions(inner.chat.completions, self)
        self.chat = type("Chat", (), {"completions": completions})()


def seed_history(agent: CopilotAgent, history: list[tuple[str, str]]) -> None:
    """Give the agent earlier question/answer pairs as conversation context.

    The agent keeps its context as chat messages (``_history``); there is no public setter.
    The pairs come from the browser, so they are context only: the new answer is still
    produced from tool results and checked sentence by sentence by the claim gate.
    """
    msgs: list[dict[str, Any]] = []
    for q, a in history:
        msgs += [{"role": "user", "content": q}, {"role": "assistant", "content": a}]
    agent._history = msgs[-8:]


def _recorded_pool(
    data: ConnectorData, q: str, *, voice: bool
) -> tuple[dict[str, Any] | None, int]:
    transcripts = data.transcripts()
    known = {r.product_code for r in data.store.records}
    related = [t for t in transcripts if _eligible(t, voice=voice) and _matches(q, t, known)]
    best = closest_recorded(q, related) if related else None
    return best, len(transcripts)


def _outcome_recorded(
    best: dict[str, Any] | None,
    reason: str,
    data: ConnectorData,
    started: float,
    attempt_ms: float = 0.0,
) -> AskOutcome:
    answer = _no_recording(reason) if best is None else _from_recorded(best, reason, data)
    shown = best if answer.provenance.source.startswith("Recorded run") and best else None
    return AskOutcome(
        answer=answer,
        live=False,
        reason=reason,
        total_ms=round((time.perf_counter() - started) * 1000.0, 1),
        recorded_question=str(shown.get("question") or "") if shown else None,
        recorded_at=str(shown.get("recorded_at_utc") or "") if shown else None,
        attempt_ms=attempt_ms,
    )


def recorded_voice_answer(data: ConnectorData, reason: str = "no_transcript") -> AskOutcome:
    """A recorded spoken-question run, for when the visitor's recording cannot be transcribed.

    The recorded question is named in the answer's lead; the visitor's own words are not
    known here, so nothing is claimed about them.

    Raises:
        SourceUnavailableError: No usable recorded voice run is stored.
    """
    started = time.perf_counter()
    usable = [t for t in data.transcripts() if _eligible(t, voice=True)]
    if not usable:
        raise SourceUnavailableError("No recorded spoken-question answer is stored.")

    def strength(t: dict[str, Any]) -> tuple[int, str]:
        passed = sum(1 for s in _recorded_sentences(t) if s.get("status") == "pass")
        return passed, str(t.get("label") or "")

    best = max(usable, key=strength)
    return _outcome_recorded(best, reason, data, started)


def _fallback(
    data: ConnectorData, q: str, spoken: bool, reason: str, started: float, attempt_ms: float
) -> AskOutcome:
    """The recorded answer for ``q`` (labelled with why), or an error when nothing is stored."""
    if not data.transcripts():
        raise SourceUnavailableError(
            "No live answer is available and no recorded answers are stored."
        )
    best, _ = _recorded_pool(data, q, voice=spoken)
    return _outcome_recorded(best, reason, data, started, attempt_ms)


def ask(
    data: ConnectorData,
    question: str,
    *,
    key_id: str,
    runtime: AskRuntime,
    now: Clock = utc_now,
    allow_live: bool = True,
) -> ToolAnswer:
    """Answer a question through the copilot and the claim gate, or from a recorded run.

    Args:
        data: Stored data.
        question: The caller's question (3 to 500 characters).
        key_id: Non-secret id of the calling API key (hash prefix), for its cost ledger.
        runtime: Live-model settings.
        now: Clock (tests).
        allow_live: False for the public demo key: never start a live model call.

    Raises:
        InvalidInputError: The question is empty or too long.
        SourceUnavailableError: No live answer and nothing recorded exists at all.
    """
    return ask_detailed(
        data, question, key_id=key_id, runtime=runtime, now=now, allow_live=allow_live
    ).answer


def ask_detailed(
    data: ConnectorData,
    question: str,
    *,
    key_id: str,
    runtime: AskRuntime,
    now: Clock = utc_now,
    history: list[tuple[str, str]] | None = None,
    spoken: bool = False,
    allow_live: bool = True,
) -> AskOutcome:
    """:func:`ask`, plus cost, timings and whether the answer was live or recorded.

    Args:
        data: Stored data.
        question: The caller's question (3 to 500 characters).
        key_id: Non-secret id of the ledger the cost is counted against.
        runtime: Live-model settings.
        now: Clock (tests).
        history: Earlier ``(question, answer)`` pairs from the same visitor (context only).
        spoken: The question is a voice transcript; spoken-question recordings may answer it.
        allow_live: False for the public demo key: a recorded answer only, never a model call.

    Raises:
        InvalidInputError: The question is empty or too long.
        SourceUnavailableError: No live answer and nothing recorded exists at all.
    """
    started = time.perf_counter()
    q = " ".join(question.split())
    if not (MIN_QUESTION_CHARS <= len(q) <= MAX_QUESTION_CHARS):
        raise InvalidInputError(
            f"Ask a question of {MIN_QUESTION_CHARS} to {MAX_QUESTION_CHARS} characters."
        )
    reason = "live_off" if os.environ.get("META_MODEL_API_KEY") else "no_model"
    attempt_ms = 0.0
    if not allow_live:
        reason = "demo_key"
    elif runtime.live_enabled():
        meter = runtime.call_meter()
        if meter is None:
            return _fallback(data, q, spoken, "live_off", started, 0.0)
        guard = SpendGuard(
            session_id=f"api-{key_id}",
            caps=runtime.caps,
            ledger=runtime.ledger_for(key_id),
            db=data.db,
            meter=meter,
        )
        try:
            guard.check("connector.ask")
            # One live ask at a time per instance: the copilot appends to the audit chain on
            # its own connection, and the redaction below recomputes that chain. Every chat call
            # of the agent (tool rounds, final answer, repair) reserves its own worst case.
            with data.live_ask_lock:
                agent = runtime.agent_factory(data, guard)
                make_read_only(agent)  # whatever the factory built: no tool that writes
                if runtime.lean:
                    apply_lean(agent, q)
                timed = _TimedClient(agent._client)
                agent._client = timed
                if history:
                    seed_history(agent, history)
                try:
                    res = agent.ask(q)
                finally:
                    data.redact_audit_questions()  # question text is not kept, only its hash
            if res.capa_ids or agent.context.created_capas:
                raise RuntimeError("a read-only ask wrote a record")  # never shown; falls back
            return AskOutcome(
                answer=_from_live(res, data, now()),
                live=True,
                cost_usd=res.cost_usd,
                model=res.model,
                model_ms=round(timed.ms, 1),
                total_ms=round((time.perf_counter() - started) * 1000.0, 1),
                tool_names=[t.name for t in res.tool_calls],
            )
        except SpendLimitError:
            reason = "cap"
            attempt_ms = round((time.perf_counter() - started) * 1000.0, 1)
        except (
            Exception
        ) as exc:  # noqa: BLE001 - any model/network failure falls back to a recording
            logger.warning("connector_ask_live_failed", error_type=type(exc).__name__)
            reason = "model_error"
            attempt_ms = round((time.perf_counter() - started) * 1000.0, 1)
    return _fallback(data, q, spoken, reason, started, attempt_ms)
