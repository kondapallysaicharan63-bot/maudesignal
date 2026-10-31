"""The budget module docstring must state the smoke limits the code enforces."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts" / "release"))

import budget  # noqa: E402


def test_docstring_states_smoke_limits() -> None:
    doc = " ".join((budget.__doc__ or "").split())
    assert budget.SMOKE_LIMITS == {"ask": 1, "photo": 0, "voice": 1}
    assert "1 live ask, 0 live photos and 1 spoken question" in doc
