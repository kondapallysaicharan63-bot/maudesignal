"""The numbers every recording quotes are recomputed from stored data and must not move."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parents[2]


def _load() -> ModuleType:
    import sys

    sys.path.insert(0, str(ROOT / "scripts"))
    spec = importlib.util.spec_from_file_location(
        "print_quoted_numbers", ROOT / "scripts/print_quoted_numbers.py"
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_quoted_numbers_are_unchanged() -> None:
    mod = _load()
    assert mod.gate_first_pass() == (28, 63, 65)
    assert mod.hand_check() == (28, 27, 65, 64)
    assert mod.llz_openfda() == (19970, 19823, "99.3")
    assert mod.sweep() == (6, 181)
    assert len(mod.lines()) == 4
