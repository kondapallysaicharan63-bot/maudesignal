"""The live smoke script and workflow (HACKATHON-BUILT): fakes only, no network, no spend."""

from __future__ import annotations

import importlib.util
import io
import json
import subprocess
import wave
from pathlib import Path
from typing import Any

import pytest
import yaml

from maudesignal.connector import app as app_module
from tests.unit.test_connector_live import Env, make_wav

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github/workflows/live-smoke.yml"


def load_script() -> Any:
    spec = importlib.util.spec_from_file_location("live_smoke", ROOT / "scripts" / "live_smoke.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def gate_script() -> str:
    wf = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    return str(next(s for s in wf["jobs"]["smoke"]["steps"] if s.get("id") == "gate")["run"])


def run_gate(work: Path, event: str) -> str:
    out = work / "out"
    out.write_text("", encoding="utf-8")
    env = {"GITHUB_EVENT_NAME": event, "GITHUB_OUTPUT": str(out), "PATH": "/usr/bin:/bin"}
    subprocess.run(
        ["bash", "-c", gate_script()], cwd=work, env=env, check=True, capture_output=True
    )
    return out.read_text(encoding="utf-8").strip()


def test_resample_to_16k_mono_pcm16(tmp_path: Path) -> None:
    mod = load_script()
    src = tmp_path / "in.wav"
    with wave.open(str(src), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(24000)
        w.writeframes(b"\x10\x00\x20\x00" * 24000)  # one second, stereo, 24 kHz
    out = mod.to_16k_mono_pcm16(src)
    with wave.open(io.BytesIO(out), "rb") as w:
        assert (w.getnchannels(), w.getsampwidth(), w.getframerate()) == (1, 2, 16000)
        assert abs(w.getnframes() - 16000) <= 1
    ok = tmp_path / "ok.wav"
    ok.write_bytes(make_wav(1.0))
    assert mod.to_16k_mono_pcm16(ok) == ok.read_bytes()  # already right: untouched


def test_no_key_runs_nothing(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv("META_MODEL_API_KEY", raising=False)
    out = tmp_path / "r.json"
    assert load_script().main(["--out", str(out)]) == 2
    assert not out.exists()


def test_full_run_with_fakes_writes_a_clean_result(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("META_MODEL_API_KEY", "KEY-NOT-REAL-should-never-be-written")
    monkeypatch.setenv("MAUDESIGNAL_ALLOW_PER_INSTANCE_CAP", "1")
    mod = load_script()
    env = Env(tmp_path)
    real_settings = app_module.Settings
    monkeypatch.setattr(mod, "Settings", lambda **kw: real_settings(**{**kw, "live": env.backends}))
    out = tmp_path / "r.json"
    assert mod.main(["--out", str(out)]) == 0
    text = out.read_text(encoding="utf-8")
    result = json.loads(text)
    assert [s["step"] for s in result["steps"]] == [
        "ask 1",
        "ask 2 (with history)",
        "voice",
        "label",
    ]
    assert result["total_cost_usd"] <= result["hard_cap_usd"] == 0.6
    assert "KEY-NOT-REAL" not in text and "testclient" not in text
    voice = result["steps"][2]
    assert voice["heard"] and voice["mode"] in ("live", "recorded")
    label = result["steps"][3]
    assert label["match_status"] in ("needs_person_to_confirm", "no_match_found")
    assert label["confirmed"] is None
    # the second chat turn really used the first as history
    users = [m["content"] for r in env.spark.requests for m in r["messages"] if m["role"] == "user"]
    assert any("manufacturer" in u for u in users)


def test_workflow_runs_only_on_the_request_file_or_by_hand() -> None:
    wf = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    on = wf.get(True) or wf["on"]  # YAML reads a bare `on` as True
    assert on["push"]["branches"] == ["track-c-live"]
    assert on["push"]["paths"] == ["demo/LIVE_SMOKE_REQUEST"]
    assert "workflow_dispatch" in on
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "secrets.META_MODEL_API_KEY" in text and "scripts/live_smoke.py" in text
    pushes = [ln.strip() for ln in text.splitlines() if "git push" in ln]
    assert pushes == ["git push origin HEAD:track-c-live"]


def test_the_first_push_is_free() -> None:
    assert (ROOT / "demo/LIVE_SMOKE_REQUEST").read_text(encoding="utf-8").strip() == "0"


@pytest.mark.parametrize(
    ("content", "expected"),
    [("0\n", "no"), ("", "no"), ("  \n", "no"), ("1\n", "yes"), ("go", "yes")],
)
def test_gate_step_skips_a_push_with_empty_or_zero(
    tmp_path: Path, content: str, expected: str
) -> None:
    (tmp_path / "demo").mkdir()
    (tmp_path / "demo/LIVE_SMOKE_REQUEST").write_text(content, encoding="utf-8")
    assert run_gate(tmp_path, "push") == f"run={expected}"


def test_gate_step_lets_a_manual_run_through(tmp_path: Path) -> None:
    assert run_gate(tmp_path, "workflow_dispatch") == "run=yes"


def test_vercel_function_ships_everything_the_live_path_loads() -> None:
    cfg = json.loads((ROOT / "vercel.json").read_text(encoding="utf-8"))
    fn = cfg["functions"]["api/index.py"]
    include = fn["includeFiles"]
    folders = include.split("}")[0].lstrip("{").split(",")
    for needed in ("src", "skills", "demo/transcripts", "demo/vision", "data/demo"):
        assert needed in folders, needed
    assert include.endswith("}/**")
    assert fn["maxDuration"] == 60
    assert any(r["source"] == "/v1/(.*)" for r in cfg["rewrites"])
    reqs = (ROOT / "api/requirements.txt").read_text(encoding="utf-8").lower()
    assert "pillow" in reqs and "httpx" in reqs and "openai" in reqs
