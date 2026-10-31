"""MCP prompts: three ready-made starting messages for a person using the connector.

HACKATHON-BUILT — Meta Global AI Developer Hackathon (Oct 26 – Nov 4, 2026).

``prompts/list`` and ``prompts/get`` (MCP 2025-06-18). A prompt only returns a user message that
asks the model to call the connector's own read-only tools; it reads no data and calls nothing
itself. Each message says to cite the FDA links, that this is not medical advice, and to say
"recorded" for recorded answers.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from maudesignal.connector.errors import InvalidInputError
from maudesignal.connector.guidance import CODE_HINT

MAX_CODES = 10
MAX_TEXT_CHARS = 500

_RULES = (
    "Cite the FDA links given in each answer. This is not medical advice and nothing is "
    "filed with FDA. If an answer is labelled recorded, say 'recorded' and give its date."
)


@dataclass(frozen=True)
class PromptArg:
    """One argument of a prompt."""

    name: str
    description: str
    required: bool = True


@dataclass(frozen=True)
class PromptSpec:
    """One prompt: name, text for the person, and its arguments."""

    name: str
    title: str
    description: str
    arguments: tuple[PromptArg, ...]

    def listing(self) -> dict[str, Any]:
        """The ``prompts/list`` entry."""
        return {
            "name": self.name,
            "title": self.title,
            "description": self.description,
            "arguments": [
                {"name": a.name, "description": a.description, "required": a.required}
                for a in self.arguments
            ],
        }


PROMPT_SPECS: tuple[PromptSpec, ...] = (
    PromptSpec(
        "morning_brief",
        "Morning brief for my device types",
        "What changed this week for each product code you watch, with links.",
        (PromptArg("product_codes", "Comma-separated three-letter product codes, e.g. LLZ,QIH."),),
    ),
    PromptSpec(
        "check_this_device",
        "Check this device",
        "Find the possible FDA records for a device read from a photo or typed in.",
        (
            PromptArg(
                "text",
                "Name, model, manufacturer, K-number or UDI, as read from the photo or typed.",
            ),
        ),
    ),
    PromptSpec(
        "does_this_apply_to_us",
        "Does this apply to us?",
        "Problem patterns for a product code, as questions to check against your own records.",
        (
            PromptArg("product_code", "Three-letter product code, e.g. LLZ."),
            PromptArg(
                "our_device_description",
                "Optional: a line about your own device.",
                required=False,
            ),
        ),
    ),
)
PROMPTS_BY_NAME: dict[str, PromptSpec] = {p.name: p for p in PROMPT_SPECS}


def prompt_list() -> list[dict[str, Any]]:
    """The ``prompts/list`` entries."""
    return [p.listing() for p in PROMPT_SPECS]


def _one_line(value: str) -> str:
    return " ".join(value.split())


def _text_arg(args: dict[str, Any], name: str, *, required: bool) -> str:
    value = args.get(name)
    if value is None or (isinstance(value, str) and not value.strip()):
        if required:
            raise InvalidInputError(f"{name} is required for this prompt.")
        return ""
    if not isinstance(value, str):
        raise InvalidInputError(f"{name} must be text.")
    clean = _one_line(value)
    if len(clean) > MAX_TEXT_CHARS:
        raise InvalidInputError(f"{name} is too long: the limit is {MAX_TEXT_CHARS} characters.")
    return clean


def _code_arg(value: str, name: str) -> str:
    code = value.strip().upper()
    if not re.fullmatch(r"[A-Z]{3}", code):
        raise InvalidInputError(f"{name}: {CODE_HINT}")
    return code


def get_prompt(name: str, arguments: Any) -> dict[str, Any]:
    """The ``prompts/get`` result.

    Raises:
        InvalidInputError: Unknown prompt, a missing or unusable argument. The message names
            the argument and never repeats its value.
    """
    spec = PROMPTS_BY_NAME.get(name)
    if spec is None:
        raise InvalidInputError(
            "Unknown prompt. Available: " + ", ".join(p.name for p in PROMPT_SPECS) + "."
        )
    if arguments is None:
        arguments = {}
    if not isinstance(arguments, dict):
        raise InvalidInputError("Prompt arguments must be an object of text values.")
    allowed = {a.name for a in spec.arguments}
    if any(k not in allowed for k in arguments):
        raise InvalidInputError(
            f"{spec.name} does not take that argument. It takes: "
            + ", ".join(sorted(allowed))
            + "."
        )
    if spec.name == "morning_brief":
        raw = _text_arg(arguments, "product_codes", required=True)
        parts = [x for x in (c.strip() for c in raw.split(",")) if x]
        if not parts:
            raise InvalidInputError("product_codes is required for this prompt.")
        if len(parts) > MAX_CODES:
            raise InvalidInputError(f"product_codes: give at most {MAX_CODES} codes.")
        codes = list(dict.fromkeys(_code_arg(c, "product_codes") for c in parts))
        text = (
            f"Give me a morning brief for these product codes: {', '.join(codes)}. "
            "Call what_changed_this_week once for each code. Then summarise what changed for "
            "each code in one or two plain sentences and put the FDA link for each fact next "
            "to it. If a code shows no change, say so in one line. " + _RULES
        )
        about = "Morning brief for " + ", ".join(codes)
    elif spec.name == "check_this_device":
        given = _text_arg(arguments, "text", required=True)
        text = (
            "I have this device, read from a photo or typed by me (it may contain misread "
            f"characters): {given}\n"
            "Call lookup_device with what you can read from it (device_name, model, "
            "manufacturer, k_number, udi, gtin). List up to 3 possible matches, each with why "
            "it might match and why it might not. Then ask me to confirm one record, or none, "
            "before going further. Do not pick one for me. " + _RULES
        )
        about = "Check a device from a photo or typed text"
    else:
        code = _code_arg(_text_arg(arguments, "product_code", required=True), "product_code")
        ours = _text_arg(arguments, "our_device_description", required=False)
        text = (
            f"Does what is recorded for product code {code} apply to our device? "
            + (f"Our device: {ours}. " if ours else "")
            + "Call check_device_type, what_changed_this_week and recalls for this code. Then "
            "describe the problem patterns you find in the reports and recalls as questions I "
            "can check against our own records (for example: do we see the same kind of "
            "failure, in the same use?). Never state a verdict on whether it applies to us; "
            "that is for me and my quality team to decide. " + _RULES
        )
        about = f"Does the record for {code} apply to us?"
    return {
        "description": about,
        "messages": [{"role": "user", "content": {"type": "text", "text": text}}],
    }
