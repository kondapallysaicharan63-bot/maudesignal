"""Tests for maudesignal.connector.keygen (HACKATHON-BUILT): the key never reaches stdout,
stderr or the repository; Vercel is called with the key only in the request body. No network.
"""

from __future__ import annotations

import importlib.util
import io
import stat
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "src" / "maudesignal" / "connector" / "keygen.py"
NOW = datetime(2026, 10, 29, 12, 0, 0, tzinfo=UTC)


def load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("new_connector_key", SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["new_connector_key"] = mod
    spec.loader.exec_module(mod)
    return mod


class FakeVercel:
    def __init__(self, envs: list[dict[str, Any]] | None = None, status: int = 200) -> None:
        self.envs = envs or []
        self.status = status
        self.old_value = "existing-key-NOT-REAL-0123456789abcdef"
        self.requests: list[tuple[str, str, dict[str, Any] | None]] = []

    def __call__(
        self, method: str, url: str, token: str, body: dict[str, Any] | None
    ) -> tuple[int, Any]:
        assert token == "vercel-token-NOT-REAL"
        self.requests.append((method, url, body))
        if method == "GET" and "/v1/projects/" in url:  # one variable, decrypted
            return self.status, {"value": self.old_value}
        if method == "GET":
            return self.status, {"envs": self.envs}
        return (201 if method == "POST" else 200) if self.status == 200 else self.status, {
            "echo": body
        }


def run(
    mod: ModuleType, argv: list[str], env: dict[str, str], http: Any = None
) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    kw: dict[str, Any] = {"env": env, "stdout": out, "stderr": err, "now": lambda: NOW}
    if http is not None:
        kw["http"] = http
    code = mod.main(argv, **kw)
    return code, out.getvalue(), err.getvalue()


def test_file_mode_writes_outside_repo_and_never_prints_the_key(tmp_path: Path) -> None:
    mod = load()
    code, out, err = run(mod, ["--out-dir", str(tmp_path / "keys")], {})
    assert code == 0 and err == ""
    files = list((tmp_path / "keys").glob("maudesignal-connector-key-*.txt"))
    assert len(files) == 1
    key = files[0].read_text(encoding="utf-8").strip()
    assert len(key) >= 32 and key.isascii()
    assert stat.S_IMODE(files[0].stat().st_mode) == 0o600
    assert key not in out and key not in err
    assert str(files[0]) in out and "not printed" in out
    for fragment in (key[:6], key[-6:]):  # not even partially
        assert fragment not in out and fragment not in err


def test_each_run_makes_a_new_key(tmp_path: Path) -> None:
    mod = load()
    keys = set()
    for i in range(3):
        d = tmp_path / str(i)
        run(mod, ["--out-dir", str(d)], {})
        keys.add(next(d.glob("*.txt")).read_text())
    assert len(keys) == 3


def test_refuses_to_write_inside_the_repository() -> None:
    mod = load()
    code, out, err = run(mod, ["--out-dir", str(ROOT / "tmp-keys")], {})
    assert code == 1 and "Nothing was written" in err and out == ""
    assert not (ROOT / "tmp-keys").exists()


def test_vercel_mode_creates_the_encrypted_production_variable() -> None:
    mod = load()
    http = FakeVercel()
    env = {"VERCEL_TOKEN": "vercel-token-NOT-REAL", "VERCEL_PROJECT_ID": "prj_123"}
    code, out, err = run(mod, [], env, http)
    assert code == 0 and err == ""
    assert [m for m, _, _ in http.requests] == ["GET", "POST"]
    _, url, body = http.requests[1]
    assert url == "https://api.vercel.com/v10/projects/prj_123/env"
    assert body is not None
    assert body["key"] == "MAUDESIGNAL_API_KEYS"
    assert body["type"] == "encrypted" and body["target"] == ["production"]
    key = body["value"]
    assert len(key) >= 32
    assert key not in out and key not in err and key[:6] not in out
    assert out.splitlines()[0] == (
        "set; copy it from Vercel > Project > Settings > Environment Variables > "
        "MAUDESIGNAL_API_KEYS (click to reveal)"
    )


def test_vercel_mode_updates_an_existing_variable_and_passes_the_team() -> None:
    mod = load()
    http = FakeVercel([{"id": "env_9", "key": "MAUDESIGNAL_API_KEYS", "target": ["production"]}])
    env = {
        "VERCEL_TOKEN": "vercel-token-NOT-REAL",
        "VERCEL_PROJECT_ID": "prj_123",
        "VERCEL_TEAM_ID": "team_7",
    }
    code, out, err = run(mod, [], env, http)
    assert code == 0
    assert [m for m, _, _ in http.requests] == ["GET", "GET", "PATCH"]
    assert http.requests[1][1].startswith("https://api.vercel.com/v1/projects/prj_123/env/env_9")
    assert (
        http.requests[2][1] == "https://api.vercel.com/v9/projects/prj_123/env/env_9?teamId=team_7"
    )
    body = http.requests[2][2]
    assert body is not None and body["type"] == "encrypted" and "key" not in body
    assert body["value"] not in out + err
    # appended, not replaced: the earlier key is still first in the list
    assert body["value"].startswith(http.old_value + ",")
    assert http.old_value not in out + err


def test_label_is_written_as_label_equals_key_and_the_key_is_appended() -> None:
    mod = load()
    http = FakeVercel([{"id": "env_9", "key": "MAUDESIGNAL_API_KEYS", "target": ["production"]}])
    env = {"VERCEL_TOKEN": "vercel-token-NOT-REAL", "VERCEL_PROJECT_ID": "prj_123"}
    code, out, err = run(mod, ["--label", "meta-review"], env, http)
    assert code == 0 and err == ""
    body = http.requests[-1][2]
    assert body is not None
    assert body["value"].startswith(http.old_value + ",meta-review=")
    new_key = body["value"].split("meta-review=", 1)[1]
    assert len(new_key) >= 32 and new_key not in out + err


def test_label_in_file_mode_prints_the_line_without_the_key(tmp_path: Path) -> None:
    mod = load()
    code, out, err = run(mod, ["--label", "charan", "--out-dir", str(tmp_path / "k")], {})
    assert code == 0 and err == ""
    key = next((tmp_path / "k").glob("*.txt")).read_text().strip()
    assert "charan=<key>" in out and key not in out


def test_bad_label_is_refused() -> None:
    mod = load()
    code, out, err = run(mod, ["--label", "no spaces=allowed"], {})
    assert code == 2 and out == "" and "label" in err


def test_vercel_failure_prints_status_only_and_no_key() -> None:
    mod = load()
    http = FakeVercel(status=403)
    env = {"VERCEL_TOKEN": "vercel-token-NOT-REAL", "VERCEL_PROJECT_ID": "prj_123"}
    code, out, err = run(mod, [], env, http)
    assert code == 1 and out == "" and "HTTP 403" in err and "No key was saved" in err
    assert "vercel-token-NOT-REAL" not in err
    assert [m for m, _, _ in http.requests] == ["GET"]


def test_real_process_stdout_and_stderr_never_hold_the_key(tmp_path: Path) -> None:
    """Run the script as a subprocess (the way an operator does) and scan both streams."""
    proc = subprocess.run(  # noqa: S603
        [sys.executable, "-m", "maudesignal.connector.keygen", "--out-dir", str(tmp_path / "k")],
        capture_output=True,
        text=True,
        env={"PATH": "/usr/bin:/bin", "HOME": str(tmp_path), "PYTHONPATH": str(ROOT / "src")},
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    key = next((tmp_path / "k").glob("*.txt")).read_text().strip()
    assert key not in proc.stdout and key not in proc.stderr
    assert key[:8] not in proc.stdout + proc.stderr


def test_the_key_it_makes_is_accepted_by_the_server_key_store(tmp_path: Path) -> None:
    from maudesignal.connector.security import KeyStore

    mod = load()
    run(mod, ["--out-dir", str(tmp_path)], {})
    key = next(tmp_path.glob("*.txt")).read_text().strip()
    store = KeyStore.from_env({"MAUDESIGNAL_API_KEYS": key})
    assert store.configured and store.verify(key) is not None


def test_no_key_literal_in_the_script_and_no_print_of_the_key() -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    assert "print(key" not in text and 'print(f"{key' not in text


def test_refuses_any_directory_under_a_git_working_tree(tmp_path: Path) -> None:
    """Also protects a different checkout than the one this module was imported from."""
    other = tmp_path / "other-checkout"
    (other / ".git").mkdir(parents=True)
    mod = load()
    code, out, err = run(mod, ["--out-dir", str(other / "keys")], {})
    assert code == 1 and "Nothing was written" in err and out == ""
    assert not (other / "keys").exists()
