"""One call that builds, optionally narrates, and renders a dossier.

HACKATHON-BUILT — Meta Global AI Developer Hackathon (Oct 26 – Nov 4, 2026).

Shared by the dashboard page and ``scripts/build_demo_dossier.py`` so both
produce byte-for-byte the same document for the same inputs.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

from maudesignal.dossier.builder import DossierBuild, build_dossier
from maudesignal.dossier.model import Illustration
from maudesignal.dossier.narrative import (
    DEFAULT_MODEL,
    NarrativeRecording,
    draft_narrative,
    gate_narrative,
    save_recording,
)
from maudesignal.dossier.render import render_html, render_pdf
from maudesignal.gate import EvidenceRecord
from maudesignal.storage.database import Database

PROJECT_ROOT = Path(__file__).resolve().parents[3]


def recorded_dir() -> Path:
    """Folder of recorded narratives / reviews / demo PDFs (``demo/dossier``)."""
    return Path(os.environ.get("MAUDESIGNAL_DOSSIER_DIR", str(PROJECT_ROOT / "demo" / "dossier")))


@dataclass
class DossierOutput:
    """A rendered dossier."""

    build: DossierBuild
    html: str
    pdf: bytes
    narrative_recording: NarrativeRecording | None = None

    @property
    def doc_id(self) -> str:
        """Document id."""
        return self.build.data.doc_id

    def cited_records(self) -> list[EvidenceRecord]:
        """Stored records of every report the dossier cites."""
        out: list[EvidenceRecord] = []
        for e in self.build.data.evidence:
            rec = self.build.store.record(e.report_id)
            if rec is not None:
                out.append(rec)
        return out


def produce(
    db: Database,
    *,
    capa_id: str | None = None,
    product_code: str | None = None,
    awareness_date: date | None = None,
    awareness_basis: str = "entered by the reviewer",
    narrative_dir: Path | None = None,
    live_client: Any | None = None,
    spark_model: str = DEFAULT_MODEL,
    save_live_narrative: bool = False,
    illustration: Illustration | None = None,
    generated_at: datetime | None = None,
    pdf: bool = True,
) -> DossierOutput:
    """Build → (optional live Muse Spark narrative) → HTML → PDF.

    Args:
        db: Open database.
        capa_id: CAPA draft to document (None → signal-only dossier).
        product_code: Signal to document when no CAPA is given.
        awareness_date: Human-entered awareness date for the MDR clock.
        awareness_basis: How that date was obtained.
        narrative_dir: Folder with recorded narratives (default ``demo/dossier``).
        live_client: OpenAI-compatible client; when given, a live narrative is drafted.
        spark_model: Narrative model (Standard tier).
        save_live_narrative: Save the live narrative recording to ``narrative_dir``.
        illustration: Optional cover illustration.
        generated_at: Timestamp to print.
        pdf: Render the PDF too (False → HTML only, for fast previews/tests).
    """
    ndir = narrative_dir or recorded_dir()
    build = build_dossier(
        db,
        capa_id=capa_id,
        product_code=product_code,
        awareness_date=awareness_date,
        awareness_basis=awareness_basis,
        recorded_dir=ndir,
        illustration=illustration,
        generated_at=generated_at,
    )
    recording = None
    if live_client is not None:
        recording = draft_narrative(live_client, build.data, build.excerpts, model=spark_model)
        build.data.narrative = gate_narrative(recording, build.store, source="live")
        if save_live_narrative:
            save_recording(recording, ndir / f"{build.data.doc_id}-narrative.json")
    html = render_html(build.data)
    return DossierOutput(
        build=build,
        html=html,
        pdf=render_pdf(html) if pdf else b"",
        narrative_recording=recording,
    )
