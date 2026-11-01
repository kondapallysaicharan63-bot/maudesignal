"""The simulated device profiles are reproducible and carry no real-world identifiers."""

from __future__ import annotations

import importlib.util
import json
import re
from datetime import date
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


def _paths(data: dict) -> list[dict]:
    return [x for p in data["profiles"].values() for x in p["decision"]["paths"]]


def test_decision_paths_have_the_realistic_mix() -> None:
    """Mostly notes to file, 2-3 CAPAs, exactly one MDR-reportable, exactly one recall ruled out."""
    data = json.loads(STORED.read_text())
    paths = _paths(data)
    decided = [x["outcome"] for x in paths if x["outcome"]]
    kinds = [o["kind"] for o in decided]
    esc = [o for o in decided if o["kind"] == "escalation"]
    capas = kinds.count("capa") + sum(1 for o in esc if o["follow_up_capa"])
    assert kinds.count("ntf") > len(decided) / 2
    assert 2 <= capas <= 3
    assert sum(o["mdr"]["result"] == "reportable" for o in esc) == 1
    assert sum(o["recall"]["result"] == "recall not warranted" for o in esc) == 1
    for x in paths:
        for step in (x["triage"], x["board"], *([x["outcome"]] if x["outcome"] else [])):
            assert step["tags"], x["id"]
        assert x["triage"]["date"] <= x["board"]["date"]


def test_decision_paths_start_after_the_signal_and_the_registration() -> None:
    """A path is dated after its signal and the registration."""
    company = json.loads((ROOT / "web" / "public" / "data" / "company.json").read_text())
    data = json.loads(STORED.read_text())
    devices = {d["id"]: d for d in company["devices"]}
    for pid, p in data["profiles"].items():
        dev = devices[pid]
        reg = dev["history"][0]["date"]
        for x in p["decision"]["paths"]:
            assert x["triage"]["date"] >= reg, x["id"]
            assert x["triage"]["date"] <= data["as_of"], x["id"]
            if x["signal"]["kind"] == "sweep":
                a = dev["sweep"]["as_of"]
                assert x["triage"]["date"] >= f"{a[:4]}-{a[4:6]}-{a[6:]}", x["id"]
                continue
            pat = next(q for q in dev["patterns"] if q["id"] == x["signal"]["pattern_id"])
            last = pat["last_received"]
            assert x["triage"]["date"] >= f"{last[:4]}-{last[4:6]}-{last[6:]}", x["id"]
            run = re.search(r"recorded run (\d{8})T", pat["basis"])
            if run:
                r = run.group(1)
                assert x["triage"]["date"] >= f"{r[:4]}-{r[4:6]}-{r[6:]}", x["id"]


def test_decision_paths_are_coherent() -> None:
    """A not-acceptable starting risk gets an escalation with a CAPA."""
    data = json.loads(STORED.read_text())
    for x in _paths(data):
        if x["risk"] and x["risk"]["before"]["zone"] == "not acceptable":
            assert x["outcome"]["kind"] == "escalation" and x["outcome"]["follow_up_capa"], x["id"]
    assert data["profiles"]["DMC-05"]["overview"]["pathway"] == "510(k)"
    assert data["profiles"]["DMC-06"]["design"]["software"]["iec62304_class"] == "C"
    scale = {"Negligible", "Minor", "Serious", "Critical", "Catastrophic"}
    for p in data["profiles"].values():
        assert {h["severity"] for h in p["design"]["hazards"]} <= scale
        for c in p["postmarket"]["capas"]:
            if c["closed"]:
                opened, closed = date.fromisoformat(c["opened"]), date.fromisoformat(c["closed"])
                assert (closed - opened).days >= 90, c["id"]
