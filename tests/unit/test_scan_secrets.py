"""The CI secret scan finds key shapes and ignores test fakes."""

from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("scan_secrets", ROOT / "scripts" / "scan_secrets.py")
assert _spec and _spec.loader
scan_secrets = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(scan_secrets)


def test_key_shapes_are_found() -> None:
    text = "\n".join(
        [
            "ok line",
            "GROQ_API_KEY=" + "gsk_" + "A" * 48,
            'client = Anthropic(api_key="' + "sk-ant-" + "b" * 30 + '")',
            "META_MODEL_API_KEY: " + "Z" * 24,
        ]
    )
    providers = [p for _, p in scan_secrets.scan_text(text)]
    assert "Groq" in providers and "Anthropic" in providers and "Assigned key" in providers


def test_fakes_and_empty_values_pass() -> None:
    text = 'groq_api_key="gsk_fake"\nMETA_MODEL_API_KEY=\nOPENFDA_API_KEY=${{ secrets.X }}'
    assert scan_secrets.scan_text(text) == []


def test_the_repository_holds_no_keys() -> None:
    assert scan_secrets.main() == 0
