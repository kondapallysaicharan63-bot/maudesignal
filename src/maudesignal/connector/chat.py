"""The chat tiers wired to the website chat and to the connector's ``ask`` tool.

HACKATHON-BUILT — Meta Global AI Developer Hackathon (Oct 26 – Nov 4, 2026).

``tiers.route`` decides the tier; this module builds the answer of tiers 1 to 3 in the two
shapes the surfaces use (the live route's JSON body, and :class:`AskAnswer` for the connector),
and runs tier 4 (``ask.ask_detailed``) for the connector with the six-hour cache around it.
The live route runs tier 4 itself (it owns the daily limit and the spend ledger).

Tiers 1 to 3 make no model call, never touch the per-call spend ledger (``callcap``) and cost
$0. Their every FDA fact passed the claim gate in ``direct.py`` or, for a cache hit, when the
live answer was first made.
"""

from __future__ import annotations

from typing import Any

from maudesignal.connector.answer_cache import AnswerCache, CachedAnswer
from maudesignal.connector.ask import AskRuntime, ask_detailed
from maudesignal.connector.data import ConnectorData
from maudesignal.connector.direct import DirectAnswer
from maudesignal.connector.direct import answer as direct_answer
from maudesignal.connector.forbidden import is_clean
from maudesignal.connector.models import AskAnswer, Fact, Provenance, WithheldSentence
from maudesignal.connector.speech import compose
from maudesignal.connector.tiers import (
    BADGE_CACHE,
    BADGE_CANNED,
    BADGE_DIRECT,
    Route,
    canned_sentences,
    route,
)
from maudesignal.connector.tools import Clock, _stamp, snapshot_provenance, utc_now

MAX_SPEAKABLE = 3
DIRECT_NOTE = (
    "Direct lookup, no AI model: the values come from MaudeSignal's own read-only tools and "
    "every sentence passed the claim gate."
)
CANNED_SOURCE = "Fixed MaudeSignal reply; no FDA facts and no model call"
_GATE_TEXT = "Sentence left out by the claim gate."


def route_for(
    data: ConnectorData,
    question: str,
    product_code: str | None = None,
    *,
    has_history: bool = False,
) -> Route:
    """The tier of a question over this connector's known product codes."""
    return route(question, data.known_product_codes(), product_code, has_history=has_history)


# ---------------------------------------------------------------------------
# Live route bodies (POST /v1/live/ask); the caller adds ``limits``
# ---------------------------------------------------------------------------


def _step(step: str, ms: float, note: str | None = None) -> dict[str, Any]:
    out: dict[str, Any] = {"step": step, "model": None, "ms": int(round(ms)), "status": "ok"}
    if note:
        out["note"] = note
    return out


def _answer_block(
    sentences: list[tuple[str, list[tuple[str, str]]]], withheld: list[str]
) -> dict[str, Any]:
    shown = [(t, ls) for t, ls in sentences if is_clean(t)]
    return {
        "speakable": [
            {"text": t, "links": [{"label": label, "url": url} for url, label in ls]}
            for t, ls in shown
        ],
        "withheld": [{"reason": r} for r in withheld],
        "spoken_text": compose([t for t, _ in shown]),
    }


def canned_body(r: Route, ms: float) -> dict[str, Any]:
    """Body of a tier-1 reply."""
    return {
        "mode": "canned",
        "tier": "canned",
        "intent": r.intent,
        "badge": BADGE_CANNED,
        "not_medical_advice": True,
        "answer": _answer_block([(t, []) for t in canned_sentences(r.intent)], []),
        "trace": [_step("Fixed reply, no model call", ms, f"recognised as {r.intent}")],
        "cost_usd": 0.0,
        "suggestions": list(r.suggestions),
    }


def direct_body(d: DirectAnswer, ms: float) -> dict[str, Any]:
    """Body of a tier-2 answer."""
    passed = len(d.sentences)
    note = (
        f"{d.gate_checked} sentence(s) checked, {len(d.withheld)} held back"
        if d.gate_checked
        else "no FDA figures in this answer"
    )
    body: dict[str, Any] = {
        "mode": "direct",
        "tier": "direct",
        "intent": d.intent,
        "badge": BADGE_DIRECT,
        "not_medical_advice": True,
        "answer": _answer_block([(s.text, s.links) for s in d.sentences], d.withheld),
        "trace": [
            _step(f"Direct lookup: {d.tool}", ms, f"{passed} sentence(s) shown"),
            _step("Claim gate", 0.0, note),
        ],
        "cost_usd": 0.0,
        "suggestions": d.suggestions,
        "source": d.source,
    }
    if d.did_you_mean:
        body["did_you_mean"] = d.did_you_mean
    if d.open:
        body["open"] = d.open
    return body


def cached_body(hit: CachedAnswer, ms: float) -> dict[str, Any]:
    """Body of a tier-3 answer: the earlier live answer, at no cost and no limit use."""
    old = hit.body
    return {
        "mode": "live",
        "tier": "cache",
        "badge": BADGE_CACHE,
        "not_medical_advice": True,
        "answer": old["answer"],
        "trace": [
            _step(
                "Answer reused from earlier today, no model call",
                ms,
                f"first answered by Muse Spark at {hit.stored_at_iso}",
            )
        ],
        "cost_usd": 0.0,
        "answered_at": hit.stored_at_iso,
        "suggestions": [],
    }


def has_fact(body: dict[str, Any]) -> bool:
    """True when a live body shows at least one gate-passed, linked sentence.

    An answer whose every sentence was held back (only the fixed "could not verify" line is
    left) is not cached: asking again may give a checked answer.
    """
    items = (body.get("answer") or {}).get("speakable") or []
    return any(isinstance(i, dict) and i.get("links") for i in items)


def cache_entry(body: dict[str, Any]) -> dict[str, Any]:
    """What is kept of a live answer for the cache (the shown answer; no question text)."""
    return {"answer": body["answer"], "mode": body.get("mode"), "cost_usd": body.get("cost_usd")}


# ---------------------------------------------------------------------------
# Connector ``ask`` (REST and MCP)
# ---------------------------------------------------------------------------


def canned_answer(r: Route, now: Clock = utc_now) -> AskAnswer:
    """Tier 1 as an :class:`AskAnswer`."""
    return AskAnswer(
        tool="ask",
        speakable=compose(list(canned_sentences(r.intent))),
        facts=[],
        provenance=Provenance(
            kind="canned_reply", source=CANNED_SOURCE, queried_at_utc=_stamp(now())
        ),
        tier="canned",
        cost_usd=0.0,
        badge=BADGE_CANNED,
        suggestions=list(r.suggestions),
    )


def direct_tool_answer(d: DirectAnswer, data: ConnectorData, now: Clock = utc_now) -> AskAnswer:
    """Tier 2 as an :class:`AskAnswer`: shown sentences become facts with their links."""
    facts = [
        Fact(text=s.text, link=url, link_label=label)
        for s in d.sentences
        for url, label in s.links
        if url.startswith("https://")
    ]
    prov = snapshot_provenance(data, None)
    prov.source = d.source
    prov.queried_at_utc = _stamp(now())
    prov.note = DIRECT_NOTE
    return AskAnswer(
        tool="ask",
        speakable=compose([s.text for s in d.sentences[:MAX_SPEAKABLE]])
        or "I have no checked answer to that.",
        facts=facts,
        provenance=prov,
        withheld=[WithheldSentence(text=_GATE_TEXT, reason=r) for r in d.withheld],
        tier="direct",
        cost_usd=0.0,
        badge=BADGE_DIRECT,
        suggestions=d.suggestions,
        did_you_mean=d.did_you_mean,
    )


def ask_with_tiers(
    data: ConnectorData,
    question: str,
    *,
    key_id: str,
    runtime: AskRuntime,
    cache: AnswerCache | None,
    now: Clock = utc_now,
    allow_live: bool = True,
    tiers_on: bool = True,
) -> AskAnswer:
    """The connector's ``ask``: tiers 1 to 3 first, then Muse Spark (or a recorded run).

    Raises:
        InvalidInputError: The question is empty or too long (tier 4 only).
        SourceUnavailableError: Tier 4 has no live answer and nothing recorded.
    """
    if tiers_on:
        r = route_for(data, question)
        if r.tier == "canned":
            return canned_answer(r, now)
        if r.tier == "direct":
            return direct_tool_answer(direct_answer(data, r), data, now)
        if cache is not None and allow_live:  # the demo key never gets a live answer
            hit = cache.get(question)
            if hit is not None:
                try:
                    cached = AskAnswer.model_validate(hit.body)
                except ValueError:
                    cached = None
                if cached is not None:
                    cached.tier, cached.cost_usd, cached.badge = "cache", 0.0, BADGE_CACHE
                    cached.provenance.note = (
                        f"{BADGE_CACHE}: first answered by Muse Spark at {hit.stored_at_iso}."
                    )
                    return cached
    outcome = ask_detailed(
        data, question, key_id=key_id, runtime=runtime, now=now, allow_live=allow_live
    )
    out = AskAnswer(
        **outcome.answer.model_dump(),
        tier="live",
        cost_usd=round(outcome.cost_usd, 6) if outcome.live else None,
    )
    if tiers_on and cache is not None and outcome.live and out.facts:
        cache.put(question, None, out.model_dump(mode="json"))  # one question, no history
    return out
