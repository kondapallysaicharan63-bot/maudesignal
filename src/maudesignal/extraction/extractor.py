"""Extractor — runs a LoadedSkill against a MAUDE record via any LLM provider.

Provider-agnostic: works with Groq, Anthropic, or OpenAI depending on
``config.llm_provider``. The provider is chosen once at Extractor
construction; all calls use that backend.

Responsibilities:
  1. Format the Skill's few-shot examples + real input as messages.
  2. Call the provider's ``complete()``.
  3. Extract JSON from the response.
  4. Validate JSON against the Skill's output schema (FR-10).
  5. Write audit-log row for the call (FR-12).
  6. Enforce the cost ceiling from config.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from typing import Any

import jsonschema

from maudesignal.common.exceptions import (
    BudgetExceededError,
    LLMOutputError,
)
from maudesignal.common.logging import get_logger, truncate_for_log
from maudesignal.config import Config
from maudesignal.extraction.llm_providers import (
    LLMMessage,
    LLMProvider,
    get_provider,
)
from maudesignal.extraction.skill_loader import LoadedSkill
from maudesignal.storage.database import Database

logger = get_logger(__name__)


@dataclass(frozen=True)
class ExtractionResult:
    """What the Extractor returns to callers."""

    output: dict[str, Any]
    model_used: str
    provider_used: str
    input_tokens: int
    output_tokens: int
    cost_estimate_usd: float
    extraction_id: str


class Extractor:
    """Invokes a Skill against a single MAUDE record via an LLM provider.

    This class is intentionally small and single-purpose. It does NOT:
      - Orchestrate ingestion (that's ingestion/)
      - Persist extractions (caller does that via Database)
      - Chain Skills together (the pipeline layer will, later)
    """

    def __init__(
        self,
        config: Config,
        db: Database,
        provider: LLMProvider | None = None,
    ) -> None:
        """Create an Extractor.

        Args:
            config: Loaded configuration (for cost ceiling and provider selection).
            db: Database for writing the audit log.
            provider: Optional pre-built provider. If None, one is built
                from ``config`` via ``get_provider()``.
        """
        self._config = config
        self._db = db
        self._provider = provider or get_provider(config)

    @property
    def provider(self) -> LLMProvider:
        """Return the active LLM provider (for introspection)."""
        return self._provider

    def run(
        self,
        skill: LoadedSkill,
        input_record: dict[str, Any],
    ) -> ExtractionResult:
        """Run the given Skill on the input record and return validated output.

        Args:
            skill: A loaded Skill (from SkillLoader.load()).
            input_record: Data matching the Skill's expected input shape.

        Returns:
            An ExtractionResult containing validated JSON output and metadata.

        Raises:
            BudgetExceededError: If cumulative LLM spend has exceeded
                ``config.cost_ceiling_usd``.
            LLMOutputError: If the response cannot be parsed or fails
                schema validation.
        """
        # Budget guardrail (Doc 6 R-12 mitigation)
        current_spend = self._db.total_llm_cost_usd()
        if current_spend >= self._config.cost_ceiling_usd:
            raise BudgetExceededError(
                f"Cumulative LLM spend ${current_spend:.2f} has reached ceiling "
                f"${self._config.cost_ceiling_usd:.2f}. Aborting further LLM calls."
            )

        messages = self._build_messages(skill, input_record)

        logger.info(
            "extraction_request_start",
            skill=skill.name,
            skill_version=skill.version,
            provider=self._provider.provider_name,
            model=self._provider.model,
            input_preview=truncate_for_log(json.dumps(input_record), 200),
        )

        response = self._provider.complete(
            system_prompt=skill.system_prompt,
            messages=messages,
            max_tokens=2048,
            temperature=0.0,
        )

        parsed = _extract_json_object(response.text)

        try:
            jsonschema.validate(instance=parsed, schema=skill.output_schema)
        except jsonschema.ValidationError as exc:
            logger.error(
                "extraction_schema_violation",
                skill=skill.name,
                provider=response.provider,
                error=str(exc.message),
                output_preview=truncate_for_log(response.text, 500),
            )
            raise LLMOutputError(
                f"Skill {skill.name} v{skill.version} output failed schema "
                f"validation via {response.provider}: {exc.message}"
            ) from exc

        cost = self._provider.estimate_cost_usd(response.input_tokens, response.output_tokens)

        call_id = str(uuid.uuid4())
        self._db.insert_audit_log(
            call_id=call_id,
            skill_name=skill.name,
            skill_version=skill.version,
            model=f"{response.provider}/{response.model}",
            input_hash=_hash_json(input_record),
            output_hash=_hash_json(parsed),
            input_tokens=response.input_tokens,
            output_tokens=response.output_tokens,
            cost_estimate_usd=cost,
        )

        logger.info(
            "extraction_request_complete",
            skill=skill.name,
            skill_version=skill.version,
            provider=response.provider,
            model=response.model,
            input_tokens=response.input_tokens,
            output_tokens=response.output_tokens,
            cost_usd=round(cost, 6),
            call_id=call_id,
        )

        return ExtractionResult(
            output=parsed,
            model_used=response.model,
            provider_used=response.provider,
            input_tokens=response.input_tokens,
            output_tokens=response.output_tokens,
            cost_estimate_usd=cost,
            extraction_id=call_id,
        )

    def _build_messages(
        self,
        skill: LoadedSkill,
        input_record: dict[str, Any],
    ) -> list[LLMMessage]:
        """Build the user-message list with up to 3 few-shot examples."""
        messages: list[LLMMessage] = []

        for example in skill.good_examples[:3]:
            example_input = example.get("input")
            example_output = example.get("expected_output")
            if not example_input or not example_output:
                continue
            messages.append(LLMMessage(role="user", content=_format_example_input(example_input)))
            messages.append(
                LLMMessage(
                    role="assistant",
                    content=json.dumps(example_output, indent=2),
                )
            )

        messages.append(LLMMessage(role="user", content=_format_example_input(input_record)))
        return messages


def _format_example_input(input_record: dict[str, Any]) -> str:
    """Format an input with a clear header and JSON pretty-print."""
    return (
        "Extract structured fields from the following MAUDE record. "
        "Respond with a single JSON object matching the output schema "
        "defined in your instructions.\n\n"
        f"INPUT:\n{json.dumps(input_record, indent=2)}"
    )


def _extract_json_object(raw: str) -> dict[str, Any]:
    """Pull the first {...} JSON object out of an LLM response string.

    LLMs sometimes wrap JSON in markdown code fences or add prose before/after.
    This helper extracts the first balanced {...} block it sees.
    """
    text = raw.replace("```json", "```").strip()
    if text.startswith("```"):
        text = text.strip("`").strip()

    start = text.find("{")
    if start < 0:
        raise LLMOutputError(f"No JSON object found in LLM output. Raw: {text[:500]!r}")
    depth = 0
    end = -1
    for i in range(start, len(text)):
        ch = text[i]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                end = i + 1
                break
    if end < 0:
        raise LLMOutputError("Unbalanced braces in LLM output.")

    candidate = text[start:end]
    try:
        parsed: dict[str, Any] = json.loads(candidate)
    except json.JSONDecodeError as exc:
        raise LLMOutputError(f"LLM output is not valid JSON: {exc}") from exc
    return parsed


def _hash_json(obj: dict[str, Any]) -> str:
    """Deterministic SHA-256 hash of a JSON-serializable object."""
    canonical = json.dumps(obj, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
