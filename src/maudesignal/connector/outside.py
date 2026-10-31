"""The ``outside_mentions`` connector tool: web research by product code (and a short topic).

HACKATHON-BUILT — Meta Global AI Developer Hackathon (Oct 26 – Nov 4, 2026).

A thin layer over :func:`maudesignal.connector.research.run_research`, the same function the
website's Research mode uses. It adds only what a connector tool needs:

* the question, built from a template in the ``web-research`` Skill (section "Connector
  question (outside_mentions)"); no prompt text lives in Python;
* the same research block back, unchanged, validated as :class:`OutsideMentionsAnswer`.

Gating (flag, full key only, per-key daily limit, product-code check, patient-data check of the
topic) and the audit entry are in ``app.py``; spend goes through the per-call ledger
(``callcap``) inside ``run_research``. The block is never passed to ``ask``, the claim gate, the
answer cache or any count: web results are not FDA records.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from pathlib import Path
from typing import Any, Protocol

from maudesignal.connector import research
from maudesignal.connector.callcap import CallLedger
from maudesignal.connector.mentions import Fetcher
from maudesignal.connector.models import OutsideMentionsAnswer
from maudesignal.extraction.skill_loader import SkillLoader

PER_KEY_DAY_ENV = "MAUDESIGNAL_RESEARCH_PER_KEY_DAY"
DEFAULT_PER_KEY_DAY = 10
QUESTION_HEADING = "## Connector question (outside_mentions)"
TOPIC_SLOT = "{topic}"
DEMO_REFUSAL = (
    "outside_mentions is not available with the demo key. It needs a full key, because each "
    "call is a paid web search."
)


class ResearchRunner(Protocol):
    """Signature of :func:`research.run_research` (tests pass a fake)."""

    def __call__(
        self,
        question: str,
        product_code: str | None,
        *,
        transport: research.ResearchTransport | None,
        ledger: CallLedger | None,
        fee_per_search: float = ...,
        news_fetcher: Callable[[], Fetcher] | None = ...,
        instructions: str | None = ...,
        hold_cap: float = ...,
    ) -> dict[str, Any]:
        """Run web research and return the research block."""


def per_key_day(env: dict[str, str] | None = None) -> int:
    """Calls per full key per UTC day (``MAUDESIGNAL_RESEARCH_PER_KEY_DAY``, default 10)."""
    raw = (os.environ if env is None else env).get(PER_KEY_DAY_ENV, "")
    try:
        value = int(str(raw).strip())
    except ValueError:
        return DEFAULT_PER_KEY_DAY
    return value if value > 0 else DEFAULT_PER_KEY_DAY


def load_templates(skills_root: Path | None = None) -> tuple[str, str]:
    """The two question templates ``(without topic, with topic)`` from the Skill file.

    Raises:
        ValueError: The section or its two quoted lines are missing, or the second has no
            ``{topic}`` slot.
    """
    root = skills_root or Path(__file__).resolve().parents[3] / "skills"
    text = SkillLoader(root).load(research.SKILL_NAME).system_prompt
    start = text.find(QUESTION_HEADING)
    if start < 0:
        raise ValueError("web-research SKILL.md has no connector question section")
    body = text[start + len(QUESTION_HEADING) :]
    end = body.find("\n## ")
    section = body if end < 0 else body[:end]
    quoted = [ln[1:].strip() for ln in section.splitlines() if ln.startswith(">")]
    if len(quoted) < 2 or TOPIC_SLOT not in quoted[1] or TOPIC_SLOT in quoted[0]:
        raise ValueError("web-research connector question section is malformed")
    return quoted[0], quoted[1]


def build_question(topic: str | None, templates: tuple[str, str] | None = None) -> str:
    """The question sent for one call (the product code is appended by ``run_research``)."""
    plain, with_topic = templates or load_templates()
    clean = " ".join((topic or "").split())
    return with_topic.replace(TOPIC_SLOT, clean) if clean else plain


def outside_mentions(
    product_code: str,
    topic: str | None,
    *,
    runner: ResearchRunner,
    transport: research.ResearchTransport | None,
    ledger: CallLedger | None,
    news_fetcher: Callable[[], Fetcher] | None,
    fee_per_search: float,
    hold_cap: float,
) -> OutsideMentionsAnswer:
    """Run web research for one product code and return the labelled block, unchanged.

    Args:
        product_code: Three-letter product code (already checked by the caller).
        topic: Optional short topic (already length- and patient-data-checked).
        runner: ``research.run_research`` (tests pass a fake).
        transport: Responses API transport, ``None`` when live calls are off.
        ledger: The daily per-call ledger; ``None`` means no call is made.
        news_fetcher: GDELT backup fetcher factory (``None``: no backup).
        fee_per_search: Search-fee allowance in USD.
        hold_cap: Research's per-call hold limit in USD (``research.hold_cap_usd``).
    """
    try:
        question = build_question(topic)
    except (OSError, ValueError):
        return OutsideMentionsAnswer.model_validate(
            research.block("unavailable", [], None, 0.0, research.NOTE_UNAVAILABLE)
        )
    found = runner(
        question,
        product_code.upper(),
        transport=transport,
        ledger=ledger,
        fee_per_search=fee_per_search,
        news_fetcher=news_fetcher,
        hold_cap=hold_cap,
    )
    return OutsideMentionsAnswer.model_validate(found)


def limit_answer(limit: int) -> OutsideMentionsAnswer:
    """The block for a key whose daily limit is used up (no call made, nothing spent)."""
    return OutsideMentionsAnswer.model_validate(research.limit_block(limit))
