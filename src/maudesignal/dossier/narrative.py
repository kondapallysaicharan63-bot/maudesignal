"""Narrative summary: drafted by Muse Spark, shown only after the claim-level gate.

HACKATHON-BUILT — Meta Global AI Developer Hackathon (Oct 26 – Nov 4, 2026).

* :func:`draft_narrative` calls Muse Spark once with the ``dossier-narrative``
  skill and the dossier's deterministic facts, and returns a
  :class:`NarrativeRecording` (raw model output + usage), which can be saved.
* :func:`gate_narrative` re-runs the deterministic gate over a recording —
  live or recorded — so a recorded narrative is re-verified on every render
  and a sentence that no longer matches the stored records is withheld.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from maudesignal.copilot.agent import default_skills_root, parse_answer
from maudesignal.copilot.meta_provider import SPARK_USD_PER_M_INPUT, SPARK_USD_PER_M_OUTPUT
from maudesignal.dossier.model import DossierData, NarrativeSection, NarrativeSentence
from maudesignal.extraction.skill_loader import LoadedSkill, SkillLoader
from maudesignal.gate import EvidenceStore, GateReport, QuoteClaim, SentenceVerdict, verify_answer
from maudesignal.monitor.digest import CHANGE_LABELS

SKILL_NAME = "dossier-narrative"
DEFAULT_MODEL = "muse-spark-1.3"
RECORDING_SCHEMA = "dossier-narrative/1"
NO_NARRATIVE_NOTE = (
    "Narrative summary omitted: no META_MODEL_API_KEY was available and no recorded Muse Spark "
    "narrative exists for this document. All other sections are deterministic."
)
STALE_NARRATIVE_NOTE = (
    "Narrative summary omitted: the recorded Muse Spark narrative was drafted for a different "
    "evidence pack (different id, cited reports or problem statement), so it is not shown. "
    "All other sections are deterministic."
)
UNBOUND_RECORDING_NOTE = "recorded before pack binding; a re-record is pending"


@dataclass
class NarrativeRecording:
    """Honest record of one Muse Spark narrative call."""

    doc_id: str
    model: str
    skill_version: str
    created_at: str
    raw_output: str
    input_tokens: int = 0
    output_tokens: int = 0
    schema: str = RECORDING_SCHEMA
    #: Binds the narrative to the pack it was drafted for (see ``pack_hash``). Empty on
    #: recordings made before the binding existed; those are never reused.
    pack_hash: str = ""

    @property
    def cost_usd(self) -> float:
        """Estimated Muse Spark cost of the call."""
        return round(
            self.input_tokens * SPARK_USD_PER_M_INPUT / 1e6
            + self.output_tokens * SPARK_USD_PER_M_OUTPUT / 1e6,
            6,
        )


def pack_hash(capa_id: str | None, report_ids: Iterable[str], problem_statement: str | None) -> str:
    """Fingerprint of the evidence pack a narrative is about.

    Hash of the pack id, its cited report ids (order-independent) and its problem statement.
    A recorded narrative is reused only when this matches the pack being rendered.
    """
    payload = json.dumps(
        [capa_id or "", sorted(set(report_ids)), (problem_statement or "").strip()],
        ensure_ascii=False,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def data_pack_hash(data: DossierData) -> str:
    """``pack_hash`` of the pack a built dossier documents."""
    capa = data.capa
    return pack_hash(
        capa.capa_id if capa else None,
        [r.report_id for r in data.evidence],
        capa.problem_statement if capa else None,
    )


def save_recording(rec: NarrativeRecording, path: Path) -> None:
    """Write a recording as JSON."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(rec), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def load_recording(path: Path) -> NarrativeRecording | None:
    """Read a recording, or None when absent / not a narrative recording."""
    if not path.is_file():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or data.get("schema") != RECORDING_SCHEMA:
        return None
    return NarrativeRecording(
        doc_id=str(data["doc_id"]),
        model=str(data["model"]),
        skill_version=str(data["skill_version"]),
        created_at=str(data["created_at"]),
        raw_output=str(data["raw_output"]),
        input_tokens=int(data.get("input_tokens", 0)),
        output_tokens=int(data.get("output_tokens", 0)),
        pack_hash=str(data.get("pack_hash", "")),
    )


def load_skill(skill: LoadedSkill | None = None) -> LoadedSkill:
    """Load the ``dossier-narrative`` skill."""
    return skill or SkillLoader(default_skills_root()).load(SKILL_NAME)


def narrative_input(data: DossierData, excerpts: dict[str, str]) -> dict[str, Any]:
    """Deterministic facts handed to the model (the only things it may state).

    Args:
        data: The dossier being summarized (narrative section not needed).
        excerpts: report_id -> narrative excerpt (≤ 600 chars) for cited reports.
    """
    s = data.signal
    figures: dict[str, Any] = {
        "current_count": s.current_count,
        "baseline_count": s.baseline_count,
        "current_severe_count": s.current_severe,
        "baseline_severe_count": s.baseline_severe,
        "baseline_weekly_mean": s.baseline_weekly_mean,
    }
    if s.spike_ratio is not None:
        figures["spike_ratio"] = s.spike_ratio
    for et, fig in s.event_type_counts:
        figures[f"current_{et}_count"] = fig
    return {
        "doc_id": data.doc_id,
        "product_code": s.product_code,
        "device": {
            "classification_name": data.device.classification_name,
            "brand_names": list(data.device.brand_names),
            "k_numbers_from_reports": list(data.device.k_numbers),
        },
        "window": {
            "current": [f"{s.current_start:%Y%m%d}", f"{s.current_end:%Y%m%d}"],
            "baseline": [f"{s.baseline_start:%Y%m%d}", f"{s.baseline_end:%Y%m%d}"],
        },
        # Plain words only ("reports suddenly increased"), never the internal labels.
        "change": CHANGE_LABELS[s.classification],
        "rules_fired": [CHANGE_LABELS[t] for t in s.triggers],
        "figures": {k: {"display": f.display, "claim": f.claim} for k, f in figures.items()},
        "evidence": [
            {
                "report_id": e.report_id,
                "date_received": e.date_received,
                "event_type": e.event_type,
                "brand_name": e.brand_name,
                "narrative_excerpt": excerpts.get(e.report_id, e.excerpt),
            }
            for e in data.evidence[:40]
        ],
        "capa": (
            {
                "capa_id": data.capa.capa_id,
                "title": data.capa.display_title or data.capa.title,
                "status": data.capa.status,
            }
            if data.capa
            else None
        ),
    }


def draft_narrative(
    client: Any,
    data: DossierData,
    excerpts: dict[str, str],
    *,
    model: str = DEFAULT_MODEL,
    skill: LoadedSkill | None = None,
    max_tokens: int = 16000,
) -> NarrativeRecording:
    """Ask Muse Spark for the narrative (one call, temperature 0).

    Args:
        client: OpenAI-compatible client (``MetaProvider.client``) or a test fake.
        data: The deterministic dossier.
        excerpts: report_id -> narrative excerpt.
        model: Standard-tier model id; Contributor models are refused.
        skill: Pre-loaded skill (loaded from ``skills/`` if omitted).
        max_tokens: Output cap (reasoning counts toward it; on 2026-10-28 the narrative
            used all 1200, then all 4000, and returned no text both times).

    Raises:
        ValueError: a Contributor-tier model was requested.
    """
    if "contributor" in model.lower():
        raise ValueError("Contributor-tier models train on your data; use Standard tier.")
    sk = load_skill(skill)
    resp = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": sk.system_prompt},
            {"role": "user", "content": json.dumps(narrative_input(data, excerpts), default=str)},
        ],
        max_tokens=max_tokens,
        temperature=0.0,
    )
    usage = getattr(resp, "usage", None)
    return NarrativeRecording(
        doc_id=data.doc_id,
        model=model,
        skill_version=sk.version,
        created_at=datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        raw_output=str(resp.choices[0].message.content or ""),
        input_tokens=int(getattr(usage, "prompt_tokens", 0) or 0) if usage else 0,
        output_tokens=int(getattr(usage, "completion_tokens", 0) or 0) if usage else 0,
        pack_hash=data_pack_hash(data),
    )


def gate_narrative(
    rec: NarrativeRecording,
    store: EvidenceStore,
    *,
    source: str,
    cited_report_ids: Iterable[str] | None = None,
) -> NarrativeSection:
    """Run the claim-level gate over a narrative recording.

    Args:
        rec: Live or recorded model output.
        store: Evidence store of stored records.
        source: ``"live"`` or ``"recorded"`` (printed in the dossier).
        cited_report_ids: Dossier mode: the pack's cited reports. A quote claim must cite one
            of them; a quote from any other stored report is withheld (the store alone would
            accept it, but the dossier would then say "cited reports" about a report it
            does not cite).

    Returns:
        The narrative section: passed sentences verbatim, withheld ones with reasons.
    """
    try:
        pairs = parse_answer(rec.raw_output)
        report = verify_answer(pairs, store)
        if cited_report_ids is not None:
            report = _restrict_quotes(report, frozenset(cited_report_ids))
    except (ValueError, json.JSONDecodeError):
        # A reply that never parsed (empty, cut off by max_tokens, prose) is withheld,
        # never shown as one claim-less "verified" sentence. The 2026-10-28 dossier
        # printed "Shown: 1" over a blank body this way, and Muse Wonder flagged it.
        report = GateReport(
            [
                SentenceVerdict(
                    rec.raw_output.strip()[:300] or "(empty model reply)",
                    "block",
                    (),
                    ("the model did not return a structured narrative, so nothing is shown",),
                )
            ]
        )
    sentences = tuple(
        NarrativeSentence(
            text=sv.text,
            status=sv.status,
            reasons=tuple(sv.reasons),
            claims_json=json.dumps(
                [{**asdict(cv.claim)} for cv in sv.claim_verdicts], sort_keys=True
            ),
        )
        for sv in report.sentences
    )
    return NarrativeSection(
        available=True,
        note=(
            f"Drafted by {rec.model} (skill {SKILL_NAME} v{rec.skill_version}); every sentence was "
            "re-checked by the deterministic claim-level gate against stored openFDA records. "
            "Withheld sentences are shown struck through with the gate's reason."
        ),
        sentences=sentences,
        model=rec.model,
        skill_version=rec.skill_version,
        source=source,
        recorded_at=rec.created_at,
        cost_usd=rec.cost_usd,
    )


def _restrict_quotes(report: GateReport, cited: frozenset[str]) -> GateReport:
    """Block sentences whose quote claims cite a report outside the pack."""
    out: list[SentenceVerdict] = []
    for sv in report.sentences:
        outside = sorted(
            {
                rid
                for cv in sv.claim_verdicts
                if isinstance(cv.claim, QuoteClaim)
                and (rid := cv.claim.report_id)
                and rid not in cited
            }
        )
        if sv.status == "pass" and outside:
            reason = (
                f"quote: report {', '.join(str(i) for i in outside)} is not one of the "
                "reports this evidence pack cites"
            )
            out.append(SentenceVerdict(sv.text, "block", sv.claim_verdicts, (reason,)))
        else:
            out.append(sv)
    return GateReport(out)


def omitted_section(note: str = NO_NARRATIVE_NOTE) -> NarrativeSection:
    """Section used when no narrative is available."""
    return NarrativeSection(available=False, note=note)
