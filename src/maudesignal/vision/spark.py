"""One structured-output Muse Spark call with images (Chat Completions).

HACKATHON-BUILT — Meta Global AI Developer Hackathon (Oct 26 – Nov 4, 2026).

Wire format, as documented (read 2026-10-27):

* images go in a USER message as ``{"type": "image_url", "image_url": {"url":
  "data:image/png;base64,..."}}`` parts, at most 50 per request
  (https://dev.meta.ai/docs/image-understanding);
* structured output is ``response_format={"type": "json_schema", "json_schema":
  {"name", "schema", "strict": true}}``; with ``strict`` the schema must set
  ``additionalProperties: false`` on every object, list every key in ``required``,
  and avoid ``oneOf`` / ``allOf`` (https://dev.meta.ai/docs/structured-output).

The behaviour contract (system prompt + schema) comes from a Skill folder, never
from Python strings. The client is any OpenAI-compatible object, injected, so
tests use a scripted fake and spend no credits. The output is still validated
locally against the Skill schema: constrained decoding is the API's promise,
the local check is ours.
"""

from __future__ import annotations

import copy
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import jsonschema

from maudesignal.common.exceptions import MaudeSignalError
from maudesignal.copilot.meta_provider import SPARK_USD_PER_M_INPUT, SPARK_USD_PER_M_OUTPUT
from maudesignal.extraction.skill_loader import LoadedSkill, SkillLoader
from maudesignal.vision.images import MAX_IMAGES_PER_REQUEST, EncodedImage

DEFAULT_VISION_MODEL = "muse-spark-1.3"
_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)
_SCHEMA_META_KEYS = ("$schema", "$id")


class VisionModelError(MaudeSignalError):
    """The model call failed or returned output that does not match the Skill schema."""


def default_skills_root() -> Path:
    """Repo-level ``skills/`` directory."""
    return Path(__file__).resolve().parents[3] / "skills"


def load_skill(name: str, skills_root: Path | None = None) -> LoadedSkill:
    """Load a vision Skill (``fda-document-reader`` / ``device-label-reader``)."""
    return SkillLoader(skills_root or default_skills_root()).load(name)


def strict_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """The Skill schema as sent to the API (meta keys removed; already strict-subset)."""
    out = copy.deepcopy(schema)
    for k in _SCHEMA_META_KEYS:
        out.pop(k, None)
    return out


def check_strict_subset(schema: dict[str, Any], path: str = "$") -> list[str]:
    """List violations of the documented strict-mode subset (empty list = OK).

    Rules checked: every object sets ``additionalProperties: false`` and lists all
    of its properties in ``required``; no ``oneOf`` / ``allOf`` anywhere; no
    ``anyOf`` at the root.
    """
    problems: list[str] = []
    if path == "$" and "anyOf" in schema:
        problems.append("$: anyOf at the root")
    for bad in ("oneOf", "allOf"):
        if bad in schema:
            problems.append(f"{path}: {bad} is not allowed")
    if schema.get("type") == "object":
        if schema.get("additionalProperties") is not False:
            problems.append(f"{path}: additionalProperties must be false")
        props = schema.get("properties", {})
        if set(schema.get("required", [])) != set(props):
            problems.append(f"{path}: required must list every property")
        for key, sub in props.items():
            if isinstance(sub, dict):
                problems.extend(check_strict_subset(sub, f"{path}.{key}"))
    items = schema.get("items")
    if isinstance(items, dict):
        problems.extend(check_strict_subset(items, f"{path}[]"))
    return problems


def image_part(img: EncodedImage) -> dict[str, Any]:
    """Chat Completions image content part (data URL inline)."""
    return {"type": "image_url", "image_url": {"url": img.data_url}}


def text_part(text: str) -> dict[str, Any]:
    """Chat Completions text content part."""
    return {"type": "text", "text": text}


@dataclass(frozen=True)
class SparkJson:
    """A validated structured answer plus its usage."""

    data: dict[str, Any]
    model: str
    input_tokens: int
    output_tokens: int

    @property
    def cost_usd(self) -> float:
        """Estimated Muse Spark cost (Standard tier list prices)."""
        return round(
            self.input_tokens * SPARK_USD_PER_M_INPUT / 1e6
            + self.output_tokens * SPARK_USD_PER_M_OUTPUT / 1e6,
            6,
        )


def call_spark_json(
    client: Any,
    *,
    skill: LoadedSkill,
    parts: list[dict[str, Any]],
    model: str = DEFAULT_VISION_MODEL,
    max_tokens: int = 4096,
) -> SparkJson:
    """Send one user message (text + images) and return schema-valid JSON.

    Args:
        client: OpenAI-compatible client (``client.chat.completions.create``).
        skill: The Skill supplying the system prompt and output schema.
        parts: User content parts (``text_part`` / ``image_part``).
        model: Muse Spark model id (Standard tier only).
        max_tokens: Output token cap.

    Raises:
        ValueError: Contributor-tier model or too many images.
        VisionModelError: API failure, non-JSON output, or schema mismatch.
    """
    if model.endswith("-contributor"):
        raise ValueError("Contributor-tier models train on your data; use Standard tier.")
    n_images = sum(1 for p in parts if p.get("type") == "image_url")
    if n_images > MAX_IMAGES_PER_REQUEST:
        raise ValueError(f"{n_images} images; the documented maximum is 50 per request")
    schema = strict_schema(skill.output_schema)
    try:
        resp = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": skill.system_prompt},
                {"role": "user", "content": parts},
            ],
            response_format={
                "type": "json_schema",
                "json_schema": {
                    "name": skill.name.replace("-", "_"),
                    "schema": schema,
                    "strict": True,
                },
            },
            max_tokens=max_tokens,
            temperature=0.0,
        )
    except Exception as exc:  # SDK raises many types; never include request data
        raise VisionModelError(f"Muse Spark call failed ({type(exc).__name__}): {exc}") from exc
    usage = getattr(resp, "usage", None)
    in_tok = int(getattr(usage, "prompt_tokens", 0) or 0) if usage is not None else 0
    out_tok = int(getattr(usage, "completion_tokens", 0) or 0) if usage is not None else 0
    content = str(resp.choices[0].message.content or "")
    data = parse_json_object(content)
    try:
        jsonschema.validate(instance=data, schema=schema)
    except jsonschema.ValidationError as exc:
        raise VisionModelError(f"output does not match {skill.name} schema: {exc.message}") from exc
    return SparkJson(
        data=data,
        model=str(getattr(resp, "model", "") or model),
        input_tokens=in_tok,
        output_tokens=out_tok,
    )


def parse_json_object(content: str) -> dict[str, Any]:
    """Parse a JSON object from model output (tolerates a code fence).

    Raises:
        VisionModelError: No JSON object.
    """
    text = _FENCE.sub("", content.strip())
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end < start:
        raise VisionModelError("model output has no JSON object")
    try:
        data = json.loads(text[start : end + 1])
    except json.JSONDecodeError as exc:
        raise VisionModelError(f"model output is not valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise VisionModelError("model output is not a JSON object")
    return data
