"""Read a 510(k) summary's page images with Muse Spark (``skills/fda-document-reader``).

HACKATHON-BUILT — Meta Global AI Developer Hackathon (Oct 26 – Nov 4, 2026).

One read = one Chat Completions call with every page as an inline image and a
strict JSON schema. The accuracy check (``verify.py``) needs two INDEPENDENT
reads, so :func:`read_twice` sends the pages once in source order at a higher
resolution and once in reverse order at a lower resolution. Each image is
labelled with its source page in a one-line data header, so page numbers stay
comparable across reads.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from maudesignal.extraction.skill_loader import LoadedSkill
from maudesignal.vision.fda_pdf import PageImage
from maudesignal.vision.images import encode, fit, open_image
from maudesignal.vision.spark import (
    DEFAULT_VISION_MODEL,
    call_spark_json,
    image_part,
    load_skill,
    text_part,
)

SKILL_NAME = "fda-document-reader"
READ_FIELDS: tuple[str, ...] = (
    "k_number",
    "applicant",
    "device_name",
    "product_code",
    "regulation_number",
    "decision_date",
    "predicate_devices",
    "indications_for_use",
    "intended_use",
    "technology_summary",
)
LIST_FIELDS = frozenset({"predicate_devices"})
VERBATIM_FIELDS = frozenset({"indications_for_use", "intended_use"})
LEGIBILITY = ("clear", "partly_legible", "illegible", "not_present")


@dataclass(frozen=True)
class ReadPass:
    """How one independent read is made."""

    label: str
    reverse: bool
    max_side: int


# Two independent passes: different resolution AND page order.
PASS_A = ReadPass("A", reverse=False, max_side=1600)
PASS_B = ReadPass("B", reverse=True, max_side=1100)


@dataclass(frozen=True)
class FieldReading:
    """One field as read from the page images."""

    value: str | list[str]
    page: int
    legibility: str

    @property
    def present(self) -> bool:
        """The read found something for this field."""
        if self.legibility == "not_present":
            return False
        return bool(self.value)

    def to_dict(self) -> dict[str, Any]:
        """JSON form."""
        return {"value": self.value, "page": self.page, "legibility": self.legibility}

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> FieldReading:
        """Inverse of :meth:`to_dict` (tolerant of missing keys)."""
        raw = d.get("value", "")
        value: str | list[str] = [str(v) for v in raw] if isinstance(raw, list) else str(raw or "")
        leg = str(d.get("legibility") or "not_present")
        return cls(value=value, page=int(d.get("page") or 0), legibility=leg)


@dataclass
class Reading:
    """One full read of a document."""

    label: str
    fields: dict[str, FieldReading]
    page_order: list[int]
    max_side: int
    model: str = ""
    skill_version: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """JSON form."""
        return {
            "label": self.label,
            "fields": {k: v.to_dict() for k, v in self.fields.items()},
            "page_order": self.page_order,
            "max_side": self.max_side,
            "model": self.model,
            "skill_version": self.skill_version,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cost_usd": self.cost_usd,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Reading:
        """Inverse of :meth:`to_dict`."""
        fields_raw = d.get("fields") or {}
        return cls(
            label=str(d.get("label") or ""),
            fields={
                name: FieldReading.from_dict(fields_raw.get(name) or {}) for name in READ_FIELDS
            },
            page_order=[int(p) for p in d.get("page_order") or []],
            max_side=int(d.get("max_side") or 0),
            model=str(d.get("model") or ""),
            skill_version=str(d.get("skill_version") or ""),
            input_tokens=int(d.get("input_tokens") or 0),
            output_tokens=int(d.get("output_tokens") or 0),
            cost_usd=float(d.get("cost_usd") or 0.0),
        )


def page_header(order: Sequence[int]) -> str:
    """Data line mapping image positions to source pages (``image 1 = page 3; ...``)."""
    return "; ".join(f"image {i} = page {p}" for i, p in enumerate(order, start=1))


def read_510k_summary(
    client: Any,
    pages: Sequence[PageImage],
    *,
    model: str = DEFAULT_VISION_MODEL,
    skill: LoadedSkill | None = None,
    label: str = "A",
    reverse: bool = False,
    max_side: int = 1600,
    max_tokens: int = 16000,
) -> Reading:
    """Read the summary fields from page images in one Muse Spark call.

    Args:
        client: OpenAI-compatible client.
        pages: Rasterized pages (source order).
        model: Muse Spark model id.
        skill: ``fda-document-reader`` (loaded from ``skills/`` if omitted).
        label: Pass label stored with the reading.
        reverse: Send the pages last-to-first.
        max_side: Longest image side sent, in pixels.
        max_tokens: Output token cap (reasoning counts toward it; 4096 cut off 3 of 5
            summaries on 2026-10-28).

    Returns:
        The reading (every field present; pages are source page numbers).

    Raises:
        ValueError: No pages.
        VisionModelError: The call failed or the output did not match the schema.
    """
    if not pages:
        raise ValueError("no pages to read")
    skill = skill or load_skill(SKILL_NAME)
    ordered = list(reversed(pages)) if reverse else list(pages)
    order = [p.page for p in ordered]
    parts: list[dict[str, Any]] = [text_part(page_header(order))]
    for p in ordered:
        parts.append(image_part(encode(fit(open_image(p.png), max_side), fmt="PNG")))
    out = call_spark_json(client, skill=skill, parts=parts, model=model, max_tokens=max_tokens)
    fields_raw = out.data.get("fields") or {}
    valid_pages = set(order)
    fields: dict[str, FieldReading] = {}
    for name in READ_FIELDS:
        fr = FieldReading.from_dict(fields_raw.get(name) or {})
        if fr.page and fr.page not in valid_pages:
            fr = FieldReading(fr.value, 0, fr.legibility)  # a page we never sent
        fields[name] = fr
    return Reading(
        label=label,
        fields=fields,
        page_order=order,
        max_side=max_side,
        model=out.model,
        skill_version=skill.version,
        input_tokens=out.input_tokens,
        output_tokens=out.output_tokens,
        cost_usd=out.cost_usd,
    )


def read_twice(
    client: Any,
    pages: Sequence[PageImage],
    *,
    model: str = DEFAULT_VISION_MODEL,
    skill: LoadedSkill | None = None,
) -> tuple[Reading, Reading]:
    """Two independent reads: (A) source order at 1600 px, (B) reverse order at 1100 px."""
    skill = skill or load_skill(SKILL_NAME)
    a, b = (
        read_510k_summary(
            client,
            pages,
            model=model,
            skill=skill,
            label=p.label,
            reverse=p.reverse,
            max_side=p.max_side,
        )
        for p in (PASS_A, PASS_B)
    )
    return a, b
