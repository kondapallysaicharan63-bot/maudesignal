"""Post-deploy smoke test of the live API and web app.

HACKATHON-BUILT — Meta Global AI Developer Hackathon (Oct 26 – Nov 4, 2026).

Runs against the deployed URLs (never prints a key):

    MAUDESIGNAL_SMOKE_KEYS=key1,key2 MAUDESIGNAL_ADMIN_KEY_SMOKE=... \
    python3 scripts/release/smoke.py --api https://maudesignal-api.vercel.app \
        --web https://<web-preview-url> --out-dir release-out

Groups: service pages, connect (a demo key is handed out), authentication (no key is 401),
keyed tool calls (the demo key from /v1/connect always; the keys in MAUDESIGNAL_SMOKE_KEYS
when given, otherwise BLOCKED: "keys not provided", never PASS), the figures the API shares
with the submission, one live chat question and one spoken question on /v1/live/* (the browser pass is mocked)
(mode and cost_usd of each are logged), a TEST visit and TEST feedback entry (deleted when
MAUDESIGNAL_ADMIN_KEY_SMOKE is set, otherwise left and reported so a person can delete them),
the web app (page loads, bundle file names and hash, a Playwright quick pass at 1440 and 390),
and a light load test.

``--no-web`` and ``--no-load`` skip those parts; a skipped part is listed as SKIPPED, which
counts as a failure unless the flag was given on purpose (then it is reported, not failed).
"""

# ruff: noqa: E501
from __future__ import annotations

import argparse
import hashlib
import os
import re
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))

from budget import HOLD_USD, LIMITS, SKIPPED_BUDGET, SMOKE_LIMITS, Budget  # noqa: E402
from compare import llz_snapshot_diffs  # noqa: E402
from leaks import contains_any, find_key_shapes  # noqa: E402
from load_test import evaluate, run_load, summarize  # noqa: E402
from media import load_voice  # noqa: E402
from netutil import Response, multipart, request  # noqa: E402
from report import BLOCKED, FAIL, KNOWN_GAP, PASS, SKIPPED, Report  # noqa: E402

VOICE_FILES = ("question-a.wav", "question.wav", "question-c.wav")
LABEL_PHOTO = ROOT / "demo" / "vision" / "labels" / "label-caresens-n.jpg"
QUESTION = "What changed this week for LLZ?"
TEST_REF = "TEST-0"


def no_answer_detail(status: int) -> str:
    """The detail of a scan-type check that had no 200 answer to look at."""
    return f"no answer to check (HTTP {status})"


def spent_usd(body: dict[str, Any]) -> float | None:
    """The ``cost_usd`` of a live answer, or None when it is not a non-negative number.

    None means the full cap stays as spent (a bool, a string, NaN, infinity and a negative
    number are all "not a cost"), never $0.
    """
    c = body.get("cost_usd")
    if isinstance(c, bool) or not isinstance(c, (int, float)):
        return None
    if c != c or c < 0 or c == float("inf"):
        return None
    return float(c)


class Smoke:
    """One run against one API and (optionally) one web app."""

    def __init__(
        self,
        api: str,
        web: str,
        rep: Report,
        secrets: list[str],
        budget: Budget | None = None,
    ) -> None:
        """Remember the targets, the report, the secret values and the one shared budget."""
        self.api, self.web, self.rep, self.secrets = api.rstrip("/"), web.rstrip("/"), rep, secrets
        # the plan is one ask and one spoken question: max 1 ask, 1 voice and 0 photos, set in
        # code (not only by the ``with_photo`` / ``--max-live-asks`` flags)
        self.budget = budget if budget is not None else Budget(limits={**LIMITS, **SMOKE_LIMITS})
        self.live_cost = 0.0
        self.load_cost = 0.0
        self.web_live_cost = 0.0  # cost_usd of the live calls the browser pass made
        self.remaining: list[int] = []
        self.demo_key = ""

    def get(self, path: str, key: str = "") -> Response:
        """GET an API path with an optional key header."""
        return request("GET", self.api + path, headers={"X-API-Key": key} if key else None)

    def scan(self, name: str, r: Response, detect: Callable[[str], bool], fail_detail: str) -> bool:
        """Run one scan-type check on a response; FAIL when there is no 200 answer to scan.

        In this script the only caller is ``clean`` (secret values and key-shaped strings in a
        response). ``clean`` handles a non-200 response first, before calling here; the 200 test
        in this method is a second guard so that a status 0 or any other status is never a pass:
        the line is FAIL "no answer to check (HTTP <status>)". Returns True when the response
        was scanned.
        """
        if r.status != 200:
            self.rep.add(name, FAIL, no_answer_detail(r.status), group="security")
            return False
        self.rep.ok(name, not detect(r.text), fail_detail, group="security")
        return True

    def clean(self, name: str, *rs: Response) -> None:
        """No secret value and no key-shaped string in the responses (FAIL when none answered)."""
        silent = [r for r in rs if r.status != 200]
        if silent:
            self.rep.add(name, FAIL, no_answer_detail(silent[0].status), group="security")
            return
        self.scan(
            name,
            Response(200, body=b"\n".join(r.body for r in rs)),
            lambda text: contains_any(text, self.secrets) or bool(find_key_shapes(text)),
            "a key or key-shaped string appears in a response",
        )

    def shape(self, name: str, r: Response) -> dict[str, Any]:
        """A tool answer: 200, speakable text, every fact with an https link."""
        body = r.json() if r.status == 200 and isinstance(r.json(), dict) else {}
        facts = body.get("facts") or []
        ok = bool(
            body.get("speakable")
            and body.get("advisory")
            and (body.get("provenance") or {}).get("kind")
            and all(str(f.get("link", "")).startswith("https://") for f in facts)
        )
        self.rep.ok(
            name, ok, f"HTTP {r.status} {r.text[:120]}", group="api", elapsed_ms=r.elapsed_ms
        )
        return body

    def service(self) -> None:
        """Health, legal pages, connect, no-key 401."""
        r = self.get("/v1/health")
        h = r.json() if isinstance(r.json(), dict) else {}
        self.rep.ok(
            "health 200 and ok",
            r.status == 200 and h.get("status") == "ok",
            f"HTTP {r.status} {r.error}",
            group="service",
        )
        self.rep.metrics["health"] = {
            k: h.get(k)
            for k in ("version", "limits_scope", "state_store", "feedback_store", "tools")
        }
        for path in ("/privacy", "/terms"):
            r = self.get(path)
            self.rep.ok(f"{path} is 200", r.status == 200, f"HTTP {r.status}", group="service")
        r = self.get("/v1/connect")
        c = r.json() if isinstance(r.json(), dict) else {}
        self.demo_key = str(c.get("demo_key") or "")
        self.rep.ok(
            "/v1/connect hands out a demo key",
            r.status == 200 and len(self.demo_key) >= 32,
            f"HTTP {r.status}; demo key present: {bool(self.demo_key)}",
            group="service",
        )
        r = self.get("/v1/tools/recalls?product_code=LLZ")
        self.rep.ok("no key is 401", r.status == 401, f"HTTP {r.status}", group="auth")

    def keyed(self, smoke_keys: list[str]) -> None:
        """Tool calls with the demo key, and with each smoke key when given."""
        if self.demo_key:
            b = self.shape(
                "demo key: what_changed_this_week LLZ",
                self.get("/v1/tools/what_changed_this_week?product_code=LLZ", self.demo_key),
            )
            diffs = llz_snapshot_diffs(b) if b else None
            if diffs is None:
                self.rep.add(
                    "quoted figures for LLZ",
                    KNOWN_GAP,
                    "answer came from live openFDA (or none): its numbers move daily, so no comparison was made",
                    group="numbers",
                    required=False,
                )
            else:
                self.rep.ok(
                    "quoted figures for LLZ unchanged (stored snapshot: 33 reports, weekly average 8.75)",
                    not diffs,
                    f"missing: {diffs}",
                    group="numbers",
                )
            self.shape(
                "demo key: recalls LLZ",
                self.get("/v1/tools/recalls?product_code=LLZ", self.demo_key),
            )
            r = self.get("/v1/audit/recent", self.demo_key)
            self.rep.ok(
                "demo key on the audit list is 403",
                r.status == 403,
                f"HTTP {r.status}",
                group="auth",
            )
        else:
            self.rep.add("demo key calls", FAIL, "no demo key from /v1/connect", group="api")
        if not smoke_keys:
            self.rep.add(
                "keyed calls with a full key",
                BLOCKED,
                "keys not provided (MAUDESIGNAL_SMOKE_KEYS is empty); only the demo key was used",
                group="api",
            )
            return
        for n, key in enumerate(smoke_keys, 1):
            tag = f"smoke key {n}"
            b = self.shape(
                f"{tag}: what_changed_this_week LLZ",
                self.get("/v1/tools/what_changed_this_week?product_code=LLZ", key),
            )
            diffs = llz_snapshot_diffs(b) if b else None
            if diffs is not None:
                self.rep.ok(
                    f"{tag}: quoted figures for LLZ unchanged",
                    not diffs,
                    f"missing: {diffs}",
                    group="numbers",
                )
            r = self.get("/v1/audit/recent?limit=20", key)
            chain = (r.json() or {}).get("chain") if isinstance(r.json(), dict) else {}
            self.rep.ok(
                f"{tag}: audit chain verifies",
                r.status == 200 and (chain or {}).get("verified") is True,
                f"HTTP {r.status} chain={chain}",
                group="api",
                entries_checked=(chain or {}).get("entries_checked"),
            )
            self.clean(f"{tag}: audit list holds no key", r)
            r = request(
                "POST",
                self.api + "/mcp",
                headers={"X-API-Key": key},
                json_body={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
            )
            names = (
                [t.get("name") for t in ((r.json() or {}).get("result") or {}).get("tools", [])]
                if isinstance(r.json(), dict)
                else []
            )
            self.rep.ok(
                f"{tag}: MCP tools/list names the tools",
                r.status == 200 and "what_changed_this_week" in names,
                f"HTTP {r.status} {names}",
                group="api",
                tools=names,
            )

    def note_live(self, name: str, r: Response, kind: str) -> None:
        """Log mode, cost and the remaining count of one live call; settle its budget hold."""
        b = r.json() if isinstance(r.json(), dict) else {}
        # a cost_usd that is not a non-negative number (or no 200 answer at all) is the full cap:
        # the server may still have spent up to it, so the hold stays as spent
        got = spent_usd(b) if r.status == 200 else None
        cost = got if got is not None else HOLD_USD[kind]
        self.live_cost += cost
        self.budget.settle(kind, got)
        left = (b.get("limits") or {}).get("remaining_today")
        if isinstance(left, int):
            self.remaining.append(left)
        mode = b.get("mode")
        self.rep.ok(
            f"{name}: HTTP 200 with the advice line",
            r.status == 200 and b.get("not_medical_advice") is True,
            f"HTTP {r.status} {r.text[:140]}",
            group="live",
            mode=mode,
            cost_usd=cost,
            elapsed_ms=r.elapsed_ms,
        )
        if r.status == 200 and mode != "live":
            self.rep.add(
                f"{name}: live model used",
                KNOWN_GAP,
                f"answered as {mode!r} (live model off, or today's cap reached): {str(b.get('recorded_note', ''))[:160]}",
                group="live",
                required=False,
                cost_usd=cost,
            )
        self.clean(f"{name}: no key in the response", r)

    def skipped_budget(self, name: str) -> None:
        """A live call the budget refused: a FAIL line, never silent."""
        self.rep.add(name, FAIL, SKIPPED_BUDGET, group="live")

    def live(self, with_photo: bool = True) -> None:
        """One chat question and one spoken question; a photo only when ``with_photo``.

        Every call is budget-checked. A photo is held at $0.30, so with the $0.60 run budget it
        does not fit beside the question and the spoken question ($0.55); by default no photo is
        sent and the report says so. The browser pass runs in recorded mode (route mocks).
        """
        if self.budget.reserve("ask"):
            r = request(
                "POST", self.api + "/v1/live/ask", json_body={"question": QUESTION}, timeout=90
            )
            self.note_live("live chat question", r, "ask")
        else:
            self.skipped_budget("live chat question")
        if not with_photo:
            self.rep.add(
                "live photo",
                KNOWN_GAP,
                "not called in the smoke run: a photo is held at $0.30 and does not fit the "
                "$0.60 run budget beside the chat and spoken questions; the browser pass uses "
                "a recorded mock; the real /v1/live/label route is not called by any automated check",
                group="live",
                required=False,
            )
        elif not LABEL_PHOTO.is_file():
            self.rep.add("live photo", FAIL, f"{LABEL_PHOTO.name} not found", group="live")
        elif self.budget.reserve("photo"):
            body, ctype = multipart(
                {"image": (LABEL_PHOTO.name, LABEL_PHOTO.read_bytes(), "image/jpeg")}
            )
            self.note_live(
                "live photo",
                request(
                    "POST",
                    self.api + "/v1/live/label",
                    body=body,
                    headers={"Content-Type": ctype},
                    timeout=120,
                ),
                "photo",
            )
        else:
            self.skipped_budget("live photo")
        voice = load_voice(ROOT, VOICE_FILES)
        if voice is None:
            self.rep.add("live voice question", FAIL, "no WAV found in demo/voice", group="live")
        elif self.budget.reserve("voice"):
            body, ctype = multipart({"audio": ("q.wav", voice[1], "audio/wav")})
            self.note_live(
                "live voice question",
                request(
                    "POST",
                    self.api + "/v1/live/voice",
                    body=body,
                    headers={"Content-Type": ctype},
                    timeout=120,
                ),
                "voice",
            )
        else:
            self.skipped_budget("live voice question")
        self.rep.metrics["live_cost_usd_so_far"] = round(self.live_cost, 6)

    def test_entries(self, admin_key: str) -> None:
        """A TEST visit and TEST feedback; deleted when the admin key is given."""
        r = request("POST", self.api + "/v1/visit", json_body={"ref": TEST_REF, "page": "smoke"})
        self.rep.ok(
            "?r=TEST-0 visit ping accepted (204)",
            r.status == 204,
            f"HTTP {r.status}",
            group="feedback",
        )
        r = request(
            "POST",
            self.api + "/v1/feedback",
            json_body={
                "rating": 4,
                "comment": "TEST smoke entry",
                "blocker": "",
                "one_thing": "",
                "consent": "no_quote",
                "ref": TEST_REF,
                "page": "smoke",
            },
        )
        self.rep.ok(
            "TEST feedback accepted (201)",
            r.status == 201,
            f"HTTP {r.status} {r.text[:100]}",
            group="feedback",
        )
        if not admin_key:
            self.rep.add(
                "TEST entries deleted",
                BLOCKED,
                "MAUDESIGNAL_ADMIN_KEY_SMOKE not provided: the TEST visit and TEST feedback entry remain; Charan deletes them (admin page, 'delete TEST entries')",
                group="feedback",
            )
            return
        r = request("POST", self.api + "/v1/admin/delete-test", headers={"X-Admin-Key": admin_key})
        deleted = (r.json() or {}).get("deleted") if isinstance(r.json(), dict) else None
        deleted = deleted if isinstance(deleted, dict) else {}
        n_visits, n_feedback = deleted.get("visits"), deleted.get("feedback")
        # This run wrote one visit and one feedback entry, so at least one of each must go.
        counts_ok = (
            r.status == 200
            and isinstance(n_visits, int)
            and isinstance(n_feedback, int)
            and n_visits >= 1
            and n_feedback >= 1
        )
        self.rep.ok(
            "/v1/admin/delete-test deleted at least the entries this run wrote (1 visit, 1 feedback)",
            counts_ok,
            f"HTTP {r.status}; deleted={deleted or r.text[:100]}",
            group="feedback",
        )
        s2 = request("GET", self.api + "/v1/admin/summary", headers={"X-Admin-Key": admin_key})
        codes = (s2.json() or {}).get("codes") if isinstance(s2.json(), dict) else None
        left = [c for c in (codes or []) if isinstance(c, dict) and c.get("code") == TEST_REF]
        self.rep.ok(
            f"{TEST_REF} is gone from /v1/admin/summary after the delete",
            s2.status == 200 and isinstance(codes, list) and not left,
            f"HTTP {s2.status}; {len(left)} entry/entries still listed for {TEST_REF}",
            group="feedback",
        )

    def web_pages(self) -> None:
        """The web app loads; its script and style files load; bundle hash reported."""
        r = request("GET", self.web + "/")
        self.rep.ok(
            "web page loads (200, HTML)",
            r.status == 200 and '<div id="root"' in r.text,
            f"HTTP {r.status} {r.error}",
            group="web",
        )
        r2 = request("GET", self.web + f"/?r={TEST_REF}")
        self.rep.ok(
            "web page with ?r=TEST-0 loads", r2.status == 200, f"HTTP {r2.status}", group="web"
        )
        assets = sorted(set(re.findall(r'(?:src|href)="(\./assets/[^"]+\.(?:js|css))"', r.text)))
        self.rep.ok(
            "the page names its script and style files",
            bool(assets),
            "no ./assets/*.js or *.css in the HTML",
            group="web",
        )
        hashes: dict[str, str] = {}
        for a in assets:
            ar = request("GET", f"{self.web}/{a[2:]}")
            ok = ar.status == 200 and len(ar.body) > 0
            self.rep.ok(f"asset {a[2:]} loads", ok, f"HTTP {ar.status}", group="web")
            if ok:
                hashes[a[2:]] = hashlib.sha256(ar.body).hexdigest()[:16]
                if a.endswith(".js"):
                    self.clean(f"asset {a[2:]} holds no key", ar)
        self.rep.metrics["web_bundle"] = hashes

    def web_browser(self, out_dir: Path) -> None:
        """The Playwright quick pass (chromium, 1440 and 390): chat, camera upload, alert panel."""
        cmd = [
            sys.executable,
            str(HERE / "e2e_web.py"),
            "--url",
            f"{self.web}/?r={TEST_REF}",  # every visit ping is a TEST entry (and is blocked)
            "--test-ref",
            TEST_REF,
            "--suite",
            "smoke",
            "--widths",
            "1440,390",
            "--out-dir",
            str(out_dir),
            "--stem",
            "smoke-web",
            # recorded mode through route mocking: the browser pass spends $0 of the budget
            "--mock-live",
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True, check=False)  # noqa: S603
        path = out_dir / "smoke-web.json"
        if not path.exists():
            self.rep.add(
                "web quick pass ran",
                FAIL,
                f"no report; exit {proc.returncode}: {(proc.stderr or proc.stdout)[-300:]}",
                group="web",
            )
            # the browser may have made calls before it stopped: assume it spent all it was given
            self.web_live_cost = self.budget.remaining_usd()
            self.budget.absorb(self.web_live_cost, self.budget.remaining_counts())
            return
        import json

        doc = json.loads(path.read_text("utf-8"))
        snap = doc.get("metrics", {}).get("budget")
        if isinstance(snap, dict):
            # the browser pass's own ledger: every reserved call, answered or not
            used = snap.get("used") or {}
            counts = {k: int(used.get(k, 0)) for k in ("ask", "photo", "voice")}
            self.web_live_cost = float(snap.get("spent_usd") or 0.0) + float(
                snap.get("held_usd") or 0.0
            )
        else:  # no ledger in the report: assume the whole remaining budget was spent
            counts = self.budget.remaining_counts()
            self.web_live_cost = self.budget.remaining_usd()
        self.budget.absorb(self.web_live_cost, counts)
        self.rep.metrics["web_pass_live_calls"] = doc.get("metrics", {}).get("live_calls", [])
        for c in doc["checks"]:
            self.rep.add(
                f"web quick pass: {c['name']}",
                c["status"],
                c["detail"],
                group="web",
                required=c["required"],
            )

    def load(self, vus: int, seconds: float, max_live: int) -> None:
        """The light load test: live asks only within what is left of the shared budget."""
        # Each live ask is held at its full cap, so the number allowed is what the dollars left
        # can carry; everything else in the load test is a public check or a health call.
        allowed = min(
            max_live, self.budget.remaining_counts()["ask"], self.budget.max_asks_by_dollars()
        )
        if allowed < max_live:
            # the request was lowered because of the budget: never silent
            self.rep.add(
                "load: live asks requested",
                FAIL,
                f"{SKIPPED_BUDGET} ({max_live - allowed} asks)",
                group="load",
            )
        if allowed <= 0:
            self.rep.add(
                "load: live asks",
                KNOWN_GAP,
                "none planned: the budget left after the live checks cannot "
                "carry one more ask at its full hold; the load test used public checks only",
                group="load",
                required=False,
            )
        refused_before = len(self.budget.refused)
        samples = run_load(
            self.api, vus=vus, seconds=seconds, max_live_asks=allowed, budget=self.budget
        )
        if len(self.budget.refused) > refused_before:
            self.rep.add(
                "load: live asks within the shared budget",
                FAIL,
                f"{SKIPPED_BUDGET} ({len(self.budget.refused) - refused_before} live ask(s) refused; "
                "public checks were made instead)",
                group="load",
            )
        stats = summarize(samples)
        stats.update(vus=vus, seconds=seconds)
        sub = Report("load")
        evaluate(sub, stats, 0.02, self.budget.max_usd, allowed)
        for c in sub.checks:
            self.rep.add(f"load: {c.name}", c.status, c.detail, group="load", required=c.required)
        self.rep.metrics["load"] = stats
        self.load_cost = float(stats["live_cost_usd"])
        if stats.get("last_remaining_today") is not None:
            self.remaining.append(stats["last_remaining_today"])

    def finish(self) -> None:
        """Total cost and budget numbers; runs on every smoke run, also with --no-load."""
        snap = self.budget.snapshot()
        self.rep.metrics["budget"] = snap
        used: dict[str, int] = snap["used"]  # type: ignore[assignment]
        limits: dict[str, int] = snap["limits"]  # type: ignore[assignment]
        counts_ok = all(used[k] <= limits[k] for k in limits)
        # spent_usd holds every settled call: its reported cost_usd, or its full hold when no
        # cost came back; held_usd is what is still reserved (zero when the run is over)
        total = float(snap["spent_usd"]) + float(snap["held_usd"])  # type: ignore[arg-type]
        self.rep.add(
            "total live cost stayed within the per-run budget",
            PASS if total <= self.budget.max_usd + 1e-9 and counts_ok else FAIL,
            f"${total:.4f} of ${self.budget.max_usd:.2f} (calls without a reported cost counted at "
            f"their full hold); calls used {used} of {limits}",
            group="load",
        )
        self.rep.metrics["live_cost_usd_total"] = round(total, 6)
        self.rep.metrics["live_cost_parts"] = {
            "live_checks": round(self.live_cost, 6),
            "load_test": round(self.load_cost, 6),
            "web_quick_pass_incl_holds": round(self.web_live_cost, 6),
        }
        seen = [*self.remaining]
        self.rep.add(
            "cap ledger: cost reported by the responses (informational)",
            KNOWN_GAP,
            f"${total:.4f} counted by this run's budget; "
            f"last remaining_today: {seen[-1] if seen else 'not reported'}",
            group="load",
            required=False,
            live_cost_usd_total=round(total, 6),
        )


API_HOST_ALLOWED = "maudesignal-api*.vercel.app"


def api_allowed(url: str) -> bool:
    """True when the API URL is https on a host that matches ``maudesignal-api*.vercel.app``."""
    from fnmatch import fnmatchcase
    from urllib.parse import urlsplit

    parts = urlsplit(url)
    return parts.scheme == "https" and fnmatchcase(parts.hostname or "", API_HOST_ALLOWED)


def mask_lines(secrets: list[str]) -> list[str]:
    """GitHub ``::add-mask::`` commands, one per secret value (each key, not the joined list)."""
    return [f"::add-mask::{v}" for v in secrets if v]


def main(argv: list[str] | None = None) -> int:
    """Run the smoke test; write ``smoke.json`` and ``.md``; exit 1 on any failure."""
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0] if __doc__ else "")
    ap.add_argument("--api", default="https://maudesignal-api.vercel.app")
    ap.add_argument("--web", default="")
    ap.add_argument("--out-dir", type=Path, default=Path("release-out"))
    ap.add_argument("--no-web", action="store_true")
    ap.add_argument("--no-load", action="store_true")
    ap.add_argument("--vus", type=int, default=20)
    ap.add_argument("--seconds", type=float, default=120.0)
    ap.add_argument("--max-live-asks", type=int, default=0)
    args = ap.parse_args(argv)
    keys = [k.strip() for k in os.environ.get("MAUDESIGNAL_SMOKE_KEYS", "").split(",") if k.strip()]
    admin = os.environ.get("MAUDESIGNAL_ADMIN_KEY_SMOKE", "").strip()
    if os.environ.get("GITHUB_ACTIONS") == "true":
        for line in mask_lines([*keys, admin]):  # GitHub masks only the whole joined string
            print(line, flush=True)
    if (keys or admin) and not api_allowed(args.api):
        print(
            f"refusing to send keys to {args.api!r}: with secrets present the API must be "
            f"https on {API_HOST_ALLOWED}",
            file=sys.stderr,
        )
        return 2
    rep = Report("smoke (live URLs)")
    rep.metrics.update(
        api=args.api, web=args.web, smoke_keys_given=len(keys), admin_key_given=bool(admin)
    )
    s = Smoke(args.api, args.web, rep, [*keys, admin])
    s.service()
    s.keyed(keys)
    browser_pass = not (args.no_web or not args.web)
    s.live(with_photo=False)  # budget $0.60: ask + voice only (browser pass is mocked)
    s.test_entries(admin)
    if not browser_pass:
        rep.add("web checks", SKIPPED, "no web URL given, or --no-web", group="web", required=False)
    else:
        s.web_pages()
        s.web_browser(args.out_dir)
    if args.no_load:
        rep.add("load test", SKIPPED, "--no-load", group="load", required=False)
    else:
        s.load(args.vus, args.seconds, args.max_live_asks)
    s.finish()
    rep.write(args.out_dir, "smoke")
    return rep.exit_code()


if __name__ == "__main__":
    sys.exit(main())
