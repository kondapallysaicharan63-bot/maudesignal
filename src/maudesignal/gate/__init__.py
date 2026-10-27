"""Claim-level citation gate (HACKATHON-BUILT, Oct 26 – Nov 4, 2026)."""

from maudesignal.gate.claims import (
    Claim,
    ClaimParseError,
    CountClaim,
    DeviceClaim,
    LiteratureClaim,
    QuoteClaim,
    RecallClaim,
    RecallCountClaim,
    RecordClaim,
    RegulationClaim,
    ShareClaim,
    claim_from_dict,
)
from maudesignal.gate.evidence import (
    DeviceRef,
    EvidenceRecord,
    EvidenceStore,
    LiteratureRef,
    RecallRef,
)
from maudesignal.gate.gate import (
    ClaimVerdict,
    GateReport,
    SentenceVerdict,
    verify,
    verify_answer,
    verify_claim,
    verify_sentence,
)

__all__ = [
    "Claim",
    "ClaimParseError",
    "ClaimVerdict",
    "CountClaim",
    "DeviceClaim",
    "DeviceRef",
    "EvidenceRecord",
    "EvidenceStore",
    "GateReport",
    "LiteratureClaim",
    "LiteratureRef",
    "QuoteClaim",
    "RecallClaim",
    "RecallCountClaim",
    "RecallRef",
    "RecordClaim",
    "RegulationClaim",
    "SentenceVerdict",
    "ShareClaim",
    "claim_from_dict",
    "verify",
    "verify_answer",
    "verify_claim",
    "verify_sentence",
]
