"""Root-level pytest fixtures shared across unit and e2e test suites."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from maudesignal.storage.database import Database


@pytest.fixture
def tmp_db(tmp_path: Path) -> Database:
    """A fresh SQLite database in a temporary directory."""
    return Database(tmp_path / "test.db")


@pytest.fixture
def sample_maude_record() -> dict[str, Any]:
    """Minimal openFDA device event payload for a stroke-triage CAD device."""
    return {
        "mdr_report_key": "TEST-001",
        "event_type": ["Malfunction"],
        "date_received": "20250601",
        "date_of_event": "20250530",
        "mdr_text": [
            {
                "text_type_code": "Description of Event",
                "text": "AI algorithm failed to flag LVO on CT scan.",
            },
            {
                "text_type_code": "Manufacturer Narrative",
                "text": "Investigation ongoing. Possible software defect.",
            },
        ],
        "device": [{"brand_name": "StrokeAI v2.1", "manufacturer_d_name": "AcmeMed AI"}],
    }


@pytest.fixture
def mock_llm_response() -> dict[str, Any]:
    """Representative Skill #1 (maude-narrative-extractor) output."""
    return {
        "failure_mode": "False negative on stroke detection",
        "device_problem": "Algorithm failed to flag hemorrhage",
        "patient_outcome": "Delayed diagnosis; patient recovered",
        "ai_related_flag": True,
        "ai_related_rationale": "Product code is an AI/ML CADt device.",
        "confidence_score": 0.90,
        "requires_human_review": False,
        "severity": "serious_injury",
    }


@pytest.fixture
def mock_openfda_response() -> dict[str, Any]:
    """Minimal openFDA API response envelope with one result."""
    return {
        "meta": {"results": {"skip": 0, "limit": 100, "total": 1}},
        "results": [
            {
                "mdr_report_key": "MOCK-001",
                "event_type": ["Injury"],
                "date_received": "20250101",
                "date_of_event": "20241230",
                "mdr_text": [
                    {
                        "text_type_code": "Description of Event",
                        "text": "Device misread input data.",
                    }
                ],
                "device": [{"brand_name": "TestDevice", "manufacturer_d_name": "TestCorp"}],
            }
        ],
    }
