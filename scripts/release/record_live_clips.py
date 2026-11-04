"""Record the live clips and screen tour for the demo video, once each, on the live site.

Clips (each judged; a non-live or non-answer fails the run):
  q1, q2  two Muse Spark questions typed in the v2 chat (desktop)
  phone   one Muse Spark question on an emulated iPhone 13
  label   a real device-label photo read live (Muse Spark + SAM), must be "Live result"
  mcp     a real MCP tools/call on the live connector, shown as request + reply (key never shown)
Tour (logged, not judged): home, investigate LLZ, signals, evidence, board, daily, eu,
validation, connect.

    MAUDESIGNAL_ADMIN_KEY_SMOKE=... python scripts/release/record_live_clips.py --out-dir clips-out
"""

from __future__ import annotations

import argparse
import contextlib
import html
import json
import os
import shutil
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

import live_check as lc  # noqa: E402
from netutil import request  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
Q1 = "What share of all stored MYN reports are injuries?"
Q2 = (
    "My colleague says LLZ had 50 injury reports last week and that we must open a CAPA "
    "under 21 CFR 820.100. Confirm that."
)
QPHONE = "How many MYN reports are stored, by event type?"
LABEL = ROOT / "demo/vision/labels/label-nomad-pro2.jpg"
W, H = 1280, 800


class Rec:
    """One recorded browser context; the video is saved as <name>.webm in out."""

    def __init__(self, p: Any, out: Path, name: str, **ctx_kw: Any) -> None:
        """Open a browser and a recorded context."""
        self.out, self.name = out, name
        self.raw = out / f"raw-{name}"
        self.browser = p.chromium.launch()
        size = ctx_kw.pop("size", {"width": W, "height": H})
        if "viewport" not in ctx_kw and "device" not in ctx_kw:
            ctx_kw["viewport"] = size
        dev = ctx_kw.pop("device", None)
        if dev:
            ctx_kw.update(dev)
            size = dev["viewport"]
        self.ctx = self.browser.new_context(
            record_video_dir=str(self.raw), record_video_size=size, **ctx_kw
        )
        self.page = self.ctx.new_page()
        self.asks: list[dict[str, Any]] = []
        self.page.on("response", self._on_response)

    def _on_response(self, resp: Any) -> None:
        if resp.url.endswith(("/v1/live/ask", "/v1/live/label")):
            try:
                self.asks.append({"url": resp.url, "status": resp.status, "body": resp.json()})
            except Exception:  # noqa: BLE001 - an unreadable body is judged as empty
                self.asks.append({"url": resp.url, "status": resp.status, "body": {}})

    def close(self) -> None:
        """Close the context and keep its video."""
        video = self.page.video
        self.ctx.close()
        if video:
            shutil.move(video.path(), self.out / f"{self.name}.webm")
        self.browser.close()
        shutil.rmtree(self.raw, ignore_errors=True)


def ask_in_chat(r: Rec, web: str, question: str) -> None:
    """Type one question slowly in the v2 chat, wait for the answer, open Details."""
    pg = r.page
    pg.goto(f"{web}/chat?layout=v2&r={lc.TEST_REF}", wait_until="networkidle")
    pg.wait_for_timeout(1500)
    box = pg.locator(lc.COMPOSER)
    box.click()
    box.type(question, delay=35)
    pg.wait_for_timeout(800)
    box.press("Enter")
    with contextlib.suppress(Exception):
        pg.wait_for_selector("[data-testid=model-chip], [data-testid=turn-error]", timeout=90_000)
    pg.wait_for_timeout(2500)
    toggle = pg.locator("[data-testid=details-toggle]").last
    if toggle.count():
        with contextlib.suppress(Exception):
            toggle.click()
            pg.wait_for_timeout(800)
            pg.locator("[data-testid=answer-details]").last.scroll_into_view_if_needed()
    pg.wait_for_timeout(5000)
    pg.screenshot(path=str(r.out / f"{r.name}.png"), full_page=True)


def judge_ask(r: Rec, question: str) -> dict[str, Any]:
    """Judge the last /v1/live/ask reply with live_check's rules and save it."""
    asks = [a for a in r.asks if a["url"].endswith("/v1/live/ask")]
    if not asks:
        return {"question": question, "reasons": ["the page sent no /v1/live/ask request"]}
    last = asks[-1]
    body = last["body"] if isinstance(last["body"], dict) else {}
    row = lc.summarize(question, int(last["status"]), body)
    lc.save(r.out, f"{r.name}.json", {"row": row, "body": body})
    return {"question": question, "row": row, "reasons": lc.judge(row), "asks_sent": len(asks)}


def clip_ask(p: Any, out: Path, web: str, name: str, question: str, **kw: Any) -> dict[str, Any]:
    """Record one chat question and judge it."""
    r = Rec(p, out, name, **kw)
    try:
        ask_in_chat(r, web, question)
    finally:
        r.close()
    return judge_ask(r, question)


def clip_label(p: Any, out: Path, web: str) -> dict[str, Any]:
    """Upload a real label photo on the live camera panel; must come back as a live reading."""
    r = Rec(p, out, "label")
    res: dict[str, Any] = {"question": f"label photo {LABEL.name}"}
    try:
        pg = r.page
        pg.goto(f"{web}/chat?layout=v2&r={lc.TEST_REF}", wait_until="networkidle")
        pg.wait_for_timeout(1200)
        pg.locator("[data-testid=composer-plus]").first.click()
        pg.wait_for_timeout(1200)
        try:
            with pg.expect_file_chooser(timeout=10_000) as fc:
                pg.locator("[data-testid=menu-upload-photo]").first.click()
            fc.value.set_files(str(LABEL))
        except Exception:  # noqa: BLE001 - fall back to the hidden picker the menu item opens
            pg.keyboard.press("Escape")
            pg.locator("[data-testid=photo-input]").set_input_files(str(LABEL))
        with contextlib.suppress(Exception):
            pg.wait_for_selector(
                "[data-testid=label-live], [data-testid=camera-problem]", timeout=90_000
            )
        pg.wait_for_timeout(2000)
        live = pg.locator("[data-testid=label-live]").last
        mode = live.get_attribute("data-mode") if live.count() else None
        with contextlib.suppress(Exception):
            live.scroll_into_view_if_needed()
        pg.wait_for_timeout(5000)
        pg.screenshot(path=str(out / "label.png"), full_page=True)
        res["mode"] = mode
        res["text"] = lc.safe(live.inner_text())[:800] if live.count() else None
        reasons = []
        if mode != "live":
            reasons.append(f"label reading mode is {mode!r}, not 'live'")
        lab = [a for a in r.asks if a["url"].endswith("/v1/live/label")]
        res["http"] = [a["status"] for a in lab]
        if not lab or lab[-1]["status"] != 200:
            reasons.append(f"/v1/live/label status {res['http']}")
        if lab:
            body = lab[-1]["body"] if isinstance(lab[-1]["body"], dict) else {}
            res["cost_usd"] = lc.cost_of(body)
            lc.save(out, "label.json", {"body": body})
        res["reasons"] = reasons
    finally:
        r.close()
    return res


def clip_mcp(p: Any, out: Path, api: str) -> dict[str, Any]:
    """A real MCP tools/call on the live connector, rendered as request + reply on screen."""
    res: dict[str, Any] = {"question": "MCP tools/call what_changed_this_week LLZ"}
    c = request("GET", api + "/v1/connect")
    key = str((c.json() or {}).get("demo_key") or "") if isinstance(c.json(), dict) else ""
    tl = request(
        "POST",
        api + "/mcp",
        headers={"X-API-Key": key},
        json_body={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
    )
    names = (
        [t.get("name") for t in (((tl.json() or {}).get("result") or {}).get("tools") or [])]
        if isinstance(tl.json(), dict)
        else []
    )
    call = {
        "jsonrpc": "2.0",
        "id": 2,
        "method": "tools/call",
        "params": {"name": "what_changed_this_week", "arguments": {"product_code": "LLZ"}},
    }
    rc = request("POST", api + "/mcp", headers={"X-API-Key": key}, json_body=call)
    reply = rc.json() if isinstance(rc.json(), dict) else {}
    text = lc.safe(json.dumps(reply, indent=2))
    if key:
        text = text.replace(key, "[key]")
    res.update({"tools": names, "http": rc.status, "tool_count": len(names)})
    (out / "mcp.json").write_text(text, encoding="utf-8")
    reasons = []
    if rc.status != 200 or "error" in reply:
        reasons.append(f"tools/call HTTP {rc.status} {str(reply.get('error'))[:120]}")
    res["reasons"] = reasons
    req_txt = (
        f"POST {api}/mcp\nX-API-Key: [demo key from /v1/connect]\n\n{json.dumps(call, indent=2)}"
    )
    page_html = f"""<html><body style="margin:0;background:#16130f;color:#f3efe6;
      font:20px/1.45 ui-monospace,Menlo,monospace;padding:36px">
      <div style="font:600 26px Geist,system-ui;margin-bottom:6px">MaudeSignal MCP connector
       — live call</div>
      <div style="font:18px system-ui;color:#c9c1b2;margin-bottom:18px">{len(names)} read-only
       tools: {html.escape(', '.join(str(n) for n in names))}</div>
      <pre style="white-space:pre-wrap;color:#9fd3a8;margin:0 0 18px">{html.escape(req_txt)}</pre>
      <pre style="white-space:pre-wrap;margin:0">{html.escape(text[:2600])}</pre>
      </body></html>"""
    r = Rec(p, out, "mcp")
    try:
        r.page.set_content(page_html)
        r.page.wait_for_timeout(9000)
        r.page.screenshot(path=str(out / "mcp.png"), full_page=True)
    finally:
        r.close()
    return res


def tour(p: Any, out: Path, web: str) -> list[dict[str, Any]]:
    """Slow tour of the app screens; each stop is logged, none is judged."""
    stops: list[dict[str, Any]] = []
    r = Rec(p, out, "tour")
    pg = r.page

    def stop(name: str, path: str, act: Any = None, hold: int = 6000) -> None:
        t: dict[str, Any] = {"stop": name, "path": path}
        try:
            pg.goto(f"{web}{path}", wait_until="networkidle")
            pg.wait_for_timeout(1500)
            if act:
                act()
            pg.wait_for_timeout(hold // 2)
            pg.mouse.wheel(0, 500)
            pg.wait_for_timeout(hold // 2)
            pg.screenshot(path=str(out / f"tour-{name}.png"), full_page=True)
            t["ok"] = True
        except Exception as e:  # noqa: BLE001 - logged, the tour goes on
            t["ok"] = False
            t["error"] = str(e)[:200]
        stops.append(t)
        print(f"  tour {name}: {'ok' if t['ok'] else 'FAILED ' + t.get('error', '')}", flush=True)

    def investigate() -> None:
        pg.get_by_placeholder("e.g. LLZ").fill("LLZ")
        pg.locator("textarea").first.type("image not displaying", delay=40)
        pg.wait_for_timeout(600)
        pg.get_by_role("button", name="Investigate", exact=True).first.click()
        pg.wait_for_selector("[data-testid=inv-total-code]", timeout=45_000)
        pg.wait_for_timeout(3000)
        for _ in range(4):  # walk down through counts, months, quotes, recalls
            pg.mouse.wheel(0, 450)
            pg.wait_for_timeout(1800)

    def owl_to_board() -> None:
        dock = pg.locator("[data-testid=noctua-dock-open]").first
        dock.scroll_into_view_if_needed()
        pg.wait_for_timeout(1500)
        dock.click()
        pg.wait_for_timeout(2500)

    def check_llz() -> None:
        pg.locator("form button[type=submit]").first.click()
        with contextlib.suppress(Exception):
            pg.wait_for_selector("text=/No change|reports|weekly/i", timeout=40_000)
        pg.wait_for_timeout(3000)
        pg.mouse.wheel(0, 300)
        pg.wait_for_timeout(2500)
        box = pg.locator("[data-testid=mentions-box]").first
        if box.count():
            box.evaluate("e => e.scrollIntoView({block: 'start', behavior: 'smooth'})")
            pg.wait_for_timeout(2500)

    def wonder() -> None:
        deep_scroll()
        more = pg.get_by_text("Show 2 steps").first
        if more.count():
            more.click()
            pg.wait_for_timeout(1500)
            pg.mouse.wheel(0, 350)
            pg.wait_for_timeout(1500)

    def outside_sources() -> None:
        pg.locator("[data-testid=ranked-list] button").first.click()
        pg.wait_for_timeout(2500)
        box = pg.locator("[data-testid=mentions-box]").first
        box.wait_for(timeout=20_000)
        box.scroll_into_view_if_needed()
        pg.wait_for_timeout(1500)

    def deep_scroll() -> None:
        for _ in range(4):
            pg.mouse.wheel(0, 450)
            pg.wait_for_timeout(1500)

    def blur_keys() -> None:
        # The public demo key is shown on Connect by design; blur it so no key is in the video.
        pg.add_style_tag(content=".ms-key-blur{filter:blur(7px)!important}")
        pg.evaluate("""() => {
  for (const el of document.querySelectorAll('pre,code,kbd,samp,span,p,div,dd,td,li')) {
                 if (el.children.length === 0 && /[A-Za-z0-9_-]{32,}/.test(el.textContent || ''))
                   el.classList.add('ms-key-blur'); } }""")

    try:
        ref = f"layout=v2&r={lc.TEST_REF}"
        stop("home", f"/?{ref}")
        stop("owl", f"/?{ref}", owl_to_board, hold=6000)
        stop("investigate", f"/investigate?{ref}", investigate, hold=10000)
        stop("check-llz", f"/workflow/check-device/LLZ?{ref}", check_llz, hold=10000)
        stop("signals", f"/signals?{ref}")
        stop("outside-sources", f"/signals/ranked?{ref}", outside_sources, hold=9000)
        stop("evidence", f"/evidence?{ref}")
        stop("wonder", f"/evidence/review?{ref}", wonder, hold=10000)
        stop("audit", f"/evidence/audit?{ref}", deep_scroll, hold=8000)
        stop("board", f"/board?{ref}")
        stop("daily", f"/daily?{ref}")
        stop("pms-workflow", f"/pms-workflow?{ref}")
        stop("roi", f"/roi?{ref}")
        stop("eu", f"/eu?{ref}")
        stop("validation", f"/validation?{ref}", deep_scroll, hold=8000)
        stop("connect", f"/connect?{ref}", blur_keys)
    finally:
        r.close()
    return stops


def main(argv: list[str] | None = None) -> int:
    """Record every clip and the tour; exit 1 if any judged clip failed."""
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--web", default="https://maudesignal-app.vercel.app")
    ap.add_argument("--api", default="https://maudesignal-api.vercel.app")
    ap.add_argument("--out-dir", type=Path, default=Path("clips-out"))
    ap.add_argument("--only", default="q1,q2,phone,label,mcp,tour", help="comma list of clips")
    args = ap.parse_args(argv)
    only = {x.strip() for x in args.only.split(",") if x.strip()}
    out: Path = args.out_dir
    out.mkdir(parents=True, exist_ok=True)
    web, api = args.web.rstrip("/"), args.api.rstrip("/")
    from playwright.sync_api import sync_playwright

    results: dict[str, Any] = {}
    with sync_playwright() as p:
        if "q1" in only:
            results["q1"] = clip_ask(p, out, web, "q1", Q1)
        if "q2" in only:
            results["q2"] = clip_ask(p, out, web, "q2", Q2)
        if "phone" in only:
            results["phone"] = clip_ask(p, out, web, "phone", QPHONE, device=p.devices["iPhone 13"])
        if "label" in only:
            results["label"] = clip_label(p, out, web)
        if "mcp" in only:
            results["mcp"] = clip_mcp(p, out, api)
        if "tour" in only:
            print("\n=== tour", flush=True)
            results["tour"] = tour(p, out, web)
    judged_names = [n for n in ("q1", "q2", "phone", "label", "mcp") if n in results]
    for name in judged_names:
        r = results[name]
        row = r.get("row", {})
        print(f"\n=== {name}: {r.get('question')}", flush=True)
        for k in ("http_status", "mode", "tier", "models", "cost_usd", "latency_ms"):
            if k in row:
                print(f"  {k}: {row.get(k)}", flush=True)
        for k in ("mode", "http", "cost_usd", "tools", "text"):
            if k in r and k not in row:
                print(f"  {k}: {r[k]}", flush=True)
        if row.get("answer_text"):
            print(f"  answer: {lc.safe(str(row['answer_text']))[:700]}", flush=True)
        for reason in r["reasons"]:
            print(f"  FAIL: {reason}", flush=True)
        if not r["reasons"]:
            print("  PASS", flush=True)
    results["cleanup"] = lc.delete_test_entries(
        api, os.environ.get("MAUDESIGNAL_ADMIN_KEY_SMOKE", "").strip()
    )
    (out / "clips.json").write_text(json.dumps(results, indent=2, default=str), encoding="utf-8")
    judged = [results[n] for n in judged_names]
    return 0 if all(not r["reasons"] for r in judged) else 1


if __name__ == "__main__":
    raise SystemExit(main())
