"""One registry of the five connector tools, shared by REST, MCP and the manifest.

HACKATHON-BUILT — Meta Global AI Developer Hackathon (Oct 26 – Nov 4, 2026).

Names, descriptions, input rules and tool annotations are defined once here. The REST routes
reuse the descriptions, ``/mcp`` builds ``tools/list`` from :func:`mcp_tools`, and
``api/mcp-manifest.json`` is generated from the same list (a test fails if it drifts).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from maudesignal.connector.ask import MAX_QUESTION_CHARS, MIN_QUESTION_CHARS
from maudesignal.connector.errors import InvalidInputError

PRODUCT_CODE_PATTERN = r"^[A-Za-z]{3}$"
REPORT_ID_PATTERN = r"^[A-Za-z0-9-]{1,24}$"

WHAT_CHANGED_DESCRIPTION = (
    "Read-only. Latest stored week from the demo snapshot (labelled with its dates). "
    "A product code outside the stored set is checked live on openFDA."
)
CHECK_DESCRIPTION = (
    "Read-only. Live openFDA report counts for any product code, using the same four "
    "rules, windows and thresholds as the weekly detector."
)
ASK_DESCRIPTION = (
    "Read-only (POST only because the question is in the body). Muse Spark answers "
    "through deterministic tools over stored records; every sentence passes the claim "
    "gate. Withheld sentences are listed in `withheld` and are never in `speakable`. "
    "With no model key, or after the key's daily cost cap, the closest recorded answer "
    "is returned and labelled recorded."
)
REPORT_DESCRIPTION = "Read-only. Key fields and the start of the narrative of one stored report."
RECALLS_DESCRIPTION = "Read-only. Stored openFDA recalls for a product code, newest first."


@dataclass(frozen=True)
class Param:
    """One input of a tool (a string)."""

    name: str
    description: str
    required: bool = True
    pattern: str | None = None
    min_length: int | None = None
    max_length: int | None = None
    example: str | None = None

    def schema(self) -> dict[str, Any]:
        """JSON Schema of this input."""
        out: dict[str, Any] = {"type": "string", "description": self.description}
        if self.pattern:
            out["pattern"] = self.pattern
        if self.min_length is not None:
            out["minLength"] = self.min_length
        if self.max_length is not None:
            out["maxLength"] = self.max_length
        if self.example:
            out["examples"] = [self.example]
        return out


@dataclass(frozen=True)
class ToolSpec:
    """One tool: name, text, inputs and annotations (all tools are read-only)."""

    name: str
    title: str
    description: str
    params: tuple[Param, ...]
    open_world: bool  # True when the tool can reach live openFDA or the live model

    def input_schema(self) -> dict[str, Any]:
        """JSON Schema of the arguments."""
        return {
            "type": "object",
            "properties": {p.name: p.schema() for p in self.params},
            "required": [p.name for p in self.params if p.required],
            "additionalProperties": False,
        }

    def annotations(self) -> dict[str, bool]:
        """MCP tool annotations: never writes, never destroys."""
        return {
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": self.open_world,
        }

    def validate(self, arguments: Any) -> dict[str, str]:
        """Check ``arguments`` against the input rules.

        Raises:
            InvalidInputError: Not an object, an unknown or missing input, or a value that
                breaks a rule. The message names the input, never its value.
        """
        if arguments is None:
            arguments = {}
        if not isinstance(arguments, dict):
            raise InvalidInputError("Invalid input: arguments must be an object.")
        known = {p.name: p for p in self.params}
        for name in arguments:
            if name not in known:
                raise InvalidInputError("Invalid input: unknown argument.")
        clean: dict[str, str] = {}
        for p in self.params:
            value = arguments.get(p.name)
            if value is None:
                if p.required:
                    raise InvalidInputError(f"Invalid input: {p.name} is required.")
                continue
            if not isinstance(value, str):
                raise InvalidInputError(f"Invalid input: {p.name} must be a string.")
            too_short = p.min_length is not None and len(value) < p.min_length
            too_long = p.max_length is not None and len(value) > p.max_length
            bad_form = p.pattern is not None and re.fullmatch(p.pattern, value) is None
            if too_short or too_long or bad_form:
                raise InvalidInputError(f"Invalid input: {p.name}.")
            clean[p.name] = value
        return clean


_CODE = "Three-letter FDA product code, e.g. LLZ."

TOOL_SPECS: tuple[ToolSpec, ...] = (
    ToolSpec(
        "what_changed_this_week",
        "What changed this week",
        WHAT_CHANGED_DESCRIPTION,
        (
            Param(
                "product_code",
                "Optional three-letter product code.",
                required=False,
                pattern=PRODUCT_CODE_PATTERN,
            ),
        ),
        open_world=True,
    ),
    ToolSpec(
        "check_device_type",
        "Check any device type live on openFDA",
        CHECK_DESCRIPTION,
        (Param("product_code", _CODE, pattern=PRODUCT_CODE_PATTERN),),
        open_world=True,
    ),
    ToolSpec(
        "ask",
        "Ask the Muse Spark copilot",
        ASK_DESCRIPTION,
        (
            Param(
                "question",
                "A question about stored MAUDE reports, recalls, 510(k)s or the MDR clock.",
                min_length=MIN_QUESTION_CHARS,
                max_length=MAX_QUESTION_CHARS,
                example="What changed this week for LLZ?",
            ),
        ),
        open_world=True,
    ),
    ToolSpec(
        "get_report",
        "One stored MAUDE report",
        REPORT_DESCRIPTION,
        (
            Param(
                "report_id",
                "MAUDE report id (mdr_report_key).",
                pattern=REPORT_ID_PATTERN,
            ),
        ),
        open_world=False,
    ),
    ToolSpec(
        "recalls",
        "FDA recalls for a product code",
        RECALLS_DESCRIPTION,
        (Param("product_code", _CODE, pattern=PRODUCT_CODE_PATTERN),),
        open_world=False,
    ),
)

SPECS_BY_NAME: dict[str, ToolSpec] = {s.name: s for s in TOOL_SPECS}


def mcp_tools(output_schema: dict[str, Any]) -> list[dict[str, Any]]:
    """The ``tools/list`` entries (also the manifest's ``tools``)."""
    return [
        {
            "name": s.name,
            "title": s.title,
            "description": s.description,
            "inputSchema": s.input_schema(),
            "outputSchema": output_schema,
            "annotations": {"title": s.title, **s.annotations()},
        }
        for s in TOOL_SPECS
    ]
