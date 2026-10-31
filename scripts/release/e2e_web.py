"""Browser checks of the built web app against a local API (Playwright, Python).

HACKATHON-BUILT — Meta Global AI Developer Hackathon (Oct 26 – Nov 4, 2026).

The release-check "e2e" job builds ``web/`` with ``VITE_MAUDESIGNAL_API_BASE`` pointing at a
local API started with the ``e2e`` profile of ``serve_api.py`` (real code, no Meta key, so
live questions are answered from recordings), serves the build, and runs:

    python3 scripts/release/e2e_web.py --url http://127.0.0.1:4173 --api http://127.0.0.1:8001 \
        --axe web/node_modules/axe-core/axe.min.js --out-dir release-out

For each engine (chromium, firefox, webkit) x width (1440, 390) x colour scheme (light, dark):
AI sweep, Check any device type, chat (recorded mode, two turns with history), the chat tiers
(greeting -> canned reply and badge; direct lookup -> badge and openFDA links; an open question
reaches the live route, mocked), camera upload
to possible matches to confirm, microphone (fake audio device; webkit has none, which is
reported as KNOWN_GAP, never as a pass), alert bell to alert panel, Our devices ("Make it
yours" when present), the CAPA-need evidence PDF link, the feedback form (submitted to the
local API), the Connect-to-Muse page, no sideways scroll on every view, and an axe-core scan of
the main views (serious or critical violations fail; the counts are reported).

The message box with the "+" menu (``VITE_FEATURE_COMPOSER_MENU``, on by default) has its own
scenarios, all with route mocks and fake media (no model call): the menu by keyboard (open,
arrows, Escape returns focus); voice Cancel sends no ``/v1/live/voice`` request; Pause and
Resume hold and restart the timer; Stop puts the transcript in the box, it is edited, and one
ask request carries the edited text; Take photo opens the live camera on a computer and the
phone camera input at 390; a refused camera falls back to the file picker with a reason; the
thumbnail's remove button drops the photo; "Research the web" is hidden when ``/v1/health``
does not offer it. On a build with the earlier composer they are NOT_PRESENT, not required.

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


LIVE_ROUTES = ("**/v1/live/**", "**/v1/label*", "**/v1/voice*")  # older clients post /v1/label


def live_kind(url: str) -> str:
    """Budget kind (ask, photo, voice) of a live-call URL; empty when it is none of them.

    Covers ``/v1/live/<ask|label|voice>`` and the older ``/v1/label`` and ``/v1/voice`` paths,
    so a deployment whose client uses them is counted in the budget too.
    """
    path = url.split("?")[0].rstrip("/")
    if "/v1/live/" in path:
        return KIND_OF_PATH.get(path.split("/v1/live/")[-1], "")
    if path.endswith("/v1/label"):
        return "photo"
    if path.endswith("/v1/voice"):
        return "voice"
    return ""


RECORDED_NOTE = (
    "Recorded sample used by the smoke test: no live model call was made. "
    "It is not an answer about any real device."
)
_MOCK_LINK = {
    "label": "openFDA device event search",
    "url": "https://api.fda.gov/device/event.json",
}
_MOCK_TRACE = [
    {
        "step": "Closest recorded answer",
        "model": None,
        "ms": 0,
        "status": "ok",
        "note": "smoke-test route mock",
    }
]


def recorded_body(kind: str) -> dict[str, Any]:
    """A recorded-mode body for a mocked /v1/live/<kind> call (no figures, no live model)."""
    base: dict[str, Any] = {
        "mode": "recorded",
        "not_medical_advice": "Not medical advice. A signal for human regulatory review.",
        "recorded_note": RECORDED_NOTE,
        "trace": _MOCK_TRACE,
        "cost_usd": None,
        "limits": {"remaining_today": None},
    }
    speakable = [{"text": "This is a recorded sample answer.", "links": [_MOCK_LINK]}]
    answer = {
        "speakable": speakable,
        "withheld": [],
        "spoken_text": "This is a recorded sample answer.",
    }
    if kind == "photo":
        cand = {
            "source": "510k",
            "k_number": None,
            "record_id": "sample",
            "applicant": "Sample applicant",
            "device_name": "Smoke-test sample device",
            "product_code": None,
            "why_matched": ["recorded sample for the smoke test"],
            "why_not_matched": [],
            "links": [_MOCK_LINK],
        }
        return base | {
            # same shape as the real /v1/live/label answer (connector/live.py): the web app
            # rejects a reading without a "fields" object
            "reading": {"legibility": "legible", "fields": {}},
            "matches": {"status": "needs_person_to_confirm", "candidates": [cand]},
            "confirmed": None,
        }
    if kind == "voice":
        return base | {"transcript": "recorded sample", "answer": answer}
    return base | {"answer": answer}


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

    def __init__(self, status: str, why: str, required: bool | None = None) -> None:
        """Keep the status (KNOWN_GAP or NOT_PRESENT), the reason and whether it is required.

        ``required`` defaults to "everything but KNOWN_GAP"; a feature that is switched off by
        design (the "+" menu on a classic build) passes ``required=False``.
        """
        super().__init__(why)
        self.status, self.why = status, why
        self.required = status != KNOWN_GAP if required is None else required


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
        kind = live_kind(resp.url)
        if not kind:
            return
        entry: dict[str, Any] = {"path": kind, "status": resp.status}
        known: float | None = None  # None: no cost came back, so the hold stays as spent
        with contextlib.suppress(Exception):
            doc = resp.json()
            entry["mode"] = doc.get("mode")
            entry["cost_usd"] = float(doc.get("cost_usd") or 0.0)
            if resp.status == 200 and doc.get("cost_usd") is not None:
                known = entry["cost_usd"]
        self.live_calls.append(entry)
        if self.budget is not None and kind in self.budget_held:
            self.budget_held.remove(kind)
            self.budget.settle(kind, known)

    def settle_unanswered(self) -> None:
        """Calls reserved but never answered (page closed first): the full hold stays as spent."""
        if self.budget is None:
            return
        while self.budget_held:
            self.budget.settle(self.budget_held.pop(), None)

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

        for pattern in LIVE_ROUTES:
            self.page.context.route(pattern, handler)

    def mock_live(self) -> None:
        """Smoke: answer every /v1/live/* call from the browser with a recorded body, no spend.

        The browser pass runs in recorded mode through route mocking, so it makes no model call
        and costs $0; the real live routes are checked only by smoke.yml after a deploy, through the
        shared budget. Each call is logged with ``mocked: true`` so a report shows it.
        """

        def handler(route: Any) -> None:
            kind = live_kind(route.request.url)
            if kind == "":
                route.continue_()
                return
            self.live_calls.append(
                {"path": kind, "status": 200, "mode": "recorded", "cost_usd": 0.0, "mocked": True}
            )
            route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps(recorded_body(kind)),
            )

        for pattern in LIVE_ROUTES:
            self.page.context.route(pattern, handler)

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


UPSTREAM_DOWN = frozenset({0, 502, 503, 504})  # no answer, bad gateway, unavailable, timeout


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
        if direct not in UPSTREAM_DOWN:
            raise AssertionError(
                f"the page said the API did not answer and a direct GET of the public check "
                f"answered HTTP {direct}, which is not an 'openFDA unreachable' status "
                f"{sorted(UPSTREAM_DOWN)}: a missing or broken route, not a known gap"
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


# --- chat tiers (docs/hackathon/CHAT_TIERS.md) -----------------------------------------------

BADGE_CANNED = "No FDA facts in this message"
BADGE_DIRECT = "Direct FDA lookup — no AI"
OPEN_QUESTION = "Which kinds of problems do the LLZ reports describe?"
MOCK_LIVE_TEXT = "This is a mocked live answer for the browser test, not about any device."


def mocked_live_body() -> dict[str, Any]:
    """A tier-4 answer for a mocked /v1/live/ask (no figures; cost unknown, so null)."""
    return {
        "mode": "live",
        "tier": "live",
        "not_medical_advice": True,
        "trace": [
            {
                "step": "Muse Spark answers from stored records",
                "model": "muse-spark-1.3",
                "ms": 0,
                "status": "ok",
                "note": "e2e route mock",
            },
        ],
        "cost_usd": None,
        "limits": {"remaining_today": 29, "resets_utc": "2026-11-01T00:00:00Z"},
        "answer": {
            "speakable": [{"text": MOCK_LIVE_TEXT, "links": [_MOCK_LINK]}],
            "withheld": [],
            "spoken_text": MOCK_LIVE_TEXT,
        },
    }


def tier_answer(env: Env, tier: str) -> dict[str, Any]:
    """Wait for the first answer of ``tier`` to be written out; its badge, chips, cost, links."""
    page = env.page
    sel = f"[data-testid=live-answer][data-tier={tier}]"
    page.wait_for_selector(sel, timeout=45_000)
    # the cost line and the chips appear once every sentence is written out; a mocked live
    # answer has no cost (null), so its advice line is the last thing to wait for
    done = (
        f"{sel} [data-testid=answer-cost]" if tier != "live" else f"{sel} [data-testid=not-advice]"
    )
    page.wait_for_selector(done, timeout=45_000)
    page.wait_for_timeout(1500)  # sentences are written word by word
    ans = page.locator(sel).first
    links = [
        ans.locator("[data-testid=sentence-links] a").nth(i).get_attribute("href") or ""
        for i in range(ans.locator("[data-testid=sentence-links] a").count())
    ]
    cost = ans.locator("[data-testid=answer-cost]")
    return {
        "badge": ans.locator("[data-testid=mode-badge]").inner_text().strip(),
        "sentences": ans.locator("[data-testid=answer-sentences] li").count(),
        "chips": ans.locator("[data-testid=suggestion-chip]").count(),
        "cost": cost.first.inner_text().strip() if cost.count() else "",
        "links": links,
    }


def s_chat_greeting(env: Env) -> str:
    """Tier 1: a greeting reaches the API and comes back as a fixed reply, its badge, chips, $0."""
    asked: list[str] = []
    env.page.on(
        "request", lambda r: asked.append(r.post_data or "") if "/v1/live/ask" in r.url else None
    )
    env.open()
    env.ask("namaste")
    st = tier_answer(env, "canned")
    if st["badge"] != BADGE_CANNED:
        raise AssertionError(f"badge is {st['badge']!r}, not {BADGE_CANNED!r}")
    if st["chips"] != 4:
        raise AssertionError(f"{st['chips']} suggestion chips, expected 4")
    if "$0.0000" not in st["cost"]:
        raise AssertionError(f"cost line is {st['cost']!r}")
    if not any("namaste" in a for a in asked):
        raise AssertionError("the greeting was not sent to /v1/live/ask")
    env.shot("chat-greeting")
    return f"canned reply, badge shown, {st['chips']} chips, {st['cost']}"


def s_chat_direct(env: Env) -> str:
    """Tier 2: a simple lookup is answered directly, every sentence linked to openFDA, $0."""
    env.open()
    env.ask("Recalls for QIH")
    st = tier_answer(env, "direct")
    if st["badge"] != BADGE_DIRECT:
        raise AssertionError(f"badge is {st['badge']!r}, not {BADGE_DIRECT!r}")
    sentences, unlinked, _held = chat_counts(env)
    if sentences == 0 or unlinked:
        raise AssertionError(f"{sentences} sentence(s), {unlinked} without a link")
    if not st["links"] or not all(h.startswith("https://api.fda.gov/") for h in st["links"]):
        raise AssertionError(f"links are not openFDA links: {st['links'][:3]}")
    if "$0.0000" not in st["cost"]:
        raise AssertionError(f"cost line is {st['cost']!r}")
    env.shot("chat-direct")
    return f"direct lookup, {sentences} linked sentence(s), {len(st['links'])} openFDA link(s)"


def s_chat_live_mocked(env: Env) -> str:
    """Tier 4: an open question reaches /v1/live/ask (mocked here, no model call, $0 spent)."""
    captured: list[dict[str, Any]] = []

    def handler(route: Any) -> None:
        with contextlib.suppress(ValueError):
            captured.append(json.loads(route.request.post_data or "{}"))
        route.fulfill(
            status=200, content_type="application/json", body=json.dumps(mocked_live_body())
        )

    env.page.route(ASK_PATH, handler)
    env.open()
    env.ask(OPEN_QUESTION)
    st = tier_answer(env, "live")
    if not captured or captured[0].get("question") != OPEN_QUESTION:
        raise AssertionError("the open question did not reach /v1/live/ask")
    if st["badge"] != "Live answer":
        raise AssertionError(f"badge is {st['badge']!r}, not 'Live answer'")
    if st["chips"]:
        raise AssertionError("a live answer shows suggestion chips it was not sent")
    env.shot("chat-live-mocked")
    return "open question sent to the live route; live badge shown (route mocked)"


def s_camera_upload(env: Env) -> str:
    """Upload a photo: possible matches appear, a person confirms one (never automatic)."""
    env.open()
    jpeg = make_jpeg()
    photo = {"name": "label.jpg", "mimeType": "image/jpeg", "buffer": jpeg}
    if has_menu(env):  # + menu -> Upload photo -> thumbnail -> Send photo
        with env.page.expect_file_chooser(timeout=10_000) as chooser:
            menu_item(env, "upload-photo")
        chooser.value.set_files(photo)
        env.page.wait_for_selector("[data-testid=photo-thumb]", timeout=15_000)
    else:
        env.page.get_by_test_id("composer-camera").click()
        env.page.get_by_test_id("image-input").set_input_files(photo)
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
    if has_menu(env):
        start_voice(env)
        env.page.wait_for_timeout(1500)
        env.page.get_by_test_id("voice-stop").click()
        env.page.wait_for_function(
            "(() => { const t = document.querySelector(\"textarea[aria-label='Ask a question']\");"
            " return (t && t.value.trim().length > 0)"
            " || !!document.querySelector('[data-testid=voice-problem], [data-testid=live-turn]') })()",
            timeout=60_000,
        )
        env.shot("mic")
        box = env.page.locator(COMPOSER)
        if box.count() and box.input_value().strip():
            return "recorded 1.5 s of fake audio; the transcript is in the box, nothing sent"
        problem = env.page.locator("[data-testid=voice-problem]")
        if problem.count():
            return "recorded 1.5 s of fake audio; honest message: " + problem.inner_text()[:100]
        return "recorded 1.5 s of fake audio; the page answered (one-call voice)"
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


# --- the message box with the "+" menu (route mocks, fake media; no model call) ----------------

PLUS = "[data-testid=composer-plus]"
VOICE_ROUTE = "**/v1/live/voice"
HEALTH_ROUTE = "**/v1/health"
HEARD = "What changed this week for LLZ?"
EDITED = "What changed this week for LLZ, by problem kind?"
CORS_ANY = {"access-control-allow-origin": "*"}


def has_menu(env: Env) -> bool:
    """True when this build shows the message box with the "+" menu."""
    return env.page.locator(PLUS).count() > 0


def need_menu(env: Env) -> None:
    """Skip (not required) on a build with the earlier composer (the switch is off)."""
    if not has_menu(env):
        raise SkipError(
            NOT_PRESENT,
            "earlier composer in this build (VITE_FEATURE_COMPOSER_MENU off or ?composer=classic)",
            required=False,
        )


def menu_item(env: Env, item: str) -> None:
    """Open the "+" menu and choose one item by its id."""
    env.page.locator(PLUS).click()
    env.page.get_by_test_id(f"menu-{item}").click()


def mock_health(env: Env, *, research: bool = False, transcribe_only: bool = True) -> None:
    """Answer GET /v1/health with the optional features under test."""
    features: dict[str, bool] = {"voice_transcribe_only": transcribe_only}
    if research:
        features["research"] = True
    body = {"status": "ok", "service": "maudesignal-connector", "features": features}
    env.page.route(
        HEALTH_ROUTE,
        lambda r: r.fulfill(
            status=200, headers=CORS_ANY, content_type="application/json", body=json.dumps(body)
        ),
    )


def transcribe_body() -> dict[str, Any]:
    """A transcribe-only voice answer (the words only, no answer)."""
    return {
        "mode": "live",
        "transcribe_only": True,
        "not_medical_advice": True,
        "heard": HEARD,
        "did_you_mean": [],
        "trace": [
            {
                "step": "Muse Voice Transcribe",
                "model": "muse-voice-transcribe-1.0",
                "ms": 0,
                "status": "ok",
            }
        ],
        "cost_usd": None,
        "limits": {"remaining_today": 9, "resets_utc": "2026-11-01T00:00:00Z"},
    }


def mock_voice(env: Env) -> list[str]:
    """Answer /v1/live/voice with a transcript; returns the list the requests are counted in."""
    seen: list[str] = []

    def handler(route: Any) -> None:
        seen.append(route.request.method)
        route.fulfill(
            status=200,
            headers=CORS_ANY,
            content_type="application/json",
            body=json.dumps(transcribe_body()),
        )

    env.page.route(VOICE_ROUTE, handler)
    return seen


def start_voice(env: Env) -> None:
    """Choose Ask by voice in the + menu; the recording bar replaces the box (or a gap is reported)."""
    menu_item(env, "voice")
    try:
        env.page.wait_for_selector("[data-testid=voice-bar]", timeout=8_000)
    except Exception as exc:
        problem = env.page.locator("[data-testid=voice-problem]")
        said = problem.first.inner_text()[:80] if problem.count() else "no message"
        if env.engine == "chromium":
            raise AssertionError(
                f"chromium has a fake microphone but no recording bar appeared; page said: {said}"
            ) from exc
        raise SkipError(KNOWN_GAP, f"no fake microphone here; page said: {said}") from exc


def voice_engine(env: Env) -> None:
    """WebKit has no fake microphone in Playwright."""
    if env.engine == "webkit":
        raise SkipError(KNOWN_GAP, "WebKit has no fake audio device in Playwright; not tested here")


def s_plus_menu(env: Env) -> str:
    """The "+" menu by keyboard: Enter opens on the first item, arrows move, Escape closes."""
    mock_health(env)
    env.open()
    need_menu(env)
    page = env.page
    for old in ("composer-camera", "composer-mic"):
        if page.get_by_test_id(old).count():
            raise AssertionError(f"the separate {old} button is still shown next to the + menu")
    env.shot("composer-closed")
    plus = page.locator(PLUS)
    if plus.get_attribute("aria-haspopup") != "menu" or not plus.get_attribute("aria-label"):
        raise AssertionError("the + button is not a labelled menu button")
    plus.focus()
    page.keyboard.press("Enter")
    page.wait_for_selector("[role=menu]", timeout=5_000)
    if plus.get_attribute("aria-expanded") != "true":
        raise AssertionError("aria-expanded is not true while the menu is open")
    items = page.locator("[role=menu] [role^=menuitem]")
    names = [items.nth(i).inner_text().split("\n")[0] for i in range(items.count())]
    for want in ("Take photo", "Upload photo", "Try a sample label", "Ask by voice"):
        if want not in names:
            raise AssertionError(f"menu item {want!r} missing: {names}")

    def focused() -> str:
        return str(
            page.evaluate("document.activeElement && document.activeElement.innerText") or ""
        )

    if "Take photo" not in (focused() or ""):
        raise AssertionError("Enter did not put focus on the first item")
    page.keyboard.press("ArrowDown")
    if "Upload photo" not in (focused() or ""):
        raise AssertionError("ArrowDown did not move to the next item")
    page.keyboard.press("End")
    if "Ask by voice" not in (focused() or ""):
        raise AssertionError("End did not move to the last item")
    env.shot("composer-menu-open")
    page.keyboard.press("Escape")
    page.wait_for_selector("[role=menu]", state="detached", timeout=5_000)
    back = page.evaluate("document.activeElement && document.activeElement.dataset.testid")
    if back != "composer-plus":
        raise AssertionError(f"focus did not return to the + button (it is on {back!r})")
    return f"menu of {len(names)} items; Enter, ArrowDown, End, Escape and focus return work"


def s_voice_cancel(env: Env) -> str:
    """Cancel discards the recording: no /v1/live/voice request is made."""
    voice_engine(env)
    seen = mock_voice(env)
    mock_health(env)
    env.open()
    need_menu(env)
    start_voice(env)
    env.page.wait_for_timeout(1200)
    env.page.get_by_test_id("voice-cancel").click()
    env.page.wait_for_selector("[data-testid=message-box]", timeout=5_000)
    env.page.wait_for_timeout(800)
    if seen:
        raise AssertionError(f"{len(seen)} /v1/live/voice request(s) after Cancel")
    if env.page.locator(COMPOSER).input_value():
        raise AssertionError("text appeared in the box after Cancel")
    return "recording cancelled; no /v1/live/voice request; the box is back and empty"


def _timer(env: Env) -> str:
    return env.page.get_by_test_id("voice-timer").inner_text().strip()


def s_voice_pause_resume(env: Env) -> str:
    """Pause holds the timer; Resume starts it again (MediaRecorder pause and resume)."""
    voice_engine(env)
    seen = mock_voice(env)
    mock_health(env)
    env.open()
    need_menu(env)
    start_voice(env)
    env.page.wait_for_timeout(2200)
    env.shot("recording")
    pause = env.page.get_by_test_id("voice-pause")
    if pause.count() == 0:
        raise SkipError(KNOWN_GAP, "this browser's MediaRecorder cannot pause", required=False)
    pause.click()
    env.page.wait_for_selector("[data-testid=voice-bar][data-state=paused]", timeout=5_000)
    held = _timer(env)
    env.page.wait_for_timeout(2200)
    if _timer(env) != held:
        raise AssertionError(f"the timer moved while paused ({held} -> {_timer(env)})")
    env.shot("recording-paused")
    if env.page.get_by_test_id("voice-pause").get_attribute("aria-label") != "Resume recording":
        raise AssertionError("the pause button does not offer Resume while paused")
    env.page.get_by_test_id("voice-pause").click()
    env.page.wait_for_selector("[data-testid=voice-bar][data-state=recording]", timeout=5_000)
    env.page.wait_for_timeout(2200)
    resumed = _timer(env)
    if resumed == held:
        raise AssertionError("the timer did not start again after Resume")
    env.page.get_by_test_id("voice-cancel").click()
    if seen:
        raise AssertionError("a voice request was sent although the recording was cancelled")
    return f"paused at {held}, held for 2 s, resumed and reached {resumed}"


def s_voice_transcript_send(env: Env) -> str:
    """Stop -> the transcript is in the box -> edited -> Send: one ask with the edited text."""
    voice_engine(env)
    voice = mock_voice(env)
    asked: list[dict[str, Any]] = []

    def ask(route: Any) -> None:
        with contextlib.suppress(ValueError):
            asked.append(json.loads(route.request.post_data or "{}"))
        route.fulfill(
            status=200,
            headers=CORS_ANY,
            content_type="application/json",
            body=json.dumps(mocked_live_body()),
        )

    env.page.route(ASK_PATH, ask)
    mock_health(env)
    env.open()
    need_menu(env)
    start_voice(env)
    env.page.wait_for_timeout(1500)
    env.page.get_by_test_id("voice-stop").click()
    box = env.page.locator(COMPOSER)
    env.page.wait_for_function(
        "want => { const t = document.querySelector(\"textarea[aria-label='Ask a question']\");"
        " return !!t && t.value === want }",
        arg=HEARD,
        timeout=20_000,
    )
    if asked:
        raise AssertionError("an ask was sent before the person pressed Send")
    if len(voice) != 1:
        raise AssertionError(f"{len(voice)} voice requests for one recording")
    env.shot("transcript-in-box")
    box.fill(EDITED)
    box.press("Enter")
    env.page.wait_for_selector("[data-testid=live-turn]", timeout=30_000)
    env.page.wait_for_timeout(500)
    if len(asked) != 1:
        raise AssertionError(f"{len(asked)} ask requests after one Send")
    if asked[0].get("question") != EDITED:
        raise AssertionError(f"the ask carried {asked[0].get('question')!r}, not the edited text")
    return "transcript placed in the box; edited; one ask with the edited text; one voice request"


def s_camera_take_photo(env: Env) -> str:
    """Take photo: the live camera at once on a computer; the phone's camera input at 390."""
    mock_health(env)
    env.open()
    need_menu(env)
    page = env.page
    if env.width == 390:
        with page.expect_file_chooser(timeout=10_000) as chooser:
            menu_item(env, "take-photo")
        el = chooser.value.element
        if el.get_attribute("capture") != "environment" or el.get_attribute("accept") != "image/*":
            raise AssertionError("the phone camera input lacks accept=image/* capture=environment")
        if page.get_by_test_id("camera-sheet").count():
            raise AssertionError("an examples page or preview opened before the phone camera")
        return "phone: the camera input (capture=environment) opened directly, no examples page"
    menu_item(env, "take-photo")
    page.wait_for_selector("[data-testid=camera-sheet]", timeout=10_000)
    page.wait_for_function(
        "(() => { const v = document.querySelector('[data-testid=camera-live]');"
        " return !!v && v.readyState >= 2 && v.videoWidth > 0 })()",
        timeout=15_000,
    )
    if page.locator("[data-testid=camera-sheet] img").count():
        raise AssertionError("an example image is shown on the take-photo path")
    env.shot("camera-preview")
    page.get_by_test_id("camera-shutter").click()
    page.wait_for_selector("[data-testid=camera-shot]", timeout=10_000)
    page.get_by_test_id("camera-retake").click()
    page.wait_for_selector("[data-testid=camera-shot]", state="detached", timeout=5_000)
    page.get_by_test_id("camera-shutter").click()
    page.get_by_test_id("camera-use").click()
    page.wait_for_selector("[data-testid=photo-thumb]", timeout=10_000)
    env.shot("thumbnail-from-camera")
    return "live preview at once; Shutter, Retake, Use photo; thumbnail above the box"


def s_camera_refused(env: Env) -> str:
    """Camera refused: the file picker opens with a short reason."""
    page = env.page
    page.add_init_script(
        "navigator.mediaDevices && (navigator.mediaDevices.getUserMedia ="
        " () => Promise.reject(new DOMException('refused by the test', 'NotAllowedError')));"
    )
    mock_health(env)
    env.open()
    need_menu(env)
    if env.width == 390:
        with page.expect_file_chooser(timeout=10_000):
            menu_item(env, "take-photo")
        return "phone: the camera input opens directly (no permission prompt from the page)"
    opened = True
    try:
        with page.expect_file_chooser(timeout=6_000):
            menu_item(env, "take-photo")
    except Exception:
        opened = False
    note = page.get_by_test_id("photo-note")
    note.wait_for(timeout=5_000)
    if "Camera blocked — choose a photo instead" not in note.inner_text():
        raise AssertionError(f"reason not shown: {note.inner_text()[:120]!r}")
    if page.get_by_test_id("camera-sheet").count():
        raise AssertionError("the camera dialog stayed open after the camera was refused")
    if not opened:  # the browser blocked the automatic picker: the note's button opens it
        with page.expect_file_chooser(timeout=6_000):
            page.get_by_test_id("photo-note-pick").click()
    env.shot("camera-refused")
    return (
        "camera refused -> file picker"
        + ("" if opened else " (from the note's button)")
        + " with the reason"
    )


def s_thumbnail_remove(env: Env) -> str:
    """An attached photo shows as a thumbnail; its remove button drops it and nothing is sent."""
    labels: list[str] = []
    page = env.page
    page.route(LABEL_PATH, lambda r: (labels.append("x"), r.abort())[1])
    mock_health(env)
    env.open()
    need_menu(env)
    with page.expect_file_chooser(timeout=10_000) as chooser:
        menu_item(env, "upload-photo")
    chooser.value.set_files({"name": "label.jpg", "mimeType": "image/jpeg", "buffer": make_jpeg()})
    page.wait_for_selector("[data-testid=photo-thumb] img", timeout=15_000)
    env.shot("thumbnail")
    remove = page.get_by_test_id("photo-remove")
    if not remove.get_attribute("aria-label"):
        raise AssertionError("the remove button has no label")
    remove.click()
    page.wait_for_selector("[data-testid=photo-thumb]", state="detached", timeout=5_000)
    page.wait_for_timeout(500)
    if labels:
        raise AssertionError("a label request was sent for a removed photo")
    return "thumbnail shown; remove dropped it; no /v1/live/label request"


def s_research_hidden(env: Env) -> str:
    """The Research the web item appears only when GET /v1/health offers it."""
    page = env.page
    mock_health(env, research=False)
    env.open()
    need_menu(env)
    page.locator(PLUS).click()
    page.wait_for_selector("[role=menu]", timeout=5_000)
    if page.get_by_test_id("menu-research").count():
        raise AssertionError("the research item is shown although health does not offer it")
    page.keyboard.press("Escape")
    page.unroute(HEALTH_ROUTE)
    mock_health(env, research=True)
    env.open()
    page.locator(PLUS).click()
    item = page.get_by_test_id("menu-research")
    item.wait_for(timeout=10_000)
    if (
        item.get_attribute("role") != "menuitemcheckbox"
        or item.get_attribute("aria-checked") != "false"
    ):
        raise AssertionError("the research item is not an unchecked menuitemcheckbox")
    return "hidden without features.research; an on/off item when offered"


COMPOSER_SCENARIOS: tuple[tuple[str, Callable[[Env], str]], ...] = (
    ("+ menu: open, keyboard, Escape", s_plus_menu),
    ("voice: cancel sends nothing", s_voice_cancel),
    ("voice: pause and resume", s_voice_pause_resume),
    ("voice: stop, transcript in box, edit, send", s_voice_transcript_send),
    ("photo: take photo (live camera / phone camera)", s_camera_take_photo),
    ("photo: camera refused, file picker with reason", s_camera_refused),
    ("photo: thumbnail remove", s_thumbnail_remove),
    ("research toggle hidden without the feature", s_research_hidden),
)


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
    ("chat tier 1: greeting, canned reply and badge", s_chat_greeting),
    ("chat tier 2: direct lookup, badge and openFDA links", s_chat_direct),
    ("chat tier 4: open question reaches the live route (mocked)", s_chat_live_mocked),
    ("camera upload, matches, confirm", s_camera_upload),
    ("mic (fake audio)", s_mic),
    ("alert bell, alert panel", s_alert_bell),
    ("Our devices / Make it yours", s_our_devices),
    ("CAPA-need evidence PDF link", s_capa_pdf),
    ("feedback form", s_feedback),
    ("Connect to Muse page", s_connect),
    ("no sideways scroll", s_no_sideways_scroll),
    ("axe-core accessibility", s_axe),
    *COMPOSER_SCENARIOS,
)
SMOKE = (
    "chat (recorded mode, two turns)",
    "camera upload, matches, confirm",
    "alert bell, alert panel",
)
# Scenarios that call a live model: in the smoke suite they run at the first width only, so the
# browser pass is mocked in the smoke suite (``--mock-live``), so these cost $0.
SMOKE_LIVE = ("chat (recorded mode, two turns)", "camera upload, matches, confirm")


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
        rep.add(label, skip.status, skip.why, group=group, required=skip.required)
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
    ap.add_argument(
        "--mock-live",
        action="store_true",
        help="smoke suite: answer every /v1/live/* call with a recorded body through route "
        "mocking, so the browser pass spends $0 and uses none of the live budget",
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
    first_width = int(args.widths.split(",")[0])
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
                    if smoke and width != first_width:  # live-spending scenarios: one width only
                        scenarios = [s for s in scenarios if s[0] not in SMOKE_LIVE]
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
                            if args.mock_live:
                                env.mock_live()
                            elif args.budget is not None:
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
                            env.settle_unanswered()  # reserved, never answered: full hold spent
                            ctx.close()
            browser.close()
    if smoke:
        ok, why = visits_all_test(visit_bodies, args.test_ref or TEST_REF)
        rep.add("no non-TEST visit ping is sent", PASS if ok else FAIL, why, group="scenario")
    for c in live_calls:
        if c.get("refused"):
            rep.add(f"live {c['path']} call from the browser", FAIL, SKIPPED_BUDGET, group="live")
    rep.metrics["live_calls"] = live_calls
    if args.mock_live:  # nothing reserved, nothing spent: the ledger smoke.py absorbs is empty
        rep.metrics["budget"] = Budget(max_usd=0.0).snapshot()
        rep.metrics["mock_live"] = True
    elif args.budget is not None:
        rep.metrics["budget"] = args.budget.snapshot()  # smoke.py absorbs this, not live_calls
    rep.metrics["live_cost_usd"] = round(sum(c.get("cost_usd", 0.0) for c in live_calls), 6)
    if args.suite == "full":
        rep.metrics["axe_violations_all_views_all_combinations"] = axe_totals
    rep.write(Path(args.out_dir), args.stem)
    return rep.exit_code()


if __name__ == "__main__":
    sys.exit(main())
