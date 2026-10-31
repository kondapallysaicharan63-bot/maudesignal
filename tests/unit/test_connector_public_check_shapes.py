"""Contract: every answer shape of GET /v1/public/check_device_type that the web page reads.

The web test ``web/src/liveCheckShapes.test.tsx`` replays the captured JSON in
``web/src/fixtures/publicCheckAnswers.json``. This file keeps that fixture equal to what the API
returns now, so a renamed field breaks here before it breaks the page (release check 41193468764:
with openFDA unreachable the API answers 200 with ``check: null`` and the page showed "the API did
not answer"). No network, no model key.
"""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import date
from pathlib import Path

import pytest

pytest.importorskip("fastapi")

from maudesignal.common.exceptions import OpenFDAAPIError  # noqa: E402
from maudesignal.connector.data import PROJECT_ROOT, ConnectorData  # noqa: E402
from maudesignal.monitor.live_check import (  # noqa: E402
    LiveCheck,
    WindowCounts,
    build_window,
    classify_counts,
)
from tests.unit.test_connector import fake_check  # noqa: E402
from tests.unit.test_connector_deploy import make, public  # noqa: E402

FIXTURE = PROJECT_ROOT / "web" / "src" / "fixtures" / "publicCheckAnswers.json"


@pytest.fixture(scope="module")
def data(tmp_path_factory: pytest.TempPathFactory) -> ConnectorData:
    return ConnectorData(work_dir=tmp_path_factory.mktemp("shapes"))


def _down(code: str) -> LiveCheck:
    raise OpenFDAAPIError("no network in tests")


def _zero(code: str) -> LiveCheck:
    result = classify_counts(
        code, WindowCounts(0, 0, 0, (), (), ()), build_window(date(2026, 9, 7))
    )
    return replace(
        result,
        as_of=None,
        window=None,
        queries=(("Everything", "https://api.fda.gov/device/event.json?search=x&limit=1"),),
    )


def test_web_fixture_equals_what_the_api_returns(data: ConnectorData, tmp_path: Path) -> None:
    fixture = json.loads(FIXTURE.read_text("utf-8"))
    live = public(make(data, tmp_path, checker=fake_check), "QAS")
    stored = public(make(data, tmp_path, checker=_down), "LLZ")
    down = public(make(data, tmp_path, checker=_down), "ZZZ")
    zero = public(make(data, tmp_path, checker=_zero), "QAS")
    for name, r in (("live", live), ("stored", stored), ("down", down), ("zero", zero)):
        assert fixture[name]["status"] == r.status_code, name
        assert fixture[name]["body"] == r.json(), name


def test_stored_fallback_is_200_with_null_check_and_a_readable_snapshot(
    data: ConnectorData, tmp_path: Path
) -> None:
    body = public(make(data, tmp_path, checker=_down), "LLZ").json()
    assert body["check"] is None
    assert body["provenance"]["kind"] == "stored_demo_snapshot"
    assert isinstance(body["speakable"], str) and body["speakable"]
    assert body["facts"] and all(
        {"text", "link", "link_label"} <= set(f) and f["link"].startswith("https://api.fda.gov/")
        for f in body["facts"]
    )
    assert isinstance(body["provenance"]["note"], str) and isinstance(
        body["provenance"]["data_dates"], str
    )


def test_unknown_code_is_422_with_message_and_suggestions_in_the_error_envelope(
    tmp_path: Path,
) -> None:
    from tests.unit.test_connector_guidance import KNOWN, make_client

    small = ConnectorData(work_dir=tmp_path / "small")
    small._known_codes = frozenset(KNOWN)
    r = make_client(small, tmp_path, empty=True).get(
        "/v1/public/check_device_type", params={"product_code": "QAH"}
    )
    assert r.status_code == 422
    assert json.loads(FIXTURE.read_text("utf-8"))["unknown"] == {"status": 422, "body": r.json()}
