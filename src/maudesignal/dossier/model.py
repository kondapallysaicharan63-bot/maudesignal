"""Data model of one Signal Evaluation & CAPA dossier.

HACKATHON-BUILT — Meta Global AI Developer Hackathon (Oct 26 – Nov 4, 2026).

Plain dataclasses: the builder fills them from stored records, the template
renders them. Nothing here calls a model.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime

from maudesignal.copilot.protocol import ProtocolRow
from maudesignal.dossier.figures import Figure

CONFIDENTIALITY_LINE = (
    "Internal quality record — contains no PHI (openFDA MAUDE data is public and de-identified)"
)
DRAFT_STAMP = "DRAFT — REQUIRES HUMAN REVIEW"
MDR_STAMP = "DRAFT WORKSHEET — NOT FOR SUBMISSION"
TBC = "To be completed by CAPA owner"


@dataclass(frozen=True)
class DeviceInfo:
    """Device identification read from the openFDA reports behind the signal."""

    product_code: str
    classification_name: str | None
    regulation_number: str | None
    device_class: str | None
    catalog_label: str | None
    brand_names: tuple[str, ...]
    generic_names: tuple[str, ...]
    manufacturers: tuple[str, ...]
    model_numbers: tuple[str, ...]
    k_numbers: tuple[str, ...]


@dataclass(frozen=True)
class WeeklyBar:
    """One bar of the weekly-count chart."""

    label: str
    date_from: date
    date_to: date
    count: Figure
    is_current: bool


@dataclass(frozen=True)
class SignalSection:
    """Signal evaluation numbers, all from ``maudesignal.monitor``."""

    product_code: str
    classification: str
    triggers: tuple[str, ...]
    as_of: date
    current_start: date
    current_end: date
    baseline_start: date
    baseline_end: date
    current_count: Figure
    baseline_count: Figure
    baseline_weekly_mean: Figure
    spike_ratio: Figure | None
    spike_threshold: Figure
    current_severe: Figure
    baseline_severe: Figure
    current_severe_share: Figure | None
    baseline_severe_share: Figure | None
    event_type_counts: tuple[tuple[str, Figure], ...]
    weekly: tuple[WeeklyBar, ...]
    chart_svg: str = ""


@dataclass(frozen=True)
class EvidenceRow:
    """One supporting MAUDE report."""

    report_id: str
    url: str
    mfr_report_number: str | None
    date_received: str | None
    event_type: str | None
    brand_name: str | None
    excerpt: str


@dataclass(frozen=True)
class CapaInfo:
    """The CAPA-need evidence pack this dossier documents (None fields while undecided)."""

    capa_id: str
    title: str
    problem_statement: str
    problem_statement_flags: tuple[str, ...]
    status: str
    created_by: str
    created_at: datetime
    decided_by: str | None
    decided_at: datetime | None
    decision_note: str | None
    decision_audit_seq: int | None
    decision_audit_hash: str | None
    report_ids: tuple[str, ...]
    #: Transcript file the pack was replayed from (None for a pack made live).
    restored_from: str | None = None
    #: UTC time the transcript recorded the original drafting (``...Z``), when restored.
    recorded_at_utc: str | None = None


@dataclass(frozen=True)
class MdrRow:
    """One row of the 3500A-mapped worksheet."""

    section: str
    item: str
    field_name: str
    cfr_para: str
    prefill: str
    source: str


@dataclass(frozen=True)
class MdrWorksheet:
    """MDR assessment worksheet. Reportability is never decided here."""

    awareness_date: date | None
    awareness_basis: str
    due_30: dict[str, str] | None
    due_5: dict[str, str] | None
    rows: tuple[MdrRow, ...]


@dataclass(frozen=True)
class NarrativeSentence:
    """One gated narrative sentence."""

    text: str
    status: str  # "pass" | "block"
    reasons: tuple[str, ...]
    claims_json: str


@dataclass(frozen=True)
class NarrativeSection:
    """The AI-drafted narrative after the claim-level gate."""

    available: bool
    note: str
    sentences: tuple[NarrativeSentence, ...] = ()
    model: str = ""
    skill_version: str = ""
    source: str = ""  # "live" | "recorded"
    recorded_at: str = ""
    cost_usd: float = 0.0
    #: Visible note when the recording cannot be bound to this pack (made before binding).
    binding_note: str = ""

    @property
    def passed(self) -> int:
        """Sentences shown."""
        return sum(1 for s in self.sentences if s.status == "pass")

    @property
    def withheld(self) -> int:
        """Sentences withheld by the gate."""
        return sum(1 for s in self.sentences if s.status == "block")


@dataclass(frozen=True)
class AuditRow:
    """One audit-trail entry relevant to this dossier."""

    seq: int
    ts: datetime
    actor: str
    action: str
    entity_id: str
    hash_prefix: str


@dataclass(frozen=True)
class Illustration:
    """Optional AI-generated cover illustration (never evidence)."""

    png_b64: str
    model: str
    caption: str = "AI-generated illustration — not evidence"


@dataclass
class DossierData:
    """Everything the template renders."""

    doc_id: str
    revision: str
    status: str  # "draft" | "approved" | "rejected" | "no-capa"
    generated_at: datetime
    prepared_by: str
    prepared_at: datetime | None
    device: DeviceInfo
    signal: SignalSection
    evidence: tuple[EvidenceRow, ...]
    evidence_count: Figure
    capa: CapaInfo | None
    mdr: MdrWorksheet
    narrative: NarrativeSection
    audit: tuple[AuditRow, ...]
    audit_chain_ok: bool
    audit_chain_first_bad: int | None
    audit_chain_total: int
    db_label: str
    figures_checked: int = 0
    figures_failed: int = 0
    illustration: Illustration | None = None
    protocol: tuple[ProtocolRow, ...] = ()
    software: str = "MaudeSignal 0.1.0 (maudesignal.dossier)"
    extra_notes: list[str] = field(default_factory=list)

    @property
    def is_approved(self) -> bool:
        """True once a named human approved the CAPA-need evidence pack."""
        return self.status == "approved"

    @property
    def header_stamp(self) -> str:
        """Running-header status stamp."""
        if self.status == "approved":
            return "APPROVED — CAPA OPEN"
        if self.status == "rejected":
            return "REJECTED BY REVIEWER"
        return DRAFT_STAMP

    @property
    def watermark(self) -> str:
        """Diagonal watermark for normal pages ('' for none)."""
        if self.status == "approved":
            return ""
        if self.status == "rejected":
            return "REJECTED"
        return "DRAFT"
