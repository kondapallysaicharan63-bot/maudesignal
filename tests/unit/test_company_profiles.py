"""The simulated device profiles are reproducible and carry no real-world identifiers."""

from __future__ import annotations

import importlib.util
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location(
    "build_company_profiles", ROOT / "scripts" / "build_company_profiles.py"
)
assert _spec and _spec.loader
builder = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(builder)

STORED = ROOT / "web" / "public" / "data" / "company_profiles.json"


def test_stored_file_is_what_the_script_builds() -> None:
    """Re-running the seeded script gives the committed file byte for byte."""
    assert builder.render() == STORED.read_text()
    assert builder.render() == builder.render()


def test_no_real_k_number_udi_or_banned_wording() -> None:
    """Only fake numbers (K-SIM-, SIM-UDI-) and no claim words appear."""
    text = STORED.read_text()
    assert not re.search(r"\bK\d{6}\b", text)
    assert not re.search(r"\b\d{14}\b", text)
    banned = r"fda[- ]approved|\bvalidated\b|\bsafe\b|\bunsafe\b|draft capa"
    assert not re.search(banned, text, re.I)
    data = json.loads(text)
    for p in data["profiles"].values():
        assert p["market"]["udi_di"].startswith("SIM-UDI-")
        assert re.fullmatch(r"(K|DEN|P)-SIM-\d{4}", p["regulatory"]["submission"]["number"])


def test_real_fields_come_from_stored_data() -> None:
    """FDA name equals company.json; class and regulation number equal the stored classification."""
    company = json.loads((ROOT / "web" / "public" / "data" / "company.json").read_text())
    data = json.loads(STORED.read_text())
    for dev in company["devices"]:
        ov = data["profiles"][dev["id"]]["overview"]
        assert ov["fda_device_name"] == dev["device_type"]["name"]
        f = ROOT / "demo" / "company" / "evidence" / f"{dev['product_code']}.json"
        if f.exists():
            cl = json.loads(f.read_text())["classification"]
            assert ov["device_class"] == (cl["device_class"] or None)
            assert ov["regulation_number"] == (cl["regulation_number"] or None)


def test_decision_paths_have_the_realistic_mix() -> None:
    """Mostly notes to file, 2-3 CAPAs, exactly one MDR-reportable, one recall ruled out."""
    data = json.loads(STORED.read_text())
    paths = [x for p in data["profiles"].values() for x in p["decision"]["paths"]]
    decided = [x["outcome"] for x in paths if x["outcome"]]
    kinds = [o["kind"] for o in decided]
    assert kinds.count("ntf") > len(decided) / 2
    assert 2 <= kinds.count("capa") <= 3
    esc = [o for o in decided if o["kind"] == "escalation"]
    assert sum(o["mdr"]["result"] == "reportable" for o in esc) == 1
    assert (
        sum(
            o["recall"]["result"] == "recall not warranted"
            and o["mdr"]["result"] == "not reportable"
            for o in esc
        )
        == 1
    )
    for x in paths:
        for step in (x["triage"], x["board"], *([x["outcome"]] if x["outcome"] else [])):
            assert step["tags"], x["id"]
        assert x["triage"]["date"] <= x["board"]["date"]
