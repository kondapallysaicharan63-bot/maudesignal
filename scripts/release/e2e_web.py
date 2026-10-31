"""Browser checks of the built web app against a local API (Playwright, Python).

HACKATHON-BUILT — Meta Global AI Developer Hackathon (Oct 26 – Nov 4, 2026).

The release-check "e2e" job builds ``web/`` with ``VITE_MAUDESIGNAL_API_BASE`` pointing at a
local API started with the ``e2e`` profile of ``serve_api.py`` (real code, no Meta key, so
live questions are answered from recordings), serves the build, and runs:

    python3 scripts/release/e2e_web.py --url http://127.0.0.1:4173 --api http://127.0.0.1:8001 \
        --axe web/node_modules/axe-core/axe.min.js --out-dir release-out

For each engine (chromium, firefox, webkit) x width (1440, 390) x colour scheme (light, dark):
AI sweep, Check any device type, chat (recorded mode, two turns with history), camera upload
to possible matches to confirm, microphone (fake audio device; webkit has none, which is
reported as KNOWN_GAP, never as a pass), alert bell to alert panel, Our devices ("Make it
yours" when present), the CAPA-need evidence PDF link, the feedback form (submitted to the
local API), the Connect-to-Muse page, no sideways scroll on every view, and an axe-core scan of
the main views (serious or critical violations fail; the counts are reported).

Error states use route mocking: openFDA down, Meta down, daily cap reached (429), slow network,
offline. Each must show an honest message, no crash and no invented data.

``--suite smoke`` runs the short pass the post-deploy smoke test uses (chromium, 1440 and 390,
light): chat, camera upload, alert panel.
"""

# ruff: noqa: E501
from __future__ import annotations

import argparse
import contextlib
import io
import json
import re
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from budget import KIND_OF_PATH, SKIPPED_BUDGET, Budget  # noqa: E402
from compare import axe_blocks, count_axe  # noqa: E402
from report import FAIL, KNOWN_GAP, NOT_PRESENT, PASS, Report  # noqa: E402

VIEWPORTS = {1440: (1440, 900), 390: (390, 844)}
ENGINES = ("chromium", "firefox", "webkit")
COMPOSER = "textarea[aria-label='Ask a question']"
ASK_PATH = "**/v1/live/ask"
LABEL_PATH = "**/v1/live/label"
PUBLIC_CHECK = "**/v1/public/check_device_type*"
CHROMIUM_ARGS = ["--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream"]
FIREFOX_PREFS = {
    "media.navigator.streams.fake": True,
    "media.navigator.permission.disabled": True,
}
AXE_VIEWS = (
    ("home", None),
    ("AI device sweep", "AI device sweep"),
    ("Check any device type", "Check any device type"),
    ("Our devices", "Our devices"),
    ("CAPA-need evidence", "CAPA-need evidence"),
)


TEST_REF = "TEST-0"


def live_kind(url: str) -> str:
    """Budget kind (ask, photo, voice) of a /v1/live/<path> URL; empty when it is none of them."""
    tail = url.split("/v1/live/")[-1].split("?")[0].strip("/") if "/v1/live/" in url else ""
    return KIND_OF_PATH.get(tail, "")


def visit_ref(post_data: str | None) -> str | None:
    """The ``ref`` field of a /v1/visit request body, or None when absent or not JSON."""
    try:
        doc = json.loads(post_data or "")
    except ValueError:
        return None
    ref = doc.get("ref") if isinstance(doc, dict) else None
    return ref if isinstance(ref, str) else None


def visits_all_test(bodies: list[str | None], ref: str = TEST_REF) -> tuple[bool, str]:
    """True when every captured /v1/visit body carries ``ref`` (an empty list is fine)."""
    bad = [b for b in bodies if visit_ref(b) != ref]
    return (
        not bad,
        f"{len(bodies)} visit ping(s) captured and blocked; {len(bad)} without ref {ref}",
    )


def chat_verdict(sentences: int, unlinked: int, error: bool, held: bool) -> tuple[bool, str]:
    """Judge one chat answer: sentences must exist (or an error / withheld line) and be linked."""
    if sentences == 0 and not error and not held:
        return False, "no answer sentence, no error and no withheld line is shown"
    if unlinked:
        return False, f"{unlinked} of {sentences} sentence(s) carry no gate link"
    return True, f"sentences={sentences} (all linked) error={error} withheld_line={held}"


class SkipError(Exception):
    """A scenario that cannot run here: carries the status to record and why."""

    def __init__(self, status: str, why: str) -> None:
        """Keep the status (KNOWN_GAP or NOT_PRESENT) and the reason."""
        super().__init__(why)
        self.status, self.why = status, why


class Env:
    """One browser context: the page plus the facts a scenario needs."""

    def __init__(
        self,
        engine: str,
        width: int,
        scheme: str,
        page: Any,
        args: argparse.Namespace,
        rep: Report,
    ):
        """Bind the page, the run options and the report."""
        self.engine, self.width, self.scheme = engine, width, scheme
        self.page, self.args, self.rep = page, args, rep
        self.page_errors: list[str] = []
        self.api_calls: list[str] = []
        self.visit_bodies: list[str | None] = []
        self.live_calls: list[dict[str, Any]] = []
        self.budget: Budget | None = getattr(args, "budget", None)
        self.budget_held: list[str] = []  # kinds reserved and not yet settled
        page.on("pageerror", lambda e: self.page_errors.append(str(e)[:200]))
        page.on("request", lambda r: self.api_calls.append(f"{r.method} {r.url}"))
        page.on("response", self._note_live)

    def _note_live(self, resp: Any) -> None:
        """Record mode and cost_usd of every /v1/live/* answer the page receives."""
        if "/v1/live/" not in resp.url:
            return
        entry: dict[str, Any] = {"path": resp.url.split("/v1/live/")[1][:20], "status": resp.status}
        with contextlib.suppress(Exception):
            doc = resp.json()
            entry["mode"] = doc.get("mode")
            entry["cost_usd"] = float(doc.get("cost_usd") or 0.0)
        self.live_calls.append(entry)
        kind = live_kind(resp.url)
        if self.budget is not None and kind in self.budget_held:
            self.budget_held.remove(kind)
            self.budget.settle(kind, float(entry.get("cost_usd", 0.0)))

    def guard_live(self) -> None:
        """Smoke only: count every /v1/live/* call in the shared budget; abort what does not fit."""

        def handler(route: Any) -> None:
            kind = live_kind(route.request.url)
            if self.budget is None or kind == "":
                route.continue_()
            elif self.budget.reserve(kind):
                self.budget_held.append(kind)
                route.continue_()
            else:
                self.live_calls.append(
                    {"path": kind, "status": 0, "cost_usd": 0.0, "refused": True}
                )
                route.abort("blockedbyclient")

        self.page.context.route("**/v1/live/**", handler)

    def block_visits(self) -> None:
        """Stop /v1/visit pings reaching the server; keep their bodies to check the ref."""

        def handler(route: Any) -> None:
            self.visit_bodies.append(route.request.post_data)
            route.fulfill(status=204, body="")

        self.page.context.route("**/v1/visit", handler)

    @property
    def tag(self) -> str:
        """Prefix for check names."""
        return f"{self.engine} {self.width} {self.scheme}"

    def open(self) -> None:
        """Load the app and wait for the composer."""
        self.page.goto(self.args.url, wait_until="load")
        self.page.wait_for_selector(COMPOSER, timeout=30_000)

    def overflow(self) -> int:
        """Document scroll width minus viewport width (0 = no sideways scroll)."""
        return int(
            self.page.evaluate(
                "document.documentElement.scrollWidth - document.documentElement.clientWidth"
            )
        )

    def shot(self, name: str) -> None:
        """Save a screenshot for the artifact."""
        out = Path(self.args.out_dir) / "screenshots"
        out.mkdir(parents=True, exist_ok=True)
        fname = re.sub(r"[^A-Za-z0-9_.-]+", "-", f"{self.tag}-{name}")
        self.page.screenshot(path=str(out / f"{fname}.png"))

    def open_workflow(self, title: str) -> None:
        """Click a sidebar workflow by its title (opening the drawer first on a phone)."""
        nav = self.page.locator("nav[aria-label='Sections']")
        if nav.count() == 0 or not nav.first.is_visible():
            toggle = self.page.get_by_label("Toggle sidebar")
            if toggle.count():
                toggle.first.click()
                self.page.wait_for_timeout(400)
        btn = nav.get_by_role("button", name=re.compile(re.escape(title), re.I)).first
        if btn.count() == 0:
            raise SkipError(NOT_PRESENT, f"no sidebar entry named {title!r}")
        btn.click()
        self.page.wait_for_timeout(500)

    def ask(self, text: str) -> None:
        """Type a question into the composer and press Enter."""
        box = self.page.locator(COMPOSER)
        box.click()
        box.fill(text)
        box.press("Enter")


def turn_state(env: Env) -> dict[str, Any]:
    """The first chat turn as the person sees it: badge, note, error text, gated sentences."""
    page = env.page
    page.wait_for_selector(
        "[data-testid=mode-badge], [data-testid=turn-error], [data-testid=limit-banner]",
        timeout=45_000,
    )

    def text(testid: str) -> str:
        loc = page.locator(f"[data-testid={testid}]")
        return loc.first.inner_text().strip() if loc.count() else ""

    return {
        "badge": text("mode-badge"),
        "note": text("recorded-note"),
        "error": text("turn-error") or text("limit-banner"),
        "sentences": page.locator("[data-testid=answer-sentences] li").count(),
    }


def honest_failure(env: Env) -> str:
    """After a failed live call the page must say so: an error, or a labelled recorded run.

    What it must never do is present stored text as a live answer.
    """
    state = turn_state(env)
    if state["badge"] == "Live answer":
        raise AssertionError("a 'Live answer' badge is shown although the live call failed")
    if state["badge"] == "Recorded run":
        if not re.search(
            r"error|HTTP|could not|unavailable|offline|reach|limit", state["note"], re.I
        ):
            raise AssertionError("a recorded run is shown without saying the live call failed")
        return f"recorded run, labelled; note: {state['note'][:90]}"
    if not state["error"]:
        raise AssertionError("neither an error message nor a labelled recorded run is shown")
    return f"error shown: {state['error'][:90]}"


# --- scenarios ---------------------------------------------------------------------------------


def s_ai_sweep(env: Env) -> str:
    """The AI-device sweep view lists its rules and numbers."""
    env.open_workflow("AI device sweep")
    env.page.wait_for_selector(
        "[data-testid=sweep-stats], [data-testid=sweep-rules]", timeout=15_000
    )
    text = env.page.locator("main").inner_text()
    if "flagged" not in text.lower():
        raise AssertionError("the sweep view does not say how many device types were flagged")
    env.shot("ai-sweep")
    return "sweep view shows flagged count"


def direct_check(env: Env) -> int | None:
    """HTTP status of a direct GET of the local API's public check for LLZ (0 = no answer).

    None when no ``--api`` was given, so the page's complaint cannot be compared with the API.
    """
    api = str(getattr(env.args, "api", "") or "").rstrip("/")
    if not api:
        return None
    try:
        resp = env.page.request.get(
            f"{api}/v1/public/check_device_type?product_code=LLZ", timeout=20_000
        )
    except Exception:
        return 0
    return int(resp.status)


def s_check_device(env: Env) -> str:
    """Check any device type with LLZ against the local API: a result or an honest message."""
    env.open_workflow("Check any device type")
    env.page.fill("#live-code", "LLZ")
    env.page.get_by_role("button", name="Check device type").click()
    env.page.wait_for_function("!document.body.innerText.includes('Checking…')", timeout=60_000)
    text = env.page.locator("main").inner_text()
    if re.search(r"did not answer|No result is shown", text):
        env.shot("check-device-honest-failure")
        direct = direct_check(env)
        if direct == 200:
            raise AssertionError(
                "the page said the API did not answer, but a direct GET of the local API's "
                "public check answered HTTP 200: the page, not the source, is at fault"
            )
        if direct is None:
            raise AssertionError(
                "the page said the API did not answer and no --api was given to test it directly"
            )
        raise SkipError(
            KNOWN_GAP,
            f"the API did not answer within the page's 8 s limit and a direct GET of its public "
            f"check also failed (HTTP {direct}; openFDA unreachable from this runner); the page "
            "said so and showed no result. Not counted as a pass.",
        )
    if "LLZ" not in text:
        raise AssertionError("the answer does not name the device type")
    if not re.search(r"openFDA|stored|snapshot|reports", text, re.I):
        raise AssertionError("the answer shows neither a source nor counts")
    env.shot("check-device")
    return "LLZ answered"


def s_chat(env: Env) -> str:
    """Chat in recorded mode: two turns, the second carrying history; gate output is shown."""
    env.open()
    env.ask("What changed this week? Did reports suddenly increase for any device?")
    env.page.wait_for_selector("[data-testid=user-bubble]", timeout=15_000)
    env.page.wait_for_selector("[data-testid=live-turn]", timeout=45_000)
    env.page.wait_for_function("!document.querySelector('[data-testid=typing]')", timeout=45_000)
    state = turn_state(env)
    if not state["badge"] and not state["error"]:
        raise AssertionError("the turn has no Recorded run / Live answer badge and no error")
    if state["badge"] == "Recorded run" and not state["note"]:
        raise AssertionError("a recorded run is shown without saying why")
    sentences, unlinked, held = chat_counts(env)
    ok, why = chat_verdict(sentences, unlinked, bool(state["error"]), held)
    if not ok:
        env.shot("chat-FAILED")
        raise AssertionError(why)
    env.ask("And which device types?")
    env.page.wait_for_function(
        "document.querySelectorAll('[data-testid=live-turn]').length >= 2", timeout=45_000
    )
    env.shot("chat")
    return f"two turns; first turn: {why}"


def chat_counts(env: Env) -> tuple[int, int, bool]:
    """Wait for the first answer to finish writing; return (sentences, unlinked, withheld line)."""
    page = env.page
    page.wait_for_selector(
        "[data-testid=answer-sentences] li, [data-testid=turn-error], "
        "[data-testid=held-back], [data-testid=limit-banner]",
        timeout=60_000,
    )
    last, stable = (-1, -1), 0
    for _ in range(60):  # sentences are written word by word; wait until the count settles
        sentences = page.locator("[data-testid=answer-sentences] li").count()
        linked = page.locator(
            "[data-testid=answer-sentences] li [data-testid=sentence-links]"
        ).count()
        now = (sentences, linked)
        stable = stable + 1 if now == last else 0
        last = now
        if stable >= 3 and linked == sentences:
            break
        page.wait_for_timeout(1000)
    held = page.locator("[data-testid=held-back]").count() > 0
    return last[0], last[0] - last[1], held


def s_camera_upload(env: Env) -> str:
    """Upload a photo: possible matches appear, a person confirms one (never automatic)."""
    env.open()
    env.page.get_by_test_id("composer-camera").click()
    jpeg = make_jpeg()
    env.page.get_by_test_id("image-input").set_input_files(
        {"name": "label.jpg", "mimeType": "image/jpeg", "buffer": jpeg}
    )
    send = env.page.get_by_role("button", name="Send photo")
    if send.count() and send.first.is_visible():  # builds that ask before sending
        send.first.click()
    env.page.wait_for_selector(
        "[data-testid=match-card], [data-testid=no-match], [data-testid=search-failed], "
        "[data-testid=turn-error], [data-testid=camera-problem]",
        timeout=60_000,
    )
    cards = env.page.locator("[data-testid=match-card]").count()
    if cards == 0:
        explicit = env.page.locator("[data-testid=no-match], [data-testid=search-failed]")
        if explicit.count() == 0:
            env.shot("camera-NO-CARDS")
            raise AssertionError(
                "no possible-match card and no explicit no-match / search-failed element after "
                "the photo (an error or silence is not an accepted outcome)"
            )
        env.shot("camera-no-match")
        return f"no match cards; explicit element shown: {explicit.first.inner_text()[:80]!r}"
    if env.page.get_by_test_id("confirmed-block").count():
        raise AssertionError("a match was confirmed before a person chose one")
    env.page.get_by_role("button", name="Confirm this match").first.click()
    env.page.wait_for_selector("[data-testid=confirmed-block]", timeout=15_000)
    env.shot("camera-confirmed")
    return f"{cards} possible matches; one confirmed by click"


def s_mic(env: Env) -> str:
    """Microphone with a fake audio device: record, stop, an answer or an honest message."""
    if env.engine == "webkit":
        raise SkipError(KNOWN_GAP, "WebKit has no fake audio device in Playwright; not tested here")
    env.open()
    env.page.get_by_test_id("composer-mic").click()
    try:
        env.page.wait_for_selector("[data-testid=recording-bar]", timeout=8_000)
    except Exception as exc:
        problem = env.page.locator("[data-testid=voice-note], [data-testid=camera-problem]")
        if problem.count():
            said = problem.first.inner_text()[:80]
            if env.engine == "chromium":
                raise AssertionError(
                    f"chromium has a fake microphone but no recording bar appeared; page said: {said}"
                ) from exc
            raise SkipError(KNOWN_GAP, f"no fake microphone here; page said: {said}") from exc
        raise
    env.page.wait_for_timeout(1500)
    env.page.get_by_test_id("composer-mic").click()
    env.page.wait_for_selector(
        "[data-testid=live-turn], [data-testid=turn-error], [data-testid=voice-recorded]",
        timeout=60_000,
    )
    env.shot("mic")
    return "recorded 1.5 s of fake audio; the page answered"


def s_alert_bell(env: Env) -> str:
    """The alert bell opens the alert panel; Escape closes it."""
    env.open()
    bell = env.page.get_by_test_id("alert-bell")
    if bell.count() == 0:
        bell = env.page.locator("button[aria-label^='Alerts:']").first
    bell.first.click()
    env.page.wait_for_selector("#alert-list, [data-testid=alert-group]", timeout=10_000)
    env.shot("alert-bell")
    env.page.keyboard.press("Escape")
    env.page.wait_for_function("!document.querySelector('#alert-list')", timeout=5_000)
    return "bell opened the list; Escape closed it"


def s_our_devices(env: Env) -> str:
    """Our devices opens (simulated company data is labelled); Make it yours when present."""
    env.open_workflow("Our devices")
    text = env.page.locator("main").inner_text()
    if "simulated" not in text.lower() and "demo" not in text.lower():
        raise AssertionError("Our devices does not say its data is simulated")
    env.shot("our-devices")
    mine = env.page.get_by_role("button", name=re.compile("make it yours", re.I))
    if mine.count() == 0:
        env.rep.add(
            f"{env.tag}: Make it yours",
            NOT_PRESENT,
            "no 'Make it yours' button in this build",
            group="scenario",
            required=False,
        )
        return "Our devices shown; 'Make it yours' is not in this build"
    mine.first.click()
    env.page.wait_for_timeout(500)
    env.shot("make-it-yours")
    return "Our devices shown; 'Make it yours' opened"


def s_capa_pdf(env: Env) -> str:
    """The CAPA-need evidence PDF link exists and the file is a real PDF."""
    env.open_workflow("CAPA-need evidence")
    env.page.wait_for_timeout(500)
    link = env.page.locator("a[href*='.pdf']").first
    if link.count() == 0:
        strip = env.page.get_by_test_id("tabstrip")
        if strip.count() == 0:  # a phone keeps the artifacts pane closed
            toggle = env.page.get_by_label("Toggle artifacts")
            if toggle.count():
                toggle.first.click()
                env.page.wait_for_timeout(400)
        tab = env.page.get_by_test_id("tabstrip").get_by_text("Dossier", exact=True)
        if tab.count():
            tab.first.evaluate("e => e.click()")
            env.page.wait_for_timeout(600)
        link = env.page.locator("a[href*='.pdf']").first
    if link.count() == 0:
        raise AssertionError("no link to a PDF in the CAPA-need evidence view")
    href = link.get_attribute("href") or ""
    url = (
        href
        if href.startswith("http")
        else env.page.evaluate("h => new URL(h, location.href).href", href)
    )
    resp = env.page.request.get(url)
    head = resp.body()[:5]
    if resp.status != 200 or head != b"%PDF-":
        raise AssertionError(f"PDF link answered HTTP {resp.status}, starts {head!r}")
    env.shot("capa-pdf")
    return f"PDF link {href.rsplit('/', 1)[-1]} answered 200 and starts with %PDF-"


def s_feedback(env: Env) -> str:
    """Give feedback: rating, consent, a TEST comment; stored by the local API."""
    env.open()
    btn = env.page.get_by_role("button", name="Give feedback")
    if btn.count() == 0 or not btn.first.is_visible():
        menu = env.page.get_by_test_id("more-menu-button")
        if menu.count():
            menu.first.click()
            env.page.wait_for_timeout(300)
        btn = env.page.get_by_role("button", name=re.compile("give feedback|feedback", re.I))
    btn.first.click()
    env.page.wait_for_selector("[role=dialog]", timeout=10_000)
    env.page.locator("label:has(input[name=fb-rating][value='4'])").click()
    env.page.get_by_label("Comment").fill("TEST release-check entry")
    env.page.locator("input[name=fb-consent][value=no_quote]").check()
    with env.page.expect_response(re.compile(r"/v1/feedback$")) as resp_info:
        env.page.get_by_role("button", name="Send feedback").click()
    status = resp_info.value.status
    if status != 201:
        raise AssertionError(f"POST /v1/feedback answered HTTP {status}")
    env.shot("feedback-sent")
    return "TEST feedback stored (HTTP 201)"


def s_connect(env: Env) -> str:
    """The Connect-to-Muse page shows the MCP address and the demo key from the API."""
    env.open()
    btn = env.page.get_by_test_id("connect-button")
    if btn.count() == 0 or not btn.first.is_visible():
        menu = env.page.get_by_test_id("more-menu-button")
        if menu.count():
            menu.first.click()
            env.page.wait_for_timeout(300)
        btn = env.page.get_by_test_id("more-connect")
    btn.first.click()
    env.page.wait_for_selector("[data-testid=connect-view]", timeout=15_000)
    text = env.page.get_by_test_id("connect-view").inner_text()
    if "/mcp" not in text:
        raise AssertionError("the MCP address is not shown")
    if env.page.get_by_test_id("value-demo-key").count() == 0 and "key" not in text.lower():
        raise AssertionError("neither the demo key nor a key note is shown")
    env.shot("connect")
    return "connect page shows the MCP address"


def s_no_sideways_scroll(env: Env) -> str:
    """No horizontal scroll on the main views."""
    bad: list[str] = []
    env.open()
    if env.overflow() > 0:
        bad.append(f"home +{env.overflow()}px")
    for title in ("AI device sweep", "Check any device type", "Our devices", "CAPA-need evidence"):
        try:
            env.open_workflow(title)
        except SkipError:
            continue
        if env.overflow() > 0:
            bad.append(f"{title} +{env.overflow()}px")
    if bad:
        raise AssertionError("sideways scroll: " + ", ".join(bad))
    return "0 px on every view"


def s_axe(env: Env) -> str:
    """axe-core on the main views: serious or critical violations fail; all counts reported."""
    axe = Path(env.args.axe)
    if not axe.is_file():
        raise AssertionError(f"axe-core not found at {axe}: install it with npm in the job")
    totals = {"minor": 0, "moderate": 0, "serious": 0, "critical": 0, "unknown": 0}
    worst: list[str] = []
    for label, workflow in AXE_VIEWS:
        env.open()
        if workflow:
            env.open_workflow(workflow)
        env.page.add_script_tag(path=str(axe))
        results = env.page.evaluate("axe.run(document, {resultTypes: ['violations']})")
        counts = count_axe(results)
        for k, v in counts.items():
            totals[k] += v
        for v in results.get("violations", []):
            if v.get("impact") in ("serious", "critical"):
                worst.append(
                    f"{label}: {v.get('id')} ({v.get('impact')}, {len(v.get('nodes', []))} nodes)"
                )
    env.axe_totals = totals  # type: ignore[attr-defined]
    if axe_blocks(totals):
        raise AssertionError("; ".join(worst[:6]) + f" | totals {totals}")
    return f"no serious or critical violations; totals {totals}"


SCENARIOS: tuple[tuple[str, Callable[[Env], str]], ...] = (
    ("AI sweep", s_ai_sweep),
    ("check device type", s_check_device),
    ("chat (recorded mode, two turns)", s_chat),
    ("camera upload, matches, confirm", s_camera_upload),
    ("mic (fake audio)", s_mic),
    ("alert bell, alert panel", s_alert_bell),
    ("Our devices / Make it yours", s_our_devices),
    ("CAPA-need evidence PDF link", s_capa_pdf),
    ("feedback form", s_feedback),
    ("Connect to Muse page", s_connect),
    ("no sideways scroll", s_no_sideways_scroll),
    ("axe-core accessibility", s_axe),
)
SMOKE = (
    "chat (recorded mode, two turns)",
    "camera upload, matches, confirm",
    "alert bell, alert panel",
)


# --- error states (route mocking) --------------------------------------------------------------


def e_openfda_down(env: Env) -> str:
    """The server cannot reach openFDA (502): an honest message, no counts, no crash."""
    env.page.route(
        PUBLIC_CHECK,
        lambda r: r.fulfill(
            status=502,
            content_type="application/json",
            body=json.dumps(
                {"error": {"code": "source_unavailable", "message": "openFDA is not reachable."}}
            ),
        ),
    )
    env.open()
    env.open_workflow("Check any device type")
    env.page.fill("#live-code", "QIH")
    env.page.get_by_role("button", name="Check device type").click()
    env.page.wait_for_function("!document.body.innerText.includes('Checking…')", timeout=30_000)
    text = env.page.locator("main").inner_text()
    if not re.search(
        r"returned HTTP|No result is shown|could not|cannot|can't|unavailable|not reachable|try again|error",
        text,
        re.I,
    ):
        raise AssertionError("no honest message when openFDA is down")
    if re.search(r"\d+ reports? received", text):
        raise AssertionError("counts are shown although openFDA was down")
    env.shot("err-openfda-down")
    return "honest message, no counts"


def e_meta_down(env: Env) -> str:
    """The live model route fails (503) or never answers: honest message, no invented answer."""
    env.page.route(
        ASK_PATH,
        lambda r: r.fulfill(
            status=503,
            content_type="application/json",
            body=json.dumps(
                {"code": "unavailable", "message": "No answer is available right now."}
            ),
        ),
    )
    env.open()
    env.ask("What changed this week for LLZ?")
    state = honest_failure(env)
    env.shot("err-meta-down")
    return state


def e_meta_timeout(env: Env) -> str:
    """The route is aborted (a timeout): honest message, the page still works."""
    env.page.route(ASK_PATH, lambda r: r.abort("timedout"))
    env.open()
    env.ask("What changed this week for LLZ?")
    state = honest_failure(env)
    env.page.locator(COMPOSER).fill("still typing")
    return state + "; the composer still works"


def e_cap_reached(env: Env) -> str:
    """The daily cap is reached (429 with Retry-After): the limit is said plainly."""
    body = {"code": "rate_limited", "message": "Daily live limit reached.", "retry_after_s": 3600}
    env.page.route(
        ASK_PATH,
        lambda r: r.fulfill(
            status=429,
            headers={"Retry-After": "3600"},
            content_type="application/json",
            body=json.dumps(body),
        ),
    )
    env.open()
    env.ask("What changed this week for LLZ?")
    env.page.wait_for_selector(
        "[data-testid=turn-error], [data-testid=limit-banner]", timeout=30_000
    )
    text = env.page.locator("body").inner_text()
    if not re.search(r"limit|too many|try again|recorded", text, re.I):
        raise AssertionError("the daily limit is not explained")
    env.shot("err-cap")
    return "limit message shown"


def e_slow_network(env: Env) -> str:
    """A slow network: the app still loads and answers, with no sideways scroll."""
    delay_ms = 1500
    if env.engine == "chromium":
        cdp = env.page.context.new_cdp_session(env.page)
        cdp.send(
            "Network.emulateNetworkConditions",
            {
                "offline": False,
                "latency": 400,
                "downloadThroughput": 50_000,
                "uploadThroughput": 25_000,
            },
        )
        how = "Chrome DevTools slow 3G (400 ms, 50 kB/s)"
    else:

        def slow(route: Any) -> None:
            time.sleep(delay_ms / 1000)
            route.continue_()

        env.page.route("**/v1/**", slow)
        how = f"{delay_ms} ms added to every API call (this engine has no network throttle)"
    started = time.monotonic()
    env.page.goto(env.args.url, wait_until="load", timeout=120_000)
    env.page.wait_for_selector(COMPOSER, timeout=120_000)
    took = time.monotonic() - started
    if env.overflow() > 0:
        raise AssertionError("sideways scroll on a slow network")
    return f"loaded in {took:.1f} s with {how}"


def e_offline(env: Env) -> str:
    """Offline after load: asking shows an honest message and no answer."""
    env.open()
    env.page.context.set_offline(True)
    try:
        env.ask("What changed this week for LLZ?")
        msg = honest_failure(env)
    finally:
        env.page.context.set_offline(False)
    env.shot("err-offline")
    return "offline: " + msg[:100]


ERROR_SCENARIOS: tuple[tuple[str, Callable[[Env], str]], ...] = (
    ("error: openFDA down", e_openfda_down),
    ("error: Meta down (503)", e_meta_down),
    ("error: Meta timeout", e_meta_timeout),
    ("error: daily cap reached (429)", e_cap_reached),
    ("error: slow network", e_slow_network),
    ("error: offline", e_offline),
)


# --- harness -----------------------------------------------------------------------------------


def make_jpeg() -> bytes:
    """A small photo with an EXIF block (the page must not need it; the server drops it)."""
    from PIL import Image, ImageDraw

    img = Image.new("RGB", (800, 600), (235, 235, 240))
    ImageDraw.Draw(img).text((40, 40), "TEST LABEL GM505NA", fill=(20, 20, 20))
    exif = Image.Exif()
    exif[0x010F] = "release-check"
    buf = io.BytesIO()
    img.save(buf, format="JPEG", exif=exif)
    return buf.getvalue()


def run_scenario(rep: Report, env: Env, name: str, fn: Callable[[Env], str], group: str) -> None:
    """Run one scenario and record PASS, FAIL, KNOWN_GAP or NOT_PRESENT."""
    label = f"{env.tag}: {name}"
    errors_before = len(env.page_errors)
    try:
        detail = fn(env)
        if len(env.page_errors) > errors_before:
            rep.add(label, FAIL, "uncaught page error: " + env.page_errors[-1], group=group)
        else:
            rep.add(label, PASS, detail, group=group)
    except SkipError as skip:
        rep.add(label, skip.status, skip.why, group=group, required=skip.status != KNOWN_GAP)
    except Exception as exc:
        with contextlib.suppress(Exception):
            env.shot("FAILED-" + re.sub(r"\W+", "-", name))
        rep.add(label, FAIL, f"{type(exc).__name__}: {str(exc)[:300]}", group=group)


def new_context(pw: Any, browser: Any, engine: str, width: int, scheme: str) -> Any:
    """A browser context with the viewport, colour scheme and media permissions."""
    w, h = VIEWPORTS[width]
    kw: dict[str, Any] = {
        "viewport": {"width": w, "height": h},
        "color_scheme": scheme,
        "service_workers": "block",
    }
    if width == 390:
        kw["is_mobile"] = engine != "firefox"
        kw["has_touch"] = True
    try:
        return browser.new_context(permissions=["microphone", "camera"], **kw)
    except Exception:
        return browser.new_context(**kw)


def launch(pw: Any, engine: str) -> Any:
    """Launch an engine with fake media where it supports it."""
    if engine == "chromium":
        return pw.chromium.launch(args=CHROMIUM_ARGS)
    if engine == "firefox":
        return pw.firefox.launch(firefox_user_prefs=FIREFOX_PREFS)
    return pw.webkit.launch()


def main(argv: list[str] | None = None) -> int:
    """Run the suite; write ``e2e.json`` / ``e2e.md`` and screenshots; exit 1 on any failure."""
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0] if __doc__ else "")
    ap.add_argument(
        "--url", required=True, help="the built web app, for example http://127.0.0.1:4173"
    )
    ap.add_argument("--api", default="", help="the API the build points at (reported only)")
    ap.add_argument("--axe", default="web/node_modules/axe-core/axe.min.js")
    ap.add_argument("--out-dir", default="release-out")
    ap.add_argument("--suite", choices=("full", "smoke"), default="full")
    ap.add_argument("--engines", default=",".join(ENGINES))
    ap.add_argument("--widths", default="1440,390")
    ap.add_argument("--schemes", default="light,dark")
    ap.add_argument("--stem", default="e2e")
    ap.add_argument(
        "--test-ref",
        default="",
        help="smoke suite: the TEST ref the visit pings must carry (default TEST-0)",
    )
    ap.add_argument(
        "--live-budget",
        default="",
        help="smoke suite: 'usd,asks,photos,voice' left in the run's shared budget; every "
        "/v1/live/* call the browser makes is counted in it and refused when it does not fit",
    )
    args = ap.parse_args(argv)
    args.budget = None
    if args.live_budget:
        usd, asks, photos, voice = args.live_budget.split(",")
        args.budget = Budget(
            max_usd=float(usd), limits={"ask": int(asks), "photo": int(photos), "voice": int(voice)}
        )
    if args.suite == "smoke":
        args.engines, args.schemes = "chromium", "light"
    rep = Report("e2e" if args.suite == "full" else "smoke web quick pass")
    rep.metrics.update(url=args.url, api=args.api, suite=args.suite)
    from playwright.sync_api import sync_playwright

    axe_totals: dict[str, int] = {}
    smoke = args.suite == "smoke"
    visit_bodies: list[str | None] = []
    live_calls: list[dict[str, Any]] = []
    with sync_playwright() as pw:
        for engine in args.engines.split(","):
            try:
                browser = launch(pw, engine)
            except Exception as exc:
                rep.add(
                    f"{engine}: browser launches", FAIL, f"{type(exc).__name__}: {str(exc)[:200]}"
                )
                continue
            rep.metrics[f"{engine}_version"] = browser.version
            for width in (int(w) for w in args.widths.split(",")):
                for scheme in args.schemes.split(","):
                    scenarios = [s for s in SCENARIOS if args.suite == "full" or s[0] in SMOKE]
                    todo = [("scenario", n, f) for n, f in scenarios]
                    if args.suite == "full":
                        todo += [("error state", n, f) for n, f in ERROR_SCENARIOS]
                    for group, name, fn in todo:
                        ctx = new_context(pw, browser, engine, width, scheme)
                        page = ctx.new_page()
                        page.set_default_timeout(30_000)
                        env = Env(engine, width, scheme, page, args, rep)
                        if smoke:  # a smoke run must not write visits to the real server
                            env.block_visits()
                            if args.budget is not None:
                                env.guard_live()
                        try:
                            if group == "scenario":
                                env.open()
                            run_scenario(rep, env, name, fn, group)
                        except Exception as exc:
                            rep.add(
                                f"{env.tag}: {name}",
                                FAIL,
                                f"could not open the app: {str(exc)[:200]}",
                                group=group,
                            )
                        finally:
                            for k, v in (getattr(env, "axe_totals", {}) or {}).items():
                                axe_totals[k] = axe_totals.get(k, 0) + v
                            visit_bodies += env.visit_bodies
                            live_calls += env.live_calls
                            ctx.close()
            browser.close()
    if smoke:
        ok, why = visits_all_test(visit_bodies, args.test_ref or TEST_REF)
        rep.add("no non-TEST visit ping is sent", PASS if ok else FAIL, why, group="scenario")
    for c in live_calls:
        if c.get("refused"):
            rep.add(f"live {c['path']} call from the browser", FAIL, SKIPPED_BUDGET, group="live")
    rep.metrics["live_calls"] = live_calls
    rep.metrics["live_cost_usd"] = round(sum(c.get("cost_usd", 0.0) for c in live_calls), 6)
    if args.suite == "full":
        rep.metrics["axe_violations_all_views_all_combinations"] = axe_totals
    rep.write(Path(args.out_dir), args.stem)
    return rep.exit_code()


if __name__ == "__main__":
    sys.exit(main())
