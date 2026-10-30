"""Recall-triggered sweep: find stored reports that describe a recall's failure.

HACKATHON-BUILT — Meta Global AI Developer Hackathon (Oct 26 – Nov 4, 2026).

When a recall is stored for a watched device type, Muse Spark (through the same tool
loop, claim gate and repair turn as the copilot) reads the recall's stated reason and
searches the stored MAUDE narratives for the same failure. It answers "N reports describe
the same problem as recall X" with quotes matched word for word to the cited report or
recall, and the count recomputed by the gate from the listed report ids. Behavior lives
in ``skills/recall-sweep/SKILL.md``; this module only builds the input data, runs the
agent and serializes the result. No new claim kind: the answer uses ``group_count``,
``quote`` and ``recall`` claims.

Nothing here fakes a run: the saved file is written from a real agent result.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote

from maudesignal.copilot.agent import CopilotAgent, CopilotResult
from maudesignal.copilot.investigator import (
    DEFAULT_TOOL_ROUNDS,
    Group,
    InvestigationError,
    _step_summary,
    groups_from_report,
)
from maudesignal.copilot.protocol import iso_z, row_from_call, tool_label
from maudesignal.copilot.tools import ToolContext
from maudesignal.copilot.transcript import _report_to_dict
from maudesignal.extraction.skill_loader import LoadedSkill, SkillLoader
from maudesignal.gate import RecallRef

SKILL_NAME = "recall-sweep"
KIND = "recall-sweep"
SCHEMA_VERSION = "1.0"
# Read tools only: the sweep never drafts a CAPA-need evidence pack.
ALLOWED_TOOLS = frozenset(
    {
        "recalls",
        "search_reports",
        "get_report",
        "report_sources",
        "device_510k",
        "product_summary",
    }
)
REASON_CHARS = 800
OPENFDA = "https://api.fda.gov/device"


@dataclass
class SweepResult:
    """One recall sweep: the agent's gated answer plus the recall that triggered it."""

    recall: RecallRef
    request: dict[str, Any]
    copilot: CopilotResult
    skill_version: str
    recorded_at: str
    groups: list[Group] = field(default_factory=list)

    @property
    def product_code(self) -> str:
        """Product code of the recalled device type."""
        return self.recall.product_code

    @property
    def trigger(self) -> str:
        """Why this run happened, in plain words."""
        return f"recall {self.recall.recall_number} stored for {self.recall.product_code}"

    @property
    def stem(self) -> str:
        """File stem ``<ts>-recall-<code>`` (``ts`` is the recording time, UTC)."""
        stamp = re.sub(r"[^0-9TZ]", "", self.recorded_at)
        return f"{stamp}-recall-{self.recall.product_code.lower()}"


def find_recall(ctx: ToolContext, recall_id: str) -> RecallRef:
    """The stored recall with this recall number (or a one-recall event number).

    Raises:
        InvestigationError: no stored recall has that id, the id names an event with more
            than one recall (give the recall number), or the recalled device type has no
            stored reports (it is not a watched device type).
    """
    rid = recall_id.strip()
    matches = ctx.store.recalls_by_number(rid)
    exact = [r for r in matches if r.recall_number.upper() == rid.upper()]
    if exact:
        matches = exact[:1]
    if not matches:
        raise InvestigationError(f"no stored recall {rid!r}")
    if len(matches) > 1:
        numbers = ", ".join(r.recall_number for r in matches[:5])
        raise InvestigationError(f"{rid!r} names {len(matches)} recalls ({numbers}); give one")
    recall = matches[0]
    if not ctx.store.select(product_code=recall.product_code):
        raise InvestigationError(
            f"recall {recall.recall_number} is for {recall.product_code}, "
            "which has no stored reports (not a watched device type)"
        )
    return recall


def build_request(ctx: ToolContext, recall: RecallRef) -> dict[str, Any]:
    """The sweep's input (a JSON object, data only), all from the stored recall and reports."""
    dates = sorted(
        r.date_received
        for r in ctx.store.select(product_code=recall.product_code)
        if r.date_received
    )
    if not dates:
        raise InvestigationError(
            f"{recall.product_code} has no dated reports; nothing to sweep against"
        )
    return {
        "task": "recall-sweep",
        "recall_number": recall.recall_number,
        "event_number": recall.event_number,
        "product_code": recall.product_code,
        "recalling_firm": recall.recalling_firm,
        "date_initiated": recall.date_initiated,
        "product_description": recall.product_description[:300],
        "reason_for_recall": recall.reason_for_recall[:REASON_CHARS],
        "k_numbers": list(recall.k_numbers),
        "window": {"date_from": dates[0], "date_to": dates[-1]},
    }


def sweep(
    client: Any,
    ctx: ToolContext,
    recall_id: str,
    *,
    model: str = "muse-spark-1.3",
    skill: LoadedSkill | None = None,
    max_tool_rounds: int = DEFAULT_TOOL_ROUNDS,
    max_tokens: int = 8000,
) -> SweepResult:
    """Run the recall sweep for one stored recall.

    Args:
        client: OpenAI-compatible client (``MetaProvider.client`` in production).
        ctx: Tool context (database + evidence store).
        recall_id: Recall number (for example ``Z-0186-2027``).
        model: Meta model id (Standard tier).
        skill: Loaded ``recall-sweep`` skill (loaded from ``skills/`` if omitted).
        max_tool_rounds: Cap on model turns that call tools.
        max_tokens: Output cap per model call.

    Returns:
        The gated result; withheld sentences stay in ``copilot.report`` with their reasons.

    Raises:
        InvestigationError: the recall is not stored, is ambiguous, or has no stored reports.
    """
    recall = find_recall(ctx, recall_id)
    request = build_request(ctx, recall)
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
    return SweepResult(
        recall=recall,
        request=request,
        copilot=result,
        skill_version=loaded.version,
        recorded_at=datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        groups=groups_from_report(result.report),
    )


def _recall_link(recall_number: str) -> str:
    """Link to the openFDA query for this recall (built from the id, not fetched)."""
    return f'{OPENFDA}/recall.json?search=product_res_number:"{quote(recall_number)}"'


def _report_link(report_id: str) -> str:
    """Link to the openFDA query that returns this MAUDE report (built from the id, not fetched)."""
    return f'{OPENFDA}/event.json?search=report_number:"{quote(report_id)}"'


def sweep_to_dict(res: SweepResult) -> dict[str, Any]:
    """``investigations.json`` entry (web/DATA_CONTRACT.md) plus the stored run detail."""
    calls = [
        {"name": t.name, "arguments": t.arguments, "result_preview": t.result_preview}
        for t in res.copilot.tool_calls
    ]
    final = _report_to_dict(res.copilot.report)
    protocol = [
        r.to_dict() for r in (row_from_call(c, res.recorded_at) for c in calls) if r is not None
    ]
    rc = res.recall
    groups = [{**g.to_dict(), "links": [_report_link(i) for i in g.report_ids]} for g in res.groups]
    return {
        "schema_version": SCHEMA_VERSION,
        "id": res.stem,
        "kind": KIND,
        "product_code": res.product_code,
        "trigger": res.trigger,
        "recall": {
            "recall_number": rc.recall_number,
            "event_number": rc.event_number,
            "recalling_firm": rc.recalling_firm,
            "date_initiated": rc.date_initiated,
            "recall_status": rc.recall_status,
            "reason_for_recall": rc.reason_for_recall,
            "link": _recall_link(rc.recall_number),
        },
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
        "groups": groups,
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


def save_sweep(res: SweepResult, out_dir: Path) -> Path:
    """Write ``<ts>-recall-<code>.json`` into ``out_dir``; returns the path."""
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{res.stem}.json"
    path.write_text(json.dumps(sweep_to_dict(res), indent=2) + "\n", encoding="utf-8")
    return path
