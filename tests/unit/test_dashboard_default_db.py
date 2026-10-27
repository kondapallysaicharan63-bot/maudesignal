"""Stored-first deploy: the dashboard falls back to the committed demo DB (HACKATHON)."""

from __future__ import annotations

from pathlib import Path

import pytest

import maudesignal.dashboard.app as app


def _setup(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    demo = tmp_path / "data" / "demo" / "maudesignal_demo.db"
    demo.parent.mkdir(parents=True)
    demo.touch()
    monkeypatch.setattr(app, "_PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(app, "_DEMO_DB_PATH", demo)
    return demo


def test_uses_demo_db_when_nothing_configured(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    demo = _setup(tmp_path, monkeypatch)
    monkeypatch.delenv("MAUDESIGNAL_DB_PATH", raising=False)
    db = app._load_db()
    assert db.path.resolve() == demo.resolve()


def test_env_var_wins_over_demo_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    demo = _setup(tmp_path, monkeypatch)
    target = tmp_path / "custom.db"
    monkeypatch.setenv("MAUDESIGNAL_DB_PATH", str(target))
    db = app._load_db()
    assert db.path.resolve() != demo.resolve()


def test_local_db_wins_over_demo_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    demo = _setup(tmp_path, monkeypatch)
    (tmp_path / "data" / "maudesignal.db").touch()
    monkeypatch.delenv("MAUDESIGNAL_DB_PATH", raising=False)
    db = app._load_db()
    assert db.path.resolve() != demo.resolve()
