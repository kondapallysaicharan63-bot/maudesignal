"""One registry of the six connector tools, shared by REST, MCP and the manifest.

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
from maudesignal.connector.guidance import CODE_HINT, K_HINT, REPORT_ID_HINT

PRODUCT_CODE_PATTERN = r"^[A-Za-z]{3}$"
REPORT_ID_PATTERN = r"^[A-Za-z0-9-]{1,24}$"

GUIDANCE = (
    "Read-only MaudeSignal tools over openFDA device data, for quality and regulatory review. "
    "Speak the text content; every fact in structuredContent has an openFDA or record link. "
    "Always cite the FDA links given in each answer. This is not medical advice, and nothing "
    "is filed with FDA. Confirm the product code with the person before guessing one: use "
    "lookup_device, or ask. When an answer is labelled recorded, say 'recorded' and give its "
    "date. Never present withheld sentences as fact; they were not verified. A person confirms "
    "every device match. Web results are not FDA records."
)

WHAT_CHANGED_DESCRIPTION = (
    "Use this to see which device types had a change in adverse-event reports in the latest "
    "stored week, or one product code if given. Read-only. Answers come from the stored demo "
    "snapshot, labelled with its dates; a product code outside the stored set is checked live "
    "on openFDA. Each fact has an openFDA link. Example questions: 'What changed for LLZ this "
    "week?'; 'Anything new in the stored week?'; 'Did MYN change?'."
)
CHECK_DESCRIPTION = (
    "Use this to check any device type on openFDA right now, by three-letter product code. "
    "Read-only. Gives live report counts for the latest week against the four weeks before, "
    "using the same four rules, windows and thresholds as the weekly detector. Each fact has "
    "an openFDA link. Example questions: 'Is anything unusual with QIH right now?'; 'Check "
    "product code LLZ on openFDA.'; 'How many reports did POK get this week?'."
)
ASK_DESCRIPTION = (
    "Use this for a free-text question about stored MAUDE reports, recalls, 510(k)s or the "
    "MDR clock when no other tool fits. Read-only (POST only because the question is in the "
    "body). Muse Spark answers through deterministic tools over stored records; every sentence "
    "passes the claim gate. Withheld sentences are listed in `withheld` and are never in "
    "`speakable`. With no model key, or after the key's daily cost cap, the closest recorded "
    "answer is returned and labelled recorded. Example questions: 'What changed this week for "
    "LLZ?'; 'Which recalls are on file for QIH?'; 'When is a malfunction report due to FDA?'."
)
REPORT_DESCRIPTION = (
    "Use this to read one stored MAUDE report when you have its report id. Read-only. Gives "
    "key fields and the start of the narrative, word for word, with the openFDA record link. "
    "Only reports in the stored demo snapshot are found; a missing report may still be on "
    "openFDA. Example questions: 'Show me report 50426770.'; 'What does MAUDE report "
    "50426770 say?'."
)
RECALLS_DESCRIPTION = (
    "Use this to list FDA recalls on file for a product code, newest first. Read-only. Reads "
    "the stored openFDA recall snapshot (top five as facts, each with its openFDA link); "
    "no recalls on file does not mean none exist. For a code with no stored recalls that is "
    "not otherwise known, it may check openFDA to confirm the code exists. "
    "Example questions: 'Show recalls for LLZ.'; "
    "'Has QIH had a recall?'; 'Who recalled POK devices?'."
)
LOOKUP_DESCRIPTION = (
    "Use this when a person has a device in hand (a photographed label, a model name, a "
    "K-number or UDI) and needs the matching FDA records. Read-only; no model call. Give what "
    "was read from the photo or label (device_name, model, manufacturer, k_number, udi or "
    "gtin, product_code; at least one) and get up to 3 possible FDA records from openFDA "
    "(510(k), registration & listing, UDI), each with why_matched and why_not_matched, plus "
    "this week's change, recent recalls and the report count for the top product code, each "
    "with its openFDA link. status is needs_person_to_confirm, no_match_found or "
    "search_failed. `confirmed` is always null: a person confirms one record, or none. "
    "Example questions: 'I photographed a label: Welch Allyn 802 LTR - which FDA records "
    "match?'; 'Which device is K123456?'; 'Find the FDA record for UDI "
    "(01)00380740000004(17)261231.'."
)
LOOKUP_PATTERN_K = r"^\s*[Kk][\s-]?[0-9]{6}\s*$"
OUTSIDE_DESCRIPTION = (
    "Use this to find public web pages (news, FDA web pages, manufacturer notices, journals) "
    "about a device type, by three-letter product code and an optional short topic. Web "
    "results are not FDA records and are not verified by the claim gate: every answer carries "
    "the label 'Web research — not FDA records, not verified by the gate', and nothing from it "
    "is ever part of a gated answer, a MAUDE count or a signal. Read-only. Muse Spark searches "
    "the web (at most two searches); if that fails, news links from the GDELT news index may be "
    "shown instead (status news_only). Each item has a title, link, source and a date only "
    "when one was returned. Full keys only (not the public demo key), a small daily limit per "
    "key, and only when the operator has switched web research on. POST only because the "
    "topic is in the body. Example questions: 'Any news about LLZ software problems?'; "
    "'Outside mentions of QIH recalls'."
)
TOPIC_MAX_CHARS = 120


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
    hint: str | None = None  # what to fix when the value breaks a rule (fixed text)

    def problem(self, kind: str) -> str:
        """Short helpful message for a broken rule.

        Args:
            kind: ``missing``, ``too_short``, ``too_long`` or ``bad_form``.

        Returns:
            Fixed text that names the input and never repeats the caller's value.
        """
        if kind == "missing":
            return f"{self.name} is required. {self.hint or self.description}"
        if kind == "too_short" and self.min_length is not None:
            return f"{self.name} is too short: it needs at least {self.min_length} characters."
        if kind == "too_long" and self.max_length is not None:
            return f"{self.name} is too long: the limit is {self.max_length} characters."
        if self.hint:
            return self.hint
        return f"{self.name} is not in the form this tool expects. {self.description}"

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
    idempotent: bool = True  # False when the same call can give different results (web search)

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
            "idempotentHint": self.idempotent,
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
        names = ", ".join(p.name for p in self.params)
        if not isinstance(arguments, dict):
            raise InvalidInputError(
                f"The arguments of {self.name} must be an object with: {names}."
            )
        known = {p.name: p for p in self.params}
        for name in arguments:
            if name not in known:
                raise InvalidInputError(f"{self.name} does not take that input. It takes: {names}.")
        clean: dict[str, str] = {}
        for p in self.params:
            value = arguments.get(p.name)
            if value is None:
                if p.required:
                    raise InvalidInputError(p.problem("missing"))
                continue
            if not isinstance(value, str):
                raise InvalidInputError(f"{p.name} must be text.")
            if p.min_length is not None and len(value) < p.min_length:
                raise InvalidInputError(p.problem("too_short"))
            if p.max_length is not None and len(value) > p.max_length:
                raise InvalidInputError(p.problem("too_long"))
            if p.pattern is not None and re.fullmatch(p.pattern, value) is None:
                raise InvalidInputError(p.problem("bad_form"))
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
                hint=CODE_HINT,
            ),
        ),
        open_world=True,
    ),
    ToolSpec(
        "check_device_type",
        "Check any device type live on openFDA",
        CHECK_DESCRIPTION,
        (Param("product_code", _CODE, pattern=PRODUCT_CODE_PATTERN, hint=CODE_HINT),),
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
                hint=REPORT_ID_HINT,
            ),
        ),
        open_world=False,
    ),
    ToolSpec(
        "recalls",
        "FDA recalls for a product code",
        RECALLS_DESCRIPTION,
        (Param("product_code", _CODE, pattern=PRODUCT_CODE_PATTERN, hint=CODE_HINT),),
        open_world=True,
    ),
    ToolSpec(
        "lookup_device",
        "Look up possible FDA records for a device",
        LOOKUP_DESCRIPTION,
        (
            Param(
                "device_name",
                "Device name as read from the photo or label.",
                required=False,
                max_length=200,
                example="Welch Allyn 802 LTR",
            ),
            Param(
                "model",
                "Model, catalog or reference number.",
                required=False,
                max_length=100,
                example="802",
            ),
            Param(
                "manufacturer",
                "Maker named on the label.",
                required=False,
                max_length=200,
                example="Welch Allyn",
            ),
            Param(
                "k_number",
                "510(k) number printed on the label: K plus six digits.",
                required=False,
                pattern=LOOKUP_PATTERN_K,
                example="K123456",
                hint=K_HINT,
            ),
            Param(
                "udi",
                "Printed UDI, for example (01)00380740000004(17)261231.",
                required=False,
                max_length=200,
            ),
            Param(
                "gtin",
                "GTIN (8, 12, 13 or 14 digits), if printed without a full UDI.",
                required=False,
                max_length=20,
            ),
            Param(
                "product_code",
                "Three-letter FDA product code, if known.",
                required=False,
                pattern=PRODUCT_CODE_PATTERN,
                hint=CODE_HINT,
            ),
        ),
        open_world=True,
    ),
)

SPECS_BY_NAME: dict[str, ToolSpec] = {s.name: s for s in TOOL_SPECS}

#: Web research tool: listed and callable only when ``MAUDESIGNAL_RESEARCH`` is on.
OUTSIDE_SPEC = ToolSpec(
    "outside_mentions",
    "Outside mentions on the web (not FDA records)",
    OUTSIDE_DESCRIPTION,
    (
        Param("product_code", _CODE, pattern=PRODUCT_CODE_PATTERN, hint=CODE_HINT),
        Param(
            "topic",
            "Optional short topic, e.g. software update or battery recall (no patient details).",
            required=False,
            min_length=2,
            max_length=TOPIC_MAX_CHARS,
            example="software update",
        ),
    ),
    open_world=True,
    idempotent=False,
)


def active_specs(research_on: bool) -> tuple[ToolSpec, ...]:
    """The tools offered right now: the core six, plus ``outside_mentions`` when research is on."""
    return TOOL_SPECS + (OUTSIDE_SPEC,) if research_on else TOOL_SPECS


def spec_for(name: str, research_on: bool) -> ToolSpec | None:
    """The spec of an offered tool, or None (``outside_mentions`` is unknown while off)."""
    return {s.name: s for s in active_specs(research_on)}.get(name)


def mcp_tools(
    output_schema: dict[str, Any],
    overrides: dict[str, dict[str, Any]] | None = None,
    specs: tuple[ToolSpec, ...] = TOOL_SPECS,
) -> list[dict[str, Any]]:
    """The ``tools/list`` entries (also the manifest's ``tools``).

    ``overrides`` maps a tool name to its own output schema (``lookup_device`` returns more
    fields than the common answer).
    """
    overrides = overrides or {}
    return [
        {
            "name": s.name,
            "title": s.title,
            "description": s.description,
            "inputSchema": s.input_schema(),
            "outputSchema": overrides.get(s.name, output_schema),
            "annotations": {"title": s.title, **s.annotations()},
        }
        for s in specs
    ]


PARAMS_BY_NAME: dict[str, Param] = {}
for _spec in (*TOOL_SPECS, OUTSIDE_SPEC):
    for _p in _spec.params:
        PARAMS_BY_NAME.setdefault(_p.name, _p)


def explain_error(name: str, error_type: str) -> str | None:
    """Helpful message for a request-validation failure on input ``name``.

    Args:
        name: The input's name (query parameter or body field).
        error_type: The validation error type (``missing``, ``string_too_long`` ...).

    Returns:
        The message, or ``None`` when ``name`` is not a tool input.
    """
    param = PARAMS_BY_NAME.get(name)
    if param is None:
        return None
    if error_type == "missing":
        kind = "missing"
    elif error_type.endswith("too_short"):
        kind = "too_short"
    elif error_type.endswith("too_long"):
        kind = "too_long"
    else:
        kind = "bad_form"
    return param.problem(kind)
