"""Weekly investigator: one agent run for a device type the weekly check flagged.

HACKATHON-BUILT — Meta Global AI Developer Hackathon (Oct 26 – Nov 4, 2026).

When the weekly "what changed" check flags a device type, Muse Spark (through the
same tool loop, claim gate and repair turn as the copilot) pulls that type's new
reports, groups them by kind of problem, checks recalls, 510(k)s and reports not
filed by a manufacturer, and writes the digest entry. Behavior lives in
``skills/weekly-investigator/SKILL.md``; this module only builds the input data,
runs the agent and serializes the result.

Every sentence passes the claim gate; a sentence that still fails after the one
repair turn is withheld and saved as such. A group exists in the saved record only
when the sentence carrying its ``group_count`` claim passed, so every group count is
recomputed from its listed report ids. Nothing here fakes a run: the saved file is
written from a real agent result.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from maudesignal.common.exceptions import MaudeSignalError
from maudesignal.copilot.agent import CopilotAgent, CopilotResult
from maudesignal.copilot.protocol import iso_z, row_from_call, tool_label
from maudesignal.copilot.tools import ToolContext, overnight_signals
from maudesignal.copilot.transcript import _report_to_dict
from maudesignal.extraction.skill_loader import LoadedSkill, SkillLoader
from maudesignal.gate import GateReport, GroupCountClaim

SKILL_NAME = "weekly-investigator"
KIND = "weekly-investigator"
SCHEMA_VERSION = "1.0"
# Read tools only: the investigator never drafts a CAPA-need evidence pack.
ALLOWED_TOOLS = frozenset(
    {
        "overnight_signals",
        "product_summary",
        "search_reports",
        "get_report",
        "report_sources",
        "recalls",
        "device_510k",
        "literature",
        "mhra_alerts",
        "compare_signals",
    }
)
# Reading every new report takes a page per 10 reports plus the other checks.
DEFAULT_TOOL_ROUNDS = 16
NOT_FLAGGED = "manual run: the weekly check did not flag this device type"


class InvestigationError(MaudeSignalError):
    """The investigation could not start (for example the database has no dated reports)."""


@dataclass(frozen=True)
class Group:
    """Reports that describe one kind of problem; ``count`` is recomputed by the gate."""

    label: str
    report_ids: tuple[str, ...]
    count: int

    def to_dict(self) -> dict[str, Any]:
        """JSON-ready dict (``investigations.json`` ``groups`` entry)."""
        return {"label": self.label, "report_ids": list(self.report_ids), "count": self.count}


@dataclass
class InvestigationResult:
    """One weekly investigation: the agent's gated answer plus what triggered it."""

    product_code: str
    trigger: str
    request: dict[str, Any]
    copilot: CopilotResult
    skill_version: str
    recorded_at: str
    groups: list[Group] = field(default_factory=list)

    @property
    def stem(self) -> str:
        """File stem ``<ts>-weekly-<code>`` (``ts`` is the recording time, UTC)."""
        stamp = re.sub(r"[^0-9TZ]", "", self.recorded_at)
        return f"{stamp}-weekly-{self.product_code.lower()}"


def flagged_codes(ctx: ToolContext) -> list[dict[str, str]]:
    """Device types the weekly check flagged, most urgent first.

    Returns:
        ``[{"product_code", "label", "reason"}]`` from the weekly check's own ranking
        (stable device types are not in it).
    """
    check = overnight_signals(ctx)
    return [
        {
            "product_code": str(r["product_code"]),
            "label": str(r["label"]),
            "reason": str(r.get("reason") or ""),
        }
        for r in check.get("ranking", [])
        if r.get("classification") != "stable"
    ]


def build_request(ctx: ToolContext, product_code: str) -> tuple[dict[str, Any], str]:
    """The investigator's input (a JSON object, data only) and the trigger text.

    Everything comes from the weekly check's stored result: the 7-day window and the
    check's label and reason for this device type.
    """
    code = product_code.strip().upper()
    check = overnight_signals(ctx)
    window = check.get("current_window") or {}
    if not window.get("date_from") or not window.get("date_to"):
        raise InvestigationError("the weekly check returned no window; is the database empty?")
    flagged = {f["product_code"]: f for f in flagged_codes(ctx)}
    hit = flagged.get(code)
    request: dict[str, Any] = {
        "task": "weekly-investigation",
        "product_code": code,
        "window": {"date_from": window["date_from"], "date_to": window["date_to"]},
        "weekly_check": (
            {"label": hit["label"], "reason": hit["reason"]}
            if hit
            else {"label": "no change", "reason": ""}
        ),
    }
    trigger = f"weekly check: {hit['label']}" if hit else NOT_FLAGGED
    return request, trigger


def groups_from_report(report: GateReport) -> list[Group]:
    """Groups whose ``group_count`` claim and whole sentence passed the gate."""
    out: list[Group] = []
    for s in report.sentences:
        if s.status != "pass":
            continue
        for cv in s.claim_verdicts:
            if cv.status == "pass" and isinstance(cv.claim, GroupCountClaim):
                out.append(
                    Group(cv.claim.label, tuple(dict.fromkeys(cv.claim.report_ids)), cv.claim.value)
                )
    return out


def investigate(
    client: Any,
    ctx: ToolContext,
    product_code: str,
    *,
    model: str = "muse-spark-1.3",
    skill: LoadedSkill | None = None,
    max_tool_rounds: int = DEFAULT_TOOL_ROUNDS,
    max_tokens: int = 8000,
) -> InvestigationResult:
    """Run the weekly investigator for one device type.

    Args:
        client: OpenAI-compatible client (``MetaProvider.client`` in production).
        ctx: Tool context (database + evidence store).
        product_code: FDA product code the weekly check flagged.
        model: Meta model id (Standard tier).
        skill: Loaded ``weekly-investigator`` skill (loaded from ``skills/`` if omitted).
        max_tool_rounds: Cap on model turns that call tools.
        max_tokens: Output cap per model call.

    Returns:
        The gated result; withheld sentences stay in ``copilot.report`` with their reasons.

    Raises:
        InvestigationError: the weekly check has no window to investigate.
    """
    request, trigger = build_request(ctx, product_code)
    loaded = skill or SkillLoader(Path(__file__).resolve().parents[3] / "skills").load(SKILL_NAME)
    agent = CopilotAgent(
        client,
        ctx,
        model=model,
        skill=loaded,
        max_tool_rounds=max_tool_rounds,
        max_tokens=max_tokens,
        allowed_tools=ALLOWED_TOOLS,
    )
    result = agent.ask(json.dumps(request, sort_keys=True))
    return InvestigationResult(
        product_code=request["product_code"],
        trigger=trigger,
        request=request,
        copilot=result,
        skill_version=loaded.version,
        recorded_at=datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        groups=groups_from_report(result.report),
    )


def _step_summary(call: dict[str, Any]) -> str:
    """One line for a tool step, built only from numbers in the stored result preview."""
    name = str(call["name"])
    row = row_from_call(call)
    if name in ("search_reports", "product_summary", "report_sources"):
        if row is not None and row.count is not None:
            return f"searched {row.count} reports"
        return tool_label(name).replace("_", " ")
    if name == "get_report":
        return "read one report"
    if name == "recalls":
        return "checked recalls"
    if name == "device_510k":
        return "checked a 510(k) record"
    if name == "overnight_signals":
        return "read the weekly check"
    return tool_label(name).replace("_", " ")


def investigation_to_dict(res: InvestigationResult) -> dict[str, Any]:
    """``investigations.json`` entry (web/DATA_CONTRACT.md) plus the stored run detail."""
    calls = [
        {"name": t.name, "arguments": t.arguments, "result_preview": t.result_preview}
        for t in res.copilot.tool_calls
    ]
    final = _report_to_dict(res.copilot.report)
    stem = res.stem
    protocol = [
        r.to_dict() for r in (row_from_call(c, res.recorded_at) for c in calls) if r is not None
    ]
    return {
        "schema_version": SCHEMA_VERSION,
        "id": stem,
        "kind": KIND,
        "product_code": res.product_code,
        "trigger": res.trigger,
        "recorded_at_utc": iso_z(res.recorded_at),
        "model": res.copilot.model,
        "skill_version": res.skill_version,
        "window": res.request["window"],
        "tool_steps": [
            {
                "name": tool_label(str(c["name"])),
                "arguments": c["arguments"],
                "summary": _step_summary(c),
            }
            for c in calls
        ],
        "sentences": final["sentences"],
        "groups": [g.to_dict() for g in res.groups],
        "protocol": protocol,
        "tool_calls": calls,
        "first_pass": _report_to_dict(res.copilot.first_pass_report),
        "repaired": res.copilot.repaired,
        "sentences_repaired": res.copilot.sentences_repaired,
        "parse_failed": res.copilot.parse_failed,
        "length_stops": res.copilot.length_stops,
        "usage": {
            "input_tokens": res.copilot.input_tokens,
            "output_tokens": res.copilot.output_tokens,
            "cost_usd": res.copilot.cost_usd,
        },
    }


def save_investigation(res: InvestigationResult, out_dir: Path) -> Path:
    """Write ``<ts>-weekly-<code>.json`` into ``out_dir``; returns the path."""
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{res.stem}.json"
    path.write_text(json.dumps(investigation_to_dict(res), indent=2) + "\n", encoding="utf-8")
    return path
