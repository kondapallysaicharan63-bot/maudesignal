"""Tests for the release-check and smoke-test scripts (scripts/release).

The scripts decide whether a release may be deployed, so their own logic is tested here:
the status and verdict rules, the comparison of quoted numbers, the key and prompt-leak
detectors, the load-test arithmetic, the HTTP helper (against a small local server) and the
test-key environment. Nothing here needs network access or a browser.
"""

from __future__ import annotations

import io
import json
import re
import sys
import threading
import wave
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest

RELEASE = Path(__file__).resolve().parents[2] / "scripts" / "release"
sys.path.insert(0, str(RELEASE))

import bundle_scan  # noqa: E402
import compare  # noqa: E402
import gate_adversarial  # noqa: E402
import leaks  # noqa: E402
import load_test  # noqa: E402
import media  # noqa: E402
import netutil  # noqa: E402
import report as rpt  # noqa: E402
import serve_api  # noqa: E402
import web_job  # noqa: E402

# --------------------------------------------------------------------------------------------
# report: statuses, verdict, exit code, markdown, merge
# --------------------------------------------------------------------------------------------


def make(*pairs: tuple[str, bool]) -> rpt.Report:
    r = rpt.Report("t")
    for status, required in pairs:
        r.add(f"c-{status}-{required}", status, "d", required=required)
    return r


def test_all_pass_is_pass() -> None:
    r = make((rpt.PASS, True), (rpt.PASS, True))
    assert r.verdict() == rpt.PASS and r.exit_code() == 0


def test_a_failure_is_fail() -> None:
    r = make((rpt.PASS, True), (rpt.FAIL, True))
    assert r.verdict() == rpt.FAIL and r.exit_code() == 1


def test_a_skipped_required_check_is_a_failure() -> None:
    assert make((rpt.PASS, True), (rpt.SKIPPED, True)).verdict() == rpt.FAIL


def test_a_skipped_optional_check_is_not() -> None:
    assert make((rpt.PASS, True), (rpt.SKIPPED, False)).verdict() == rpt.PASS


def test_not_present_fails_only_when_required() -> None:
    assert make((rpt.PASS, True), (rpt.NOT_PRESENT, True)).verdict() == rpt.FAIL
    assert make((rpt.PASS, True), (rpt.NOT_PRESENT, False)).verdict() == rpt.PASS


def test_blocked_is_never_pass_but_does_not_crash_the_job() -> None:
    r = make((rpt.PASS, True), (rpt.BLOCKED, True))
    assert r.verdict() == rpt.BLOCKED and r.exit_code() == 0


def test_fail_beats_blocked() -> None:
    assert make((rpt.BLOCKED, True), (rpt.FAIL, True)).verdict() == rpt.FAIL


def test_known_gap_is_reported_not_counted_as_pass() -> None:
    r = make((rpt.PASS, True), (rpt.KNOWN_GAP, False))
    assert r.counts()[rpt.PASS] == 1 and r.counts()[rpt.KNOWN_GAP] == 1


def test_an_empty_report_is_a_failure_not_a_pass() -> None:
    assert rpt.Report("t").verdict() == rpt.FAIL


def test_unknown_status_is_refused() -> None:
    with pytest.raises(ValueError):
        rpt.Report("t").add("x", "MAYBE")


def test_ok_records_the_detail_only_on_failure() -> None:
    r = rpt.Report("t")
    r.ok("a", True, "never shown")
    r.ok("b", False, "shown")
    assert [c.detail for c in r.checks] == ["", "shown"]


def test_markdown_lists_failures_first_and_every_check() -> None:
    r = rpt.Report("job")
    r.add("good", rpt.PASS, "fine", group="g")
    r.add("bad one", rpt.FAIL, "broke | here")
    r.metrics["n"] = 3
    md = r.to_markdown()
    assert "## job: FAIL" in md and "### Failures" in md
    assert "**FAIL** bad one" in md and "| PASS | g | good | fine |" in md
    assert "broke \\| here" in md  # a pipe cannot break the table
    assert "n: `3`" in md
    assert md.index("### Failures") < md.index("### All checks")


def test_write_creates_json_and_markdown(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    summary = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    r = rpt.Report("job")
    r.add("x", rpt.PASS)
    j, m = r.write(tmp_path / "out", "job")
    assert json.loads(j.read_text())["verdict"] == rpt.PASS
    assert m.read_text().startswith("## job: PASS")
    assert "## job: PASS" in summary.read_text()


def test_gap_only_report_is_info_never_pass_in_the_merged_markdown() -> None:
    note = rpt.Report("live model (not called)")
    note.add("live model", rpt.KNOWN_GAP, "checked after deploy by smoke.yml", required=False)
    real = rpt.Report("python")
    real.add("ruff", rpt.PASS)
    assert note.verdict() == rpt.INFO
    assert rpt.overall([note.verdict(), real.verdict()]) == rpt.PASS
    assert rpt.overall([note.verdict()]) == rpt.INFO
    assert note.exit_code() == 0
    doc = rpt.merge([note.to_dict(), real.to_dict()], "t")
    md = rpt.render_markdown([note.to_dict(), real.to_dict()])
    assert "| live model (not called) | INFO |" in md
    assert "live model" not in "".join(ln for ln in md.splitlines() if "| PASS |" in ln)
    assert doc["verdict"] == rpt.PASS


def test_merge_takes_the_worst_verdict_and_adds_counts() -> None:
    a = make((rpt.PASS, True)).to_dict()
    b = make((rpt.FAIL, True), (rpt.PASS, True)).to_dict()
    doc = rpt.merge([a, b])
    assert doc["verdict"] == rpt.FAIL
    assert doc["counts"][rpt.PASS] == 2 and doc["counts"][rpt.FAIL] == 1
    assert rpt.overall([rpt.PASS, rpt.BLOCKED]) == rpt.BLOCKED
    assert rpt.overall([]) == rpt.FAIL


def test_merge_cli_turns_a_missing_job_report_into_a_failure(tmp_path: Path) -> None:
    good = tmp_path / "python-job.json"
    good.write_text(json.dumps(make((rpt.PASS, True)).to_dict()))
    out_j, out_m = tmp_path / "all.json", tmp_path / "all.md"
    code = rpt.main(
        [
            "merge",
            str(good),
            str(tmp_path / "web-job.json"),
            "--json",
            str(out_j),
            "--md",
            str(out_m),
        ]
    )
    assert code == 1
    doc = json.loads(out_j.read_text())
    assert doc["verdict"] == rpt.FAIL and len(doc["jobs"]) == 2
    assert "web-job.json was not produced" in out_m.read_text()
    assert "| t | PASS |" in out_m.read_text()


# --------------------------------------------------------------------------------------------
# compare: quoted numbers, reviews, pytest / npm / axe parsing
# --------------------------------------------------------------------------------------------

GOOD_QUOTED = """gate first pass:  63/65 sentences (28 answers)
hand-check:       27/28 answers fully correct; 64/65 sentences correct
LLZ on openFDA:   19,970 reports, 19,823 filed by a manufacturer (99.3%)
AI sweep:         6 of 181 flagged
"""


def test_quoted_numbers_unchanged_is_no_diff() -> None:
    assert compare.compare_quoted_numbers(GOOD_QUOTED) == []


def test_a_changed_quoted_number_is_reported_with_the_line() -> None:
    diffs = compare.compare_quoted_numbers(GOOD_QUOTED.replace("63/65", "64/65"))
    assert len(diffs) == 1 and "line 1" in diffs[0] and "64/65" in diffs[0]


def test_a_missing_or_extra_quoted_line_is_reported() -> None:
    assert compare.compare_quoted_numbers("\n".join(GOOD_QUOTED.splitlines()[:3]))
    assert compare.compare_quoted_numbers(GOOD_QUOTED + "extra line\n")


def test_the_real_quoted_numbers_script_matches_the_expected_lines() -> None:
    """The lines this file expects are the ones the submission script prints today."""
    import subprocess

    root = RELEASE.parents[1]
    p = subprocess.run(
        [sys.executable, "scripts/print_quoted_numbers.py"],
        cwd=root,
        env={"PYTHONPATH": "src", "PATH": "/usr/bin:/bin"},
        capture_output=True,
        text=True,
        check=False,
    )
    assert p.returncode == 0, p.stderr[-300:]
    assert compare.compare_quoted_numbers(p.stdout) == []


def test_review_findings_counts_and_flags_unreadable(tmp_path: Path) -> None:
    (tmp_path / "A-review.json").write_text(json.dumps({"findings": []}))
    (tmp_path / "B-review.json").write_text(json.dumps({"findings": [{"x": 1}]}))
    (tmp_path / "C-review.json").write_text("not json")
    (tmp_path / "D-review.json").write_text(json.dumps({"findings": "no"}))
    assert compare.review_findings(tmp_path) == {
        "A-review.json": 0,
        "B-review.json": 1,
        "C-review.json": None,
        "D-review.json": None,
    }


def test_the_real_review_files_have_no_findings() -> None:
    found = compare.review_findings(RELEASE.parents[1] / "demo" / "dossier")
    assert found and all(v == 0 for v in found.values()), found


def test_llz_snapshot_comparison() -> None:
    stored = {
        "provenance": {"kind": "stored_demo_snapshot"},
        "speakable": "33 reports against a weekly average of 8.75",
        "facts": [],
    }
    assert compare.llz_snapshot_diffs(stored) == []
    changed = {**stored, "speakable": "34 reports against a weekly average of 8.75"}
    assert compare.llz_snapshot_diffs(changed) == ["33 reports"]
    live = {**stored, "provenance": {"kind": "live_openfda"}}
    assert compare.llz_snapshot_diffs(live) is None  # live numbers move: no comparison


def test_parse_pytest_summary_and_coverage() -> None:
    out = "....\nTOTAL   9000   1900   78%\n=== 1147 passed, 3 skipped, 1 warning in 41.2s ===\n"
    assert compare.parse_pytest_summary(out) == {"passed": 1147, "skipped": 3}
    assert compare.parse_coverage_total(out) == 78.0
    assert compare.parse_pytest_summary("=== 2 failed, 5 passed in 1s ===") == {
        "failed": 2,
        "passed": 5,
    }
    assert compare.parse_coverage_total("no table") is None


def test_parse_npm_audit_and_blocking() -> None:
    raw = json.dumps(
        {"metadata": {"vulnerabilities": {"low": 2, "high": 1, "critical": 0, "total": 3}}}
    )
    counts = compare.parse_npm_audit(raw)
    assert counts["high"] == 1 and compare.audit_blocks(counts) == 1
    assert compare.audit_blocks({"low": 5, "moderate": 2}) == 0
    with pytest.raises(ValueError):
        compare.parse_npm_audit(json.dumps({"error": "offline"}))


def test_axe_counts_and_blocking() -> None:
    results = {
        "violations": [
            {"impact": "minor"},
            {"impact": "serious"},
            {"impact": None},
            {"impact": "odd"},
        ]
    }
    counts = compare.count_axe(results)
    assert counts == {"minor": 1, "moderate": 0, "serious": 1, "critical": 0, "unknown": 2}
    assert compare.axe_blocks(counts) == 1 and compare.axe_blocks({"minor": 9}) == 0


def test_vitest_numbers() -> None:
    out = " Test Files  12 passed (12)\n      Tests  57 passed (57)\n"
    assert web_job.vitest_numbers(out) == {
        "files_passed": 12,
        "files_failed": 0,
        "tests_passed": 57,
        "tests_failed": 0,
    }
    failed = " Test Files  1 failed | 11 passed (12)\n      Tests  2 failed | 55 passed (57)\n"
    assert web_job.vitest_numbers(failed)["tests_failed"] == 2


# --------------------------------------------------------------------------------------------
# leaks: key shapes and copied prompt text; bundle scan
# --------------------------------------------------------------------------------------------


def test_key_shapes_are_found_and_never_returned() -> None:
    fake = "sk-ant-" + "a1" * 20
    found = leaks.find_key_shapes(f"here is {fake} ok")
    assert "Anthropic key" in found and fake not in " ".join(found)
    assert leaks.find_key_shapes("gsk_" + "A" * 44) == ["Groq key"]
    assert leaks.find_key_shapes('{"META_MODEL_API_KEY": "abcd1234efgh5678"}') == [
        "Named key with a value"
    ]
    assert leaks.find_key_shapes("Authorization: Bearer " + "x" * 30) == ["Bearer token"]


def test_a_key_name_without_a_value_or_plain_text_is_not_a_hit() -> None:
    assert leaks.find_key_shapes("Set META_MODEL_API_KEY in the project settings.") == []
    assert leaks.find_key_shapes("What changed this week for LLZ?") == []
    assert leaks.find_key_shapes("sha256 hash 9f86d081884c7d659a2feaa0c55ad015") == []


def test_contains_any_ignores_short_values() -> None:
    assert leaks.contains_any("abc secret-value-123 xyz", ["secret-value-123", "abc"]) == [0]


def test_copied_prompt_text_is_found_even_when_reflowed(tmp_path: Path) -> None:
    prompt = tmp_path / "SKILL.md"
    prompt.write_text(
        "You answer only from stored MAUDE records and you never invent a number or a link.\n"
        "Every sentence must carry a claim the gate can check against openFDA data.\n"
    )
    windows = leaks.prompt_windows([prompt])
    assert windows
    copied = (
        "Sure: you answer only from stored MAUDE records and you never\ninvent a number or a link."
    )
    assert leaks.copied_prompt_text(copied, windows) >= 1
    assert leaks.copied_prompt_text("I have no verified answer to that question.", windows) == 0
    assert leaks.copied_prompt_text("anything", set()) == 0
    assert leaks.prompt_windows([tmp_path / "missing.md"]) == set()


def test_bundle_scan_finds_a_key_without_printing_it(tmp_path: Path) -> None:
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "assets" / "a.js").write_text("const a=1;\nconst k='gsk_" + "Z" * 44 + "';\n")
    (dist / "assets" / "b.js").write_text("const clean = 'hello';")
    (dist / "logo.png").write_bytes(b"\x89PNG not scanned")
    files, hits = bundle_scan.scan_dir(dist)
    assert files == 2
    assert hits == [("assets/a.js", "Groq key", 2)]
    assert "ZZZZ" not in json.dumps(hits)


def test_bundle_scan_main_fails_on_a_hit_and_on_a_missing_folder(tmp_path: Path) -> None:
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "a.js").write_text("ok")
    assert bundle_scan.main([str(dist), "--out-dir", str(tmp_path / "o1")]) == 0
    (dist / "b.js").write_text("x='AIza" + "B" * 35 + "'")
    assert bundle_scan.main([str(dist), "--out-dir", str(tmp_path / "o2")]) == 1
    assert bundle_scan.main([str(tmp_path / "nope"), "--out-dir", str(tmp_path / "o3")]) == 1
    empty = tmp_path / "empty"
    empty.mkdir()
    assert bundle_scan.main([str(empty), "--out-dir", str(tmp_path / "o4")]) == 1  # nothing read


# --------------------------------------------------------------------------------------------
# gate adversarial arithmetic and the real set
# --------------------------------------------------------------------------------------------


def test_confusion_counts_false_passes_and_false_blocks() -> None:
    cases = [{"expect": "block"}, {"expect": "block"}, {"expect": "pass"}, {"expect": "pass"}]
    out = gate_adversarial.confusion(cases, ["pass", "block", "block", "pass"])
    assert out == {"cases": 4, "must_block": 2, "must_pass": 2, "false_pass": 1, "false_block": 1}
    with pytest.raises(ValueError):
        gate_adversarial.confusion(cases, ["pass"])


def test_the_real_adversarial_set_has_no_false_pass_or_false_block() -> None:
    cases, statuses = gate_adversarial.run_gate()
    out = gate_adversarial.confusion(cases, statuses)
    assert out["cases"] >= 50
    assert (out["false_pass"], out["false_block"]) == (0, 0)


# --------------------------------------------------------------------------------------------
# netutil against a local server
# --------------------------------------------------------------------------------------------


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *a: Any) -> None:
        pass

    def _send(self, status: int, body: bytes, headers: dict[str, str] | None = None) -> None:
        self.send_response(status)
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/json":
            self._send(200, b'{"error": {"code": "rate_limited", "message": "m"}}', {"X-A": "b"})
        elif self.path == "/flat":
            self._send(429, b'{"code": "too_large", "message": "m"}', {"Retry-After": "7"})
        else:
            self._send(404, b"not json")

    def do_POST(self) -> None:  # noqa: N802
        n = int(self.headers.get("Content-Length", "0"))
        if n > 1000:  # refuse early, without reading the body
            self._send(413, b'{"code": "too_large"}')
            self.close_connection = True
            return
        data = self.rfile.read(n)
        self._send(
            200, json.dumps({"len": len(data), "ct": self.headers.get("Content-Type")}).encode()
        )


@pytest.fixture
def server() -> Any:
    srv = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


def test_request_returns_status_headers_and_json(server: str) -> None:
    r = netutil.request("GET", server + "/json")
    assert r.status == 200 and r.headers["x-a"] == "b" and r.error_code() == "rate_limited"
    flat = netutil.request("GET", server + "/flat")
    assert (
        flat.status == 429
        and flat.headers["retry-after"] == "7"
        and flat.error_code() == "too_large"
    )
    bad = netutil.request("GET", server + "/other")
    assert bad.status == 404 and bad.json() is None and bad.error_code() == ""


def test_request_posts_json(server: str) -> None:
    r = netutil.request("POST", server + "/x", json_body={"a": 1})
    assert r.status == 200 and r.json()["ct"] == "application/json"


def test_request_reads_an_early_refusal_of_a_big_upload(server: str) -> None:
    r = netutil.request("POST", server + "/x", body=b"z" * 3_000_000)
    assert r.status == 413


def test_request_reports_no_answer_as_status_zero() -> None:
    r = netutil.request("GET", "http://127.0.0.1:1/", timeout=2)
    assert r.status == 0 and r.error


def test_multipart_has_the_parts() -> None:
    body, ctype = netutil.multipart({"image": ("a.jpg", b"JPEGDATA", "image/jpeg")})
    boundary = ctype.split("boundary=")[1]
    assert body.startswith(f"--{boundary}".encode()) and b'name="image"' in body
    assert b"JPEGDATA" in body and body.endswith(f"--{boundary}--\r\n".encode())


def test_percentile_nearest_rank() -> None:
    vals = [float(x) for x in range(1, 101)]
    assert netutil.percentile(vals, 50) == 50.0 and netutil.percentile(vals, 95) == 95.0
    assert netutil.percentile([], 95) == 0.0 and netutil.percentile([7.0], 95) == 7.0


# --------------------------------------------------------------------------------------------
# load test arithmetic and limits
# --------------------------------------------------------------------------------------------


def test_summarize_separates_errors_from_rate_limits() -> None:
    samples = [
        ("health", 200, 10, 0.0, None),
        ("health", 200, 30, 0.0, None),
        ("public_check", 429, 5, 0.0, None),
        ("public_check", 502, 50, 0.0, None),
        ("live_ask", 200, 900, 0.04, 17),
        ("live_ask", 0, 0, 0.0, None),
    ]
    s = load_test.summarize(samples)
    assert s["calls"] == 6 and s["errors"] == 2 and s["error_rate"] == round(2 / 6, 4)
    assert s["limited_429"] == 1 and s["live_asks"] == 2 and s["live_cost_usd"] == 0.04
    assert s["last_remaining_today"] == 17
    assert s["kinds"]["health"]["p50_ms"] == 10 and s["kinds"]["health"]["p95_ms"] == 30
    assert s["kinds"]["public_check"]["limited_429"] == 1


def test_summarize_of_nothing_is_a_total_failure() -> None:
    assert load_test.summarize([])["error_rate"] == 1.0


def test_run_load_caps_live_asks_and_stops_on_time() -> None:
    clock = {"t": 0.0}
    lock = threading.Lock()

    def now() -> float:
        return clock["t"]

    def sleep(seconds: float) -> None:
        with lock:
            clock["t"] += seconds

    live_calls: list[str] = []

    def send(method: str, url: str, **kw: Any) -> netutil.Response:
        if url.endswith("/v1/live/ask"):
            live_calls.append(url)
            body = json.dumps({"cost_usd": 0.05, "limits": {"remaining_today": 9}}).encode()
            return netutil.Response(200, {}, body, 100)
        return netutil.Response(200, {}, b"{}", 5)

    samples = load_test.run_load(
        "http://x",
        vus=1,
        seconds=100,
        max_live_asks=3,
        think_s=1.0,
        send=send,
        clock=now,
        sleep=sleep,
    )
    assert len(live_calls) == 3  # never more than the cap, however long the run
    assert len(samples) > 50
    stats = load_test.summarize(samples)
    assert stats["live_asks"] == 3 and stats["live_cost_usd"] == pytest.approx(0.15)


def test_evaluate_fails_on_errors_and_on_cost() -> None:
    stats = load_test.summarize(
        [("health", 500, 5, 0.0, None)] * 4 + [("health", 200, 5, 0.0, None)]
    )
    rep = rpt.Report("l")
    load_test.evaluate(rep, stats, 0.02, 1.0, 10)
    failed = [c.name for c in rep.failures()]
    assert any("error rate" in n for n in failed)
    stats2 = load_test.summarize([("live_ask", 200, 5, 2.0, None)])
    rep2 = rpt.Report("l")
    load_test.evaluate(rep2, stats2, 0.5, 1.0, 10)
    assert any("live cost" in c.name for c in rep2.failures())


# --------------------------------------------------------------------------------------------
# serve_api: test keys and the environment for the local API
# --------------------------------------------------------------------------------------------


def test_made_keys_are_long_distinct_and_random() -> None:
    a, b = serve_api.make_keys(), serve_api.make_keys()
    assert len({*a.values(), *b.values()}) == 8
    assert all(len(v) >= 32 for v in a.values())  # the API refuses keys shorter than 32


def test_env_holds_the_keys_the_origin_and_no_meta_key(tmp_path: Path) -> None:
    keys = serve_api.make_keys()
    env = serve_api.build_env(keys, "contract", ["http://127.0.0.1:4173"], str(tmp_path))
    assert (
        keys["key"] in env["MAUDESIGNAL_API_KEYS"] and keys["key2"] in env["MAUDESIGNAL_API_KEYS"]
    )
    assert env["MAUDESIGNAL_DEMO_KEYS"].endswith(keys["demo"])
    assert env["MAUDESIGNAL_WEB_ORIGINS"] == "http://127.0.0.1:4173"
    assert env["MAUDESIGNAL_TRUST_FORWARDED"] == "1"
    assert not any("META" in k or "OPENFDA" in k for k in env)
    assert int(env["MAUDESIGNAL_RATE_LIMIT_PER_MIN"]) >= 100
    e2e = serve_api.build_env(keys, "e2e", ["http://127.0.0.1:4173"], str(tmp_path))
    assert int(e2e["MAUDESIGNAL_LIVE_PER_MIN"]) >= 1000


def test_prepare_writes_private_files_and_masks_in_actions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    kf, ef = tmp_path / "keys.json", tmp_path / "api.env"
    assert (
        serve_api.main(
            ["prepare", "--profile", "contract", "--keys-file", str(kf), "--env-file", str(ef)]
        )
        == 0
    )
    keys = json.loads(kf.read_text())
    out = capsys.readouterr().out
    assert out.count("::add-mask::") == 5  # four keys and the pepper
    assert all(v in out for v in keys.values())  # masked lines only; no other line prints them
    printed_plain = [ln for ln in out.splitlines() if not ln.startswith("::add-mask::")]
    assert not any(v in ln for ln in printed_plain for v in keys.values())
    assert (kf.stat().st_mode & 0o777) == 0o600 and (ef.stat().st_mode & 0o777) == 0o600
    assert "export MAUDESIGNAL_API_KEYS=" in ef.read_text()


# --------------------------------------------------------------------------------------------
# media
# --------------------------------------------------------------------------------------------


def _wav(rate: int, channels: int = 1, seconds: float = 0.5, width: int = 2) -> bytes:
    buf = io.BytesIO()
    n = int(rate * seconds)
    with wave.open(buf, "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(width)
        w.setframerate(rate)
        frame = (b"\x10\x00" * channels) if width == 2 else (b"\x90" * channels)
        w.writeframes(frame * n)
    return buf.getvalue()


def test_resample_to_16k_mono_keeps_the_length() -> None:
    for rate, channels, width in ((44100, 1, 2), (48000, 2, 2), (8000, 1, 1)):
        out = media.to_16k_mono_pcm16(_wav(rate, channels, 0.5, width))
        info = media.wav_info(out)
        assert info["rate"] == 16000 and info["channels"] == 1 and info["width"] == 2
        assert info["seconds"] == pytest.approx(0.5, abs=0.01)


def test_a_wav_already_in_the_right_format_is_returned_unchanged() -> None:
    wav = _wav(16000)
    assert media.to_16k_mono_pcm16(wav) == wav


def test_the_real_voice_samples_convert() -> None:
    root = RELEASE.parents[1]
    voice = media.load_voice(root, ("question-a.wav", "question.wav", "question-c.wav"))
    assert voice is not None
    assert media.wav_info(voice[1])["rate"] == 16000
    assert media.load_voice(root, ("does-not-exist.wav",)) is None


# --------------------------------------------------------------------------------------------
# the workflows name real scripts and real secrets
# --------------------------------------------------------------------------------------------

WORKFLOWS = Path(__file__).resolve().parents[2] / ".github" / "workflows"


@pytest.mark.parametrize("name", ["release-check.yml", "smoke.yml"])
def test_workflow_scripts_exist(name: str) -> None:
    text = (WORKFLOWS / name).read_text()
    for script in set(re.findall(r"scripts/release/([A-Za-z0-9_]+\.py)", text)):
        assert (RELEASE / script).is_file(), f"{name} calls scripts/release/{script}"


def test_workflow_triggers_and_secret_rules() -> None:
    import yaml

    rc = yaml.safe_load((WORKFLOWS / "release-check.yml").read_text())
    triggers = rc.get("on") or rc.get(True)
    assert triggers["push"]["branches"] == ["release/**"] and "workflow_dispatch" in triggers
    sm = yaml.safe_load((WORKFLOWS / "smoke.yml").read_text())
    st = sm.get("on") or sm.get(True)
    assert st["push"]["branches"] == ["smoke/**"] and "workflow_dispatch" in st
    jobs = rc["jobs"]
    # the release check has no live job and no secret at all: it spends $0
    assert "live" not in jobs and "gate-live" not in jobs
    text = (WORKFLOWS / "release-check.yml").read_text()
    assert "META_MODEL_API_KEY" not in text and "secrets." not in text
    assert "live_check" not in text and "release-live" not in text
    assert set(jobs["report"]["needs"]) == {"python", "web", "api-contract", "e2e"}


def test_report_job_adds_the_informational_live_model_line() -> None:
    import yaml

    rc = yaml.safe_load((WORKFLOWS / "release-check.yml").read_text())
    merge = json.dumps(rc["jobs"]["report"])
    assert "checked after deploy by smoke.yml" in merge and "KNOWN_GAP" in merge
    assert "required=False" in merge and "live-model-note.json" in merge
    assert "needs.live" not in merge


# --------------------------------------------------------------------------------------------
# TEST refs, the shared spend budget, delete-test effect, pinned installs
# --------------------------------------------------------------------------------------------

# A copy of the server's rule (src/maudesignal/connector/feedback.py on track-c-live).
SERVER_TEST_CODE = re.compile(r"^test[0-9._~-]*$", re.IGNORECASE)


def test_test_refs_match_the_server_rule() -> None:
    import api_contract
    import e2e_web
    import smoke

    assert SERVER_TEST_CODE.fullmatch("TEST-0") and SERVER_TEST_CODE.fullmatch("TEST-1")
    assert not SERVER_TEST_CODE.fullmatch("TEST-smoke")  # the old refs were not TEST codes
    assert not SERVER_TEST_CODE.fullmatch("TEST-release")
    assert smoke.TEST_REF == e2e_web.TEST_REF == "TEST-0"
    assert api_contract.TEST_REF == "TEST-1"
    assert not SERVER_TEST_CODE.fullmatch(api_contract.KEEP_REF)  # the survivor is not a TEST code


def test_visits_all_test_uses_the_matching_ref() -> None:
    import e2e_web

    ok, _ = e2e_web.visits_all_test([json.dumps({"ref": "TEST-0", "page": "x"})])
    assert ok
    bad, _ = e2e_web.visits_all_test([json.dumps({"ref": "TEST-smoke"})])
    assert not bad


def test_budget_holds_counts_and_dollars() -> None:
    import budget

    b = budget.Budget(max_usd=1.0)
    assert b.reserve("voice") and not b.reserve("voice")  # one voice question per run
    assert b.refused == ["voice"]
    b.settle("voice", 0.10)
    assert b.reserve("photo") and b.reserve("photo") and not b.reserve("photo")  # 2 photos
    b.settle("photo", 0.14)
    b.settle("photo", 0.14)
    # spent 0.38; an ask holds 0.25 -> 0.63 fits; once settled at 0.25 a second ask would
    # reach 0.88 + hold 0.25 > 1.0 and is refused
    assert b.reserve("ask")
    b.settle("ask", 0.25)
    assert b.reserve("ask")
    b.settle("ask", 0.25)
    assert not b.reserve("ask")
    assert b.snapshot()["spent_usd"] == pytest.approx(0.88)


def test_budget_holds_are_the_deployed_caps() -> None:
    # copied from connector/globalcap.py on track-c-live (DEFAULT_ASK/VOICE/LABEL_USD); the smoke
    # run talks to the deployment
    import budget

    assert budget.HOLD_USD == {"ask": 0.25, "voice": 0.30, "photo": 0.30}


def test_budget_counts_holds_of_calls_in_flight() -> None:
    import budget

    b = budget.Budget(max_usd=0.60)
    taken = sum(1 for _ in range(10) if b.reserve("ask"))  # nothing settled yet: holds add up
    assert taken == 2  # 2 x 0.25 = 0.50; a third hold would pass 0.60
    assert b.remaining_usd() == pytest.approx(0.10)


def test_budget_settles_a_call_without_a_cost_at_its_full_hold() -> None:
    import budget

    b = budget.Budget()
    assert b.reserve("ask") and b.reserve("photo")
    b.settle("ask", None)  # timeout / non-200 / no cost_usd: the server may have spent the cap
    b.settle("photo", 0.01)
    assert b.spent == pytest.approx(0.25 + 0.01)
    assert b.held == pytest.approx(0.0)


def test_budget_absorb_adds_browser_calls() -> None:
    import budget

    b = budget.Budget()
    b.absorb(0.2, {"ask": 2, "photo": 1})
    assert b.remaining_counts() == {"ask": 8, "photo": 1, "voice": 1}
    assert b.spent == pytest.approx(0.2)


def test_budget_ceiling_is_sixty_cents() -> None:
    import budget

    assert budget.MAX_USD == pytest.approx(0.60)


def test_the_full_smoke_plan_fits_the_budget_with_every_call_at_its_full_hold() -> None:
    import budget

    b = budget.Budget()
    for part in ("direct", "web"):
        for kind in budget.SMOKE_PLAN[part]:
            assert b.reserve(kind), f"{part} {kind} refused: {b.snapshot()}"
            b.settle(kind, None)  # worst case: no cost came back for any call
    assert b.refused == []
    assert b.spent == pytest.approx(0.55) and b.spent <= b.max_usd
    # what is left cannot carry another live ask, so the load test uses public checks only
    assert b.max_asks_by_dollars() == 0
    assert budget.SMOKE_PLAN["web"] == ()


def test_a_photo_does_not_fit_beside_the_planned_calls() -> None:
    import budget

    b = budget.Budget()
    assert b.reserve("ask") and b.reserve("voice")
    assert not b.reserve("photo") and b.refused == ["photo"]


def test_mocked_live_bodies_are_recorded_mode_with_no_cost() -> None:
    import e2e_web

    for kind in ("ask", "photo", "voice"):
        body = e2e_web.recorded_body(kind)
        assert body["mode"] == "recorded" and body["cost_usd"] is None
        assert body["recorded_note"]
    cands = e2e_web.recorded_body("photo")["matches"]["candidates"]
    assert len(cands) == 1


def test_standalone_load_test_defaults_to_no_live_asks() -> None:
    import load_test

    src = Path(load_test.__file__).read_text("utf-8")
    assert '"--max-live-asks", type=int, default=0' in src
    assert "Budget(max_usd=MAX_USD)" in src


def test_web_pass_ledger_is_absorbed_with_unanswered_calls_at_full_hold() -> None:
    import budget

    web = budget.Budget(max_usd=1.0, limits={"ask": 5, "photo": 1, "voice": 0})
    assert web.reserve("ask") and web.reserve("ask")
    web.settle("ask", 0.01)  # answered
    web.settle("ask", None)  # reserved, never answered before the page closed
    snap = web.snapshot()
    parent = budget.Budget()
    parent.absorb(float(snap["spent_usd"]) + float(snap["held_usd"]), snap["used"])  # type: ignore[arg-type]
    assert parent.used["ask"] == 2
    assert parent.spent == pytest.approx(0.26)


def test_live_kind_covers_live_and_older_paths() -> None:
    import e2e_web

    assert e2e_web.live_kind("https://a/v1/live/ask") == "ask"
    assert e2e_web.live_kind("https://a/v1/live/label?x=1") == "photo"
    assert e2e_web.live_kind("https://a/v1/live/voice") == "voice"
    assert e2e_web.live_kind("https://a/v1/label") == "photo"
    assert e2e_web.live_kind("https://a/v1/voice") == "voice"
    assert e2e_web.live_kind("https://a/v1/health") == ""


def test_check_device_known_gap_only_for_upstream_down_statuses() -> None:
    import e2e_web

    assert e2e_web.UPSTREAM_DOWN == {0, 502, 503, 504}
    for status in (401, 404, 500):
        assert status not in e2e_web.UPSTREAM_DOWN


def test_api_contract_runs_only_against_a_local_api() -> None:
    import api_contract

    assert api_contract.is_local_base("http://127.0.0.1:8000")
    assert api_contract.is_local_base("http://localhost:8002")
    for bad in (
        "https://maudesignal-api.vercel.app",
        "http://127.0.0.1.evil.example",
        "http://example.com/127.0.0.1",
        "ftp://127.0.0.1",
    ):
        assert not api_contract.is_local_base(bad)
    assert (
        api_contract.main(["--base", "https://maudesignal-api.vercel.app", "--keys-file", "x"]) == 2
    )


def test_smoke_finish_writes_the_total_cost_check_without_a_load_test() -> None:
    import smoke

    rep = rpt.Report("t")
    s = smoke.Smoke("https://a", "", rep, [])
    s.budget.reserve("ask")
    s.budget.settle("ask", None)
    s.finish()
    line = next(c for c in rep.checks if c.name.startswith("total live cost"))
    assert line.status == rpt.PASS and "$0.2500" in line.detail
    assert rep.metrics["budget"]["spent_usd"] == pytest.approx(0.25)  # type: ignore[index]


def test_smoke_note_live_keeps_the_hold_when_the_answer_has_no_cost(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import smoke

    rep = rpt.Report("t")
    s = smoke.Smoke("https://a", "", rep, [], budget=smoke.Budget())
    assert s.budget.reserve("ask")
    s.note_live("x", netutil.Response(504, {}, b"", 90_000), "ask")  # timeout / error
    assert s.budget.spent == pytest.approx(0.25)
    assert s.budget.reserve("ask")
    s.note_live("y", netutil.Response(200, {}, b'{"cost_usd": 0.02}', 5), "ask")
    assert s.budget.spent == pytest.approx(0.27)


def test_run_load_uses_public_checks_when_the_budget_is_short() -> None:
    import budget

    clock = {"t": 0.0}

    def sleep(seconds: float) -> None:
        clock["t"] += seconds

    asks: list[str] = []
    publics: list[str] = []

    def send(method: str, url: str, **kw: Any) -> netutil.Response:
        if url.endswith("/v1/live/ask"):
            asks.append(url)
            return netutil.Response(200, {}, json.dumps({"cost_usd": 0.25}).encode(), 50)
        if "check_device_type" in url:
            publics.append(url)
        return netutil.Response(200, {}, b"{}", 5)

    b = budget.Budget(max_usd=0.60)
    load_test.run_load(
        "http://x",
        vus=1,
        seconds=200,
        max_live_asks=10,
        think_s=1.0,
        send=send,
        clock=lambda: clock["t"],
        sleep=sleep,
        budget=b,
    )
    # each ask really cost 0.25: two fit; a third (0.50 + a 0.25 hold = 0.75) is refused
    assert len(asks) == 2
    assert b.refused  # recorded, so the smoke run can write 'skipped: budget'
    assert len(publics) > 20


def test_smoke_delete_test_checks_counts_and_summary(monkeypatch: pytest.MonkeyPatch) -> None:
    import smoke

    def run(deleted: dict[str, int], codes: list[dict[str, Any]]) -> rpt.Report:
        def fake(method: str, url: str, **kw: Any) -> netutil.Response:
            if url.endswith("/v1/admin/delete-test"):
                return netutil.Response(200, {}, json.dumps({"deleted": deleted}).encode(), 1)
            if url.endswith("/v1/admin/summary"):
                return netutil.Response(200, {}, json.dumps({"codes": codes}).encode(), 1)
            return netutil.Response(201 if url.endswith("/v1/feedback") else 204, {}, b"", 1)

        monkeypatch.setattr(smoke, "request", fake)
        rep = rpt.Report("t")
        smoke.Smoke("https://a", "", rep, []).test_entries("adminkey")
        return rep

    assert run({"visits": 1, "feedback": 1}, [{"code": "someone-7"}]).exit_code() == 0
    assert run({"visits": 0, "feedback": 1}, []).exit_code() != 0
    assert run({"visits": 1, "feedback": 1}, [{"code": "TEST-0"}]).exit_code() != 0


def test_smoke_live_records_a_fail_line_when_the_budget_is_short(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import budget
    import smoke

    calls: list[str] = []

    def fake(method: str, url: str, **kw: Any) -> netutil.Response:
        calls.append(url)
        return netutil.Response(200, {}, b"{}", 1)

    monkeypatch.setattr(smoke, "request", fake)
    rep = rpt.Report("t")
    smoke.Smoke("https://a", "", rep, [], budget.Budget(max_usd=0.05)).live()
    assert calls == []  # not even one call fits
    lines = [c for c in rep.checks if c.detail == "skipped: budget"]
    assert len(lines) == 3 and all(c.status == rpt.FAIL for c in lines)


def test_smoke_and_release_install_the_same_pinned_playwright_and_pillow() -> None:
    def pins(name: str) -> set[str]:
        text = (WORKFLOWS / name).read_text()
        return set(re.findall(r"(playwright==[0-9.]+|pillow==[0-9.]+)", text))

    smoke_pins = pins("smoke.yml")
    assert len(smoke_pins) == 2, smoke_pins
    assert smoke_pins == pins("release-check.yml")


def test_workflows_pin_uvicorn_and_do_not_upgrade_pip() -> None:
    for name in ("release-check.yml", "smoke.yml"):
        text = (WORKFLOWS / name).read_text()
        assert "--upgrade pip" not in text
        assert "uvicorn>=" not in text
    assert "uvicorn==" in (WORKFLOWS / "release-check.yml").read_text()


def test_smoke_default_budget_allows_one_live_ask() -> None:
    import smoke

    s = smoke.Smoke("https://a", "", rpt.Report("t"), [])
    assert s.budget.reserve("ask")
    assert not s.budget.reserve("ask")


def test_smoke_default_budget_allows_one_ask_one_voice_and_no_photo() -> None:
    import smoke

    s = smoke.Smoke("https://a", "", rpt.Report("t"), [])
    assert s.budget.limits == {"ask": 1, "photo": 0, "voice": 1}
    assert s.budget.reserve("ask") and not s.budget.reserve("ask")
    assert s.budget.reserve("voice") and not s.budget.reserve("voice")
    assert not s.budget.reserve("photo")


def test_vitest_numbers_strips_ansi_colour() -> None:
    out = (
        " \x1b[2m Test Files \x1b[22m \x1b[1m\x1b[32m12 passed\x1b[39m (12)\n"
        " \x1b[2m Tests \x1b[22m \x1b[31m2 failed\x1b[39m | \x1b[32m55 passed\x1b[39m (57)\n"
    )
    nums = web_job.vitest_numbers(out)
    assert nums["files_passed"] == 12 and nums["tests_passed"] == 55
    assert nums["tests_failed"] == 2
    assert web_job.vitest_numbers("no summary here") == {}
    assert web_job.NO_COLOUR == {"NO_COLOR": "1", "FORCE_COLOR": "0"}


def test_api_contract_sample_args_are_valid() -> None:
    import api_contract

    schema = {"properties": {"device_name": {}, "manufacturer": {}, "k_number": {}}}
    lookup = api_contract.Contract.sample_args("lookup_device", schema)
    assert lookup == {"device_name": "Welch Allyn 802 LTR", "manufacturer": "Welch Allyn"}
    assert api_contract.Contract.sample_args("x", {"properties": {"k_number": {}}}) == {
        "k_number": "K123456"
    }
    assert re.fullmatch(r"K\d{6}", api_contract.SAMPLE_VALUES["k_number"])
    ok = api_contract.Contract.lookup_result_ok
    for status in ("needs_person_to_confirm", "no_match_found", "search_failed"):
        assert ok({"isError": False, "structuredContent": {"status": status}})
    assert not ok({"isError": True, "structuredContent": {"status": "no_match_found"}})
    assert not ok({"isError": False, "structuredContent": {}})
    assert not ok({})
