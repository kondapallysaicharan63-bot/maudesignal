"""The one answer shape every connector tool returns.

HACKATHON-BUILT — Meta Global AI Developer Hackathon (Oct 26 – Nov 4, 2026).
"""

from __future__ import annotations

from typing import Any, Literal

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
    "canned_reply",
]
#: Which chat tier answered: fixed reply, direct lookup, earlier answer reused, or Muse Spark.
AnswerTier = Literal["canned", "direct", "cache", "live"]


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
        description=(
            "stored_demo_snapshot, live_openfda, recorded_answer, live_model or canned_reply."
        )
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
    claim_kinds: list[str] = Field(
        default_factory=list, description="Kinds of claim the sentence made (e.g. count, quote)."
    )
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


class AskAnswer(ToolAnswer):
    """What ``ask`` returns: the common answer plus which chat tier answered and its cost."""

    tier: AnswerTier = Field(
        description=(
            "canned (fixed reply, no FDA facts, no model), direct (deterministic lookup through "
            "the claim gate, no model), cache (the same question's live answer from the last "
            "six hours) or live (Muse Spark, or a labelled recorded run when no live call can "
            "be made)."
        )
    )
    cost_usd: float | None = Field(
        default=None,
        description="Model cost of this answer in USD: 0 for canned, direct and cache; the "
        "estimated Muse Spark cost for a live answer; null for a recorded run.",
    )
    badge: str | None = Field(
        default=None, description="Short label to show with the answer (tiers 1 to 3)."
    )
    suggestions: list[str] = Field(
        default_factory=list, description="Follow-up questions to offer (never sent by itself)."
    )
    did_you_mean: list[str] = Field(
        default_factory=list,
        description="Known product codes one letter away from an unknown one; never applied.",
    )


LookupStatus = Literal["needs_person_to_confirm", "no_match_found", "search_failed"]


class LookupLink(BaseModel):
    """A public openFDA link behind a lookup result."""

    model_config = ConfigDict(extra="forbid")

    label: str
    url: str

    @field_validator("url")
    @classmethod
    def _https(cls, value: str) -> str:
        if not value.startswith("https://"):
            raise ValueError("every link is https")
        return value


class LookupMatch(BaseModel):
    """One possible FDA record for the device that was described. Never chosen for the person."""

    model_config = ConfigDict(extra="forbid")

    rank: int = Field(description="1 is the best-scoring possible match; it is not a decision.")
    source: str = Field(description="510k, udi or registrationlisting.")
    record_id: str = Field(description="K-number, UDI record key or registration number.")
    k_number: str | None = Field(description="510(k) number when the record is a 510(k).")
    device_name: str | None
    applicant: str | None = Field(description="Applicant, owner or maker named on the record.")
    product_code: str | None
    decision_date: str | None = Field(description="510(k) decision date as openFDA gives it.")
    exact_id: str | None = Field(
        description="k_number or gtin when an id you gave equals the record, else null."
    )
    score: int
    why_matched: list[str]
    why_not_matched: list[str]
    links: list[LookupLink]


class LookupDeviceType(BaseModel):
    """What openFDA shows for a product code of the top possible matches."""

    model_config = ConfigDict(extra="forbid")

    product_code: str
    device_type_name: str | None
    this_week_change: str | None = Field(
        description="Same deterministic check as check_device_type, in plain words."
    )
    this_week_reports: int | None
    recent_recalls_count: int | None = Field(
        description="Recall records started in the window below (null if openFDA failed)."
    )
    recent_recalls_window: str
    recent_recalls_link: str | None
    report_count: int | None = Field(description="All adverse-event reports for the code.")
    report_count_link: str | None
    check_link: str | None = Field(description="openFDA link for this week's report count.")
    note: str | None = None


class LookupAnswer(ToolAnswer):
    """``lookup_device``: possible FDA records for a described device. A person confirms."""

    status: LookupStatus
    confirmed: None = Field(
        default=None,
        description="Always null. This tool never picks a record; a person confirms one or none.",
    )
    note: str | None = None
    searched_with: list[str] = Field(
        default_factory=list, description="Which of your inputs were used for the search."
    )
    matches: list[LookupMatch] = Field(default_factory=list, description="At most 3.")
    device_types: list[LookupDeviceType] = Field(default_factory=list)


class ErrorBody(BaseModel):
    """Error detail (never contains a key)."""

    code: str
    message: str
    suggestions: list[str] | None = None


class ErrorResponse(BaseModel):
    """Error envelope for 4xx and 5xx responses."""

    error: ErrorBody


class CheckWindow(BaseModel):
    """The two windows of a check (dates as YYYYMMDD)."""

    model_config = ConfigDict(extra="forbid")

    as_of: str
    current_start: str
    current_end: str
    baseline_start: str
    baseline_end: str


class LiveCheckData(BaseModel):
    """``LiveCheck.to_dict()`` of ``monitor/live_check.py``, field for field.

    Shares are fractions from 0 to 1; ``severe_share_delta_pp`` is in percentage points;
    ``queries`` is a list of ``[label, openFDA url]`` pairs, one per figure.
    """

    model_config = ConfigDict(extra="forbid")

    product_code: str
    as_of: str | None
    window: CheckWindow | None
    classification: Literal["new_signal", "severity_escalation", "spike", "stable"]
    triggers: list[str]
    current_count: int
    current_severe_count: int
    current_severe_share: float | None
    baseline_count: int
    baseline_weekly_mean: float
    baseline_severe_count: int
    baseline_severe_share: float | None
    severe_share_delta_pp: float | None
    spike_ratio: float | None
    prior_report_count: int
    new_event_types: list[str]
    current_event_type_counts: list[list[Any]]
    queries: list[list[str]]
    change: str


class RecallsAnswer(ToolAnswer):
    """``recalls``: the normal answer plus the close known codes, when the code is unknown."""

    suggestions: list[str] = Field(
        default_factory=list,
        description=(
            'Close known product codes ("did you mean"), shown to the person and never '
            "applied; empty when there are none. Same values as the suggestions in an error."
        ),
    )


class PublicCheckAnswer(ToolAnswer):
    """The keyless web answer: the normal answer plus the full figures behind it."""

    check: LiveCheckData | None = Field(
        default=None,
        description=(
            "The live check behind the answer (null when openFDA could not be reached and "
            "the stored snapshot answered instead)."
        ),
    )


class AuditEntry(BaseModel):
    """One entry of the hash-chained audit log (the ``audit_export`` shape)."""

    model_config = ConfigDict(extra="forbid")

    seq: int
    ts: str = Field(description="UTC time, ISO 8601, no zone suffix.")
    actor: str = Field(
        description="connector:key:[<label>:]<server-side keyed hash of the key> or public."
    )
    action: str
    entity_id: str
    payload_json: str = Field(
        description="Tool, inputs, answer SHA-256, gate counts and provenance as JSON text."
    )
    prev_hash: str
    entry_hash: str


class ChainStatus(BaseModel):
    """Result of re-computing the hashes of the entries returned."""

    verified: bool
    first_bad_seq: int | None = None
    entries_checked: int


class AuditRecent(BaseModel):
    """``GET /v1/audit/recent`` body."""

    store: str = Field(description="upstash_redis or in_memory_per_instance.")
    chain: ChainStatus
    entries: list[AuditEntry]
