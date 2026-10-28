"""Independent AI reviewer of a rendered dossier (Muse Wonder 1.0).

HACKATHON-BUILT — Meta Global AI Developer Hackathon (Oct 26 – Nov 4, 2026).

Before a human approves a CAPA-need evidence pack, the rendered dossier is sent to
``muse-wonder-1.0`` together with the full stored narratives of every cited
report. Wonder returns a findings list (``skills/dossier-reviewer``). Findings
are shown next to the dossier and stored in the hash-chained audit trail; they
never edit the document.

How the PDF is passed: Meta's file-handling docs
(https://dev.meta.ai/docs/file-handling) document a Chat Completions ``file``
content part with ``file_data`` (base64 data URL, ≤ 50 MB inline). ``mode="pdf"``
sends the PDF that way plus the evidence as text; ``mode="text"`` sends the
dossier's extracted text instead (Wonder's 1M-token context makes this cheap
enough), and is used automatically if the PDF request is rejected.

Standard tier only: a ``-contributor`` model is refused (Contributor trains on
your data).
"""

from __future__ import annotations

import base64
import json
import re
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

from maudesignal.copilot.agent import default_skills_root
from maudesignal.extraction.skill_loader import LoadedSkill, SkillLoader
from maudesignal.gate import EvidenceRecord, EvidenceStore
from maudesignal.storage.database import Database

SKILL_NAME = "dossier-reviewer"
WONDER_MODEL = "muse-wonder-1.0"
WONDER_USD_PER_M_INPUT = 4.00
WONDER_USD_PER_M_OUTPUT = 20.00
RECORDING_SCHEMA = "dossier-review/1"
ISSUE_TYPES = frozenset({"unsupported", "contradicted", "missing_required_element", "unclear"})
SEVERITIES = ("high", "medium", "low")
_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)


class ReviewError(ValueError):
    """Raised for refused models or unusable reviewer output."""


@dataclass(frozen=True)
class Finding:
    """One reviewer finding (advisory; never applied to the document)."""

    section: str
    statement: str
    issue_type: str
    evidence_ids: tuple[str, ...]
    severity: str
    explanation: str = ""
    evidence_check: str = ""  # "no ids" | "ids exist" | "unknown ids: …"


@dataclass
class ReviewResult:
    """Outcome of one reviewer run."""

    doc_id: str
    model: str
    skill_version: str
    mode: str
    created_at: str
    raw_output: str
    findings: list[Finding] = field(default_factory=list)
    parse_error: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    schema: str = RECORDING_SCHEMA

    @property
    def cost_usd(self) -> float:
        """Estimated Muse Wonder (Standard) cost: $4 / $20 per 1M input / output tokens."""
        return round(
            self.input_tokens * WONDER_USD_PER_M_INPUT / 1e6
            + self.output_tokens * WONDER_USD_PER_M_OUTPUT / 1e6,
            6,
        )


def check_model(model: str) -> None:
    """Refuse Contributor-tier models.

    Raises:
        ReviewError: the model id names a Contributor-tier model.
    """
    if "contributor" in model.lower():
        raise ReviewError("Contributor-tier models train on your data; use Standard tier.")


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in ("style", "script", "svg", "title"):
            self._skip += 1
        elif tag in ("p", "div", "tr", "h1", "h2", "h3", "li", "section", "br"):
            self.parts.append("\n")
        elif tag in ("td", "th"):
            self.parts.append(" | ")

    def handle_endtag(self, tag: str) -> None:
        if tag in ("style", "script", "svg", "title") and self._skip:
            self._skip -= 1

    def handle_data(self, data: str) -> None:
        if not self._skip:
            self.parts.append(data)


def html_to_text(html: str) -> str:
    """Plain text of the dossier HTML (styles and the SVG chart dropped)."""
    p = _TextExtractor()
    p.feed(html)
    lines = [" ".join(line.split()) for line in "".join(p.parts).splitlines()]
    return "\n".join(line for line in lines if line.strip("| "))


def evidence_payload(records: list[EvidenceRecord]) -> list[dict[str, Any]]:
    """Full stored narratives of the cited reports (the reviewer's ground truth)."""
    return [
        {
            "report_id": r.report_id,
            "date_received": r.date_received,
            "event_type": r.event_type,
            "brand_name": r.brand_name,
            "text": r.text[:6000],
        }
        for r in records
    ]


def build_messages(
    skill: LoadedSkill,
    *,
    doc_id: str,
    html: str,
    pdf: bytes | None,
    evidence: list[EvidenceRecord],
    mode: str,
) -> list[dict[str, Any]]:
    """Chat Completions messages for the reviewer (PDF part in ``pdf`` mode)."""
    payload: dict[str, Any] = {"doc_id": doc_id, "evidence": evidence_payload(evidence)}
    if mode == "text" or pdf is None:
        payload["dossier_text"] = html_to_text(html)
    content: list[dict[str, Any]] = [{"type": "text", "text": json.dumps(payload)}]
    if mode == "pdf" and pdf is not None:
        content.append(
            {
                "type": "file",
                "file": {
                    "filename": f"{doc_id}.pdf",
                    "file_data": "data:application/pdf;base64,"
                    + base64.b64encode(pdf).decode("ascii"),
                },
            }
        )
    return [
        {"role": "system", "content": skill.system_prompt},
        {"role": "user", "content": content},
    ]


def parse_findings(content: str, store: EvidenceStore) -> list[Finding]:
    """Parse and sanity-check the reviewer JSON.

    Invalid items are dropped; evidence ids are checked against the store and
    the result is recorded on each finding (the reviewer is not trusted either).

    Raises:
        ReviewError: no JSON object with a ``findings`` list.
    """
    text = _FENCE.sub("", content.strip())
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end < 0:
        raise ReviewError("no JSON object in reviewer output")
    try:
        data = json.loads(text[start : end + 1])
    except json.JSONDecodeError as exc:
        raise ReviewError(f"invalid JSON: {exc}") from exc
    items = data.get("findings") if isinstance(data, dict) else None
    if not isinstance(items, list):
        raise ReviewError("missing 'findings' list")
    out: list[Finding] = []
    for it in items[:15]:
        if not isinstance(it, dict):
            continue
        issue = str(it.get("issue_type", "")).strip()
        sev = str(it.get("severity", "")).strip().lower()
        if issue not in ISSUE_TYPES or sev not in SEVERITIES:
            continue
        ids = tuple(str(i) for i in (it.get("evidence_ids") or []) if str(i).strip())
        unknown = [i for i in ids if store.record(i) is None]
        check = (
            "no ids"
            if not ids
            else (f"unknown ids: {', '.join(unknown)}" if unknown else "ids exist")
        )
        out.append(
            Finding(
                section=str(it.get("section", "")).strip()[:20] or "?",
                statement=str(it.get("statement", "")).strip()[:300],
                issue_type=issue,
                evidence_ids=ids,
                severity=sev,
                explanation=str(it.get("explanation", "")).strip()[:300],
                evidence_check=check,
            )
        )
    out.sort(key=lambda f: SEVERITIES.index(f.severity))
    return out


def review_dossier(
    client: Any,
    *,
    doc_id: str,
    html: str,
    pdf: bytes | None,
    evidence: list[EvidenceRecord],
    store: EvidenceStore,
    model: str = WONDER_MODEL,
    mode: str = "pdf",
    skill: LoadedSkill | None = None,
    max_tokens: int = 24000,
) -> ReviewResult:
    """Run the independent reviewer once.

    Args:
        client: OpenAI-compatible client (``MetaProvider.client``) or a test fake.
        doc_id: Dossier document id.
        html: Rendered dossier HTML (used for text mode / fallback).
        pdf: Rendered PDF bytes (sent as a file part in ``pdf`` mode).
        evidence: Stored records of the cited reports.
        store: Evidence store (to check the reviewer's evidence ids).
        model: Standard-tier model id; Contributor models are refused.
        mode: ``"pdf"`` or ``"text"``.
        skill: Pre-loaded ``dossier-reviewer`` skill.
        max_tokens: Output cap (reasoning counts toward it; the 2026-10-28 recording used
            all 4000 and returned no JSON; at 16000 it used 15,588).

    Raises:
        ReviewError: Contributor model requested.
    """
    check_model(model)
    if mode not in ("pdf", "text"):
        raise ReviewError(f"unknown mode {mode!r}")
    sk = skill or SkillLoader(default_skills_root()).load(SKILL_NAME)

    def call(m: str) -> Any:
        msgs = build_messages(sk, doc_id=doc_id, html=html, pdf=pdf, evidence=evidence, mode=m)
        return client.chat.completions.create(
            model=model, messages=msgs, max_tokens=max_tokens, temperature=0.0
        )

    used = mode
    try:
        resp = call(mode)
    except Exception:  # any API rejection of the file part falls back to text mode
        if mode != "pdf":
            raise
        used = "text"
        resp = call("text")
    usage = getattr(resp, "usage", None)
    raw = str(resp.choices[0].message.content or "")
    result = ReviewResult(
        doc_id=doc_id,
        model=model,
        skill_version=sk.version,
        mode=used,
        created_at=datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        raw_output=raw,
        input_tokens=int(getattr(usage, "prompt_tokens", 0) or 0) if usage else 0,
        output_tokens=int(getattr(usage, "completion_tokens", 0) or 0) if usage else 0,
    )
    try:
        result.findings = parse_findings(raw, store)
    except ReviewError as exc:
        result.parse_error = str(exc)
    return result


def result_to_dict(r: ReviewResult) -> dict[str, Any]:
    """Serializable form (saved next to the PDF)."""
    d = asdict(r)
    d["cost_usd"] = r.cost_usd
    return d


def save_review(r: ReviewResult, path: Path) -> None:
    """Write a review recording as JSON."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(result_to_dict(r), indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )


def load_review(path: Path, store: EvidenceStore | None = None) -> ReviewResult | None:
    """Read a recorded review (findings re-parsed from the raw output when a store is given)."""
    if not path.is_file():
        return None
    d = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(d, dict) or d.get("schema") != RECORDING_SCHEMA:
        return None
    r = ReviewResult(
        doc_id=str(d["doc_id"]),
        model=str(d["model"]),
        skill_version=str(d["skill_version"]),
        mode=str(d["mode"]),
        created_at=str(d["created_at"]),
        raw_output=str(d["raw_output"]),
        parse_error=str(d.get("parse_error", "")),
        input_tokens=int(d.get("input_tokens", 0)),
        output_tokens=int(d.get("output_tokens", 0)),
    )
    if store is not None:
        try:
            r.findings = parse_findings(r.raw_output, store)
        except ReviewError as exc:
            r.parse_error = str(exc)
    else:
        r.findings = [
            Finding(**{**f, "evidence_ids": tuple(f.get("evidence_ids", []))})
            for f in d.get("findings", [])
        ]
    return r


def record_review(db: Database, r: ReviewResult) -> None:
    """Store the findings in the hash-chained audit trail (entity = document id)."""
    db.append_audit(
        actor=f"ai-reviewer:{r.model}",
        action="dossier.review",
        entity_id=r.doc_id,
        payload={
            "model": r.model,
            "skill_version": r.skill_version,
            "mode": r.mode,
            "findings": [asdict(f) for f in r.findings],
            "parse_error": r.parse_error,
            "input_tokens": r.input_tokens,
            "output_tokens": r.output_tokens,
            "cost_usd": r.cost_usd,
        },
    )
