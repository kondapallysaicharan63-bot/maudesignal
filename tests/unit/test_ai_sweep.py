"""The AI-device sweep reads FDA's list table and writes an honest report."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("ai_sweep", ROOT / "scripts" / "ai_device_sweep.py")
assert _spec and _spec.loader
sweep = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(sweep)

PAGE = """<html><body><table>
<thead><tr><th>Date of Final Decision</th><th>Submission Number</th><th>Device</th>
<th>Company</th><th>Panel (lead)</th><th>Primary Product Code</th></tr></thead>
<tbody>
<tr><td>08/01/2026</td><td>K261677</td><td>A</td><td>X</td><td>Radiology</td><td>LLZ</td></tr>
<tr><td>07/01/2026</td><td>K261111</td><td>B</td><td>Y</td><td>Radiology</td><td>LLZ</td></tr>
<tr><td>06/01/2026</td><td>DEN250001</td><td>C</td><td>Z</td><td>Cardiovascular</td><td>QIH</td></tr>
<tr><td>05/01/2026</td><td>K250002</td><td>D</td><td>W</td><td>Radiology</td><td></td></tr>
</tbody></table></body></html>"""


def test_codes_are_read_from_the_product_code_column() -> None:
    pytest.importorskip("lxml")
    per_code, devices = sweep.ai_list_codes(PAGE)
    assert devices == 4
    assert per_code == {"LLZ": 2, "QIH": 1}


def test_report_lists_only_flagged_codes_with_their_query(tmp_path: Path) -> None:
    meta = {
        "generated_utc": "2026-10-29T12:00:00Z",
        "run_id": "1",
        "devices_on_list": 4,
        "codes_on_list": 2,
        "codes_checked": 2,
        "capped": False,
        "errors": 0,
        "window": {
            "as_of": "2026-08-31",
            "current_start": "2026-08-25",
            "current_end": "2026-08-31",
            "baseline_start": "2026-07-28",
            "baseline_end": "2026-08-24",
        },
    }
    base = {
        "current_severe_count": 0,
        "queries": [["a", "https://api.fda.gov/1"], ["b", "https://api.fda.gov/2"]],
    }
    rows = [
        {
            **base,
            "product_code": "LLZ",
            "ai_devices_on_list": 2,
            "classification": "spike",
            "change": "reports suddenly increased",
            "current_count": 33,
            "baseline_weekly_mean": 8.75,
        },
        {
            **base,
            "product_code": "QIH",
            "ai_devices_on_list": 1,
            "classification": "stable",
            "change": "no change",
            "current_count": 0,
            "baseline_weekly_mean": 0.0,
        },
    ]
    out = tmp_path / "s.md"
    sweep.write_markdown(meta, rows, out)
    text = out.read_text()
    assert "Flagged: 1 of 2 (reports suddenly increased: 1)." in text
    assert (
        "| LLZ | 2 | reports suddenly increased | 33 | 8.75 | 0 | [open](https://api.fda.gov/2) |"
        in text
    )
    assert "| QIH |" not in text
    assert "not a finding about any device or company" in text
    assert "Flags need at least 3 reports this week; 0 code(s) skipped" in text


def test_app_summary_reads_the_sweep_file(tmp_path: Path) -> None:
    from maudesignal.dashboard.live_check_ui import load_sweep, sweep_summary

    assert load_sweep(tmp_path / "missing.json") is None
    f = tmp_path / "s.json"
    f.write_text(
        '{"meta": {"generated_utc": "2026-10-29T12:00:00Z", "window": {"current_start": '
        '"2026-08-25", "current_end": "2026-08-31"}}, "rows": [{"classification": "spike"}, '
        '{"classification": "stable"}]}'
    )
    data = load_sweep(f)
    assert data is not None
    assert sweep_summary(data).startswith("1 of 2 AI device types on FDA's list were flagged")
