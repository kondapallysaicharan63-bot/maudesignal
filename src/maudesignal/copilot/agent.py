"""Tool-using safety copilot with a claim-level gate and a repair turn.

HACKATHON-BUILT — Meta Global AI Developer Hackathon (Oct 26 – Nov 4, 2026).

Loop, for one user question:

1. Muse Spark (Meta Model API) picks tools — what changed, product
   summaries, report search, MDR deadline clock, CAPA-need evidence pack — and reads their
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
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from maudesignal.copilot.dates import render_date_context, utc_today
from maudesignal.copilot.meta_provider import SPARK_USD_PER_M_INPUT, SPARK_USD_PER_M_OUTPUT
from maudesignal.copilot.protocol import ProtocolRow, protocol_from_calls
from maudesignal.copilot.tools import TOOL_SCHEMAS, ToolContext, call_tool
from maudesignal.extraction.skill_loader import LoadedSkill, SkillLoader
from maudesignal.gate import (
    Claim,
    ClaimParseError,
    GateReport,
    SentenceVerdict,
    claim_from_dict,
    verify_answer,
)

SKILL_NAME = "safety-copilot"
RESPONSE_FORMAT_NAME = "safety_copilot_answer"
# Accepted by Muse Spark per https://dev.meta.ai/docs/reasoning (checked 2026-10-27);
# "none" returns HTTP 400 for Muse Spark, so it is not offered.
REASONING_EFFORTS = ("minimal", "low", "medium", "high", "xhigh", "max")
_SCHEMA_META_KEYS = ("$schema", "$id", "title", "description")
_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)


#: Markers around the short live prompt inside ``skills/safety-copilot/SKILL.md``.
COMPACT_START = "<!-- live-compact-prompt:start -->"
COMPACT_END = "<!-- live-compact-prompt:end -->"


#: Markers around the date-context template inside ``skills/safety-copilot/SKILL.md``.
DATE_CONTEXT_START = "<!-- date-context:start -->"
DATE_CONTEXT_END = "<!-- date-context:end -->"


def _cut_block(text: str, start_marker: str, end_marker: str) -> tuple[str, str | None]:
    """``(text without the block, block body)``; the body is None when the markers are absent."""
    start, end = text.find(start_marker), text.find(end_marker)
    if start < 0 or end < start:
        return text, None
    body = text[start + len(start_marker) : end].strip()
    rest = (text[:start].rstrip() + "\n\n" + text[end + len(end_marker) :].lstrip()).strip()
    return rest, body or None


def date_context_template(skill_md: str) -> str | None:
    """The date-context template of a SKILL.md text (None when it has none).

    Its ``{today}``, ``{data_from}``, ``{data_to}``, ``{data_year}``, ``{code_windows}`` and
    ``{sweep}`` placeholders are filled by :func:`maudesignal.copilot.dates.render_date_context`
    on every question and appended to the system prompt (full or compact).
    """
    return _cut_block(skill_md, DATE_CONTEXT_START, DATE_CONTEXT_END)[1]


def split_prompts(skill_md: str) -> tuple[str, str | None]:
    """``(full_prompt, compact_prompt)`` from a SKILL.md text.

    The compact prompt is the text between :data:`COMPACT_START` and :data:`COMPACT_END`
    (None when the markers are absent). The full prompt is the whole file without that block,
    so other callers are never sent the compact text twice. The date-context template is
    removed from both (it is filled and appended per question, see
    :func:`date_context_template`).
    """
    skill_md = _cut_block(skill_md, DATE_CONTEXT_START, DATE_CONTEXT_END)[0]
    start, end = skill_md.find(COMPACT_START), skill_md.find(COMPACT_END)
    if start < 0 or end < start:
        return skill_md, None
    compact = skill_md[start + len(COMPACT_START) : end].strip()
    full = (
        skill_md[:start].rstrip() + "\n\n" + skill_md[end + len(COMPACT_END) :].lstrip()
    ).strip()
    return full, compact or None


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
    length_stops: int = 0

    @property
    def protocol(self) -> list[ProtocolRow]:
        """Search protocol of this answer: one row per search tool call, from stored values."""
        return protocol_from_calls(
            [
                {"name": t.name, "arguments": t.arguments, "result_preview": t.result_preview}
                for t in self.tool_calls
            ]
        )

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


UNPARSED_REASON = "the model did not return a structured answer, so nothing from it is shown"


def _unparsed(content: str) -> GateReport:
    """A reply that never parsed is withheld, never passed as one claim-less sentence.

    Passing it would let an empty reply, or claims hidden inside JSON-looking text,
    count as verified (both happened in the 2026-10-28 recording).
    """
    text = content.strip()[:300] or "(empty reply)"
    return GateReport([SentenceVerdict(text, "block", (), (UNPARSED_REASON,))])


EventFn = Callable[[str, dict[str, Any]], None]
"""Progress callback: ``(kind, data)`` with kind in model / tool / gate / repair / done."""


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
        max_tokens: int = 8000,
        structured_output: bool = True,
        reasoning_effort: str | None = None,
        allowed_tools: frozenset[str] | None = None,
    ) -> None:
        """Create an agent.

        Args:
            client: OpenAI-compatible client (``MetaProvider.client`` in production).
            ctx: Tool context (database + evidence store).
            model: Meta model id. Standard tier only — never a ``-contributor`` model.
            skill: Loaded ``safety-copilot`` skill (loaded from ``skills/`` if omitted).
            max_tool_rounds: Cap on model turns that call tools.
            max_repairs: Repair turns after a gate block.
            max_tokens: Output cap per model call. Reasoning tokens count toward it:
                at 1500, 11 of the 21 answers in the 2026-10-28 recording never returned
                parseable JSON, so it went to 4000; in the third recording 4 calls
                still stopped at 4000 and one answer came back empty, so the default
                is 8000 (≤ $0.034 of output per call, paid only when used);
                ``length_stops`` records whether the cap was the cause.
            structured_output: Request the final answer with the strict
                ``json_schema`` response_format (no tools on that call).
            reasoning_effort: Optional Chat Completions ``reasoning_effort``
                (``minimal`` ... ``max``); None omits the parameter so the model
                reasons at its own default level.
            allowed_tools: Tool names the model may use; None allows all. A call to any
                other tool is refused with an error result and is not executed.
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
        self._allowed_tools = allowed_tools
        self._response_format = response_format_from_schema(self._skill.output_schema)
        self._system_prompt, self._compact_prompt = split_prompts(self._skill.system_prompt)
        self._date_template = date_context_template(self._skill.system_prompt)
        self._repair_with_tools = True
        self._max_tool_result_chars: int | None = None
        self._history: list[dict[str, Any]] = []
        self._on_event: EventFn | None = None

    def configure_lean(
        self,
        *,
        reasoning_effort: str,
        max_tool_rounds: int,
        max_tokens: int,
        max_tool_result_chars: int,
    ) -> None:
        """Cheaper settings for the public chat (tier 4): compact prompt, fewer calls.

        * the short prompt between the live-compact markers of SKILL.md (if present);
        * ``reasoning_effort`` (``low`` or ``medium``) and a lower ``max_tokens``;
        * at most ``max_tool_rounds`` tool rounds;
        * the repair turn (still only when the gate blocked a sentence) asks for the corrected
          JSON directly, without another tool round;
        * each tool result sent back to the model is cut to ``max_tool_result_chars``.

        Temperature stays 0. The gate is unchanged.
        """
        if reasoning_effort not in REASONING_EFFORTS:
            raise ValueError(f"reasoning_effort must be one of {REASONING_EFFORTS}")
        if self._compact_prompt:
            self._system_prompt = self._compact_prompt
        self._reasoning_effort = reasoning_effort
        self._max_tool_rounds = max(1, max_tool_rounds)
        self._max_tokens = max_tokens
        self._repair_with_tools = False
        self._max_tool_result_chars = max_tool_result_chars

    @property
    def system_prompt(self) -> str:
        """The system prompt sent with every call."""
        return self._system_prompt

    def date_context(self) -> str:
        """Today's date (UTC) and the stored data window, from the Skill's template.

        Recomputed for every question, so "this week" or "last week of August" is read against
        the stored data and today's date, never the model's own guess of the year (on the live
        site the model once queried 2025 dates for 2026 data and answered "0 reports").
        Empty when the Skill has no date-context block.
        """
        if not self._date_template:
            return ""
        return render_date_context(
            self._date_template,
            self._ctx.store,
            today=self._ctx.today or utc_today(),
            sweep_window=self._ctx.sweep_window,
        )

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
            kwargs["tools"] = [
                t
                for t in TOOL_SCHEMAS
                if self._allowed_tools is None or t["function"]["name"] in self._allowed_tools
            ]
            kwargs["tool_choice"] = "auto"  # the only value Meta's API accepts
        elif self._structured:
            kwargs["response_format"] = self._response_format
        return self._client.chat.completions.create(**kwargs)

    def _final_answer(self, messages: list[dict[str, Any]], result: CopilotResult) -> str:
        """Final-answer call: no tools, schema-constrained when structured output is on."""
        resp = self._create(messages, tools=False)
        self._count(resp, result)
        if getattr(resp.choices[0], "finish_reason", None) == "length":
            result.length_stops += 1  # hit max_tokens: the JSON is cut off
        return str(resp.choices[0].message.content or "")

    def _emit(self, kind: str, **data: Any) -> None:
        if self._on_event is not None:
            self._on_event(kind, data)

    def ask(self, question: str, on_event: EventFn | None = None) -> CopilotResult:
        """Answer one question (multi-turn: earlier Q/A pairs are kept as context).

        Args:
            question: The analyst's question.
            on_event: Optional progress callback, called as the work happens (model
                calls, each tool call, each gate pass, the repair turn), so a UI can
                stream progress. Only gate-verified sentences are ever in the result.
        """
        self._on_event = on_event
        try:
            return self._ask(question)
        finally:
            self._on_event = None

    def _ask(self, question: str) -> CopilotResult:
        dates = self.date_context()
        system = f"{self._system_prompt}\n\n{dates}" if dates else self._system_prompt
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": system},
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
        report = verify_answer(sentences, self._ctx.store) if ok else _unparsed(content)
        result.first_pass_report = report
        self._emit("gate", stage="first pass", passed=report.passed, blocked=report.blocked)

        repairs = 0
        while report.blocked and repairs < self._max_repairs:
            repairs += 1
            self._emit("repair", blocked=report.blocked)
            messages.append({"role": "user", "content": _repair_message(report)})
            if self._repair_with_tools:
                content = self._run_until_answer(messages, result)
            else:
                content = self._final_answer(messages, result)
            repaired, ok = self._parse_or_retry(content, messages, result)
            if not ok:
                break
            report = verify_answer(repaired, self._ctx.store)
            self._emit("gate", stage="after repair", passed=report.passed, blocked=report.blocked)
            result.repaired = True
            result.parse_failed = False

        result.report = report
        result.answer = report.render()
        result.capa_ids = list(self._ctx.created_capas[capa_start:])
        self._history += [
            {"role": "user", "content": question},
            {"role": "assistant", "content": result.answer},
        ]
        self._history = self._history[-8:]
        self._audit(result)
        self._emit("done", passed=report.passed, blocked=report.blocked)
        return result

    def _run_until_answer(self, messages: list[dict[str, Any]], result: CopilotResult) -> str:
        for n in range(self._max_tool_rounds):
            self._emit("model", round=n + 1)
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
                self._emit("tool", name=tc.function.name, arguments=tc.function.arguments)
                if self._allowed_tools is not None and tc.function.name not in self._allowed_tools:
                    out = {"error": f"tool {tc.function.name} is not available in this run"}
                else:
                    out = call_tool(self._ctx, tc.function.name, tc.function.arguments)
                payload = json.dumps(out, default=str)
                cap = self._max_tool_result_chars
                sent = payload
                if cap is not None and len(payload) > cap:
                    sent = payload[:cap] + f" ... [cut: {len(payload) - cap} more characters]"
                try:
                    args = json.loads(tc.function.arguments or "{}")
                except ValueError:
                    args = {"_raw": tc.function.arguments}
                result.tool_calls.append(ToolCallTrace(tc.function.name, args, payload[:300]))
                messages.append({"role": "tool", "tool_call_id": tc.id, "content": sent})
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
