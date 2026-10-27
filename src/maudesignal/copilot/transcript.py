"""Record copilot runs so the public demo can replay them with no API key.

HACKATHON-BUILT — Meta Global AI Developer Hackathon (Oct 26 – Nov 4, 2026).

A transcript is the full, honest record of one real Muse Spark run: the
question, every tool call, the first-pass gate verdicts, whether a repair turn
ran, the final per-sentence verdicts with reasons, tokens and cost. The
deployed demo shows these ("stored-first"); it never fakes a live call.
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from maudesignal.copilot.agent import CopilotResult
from maudesignal.gate import GateReport

TRANSCRIPT_SCHEMA_VERSION = "1.0"


def _report_to_dict(report: GateReport) -> dict[str, Any]:
    return {
        "passed": report.passed,
        "blocked": report.blocked,
        "claims": report.claim_counts,
        "sentences": [
            {
                "text": s.text,
                "status": s.status,
                "reasons": s.reasons,
                "claims": [
                    {
                        "kind": cv.claim.kind,
                        "status": cv.status,
                        "reason": cv.reason,
                        "evidence_ids": list(cv.evidence_ids),
                    }
                    for cv in s.claim_verdicts
                ],
            }
            for s in report.sentences
        ],
    }


def result_to_dict(
    result: CopilotResult, *, label: str = "", voice: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Serialize a copilot result.

    Args:
        result: The copilot result.
        label: Demo story label (sort key).
        voice: Optional ``Transcript.to_voice_block()`` when the question was spoken
            (``transcript_text``, ``language``, ``audio_seconds``). Omitted when None, so
            text-only transcripts are unchanged.
    """
    out: dict[str, Any] = {
        "schema_version": TRANSCRIPT_SCHEMA_VERSION,
        "label": label,
        "recorded_at_utc": datetime.now(UTC).isoformat(timespec="seconds"),
        "model": result.model,
        "question": result.question,
        "answer": result.answer,
        "tool_calls": [
            {"name": t.name, "arguments": t.arguments, "result_preview": t.result_preview}
            for t in result.tool_calls
        ],
        "first_pass": _report_to_dict(result.first_pass_report),
        "final": _report_to_dict(result.report),
        "repaired": result.repaired,
        "sentences_repaired": result.sentences_repaired,
        "capa_ids": result.capa_ids,
        "parse_failed": result.parse_failed,
        "usage": {
            "input_tokens": result.input_tokens,
            "output_tokens": result.output_tokens,
            "cost_usd": result.cost_usd,
        },
    }
    if voice is not None:
        out["voice"] = dict(voice)
    return out


def save_transcript(
    result: CopilotResult,
    out_dir: Path,
    *,
    label: str = "",
    voice: dict[str, Any] | None = None,
) -> Path:
    """Write one transcript as JSON; returns the path (``voice`` as in ``result_to_dict``)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    slug = re.sub(r"[^a-z0-9]+", "-", (label or result.question).lower()).strip("-")[:48]
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    path = out_dir / f"{stamp}-{slug}.json"
    path.write_text(
        json.dumps(result_to_dict(result, label=label, voice=voice), indent=2), encoding="utf-8"
    )
    return path


def load_transcripts(directory: Path) -> list[dict[str, Any]]:
    """Load every transcript in a directory, ordered by label (the demo story order)."""
    if not directory.is_dir():
        return []
    out: list[dict[str, Any]] = []
    for p in sorted(directory.glob("*.json")):
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except ValueError:
            continue
        if isinstance(data, dict) and data.get("schema_version") == TRANSCRIPT_SCHEMA_VERSION:
            data["_file"] = p.name
            out.append(data)
    return sorted(out, key=lambda d: (str(d.get("label") or ""), str(d.get("_file"))))
