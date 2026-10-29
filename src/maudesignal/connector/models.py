"""The one answer shape every connector tool returns.

HACKATHON-BUILT — Meta Global AI Developer Hackathon (Oct 26 – Nov 4, 2026).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

#: Fixed line on every answer (word for word).
ADVISORY = (
    "Advisory triage aid for quality and regulatory review; not medical advice; "
    "nothing is filed with FDA."
)

ProvenanceKind = Literal[
    "stored_demo_snapshot",
    "live_openfda",
    "recorded_answer",
    "live_model",
]


class Fact(BaseModel):
    """One checkable statement with the link a reader can open to see it."""

    model_config = ConfigDict(extra="forbid")

    text: str = Field(description="One plain-language fact; every number comes from the source.")
    link: str = Field(description="https link to the openFDA query or record behind the fact.")
    link_label: str = Field(default="openFDA", description="What the link opens.")

    @field_validator("link")
    @classmethod
    def _https(cls, value: str) -> str:
        if not value.startswith("https://"):
            raise ValueError("every fact needs an https link")
        return value


class Provenance(BaseModel):
    """Where the data came from and how fresh it is."""

    model_config = ConfigDict(extra="forbid")

    kind: ProvenanceKind = Field(
        description="stored_demo_snapshot, live_openfda, recorded_answer or live_model."
    )
    source: str = Field(description="Plain description of the source.")
    data_dates: str | None = Field(
        default=None, description="Dates the data covers (a stored snapshot, or the live window)."
    )
    queried_at_utc: str | None = Field(
        default=None, description="UTC time of the live openFDA query or live model call."
    )
    note: str | None = Field(default=None, description="Why this source was used, if not obvious.")


class WithheldSentence(BaseModel):
    """A sentence the gate did not verify. It is never part of ``speakable``."""

    model_config = ConfigDict(extra="forbid")

    text: str = Field(description="NOT VERIFIED. Do not state or speak this as fact.")
    reason: str = Field(description="Why the gate withheld it.")
    status: Literal["withheld"] = "withheld"


class ToolAnswer(BaseModel):
    """What every tool returns."""

    model_config = ConfigDict(extra="forbid")

    tool: str
    speakable: str = Field(
        description="1 to 3 plain sentences, no markdown, written to be read aloud."
    )
    facts: list[Fact] = Field(default_factory=list)
    advisory: str = Field(default=ADVISORY)
    provenance: Provenance
    withheld: list[WithheldSentence] = Field(
        default_factory=list, description="Only ask() uses this; gate-withheld sentences."
    )


class ErrorBody(BaseModel):
    """Error detail (never contains a key)."""

    code: str
    message: str


class ErrorResponse(BaseModel):
    """Error envelope for 4xx and 5xx responses."""

    error: ErrorBody
