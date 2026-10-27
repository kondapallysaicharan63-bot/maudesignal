"""Tool-using safety copilot with a claim-level gate and a repair turn.

HACKATHON-BUILT — Meta Global AI Developer Hackathon (Oct 26 – Nov 4, 2026).

Loop, for one user question:

1. Muse Spark (Meta Model API) picks tools — overnight signals, product
   summaries, report search, MDR deadline clock, CAPA draft — and reads their
   JSON results.
2. When it stops calling tools, the final answer is requested with Meta's
   strict ``json_schema`` ``response_format`` (schema from
   ``skills/safety-copilot/schemas/output.schema.json``) and no tools, so it is
   always structured sentences, each tagged with the claims it makes. Tool
   rounds never carry ``response_format``: Meta's docs do not say the two may
   be combined in one request. The tolerant ``parse_answer`` stays as fallback.
3. The deterministic gate (``maudesignal.gate``) recomputes every number and
   matches every quote / id / CFR section against stored evidence.
4. If anything is blocked, the model gets ONE repair turn with the gate's
   reasons and recomputed values. Whatever still fails is withheld, with the
   reason shown.
5. The question, tools used and gate outcome are written to the hash-chained
   audit trail.

The model client is injected (any OpenAI-compatible client), so tests run with
a scripted fake and the demo can replay stored transcripts with no key.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from maudesignal.copilot.meta_provider import SPARK_USD_PER_M_INPUT, SPARK_USD_PER_M_OUTPUT
from maudesignal.copilot.tools import TOOL_SCHEMAS, ToolContext, call_tool
from maudesignal.extraction.skill_loader import LoadedSkill, SkillLoader
from maudesignal.gate import Claim, ClaimParseError, GateReport, claim_from_dict, verify_answer

SKILL_NAME = "safety-copilot"
RESPONSE_FORMAT_NAME = "safety_copilot_answer"
# Accepted by Muse Spark per https://dev.meta.ai/docs/reasoning (checked 2026-10-27);
# "none" returns HTTP 400 for Muse Spark, so it is not offered.
REASONING_EFFORTS = ("minimal", "low", "medium", "high", "xhigh", "max")
_SCHEMA_META_KEYS = ("$schema", "$id", "title", "description")
_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)


def default_skills_root() -> Path:
    """Repo-level ``skills/`` directory."""
    return Path(__file__).resolve().parents[3] / "skills"


@dataclass
class ToolCallTrace:
    """One tool call the model made."""

    name: str
    arguments: dict[str, Any]
    result_preview: str


@dataclass
class CopilotResult:
    """Everything the UI needs to show an answer honestly."""

    question: str
    answer: str
    report: GateReport
    first_pass_report: GateReport
    repaired: bool
    tool_calls: list[ToolCallTrace] = field(default_factory=list)
    capa_ids: list[str] = field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0
    model: str = ""
    parse_failed: bool = False

    @property
    def cost_usd(self) -> float:
        """Estimated Muse Spark cost of this answer."""
        return round(
            self.input_tokens * SPARK_USD_PER_M_INPUT / 1e6
            + self.output_tokens * SPARK_USD_PER_M_OUTPUT / 1e6,
            6,
        )

    @property
    def sentences_repaired(self) -> int:
        """Sentences blocked on the first pass that passed after the repair turn."""
        if not self.repaired:
            return 0
        return max(0, self.report.passed - self.first_pass_report.passed)


def parse_answer(content: str) -> list[tuple[str, list[Claim]]]:
    """Parse the model's JSON answer into (sentence, claims) pairs.

    Raises:
        ValueError: content is not the expected JSON shape.
    """
    text = _FENCE.sub("", content.strip())
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end < 0:
        raise ValueError("no JSON object in model output")
    data = json.loads(text[start : end + 1])
    sentences = data.get("sentences") if isinstance(data, dict) else None
    if not isinstance(sentences, list):
        raise ValueError("missing 'sentences' list")
    out: list[tuple[str, list[Claim]]] = []
    for s in sentences:
        if not isinstance(s, dict) or not isinstance(s.get("text"), str):
            raise ValueError("each sentence needs a 'text' string")
        claims: list[Claim] = []
        for c in s.get("claims") or []:
            try:
                claims.append(claim_from_dict(c))
            except ClaimParseError:
                # A malformed claim can't be verified: keep the sentence but force a block
                # by tagging a claim that can never pass.
                claims.append(claim_from_dict({"kind": "record", "report_id": "<malformed>"}))
        out.append((s["text"].strip(), claims))
    return out


def response_format_from_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Wrap a Skill output schema as a strict ``json_schema`` response_format.

    Root-level annotation keys (``$schema``, ``title``, ...) are dropped: the
    strict subset requires a plain object root and the docs do not list them.
    """
    body = {k: v for k, v in schema.items() if k not in _SCHEMA_META_KEYS}
    return {
        "type": "json_schema",
        "json_schema": {"name": RESPONSE_FORMAT_NAME, "schema": body, "strict": True},
    }


def _repair_message(report: GateReport) -> str:
    lines = ["GATE BLOCKED — these sentences were withheld:"]
    for i, s in enumerate(report.sentences):
        if s.status == "block":
            lines.append(f"[{i}] {s.text}")
            for cv in s.claim_verdicts:
                if cv.status == "block":
                    extra = f" (recomputed={cv.recomputed})" if cv.recomputed is not None else ""
                    lines.append(f"    - {cv.claim.kind}: {cv.reason}{extra}")
            for u in s.ungrounded:
                lines.append(f"    - ungrounded: {u}")
    lines.append("Return the full corrected answer as the same JSON object.")
    return "\n".join(lines)


class CopilotAgent:
    """Muse Spark tool-use loop + citation gate + one repair turn."""

    def __init__(
        self,
        client: Any,
        ctx: ToolContext,
        *,
        model: str = "muse-spark-1.3",
        skill: LoadedSkill | None = None,
        max_tool_rounds: int = 6,
        max_repairs: int = 1,
        max_tokens: int = 1500,
        structured_output: bool = True,
        reasoning_effort: str | None = None,
    ) -> None:
        """Create an agent.

        Args:
            client: OpenAI-compatible client (``MetaProvider.client`` in production).
            ctx: Tool context (database + evidence store).
            model: Meta model id. Standard tier only — never a ``-contributor`` model.
            skill: Loaded ``safety-copilot`` skill (loaded from ``skills/`` if omitted).
            max_tool_rounds: Cap on model turns that call tools.
            max_repairs: Repair turns after a gate block.
            max_tokens: Output cap per model call (reasoning tokens count toward it).
            structured_output: Request the final answer with the strict
                ``json_schema`` response_format (no tools on that call).
            reasoning_effort: Optional Chat Completions ``reasoning_effort``
                (``minimal`` ... ``max``); None omits the parameter so the model
                reasons at its own default level.
        """
        if "contributor" in model.lower():
            raise ValueError("Contributor-tier models train on your data; use Standard tier.")
        if reasoning_effort is not None and reasoning_effort not in REASONING_EFFORTS:
            raise ValueError(f"reasoning_effort must be one of {REASONING_EFFORTS}")
        self._client = client
        self._ctx = ctx
        self._model = model
        self._skill = skill or SkillLoader(default_skills_root()).load(SKILL_NAME)
        self._max_tool_rounds = max_tool_rounds
        self._max_repairs = max_repairs
        self._max_tokens = max_tokens
        self._structured = structured_output
        self._reasoning_effort = reasoning_effort
        self._response_format = response_format_from_schema(self._skill.output_schema)
        self._history: list[dict[str, Any]] = []

    @property
    def context(self) -> ToolContext:
        """The tool context (database + evidence store) this agent answers from."""
        return self._ctx

    @staticmethod
    def question_entity_id(question: str) -> str:
        """Audit-trail entity id of a ``copilot.answer`` entry for ``question``."""
        return f"Q-{hashlib.sha256(question.encode('utf-8')).hexdigest()[:16]}"

    @property
    def skill_version(self) -> str:
        """Version of the behavior contract in use."""
        return self._skill.version

    @property
    def response_format(self) -> dict[str, Any]:
        """The strict json_schema response_format sent on final-answer calls."""
        return self._response_format

    def _create(self, messages: list[dict[str, Any]], *, tools: bool) -> Any:
        """One chat-completions call: a tool round (``tools``) or a final-answer call."""
        kwargs: dict[str, Any] = {
            "model": self._model,
            "messages": messages,
            "max_tokens": self._max_tokens,
            "temperature": 0.0,
        }
        if self._reasoning_effort is not None:
            kwargs["reasoning_effort"] = self._reasoning_effort
        if tools:
            kwargs["tools"] = TOOL_SCHEMAS
            kwargs["tool_choice"] = "auto"  # the only value Meta's API accepts
        elif self._structured:
            kwargs["response_format"] = self._response_format
        return self._client.chat.completions.create(**kwargs)

    def _final_answer(self, messages: list[dict[str, Any]], result: CopilotResult) -> str:
        """Final-answer call: no tools, schema-constrained when structured output is on."""
        resp = self._create(messages, tools=False)
        self._count(resp, result)
        return str(resp.choices[0].message.content or "")

    def ask(self, question: str) -> CopilotResult:
        """Answer one question (multi-turn: earlier Q/A pairs are kept as context)."""
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": self._skill.system_prompt},
            *self._history,
            {"role": "user", "content": question},
        ]
        result = CopilotResult(
            question=question,
            answer="",
            report=GateReport(),
            first_pass_report=GateReport(),
            repaired=False,
            model=self._model,
        )
        capa_start = len(self._ctx.created_capas)
        content = self._run_until_answer(messages, result)
        sentences, ok = self._parse_or_retry(content, messages, result)
        result.parse_failed = not ok
        report = verify_answer(sentences, self._ctx.store)
        result.first_pass_report = report

        repairs = 0
        while report.blocked and repairs < self._max_repairs:
            repairs += 1
            messages.append({"role": "user", "content": _repair_message(report)})
            content = self._run_until_answer(messages, result)
            repaired, ok = self._parse_or_retry(content, messages, result)
            if not ok:
                break
            report = verify_answer(repaired, self._ctx.store)
            result.repaired = True

        result.report = report
        result.answer = report.render()
        result.capa_ids = list(self._ctx.created_capas[capa_start:])
        self._history += [
            {"role": "user", "content": question},
            {"role": "assistant", "content": result.answer},
        ]
        self._history = self._history[-8:]
        self._audit(result)
        return result

    def _run_until_answer(self, messages: list[dict[str, Any]], result: CopilotResult) -> str:
        for _ in range(self._max_tool_rounds):
            resp = self._create(messages, tools=True)
            self._count(resp, result)
            msg = resp.choices[0].message
            tool_calls = getattr(msg, "tool_calls", None) or []
            if not tool_calls:
                if self._structured:
                    # The model is done with tools; ask again for the answer
                    # under the strict schema (its free-form draft is dropped).
                    return self._final_answer(messages, result)
                return str(msg.content or "")
            messages.append(
                {
                    "role": "assistant",
                    "content": msg.content or "",
                    "tool_calls": [
                        {
                            "id": tc.id,
                            "type": "function",
                            "function": {
                                "name": tc.function.name,
                                "arguments": tc.function.arguments,
                            },
                        }
                        for tc in tool_calls
                    ],
                }
            )
            for tc in tool_calls:
                out = call_tool(self._ctx, tc.function.name, tc.function.arguments)
                payload = json.dumps(out, default=str)
                try:
                    args = json.loads(tc.function.arguments or "{}")
                except ValueError:
                    args = {"_raw": tc.function.arguments}
                result.tool_calls.append(ToolCallTrace(tc.function.name, args, payload[:300]))
                messages.append({"role": "tool", "tool_call_id": tc.id, "content": payload})
        # Tool budget exhausted: ask for the answer without tools.
        messages.append({"role": "user", "content": "Answer now with the JSON object only."})
        return self._final_answer(messages, result)

    def _parse_or_retry(
        self, content: str, messages: list[dict[str, Any]], result: CopilotResult
    ) -> tuple[list[tuple[str, list[Claim]]], bool]:
        try:
            parsed = parse_answer(content)
            messages.append({"role": "assistant", "content": content})
            return parsed, True
        except (ValueError, json.JSONDecodeError):
            messages.append({"role": "assistant", "content": content})
            messages.append(
                {
                    "role": "user",
                    "content": "Your reply was not the required JSON object. "
                    'Return only {"sentences": [{"text": ..., "claims": [...]}]}.',
                }
            )
            retry = self._final_answer(messages, result)
            try:
                parsed = parse_answer(retry)
                messages.append({"role": "assistant", "content": retry})
                return parsed, True
            except (ValueError, json.JSONDecodeError):
                # Unparseable prose is gated as one claim-less sentence: anything
                # checkable inside it is then blocked as ungrounded.
                return [(retry.strip() or content.strip(), [])], False

    @staticmethod
    def _count(resp: Any, result: CopilotResult) -> None:
        usage = getattr(resp, "usage", None)
        if usage is not None:
            result.input_tokens += int(getattr(usage, "prompt_tokens", 0) or 0)
            result.output_tokens += int(getattr(usage, "completion_tokens", 0) or 0)

    def _audit(self, result: CopilotResult) -> None:
        self._ctx.db.append_audit(
            actor=self._ctx.actor,
            action="copilot.answer",
            entity_id=self.question_entity_id(result.question),
            payload={
                "question": result.question[:500],
                "model": result.model,
                "skill_version": self.skill_version,
                "structured_output": self._structured,
                "reasoning_effort": self._reasoning_effort,
                "tools": [t.name for t in result.tool_calls],
                "gate_first_pass": {
                    "passed": result.first_pass_report.passed,
                    "blocked": result.first_pass_report.blocked,
                },
                "gate_final": {"passed": result.report.passed, "blocked": result.report.blocked},
                "repaired": result.repaired,
                "capa_ids": result.capa_ids,
                "input_tokens": result.input_tokens,
                "output_tokens": result.output_tokens,
            },
        )
