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

import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from maudesignal.copilot.agent import default_skills_root, parse_answer
from maudesignal.copilot.meta_provider import SPARK_USD_PER_M_INPUT, SPARK_USD_PER_M_OUTPUT
from maudesignal.dossier.model import DossierData, NarrativeSection, NarrativeSentence
from maudesignal.extraction.skill_loader import LoadedSkill, SkillLoader
from maudesignal.gate import EvidenceStore, verify_answer

SKILL_NAME = "dossier-narrative"
DEFAULT_MODEL = "muse-spark-1.3"
RECORDING_SCHEMA = "dossier-narrative/1"
NO_NARRATIVE_NOTE = (
    "Narrative summary omitted: no META_MODEL_API_KEY was available and no recorded Muse Spark "
    "narrative exists for this document. All other sections are deterministic."
)


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

    @property
    def cost_usd(self) -> float:
        """Estimated Muse Spark cost of the call."""
        return round(
            self.input_tokens * SPARK_USD_PER_M_INPUT / 1e6
            + self.output_tokens * SPARK_USD_PER_M_OUTPUT / 1e6,
            6,
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
        "classification": s.classification,
        "triggers": list(s.triggers),
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
            {"capa_id": data.capa.capa_id, "title": data.capa.title, "status": data.capa.status}
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
    max_tokens: int = 4000,
) -> NarrativeRecording:
    """Ask Muse Spark for the narrative (one call, temperature 0).

    Args:
        client: OpenAI-compatible client (``MetaProvider.client``) or a test fake.
        data: The deterministic dossier.
        excerpts: report_id -> narrative excerpt.
        model: Standard-tier model id; Contributor models are refused.
        skill: Pre-loaded skill (loaded from ``skills/`` if omitted).
        max_tokens: Output cap (reasoning counts toward it; the 2026-10-28 recording used
            all 1200 and returned no text).

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
    )


def gate_narrative(
    rec: NarrativeRecording, store: EvidenceStore, *, source: str
) -> NarrativeSection:
    """Run the claim-level gate over a narrative recording.

    Args:
        rec: Live or recorded model output.
        store: Evidence store of stored records.
        source: ``"live"`` or ``"recorded"`` (printed in the dossier).

    Returns:
        The narrative section: passed sentences verbatim, withheld ones with reasons.
    """
    try:
        pairs = parse_answer(rec.raw_output)
    except (ValueError, json.JSONDecodeError):
        # Unparseable prose is gated as one claim-less sentence; anything checkable in it
        # is then blocked as ungrounded.
        pairs = [(rec.raw_output.strip(), [])]
    report = verify_answer(pairs, store)
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


def omitted_section(note: str = NO_NARRATIVE_NOTE) -> NarrativeSection:
    """Section used when no narrative is available."""
    return NarrativeSection(available=False, note=note)
