"""Verification questions per problem pattern, suggested by Muse Spark.

HACKATHON-BUILT — Meta Global AI Developer Hackathon (Oct 26 – Nov 4, 2026).

Muse Spark suggests 2-3 plain questions per problem pattern (``verification-questions``
Skill). Questions only: never an answer, a status or advice. The reply is validated by the
Skill's JSON schema and by deterministic checks here; a pattern whose questions fail any
check is dropped (never edited). The model call uses an OpenAI-compatible client (the
``MetaProvider.client`` the other Muse Spark features use), temperature 0.

Every surface that shows these questions prints :data:`LABEL`.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import jsonschema

from maudesignal.company.constants import contains_forbidden
from maudesignal.company.patterns import Pattern
from maudesignal.copilot.agent import default_skills_root
from maudesignal.copilot.meta_provider import SPARK_USD_PER_M_INPUT, SPARK_USD_PER_M_OUTPUT
from maudesignal.extraction.skill_loader import LoadedSkill, SkillLoader

SKILL_NAME = "verification-questions"
DEFAULT_MODEL = "muse-spark-1.3"
QUESTIONS_SCHEMA = "company-questions/1"
#: Printed on every surface that shows the questions.
LABEL = "Suggested by Muse Spark — your team decides"
CONFIDENCE_CAP = 0.95
MAX_QUOTES_SENT = 2

#: Status names, a decision or advice: none may appear in a question.
_STATUS_WORDS = re.compile(
    r"needs review|testing in progress|already covered|not applicable|monitoring"
    r"|\bstatus\b|\bcapa\b|\bshould\b|\bmust\b|need to|\bensure\b|recommend|\badvise\b"
    r"|\bdiagnos|\btreat(?:ment)?\b|clinical decision",
    re.IGNORECASE,
)
_DIGIT = re.compile(r"\d")


@dataclass(frozen=True)
class PatternQuestions:
    """Questions for one pattern, as accepted."""

    pattern_id: str
    questions: tuple[str, ...]
    confidence_score: float


@dataclass
class QuestionsResult:
    """Accepted questions plus the reasons any pattern was dropped."""

    accepted: list[PatternQuestions] = field(default_factory=list)
    dropped: list[tuple[str, str]] = field(default_factory=list)  # (pattern_id, reason)
    error: str | None = None


def load_skill(skill: LoadedSkill | None = None) -> LoadedSkill:
    """Load the ``verification-questions`` Skill."""
    return skill or SkillLoader(default_skills_root()).load(SKILL_NAME)


def question_problem(question: str) -> str | None:
    """Why a question is refused, or None when it is acceptable."""
    q = question.strip()
    if not q.endswith("?"):
        return "not a question"
    if q.count("?") != 1:
        return "more than one sentence"
    if _DIGIT.search(q):
        return "contains a number"
    if contains_forbidden(q):
        return "uses a word the product never prints"
    if _STATUS_WORDS.search(q):
        return "names a status, a decision or gives advice"
    return None


def patterns_input(patterns: list[Pattern]) -> dict[str, Any]:
    """Facts handed to the model: label, count and the gated verbatim quotes."""
    return {
        "patterns": [
            {
                "pattern_id": p.pattern_id,
                "label": p.label,
                "report_count": p.count,
                "quotes": [
                    {"report_id": q.report_id, "text": q.text} for q in p.quotes[:MAX_QUOTES_SENT]
                ],
            }
            for p in patterns
        ]
    }


def validate_questions(
    raw: str, allowed_ids: set[str], skill: LoadedSkill | None = None
) -> QuestionsResult:
    """Validate a model reply: JSON schema first, then per-pattern deterministic checks."""
    sk = load_skill(skill)
    res = QuestionsResult()
    try:
        doc = json.loads(raw)
        jsonschema.validate(doc, sk.output_schema)
    except (ValueError, jsonschema.ValidationError) as exc:
        res.error = f"reply is not valid against the schema: {str(exc).splitlines()[0][:160]}"
        return res
    seen: set[str] = set()
    for item in doc["patterns"]:
        pid = str(item["pattern_id"])
        conf = float(item["confidence_score"])
        questions = [str(q).strip() for q in item["questions"]]
        reason: str | None = None
        if pid not in allowed_ids:
            reason = "unknown pattern id"
        elif pid in seen:
            reason = "duplicate pattern id"
        elif conf >= 1.0 or conf > CONFIDENCE_CAP:
            reason = "confidence above the 0.95 cap"
        elif len({q.lower() for q in questions}) != len(questions):
            reason = "repeated question"
        else:
            for q in questions:
                reason = question_problem(q)
                if reason:
                    reason = f"{reason}: {q[:60]}"
                    break
        seen.add(pid)
        if reason:
            res.dropped.append((pid, reason))
        else:
            res.accepted.append(PatternQuestions(pid, tuple(questions), conf))
    return res


@dataclass
class QuestionsDraft:
    """Raw model call outcome."""

    raw_output: str
    model: str
    skill_version: str
    input_tokens: int = 0
    output_tokens: int = 0

    @property
    def cost_usd(self) -> float:
        """Estimated Muse Spark cost of the call."""
        return round(
            self.input_tokens * SPARK_USD_PER_M_INPUT / 1e6
            + self.output_tokens * SPARK_USD_PER_M_OUTPUT / 1e6,
            6,
        )


def draft_questions(
    client: Any,
    patterns: list[Pattern],
    *,
    model: str = DEFAULT_MODEL,
    skill: LoadedSkill | None = None,
    max_tokens: int = 16000,
) -> QuestionsDraft:
    """Ask Muse Spark for questions (one call, temperature 0).

    Raises:
        ValueError: a Contributor-tier model was requested.
    """
    if "contributor" in model.lower():
        raise ValueError("Contributor-tier models train on your data; use Standard tier.")
    sk = load_skill(skill)
    resp = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": sk.system_prompt},
            {"role": "user", "content": json.dumps(patterns_input(patterns), default=str)},
        ],
        max_tokens=max_tokens,
        temperature=0.0,
    )
    usage = getattr(resp, "usage", None)
    return QuestionsDraft(
        raw_output=str(resp.choices[0].message.content or ""),
        model=model,
        skill_version=sk.version,
        input_tokens=int(getattr(usage, "prompt_tokens", 0) or 0) if usage else 0,
        output_tokens=int(getattr(usage, "completion_tokens", 0) or 0) if usage else 0,
    )


def questions_path(folder: Path | None = None) -> Path:
    """Where the recorded questions live."""
    from maudesignal.company.constants import company_dir

    return (folder or company_dir()) / "questions.json"


def questions_document(
    per_code: dict[str, tuple[QuestionsDraft, QuestionsResult]],
    now: datetime | None = None,
) -> dict[str, Any]:
    """The ``questions.json`` document: accepted questions per product code, with the label."""
    created = (now or datetime.now(UTC)).strftime("%Y-%m-%dT%H:%M:%SZ")
    codes: dict[str, Any] = {}
    cost = 0.0
    for code, (draft, res) in sorted(per_code.items()):
        cost += draft.cost_usd
        codes[code] = {
            "model": draft.model,
            "skill_version": draft.skill_version,
            "input_tokens": draft.input_tokens,
            "output_tokens": draft.output_tokens,
            "error": res.error,
            "patterns": {
                a.pattern_id: {
                    "questions": list(a.questions),
                    "confidence_score": a.confidence_score,
                }
                for a in res.accepted
            },
            "dropped": [{"pattern_id": pid, "reason": why} for pid, why in res.dropped],
        }
    return {
        "schema": QUESTIONS_SCHEMA,
        "label": LABEL,
        "banner": "Simulated company — sample data. Problem evidence is real FDA data.",
        "note": "Questions only. Not answers, not a status, not advice.",
        "created_at": created,
        "cost_usd": round(cost, 6),
        "codes": codes,
    }


def load_questions(folder: Path | None = None) -> dict[str, dict[str, list[str]]]:
    """Product code -> pattern id -> questions, from ``questions.json`` ({} when absent).

    The stored questions are re-checked with :func:`question_problem` on every load, so
    an edited file cannot show a status word, a number or advice.
    """
    path = questions_path(folder)
    if not path.is_file():
        return {}
    doc = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(doc, dict) or doc.get("schema") != QUESTIONS_SCHEMA:
        return {}
    out: dict[str, dict[str, list[str]]] = {}
    for code, body in (doc.get("codes") or {}).items():
        for pid, item in (body.get("patterns") or {}).items():
            qs = [str(q) for q in item.get("questions", [])]
            if 2 <= len(qs) <= 3 and all(question_problem(q) is None for q in qs):
                out.setdefault(code, {})[pid] = qs
    return out
