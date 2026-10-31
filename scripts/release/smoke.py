"""Post-deploy smoke test of the live API and web app.

HACKATHON-BUILT — Meta Global AI Developer Hackathon (Oct 26 – Nov 4, 2026).

Runs against the deployed URLs (never prints a key):

    MAUDESIGNAL_SMOKE_KEYS=key1,key2 MAUDESIGNAL_ADMIN_KEY_SMOKE=... \
    python3 scripts/release/smoke.py --api https://maudesignal-api.vercel.app \
        --web https://<web-preview-url> --out-dir release-out

Groups: service pages, connect (a demo key is handed out), authentication (no key is 401),
keyed tool calls (the demo key from /v1/connect always; the keys in MAUDESIGNAL_SMOKE_KEYS
when given, otherwise BLOCKED: "keys not provided", never PASS), the figures the API shares
with the submission, one live chat question, one photo and one spoken question on /v1/live/*
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
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))

from compare import llz_snapshot_diffs  # noqa: E402
from leaks import contains_any, find_key_shapes  # noqa: E402
from load_test import evaluate, run_load, summarize  # noqa: E402
from media import load_voice  # noqa: E402
from netutil import Response, multipart, request  # noqa: E402
from report import BLOCKED, FAIL, KNOWN_GAP, SKIPPED, Report  # noqa: E402

VOICE_FILES = ("question-a.wav", "question.wav", "question-c.wav")
LABEL_PHOTO = ROOT / "demo" / "vision" / "labels" / "label-caresens-n.jpg"
QUESTION = "What changed this week for LLZ?"
TEST_REF = "TEST-smoke"


class Smoke:
    """One run against one API and (optionally) one web app."""

    def __init__(self, api: str, web: str, rep: Report, secrets: list[str]) -> None:
        """Remember the targets, the report and the secret values that must never appear."""
        self.api, self.web, self.rep, self.secrets = api.rstrip("/"), web.rstrip("/"), rep, secrets
        self.live_cost = 0.0
        self.web_live_cost = 0.0  # cost_usd of the live calls the browser pass made
        self.remaining: list[int] = []
        self.demo_key = ""

    def get(self, path: str, key: str = "") -> Response:
        """GET an API path with an optional key header."""
        return request("GET", self.api + path, headers={"X-API-Key": key} if key else None)

    def clean(self, name: str, *rs: Response) -> None:
        """No secret value and no key-shaped string in the responses."""
        bad = any(contains_any(r.text, self.secrets) or find_key_shapes(r.text) for r in rs)
        self.rep.ok(
            name, not bad, "a key or key-shaped string appears in a response", group="security"
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

    def note_live(self, name: str, r: Response) -> None:
        """Log mode, cost and the remaining count of one live call."""
        b = r.json() if isinstance(r.json(), dict) else {}
        cost = float(b.get("cost_usd") or 0.0)
        self.live_cost += cost
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

    def live(self) -> None:
        """One chat question, one photo, one spoken question on /v1/live/*."""
        r = request("POST", self.api + "/v1/live/ask", json_body={"question": QUESTION}, timeout=90)
        self.note_live("live chat question", r)
        if LABEL_PHOTO.is_file():
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
            )
        else:
            self.rep.add("live photo", FAIL, f"{LABEL_PHOTO.name} not found", group="live")
        voice = load_voice(ROOT, VOICE_FILES)
        if voice is None:
            self.rep.add("live voice question", FAIL, "no WAV found in demo/voice", group="live")
        else:
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
            )
        self.rep.metrics["live_cost_usd_so_far"] = round(self.live_cost, 6)

    def test_entries(self, admin_key: str) -> None:
        """A TEST visit and TEST feedback; deleted when the admin key is given."""
        r = request("POST", self.api + "/v1/visit", json_body={"ref": TEST_REF, "page": "smoke"})
        self.rep.ok(
            "?r=TEST-smoke visit ping accepted (204)",
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
        self.rep.ok(
            "TEST entries deleted by /v1/admin/delete-test",
            r.status == 200,
            f"HTTP {r.status} {r.text[:120]}",
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
            "web page with ?r=TEST-smoke loads", r2.status == 200, f"HTTP {r2.status}", group="web"
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
            return
        import json

        doc = json.loads(path.read_text("utf-8"))
        self.web_live_cost = float(doc.get("metrics", {}).get("live_cost_usd") or 0.0)
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
        """The light load test; the cap total comes from the cost of every live ask."""
        samples = run_load(self.api, vus=vus, seconds=seconds, max_live_asks=max_live)
        stats = summarize(samples)
        stats.update(vus=vus, seconds=seconds)
        sub = Report("load")
        evaluate(sub, stats, 0.02, 1.0, max_live)
        for c in sub.checks:
            self.rep.add(f"load: {c.name}", c.status, c.detail, group="load", required=c.required)
        self.rep.metrics["load"] = stats
        total = self.live_cost + float(stats["live_cost_usd"]) + self.web_live_cost
        self.rep.metrics["live_cost_usd_total"] = round(total, 6)
        self.rep.metrics["live_cost_parts"] = {
            "live_checks": round(self.live_cost, 6),
            "load_test": round(float(stats["live_cost_usd"]), 6),
            "web_quick_pass": round(self.web_live_cost, 6),
        }
        seen = [*self.remaining]
        if stats.get("last_remaining_today") is not None:
            seen.append(stats["last_remaining_today"])
        self.rep.add(
            "cap ledger: cost reported by the responses (informational)",
            KNOWN_GAP,
            f"${total:.4f} summed from cost_usd of live checks, load test and web pass; "
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
    ap.add_argument("--max-live-asks", type=int, default=10)
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
    s.live()
    s.test_entries(admin)
    if args.no_web or not args.web:
        rep.add("web checks", SKIPPED, "no web URL given, or --no-web", group="web", required=False)
    else:
        s.web_pages()
        s.web_browser(args.out_dir)
    if args.no_load:
        rep.add("load test", SKIPPED, "--no-load", group="load", required=False)
    else:
        s.load(args.vus, args.seconds, args.max_live_asks)
    rep.write(args.out_dir, "smoke")
    return rep.exit_code()


if __name__ == "__main__":
    sys.exit(main())
