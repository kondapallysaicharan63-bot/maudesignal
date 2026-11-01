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
thumbnail's remove button drops the photo; "Web research" is hidden when ``/v1/health``
does not offer it. On a build with the earlier composer they are NOT_PRESENT, not required.

Error states use route mocking: openFDA down, Meta down, daily cap reached (429), slow network,
offline. Each must show an honest message, no crash and no invented data.

``--layout v2`` runs the v2 layout scenarios instead (the chat-app shell at ``?layout=v2``): Home's
top 3 real alerts and "View all", New chat saving the chat before it, Recents (reopen, rename, delete),
Ctrl K search, refresh and Back on ``/chat/<id>``, every section and subtab, the bell (real alerts only),
``?r=TEST1``, the chat chrome, keyboard and labels with axe, no sideways scroll and the phone drawer,
the other themes (smoke), the interface font, and the simulated device profiles (all 12 at
``/devices/<id>``, every tab labelled SIMULATED on screen and in the title, the Our devices tiles,
Back and refresh, every theme). Live calls are route-mocked ($0).

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


REFUSED_REASON = "Camera blocked — choose a photo instead"
#: Refuses the camera in every engine: replaces getUserMedia on the prototype and on the instance (WebKit keeps it
#: on the prototype and ignores a plain assignment on some versions), and adds mediaDevices if it is missing.
REFUSE_CAMERA_JS = """
(() => {
  const refuse = () => Promise.reject(new DOMException('refused by the test', 'NotAllowedError'));
  try {
    if (window.MediaDevices && MediaDevices.prototype)
      Object.defineProperty(MediaDevices.prototype, 'getUserMedia', { value: refuse, configurable: true, writable: true });
  } catch (e) {}
  try {
    if (!navigator.mediaDevices)
      Object.defineProperty(navigator, 'mediaDevices', { value: {}, configurable: true });
    Object.defineProperty(navigator.mediaDevices, 'getUserMedia', { value: refuse, configurable: true, writable: true });
  } catch (e) {}
})();
"""


def s_camera_refused(env: Env) -> str:
    """Camera refused: the file picker opens with a short reason."""
    page = env.page
    page.add_init_script(REFUSE_CAMERA_JS)
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
    try:
        note.wait_for(timeout=8_000)
    except Exception as exc:
        # The refusal stub did not reach this engine's getUserMedia: the dialog keeps waiting (the page never closes
        # it on time alone). That is the right page behaviour, but the refusal path was not exercised here.
        if env.engine == "webkit" and page.get_by_test_id("camera-waiting").count():
            raise SkipError(
                KNOWN_GAP,
                "WebKit: the getUserMedia refusal stub does not take effect in Playwright, so the camera"
                " request stays pending; the refusal path is checked in chromium and firefox",
            ) from exc
        raise
    said = note.inner_text()
    if REFUSED_REASON not in said:
        raise AssertionError(f"reason not shown: {said[:120]!r}")
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


def s_camera_stalls(env: Env) -> str:
    """The camera does not start (an open permission prompt): the dialog stays open and offers a photo after ~4 s."""
    page = env.page
    page.add_init_script(
        REFUSE_CAMERA_JS.replace(
            "Promise.reject(new DOMException('refused by the test', 'NotAllowedError'))",
            "new Promise(() => {})",
        )
    )
    mock_health(env)
    env.open()
    need_menu(env)
    if env.width == 390:
        raise SkipError(
            NOT_PRESENT, "phones open their own camera app; no in-page camera", required=False
        )
    menu_item(env, "take-photo")
    page.wait_for_selector("[data-testid=camera-sheet]", timeout=5_000)
    started = time.monotonic()
    page.wait_for_selector("[data-testid=camera-use-file]", timeout=10_000)
    waited = time.monotonic() - started
    if waited < 2.5:
        raise AssertionError(
            f"'Use a photo instead' came after {waited:.1f} s, before the camera had time"
        )
    if "Camera not started yet" not in page.get_by_test_id("camera-slow").inner_text():
        raise AssertionError("the waiting dialog does not say the camera has not started")
    page.wait_for_timeout(2_000)
    if not page.get_by_test_id("camera-sheet").count():
        raise AssertionError("the camera dialog closed on time alone")
    if page.get_by_test_id("photo-note").count():
        raise AssertionError("a refusal reason was shown although nothing was refused")
    env.shot("camera-slow")
    with page.expect_file_chooser(timeout=6_000):
        page.get_by_test_id("camera-use-file").click()
    page.wait_for_selector("[data-testid=camera-sheet]", state="detached", timeout=5_000)
    return f"dialog stays open; 'Use a photo instead' after {waited:.1f} s opens the file picker"


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
    """The Web research item appears only when GET /v1/health offers it."""
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


def s_voice_limit(env: Env) -> str:
    """At 1:00 the recording pauses and waits: no voice request until the person presses Stop."""
    voice_engine(env)
    seen = mock_voice(env)
    mock_health(env)
    env.page.clock.install()
    env.open()
    need_menu(env)
    start_voice(env)
    env.page.wait_for_timeout(800)
    env.page.clock.fast_forward("00:46")
    env.page.wait_for_function(
        "(() => { const e = document.querySelector('[data-testid=voice-limit]');"
        " return !!e && e.textContent.includes('Stops at 1:00') })()",
        timeout=10_000,
    )
    env.page.clock.fast_forward("00:16")
    env.page.wait_for_selector("[data-testid=voice-bar][data-limit=true]", timeout=10_000)
    said = env.page.get_by_test_id("voice-limit").inner_text()
    if "Limit reached" not in said:
        raise AssertionError(f"the limit is not explained: {said!r}")
    env.page.wait_for_timeout(1000)
    if seen:
        raise AssertionError("a voice request was sent at the limit before Stop was pressed")
    env.shot("recording-limit")
    env.page.get_by_test_id("voice-stop").click()
    env.page.wait_for_function(
        "want => { const t = document.querySelector(\"textarea[aria-label='Ask a question']\");"
        " return !!t && t.value === want }",
        arg=HEARD,
        timeout=20_000,
    )
    if len(seen) != 1:
        raise AssertionError(f"{len(seen)} voice requests after one Stop")
    return "paused at 1:00 with the limit message; no voice request until Stop; then one"


def s_voice_unavailable(env: Env) -> str:
    """Without voice_transcribe_only in /v1/health, voice never records: it opens the recorded run."""
    seen = mock_voice(env)
    env.page.route(
        HEALTH_ROUTE,
        lambda r: r.fulfill(
            status=200,
            headers=CORS_ANY,
            content_type="application/json",
            body=json.dumps({"status": "ok", "features": {}}),
        ),
    )
    env.open()
    need_menu(env)
    env.page.locator(PLUS).click()
    hint = env.page.get_by_test_id("menu-voice").inner_text()
    if "Voice needs the live service" not in hint:
        raise AssertionError(f"the voice item does not say it needs the live service: {hint!r}")
    env.page.get_by_test_id("menu-voice").click()
    env.page.wait_for_timeout(1000)
    if env.page.get_by_test_id("voice-bar").count():
        raise AssertionError("a recording started although transcribe-only is not offered")
    if seen:
        raise AssertionError("a voice request was sent although transcribe-only is not offered")
    return "voice item says it needs the live service; opens the recorded run; nothing recorded or sent"


COMPOSER_SCENARIOS: tuple[tuple[str, Callable[[Env], str]], ...] = (
    ("+ menu: open, keyboard, Escape", s_plus_menu),
    ("voice: cancel sends nothing", s_voice_cancel),
    ("voice: pause and resume", s_voice_pause_resume),
    ("voice: stop, transcript in box, edit, send", s_voice_transcript_send),
    ("photo: take photo (live camera / phone camera)", s_camera_take_photo),
    ("photo: camera refused, file picker with reason", s_camera_refused),
    ("photo: camera slow to start, dialog stays open, photo offered", s_camera_stalls),
    ("photo: thumbnail remove", s_thumbnail_remove),
    ("research toggle hidden without the feature", s_research_hidden),
    ("voice: 1:00 limit pauses, no request until Stop", s_voice_limit),
    ("voice: unavailable without transcribe-only", s_voice_unavailable),
)


# --- v2 answer turn (?layout=v2): chip, Details, Copy, Read aloud, thumbs ----------------------

V2_ANSWER = "[data-testid=live-answer][data-layout=v2]"
V2_QUESTION = "Which kinds of problems do the LLZ reports describe this week?"
V2_LIVE_TEXT = "This is a mocked live answer for the browser test, not about any device."
# Stubbed speechSynthesis: voices arrive late (voiceschanged), every utterance is logged on window.
SPEECH_STUB = """
(() => {
  const voices = [
    {name: 'Microsoft David - English (United States)', lang: 'en-US', default: true, localService: true, voiceURI: 'd'},
    {name: 'Microsoft Aria Online (Natural) - English (United States)', lang: 'en-US', default: false, localService: false, voiceURI: 'a'},
    {name: 'Microsoft Jenny (Natural) - English (United States)', lang: 'en-US', default: false, localService: true, voiceURI: 'j'},
  ];
  let ready = false; const ls = [];
  window.__spoken = []; window.__cancels = 0;
  window.SpeechSynthesisUtterance = function (t) { this.text = t; this.rate = 1; this.voice = null; this.lang = ''; };
  const synth = {
    speaking: false,
    getVoices: () => (ready ? voices : []),
    addEventListener: (t, f) => { if (t === 'voiceschanged') ls.push(f); },
    removeEventListener: () => {},
    speak: (u) => { window.__spoken.push({text: u.text, rate: u.rate, voice: u.voice && u.voice.name}); },
    cancel: () => { window.__cancels++; },
  };
  Object.defineProperty(window, 'speechSynthesis', {value: synth, configurable: true});
  setTimeout(() => { ready = true; ls.forEach((f) => f()); }, 300);
})();
"""


def v2_live_body() -> dict[str, Any]:
    """A tier-4 answer with a source link, a withheld sentence, cost and tokens (mocked, $0 spent)."""
    body = mocked_live_body()
    body["answer"] = {
        "speakable": [
            {"text": V2_LIVE_TEXT, "links": [_MOCK_LINK]},
            {"text": "A second mocked sentence with no figures.", "links": []},
        ],
        "withheld": [{"reason": "a number did not match the stored data"}],
        "spoken_text": V2_LIVE_TEXT + " A second mocked sentence with no figures.",
    }
    body["trace"] = [
        {**body["trace"][0], "ms": 812},
        {"step": "Read-only tools and claim gate", "model": None, "ms": 6, "status": "ok"},
    ]
    body["cost_usd"] = 0.0
    body["usage"] = {"input_tokens": 1200, "output_tokens": 140}
    return body


def v2_recorded_body() -> dict[str, Any]:
    """A recorded answer that names its recording date (mocked)."""
    body = recorded_body("ask")
    body["recorded_note"] = (
        "Recorded sample used by the browser test (recorded 2026-10-28): no live model call was made."
    )
    return body


def open_v2(env: Env, speech: bool = True) -> None:
    """Load the app with ?layout=v2 and wait for the composer.

    ``speech`` installs the speechSynthesis stub (headless browsers have no voices, so Read aloud
    would be hidden); the greeting scenario runs without it to check the button stays hidden.
    """
    if speech:
        env.page.add_init_script(SPEECH_STUB)
    sep = "&" if "?" in env.args.url else "?"
    env.page.goto(env.args.url + sep + "layout=v2", wait_until="load")
    env.page.wait_for_selector(COMPOSER, timeout=30_000)


def mock_ask(env: Env, body: dict[str, Any]) -> list[dict[str, Any]]:
    """Answer /v1/live/ask with ``body``; returns the request bodies seen."""
    seen: list[dict[str, Any]] = []

    def handler(route: Any) -> None:
        with contextlib.suppress(ValueError):
            seen.append(json.loads(route.request.post_data or "{}"))
        route.fulfill(status=200, content_type="application/json", body=json.dumps(body))

    env.page.route(ASK_PATH, handler)
    return seen


def v2_answer(env: Env) -> Any:
    """Wait for the v2 answer turn and its action bar; return the answer locator."""
    env.page.wait_for_selector(V2_ANSWER, timeout=45_000)
    env.page.wait_for_selector(f"{V2_ANSWER} [data-testid=details-toggle]", timeout=10_000)
    return env.page.locator(V2_ANSWER).first


def visible_text(env: Env) -> str:
    """Text the person can see in the conversation (hidden Details excluded)."""
    log = env.page.locator("[role=log]")
    return log.first.inner_text() if log.count() else env.page.locator("body").inner_text()


def s_v2_live_chip(env: Env) -> str:
    """A mocked live answer shows one quiet chip 'Muse Spark 1.3 · Live'; no cost or step lines."""
    mock_ask(env, v2_live_body())
    open_v2(env)
    env.ask(V2_QUESTION)
    ans = v2_answer(env)
    chip = ans.get_by_test_id("model-chip").inner_text().strip()
    if chip != "Muse Spark 1.3 · Live":
        raise AssertionError(f"chip is {chip!r}")
    seen = visible_text(env)
    for noisy in (
        "Cost of this answer",
        "812 ms",
        "818 ms",
        "1200 in",
        "Fixed reply, no model call",
    ):
        if noisy in seen:
            raise AssertionError(f"{noisy!r} is visible in the main view")
    if (
        ans.get_by_test_id("mark-verified").count() != 1
        or ans.get_by_test_id("held-back").count() != 1
    ):
        raise AssertionError("Verified / Withheld marks missing")
    if env.overflow() > 1:
        raise AssertionError(f"sideways scroll of {env.overflow()} px")
    env.shot("v2-live-answer")
    axe = Path(env.args.axe)
    if not axe.is_file():
        return f"chip {chip!r}; no cost, no step timings; marks shown (axe-core not found)"
    ans.get_by_test_id("details-toggle").click()
    env.page.add_script_tag(path=str(axe))
    results = env.page.evaluate(
        "axe.run(document.querySelector('[data-testid=live-answer][data-layout=v2]'),"
        " {resultTypes: ['violations']})"
    )
    counts = count_axe(results)
    if axe_blocks(counts):
        ids = [v.get("id") for v in results.get("violations", [])]
        raise AssertionError(f"axe on the v2 answer (Details open): {ids} {counts}")
    return (
        f"chip {chip!r}; no cost, no step timings; Verified and Withheld marks shown; "
        f"axe on the answer with Details open: {counts}"
    )


def s_v2_greeting(env: Env) -> str:
    """A greeting (tier 1, from the local API, $0) shows 'Instant answer' and no cost line."""
    open_v2(env, speech=False)
    env.ask("namaste")
    ans = v2_answer(env)
    voices = int(
        env.page.evaluate("window.speechSynthesis ? window.speechSynthesis.getVoices().length : 0")
    )
    if voices == 0 and ans.get_by_test_id("action-read").count():
        raise AssertionError("Read aloud is shown although the browser has no voices")
    chip = ans.get_by_test_id("model-chip").inner_text().strip()
    if chip != "Instant answer":
        raise AssertionError(f"chip is {chip!r}")
    seen = visible_text(env)
    for noisy in (
        "Cost of this answer",
        "$0.0000",
        "No FDA facts in this message",
        "no model call",
    ):
        if noisy in seen:
            raise AssertionError(f"{noisy!r} is visible in the main view")
    env.shot("v2-instant-answer")
    return "Instant answer chip; no cost line, no 'No FDA facts' line"


def s_v2_recorded(env: Env) -> str:
    """A recorded answer shows 'Recorded · Oct 28, 2026'."""
    mock_ask(env, v2_recorded_body())
    open_v2(env)
    env.ask(V2_QUESTION)
    ans = v2_answer(env)
    chip = ans.get_by_test_id("model-chip").inner_text().strip()
    if chip != "Recorded · Oct 28, 2026":
        raise AssertionError(f"chip is {chip!r}")
    env.shot("v2-recorded-answer")
    return f"chip {chip!r}"


def s_v2_details(env: Env) -> str:
    """Details is closed by default (aria-expanded false), opens by mouse and by keyboard."""
    mock_ask(env, v2_live_body())
    open_v2(env)
    env.ask(V2_QUESTION)
    ans = v2_answer(env)
    toggle = ans.get_by_test_id("details-toggle")
    if (
        toggle.get_attribute("aria-expanded") != "false"
        or ans.get_by_test_id("answer-details").count()
    ):
        raise AssertionError("Details is not closed by default")
    if toggle.get_attribute("aria-label") != "Details":
        raise AssertionError("Details toggle has no label")
    toggle.focus()
    env.page.keyboard.press("Enter")
    env.page.wait_for_selector(f"{V2_ANSWER} [data-testid=answer-details]", timeout=5_000)
    if toggle.get_attribute("aria-expanded") != "true":
        raise AssertionError("aria-expanded did not change to true")
    panel = ans.get_by_test_id("answer-details").inner_text()
    for need in ("Live model answer", "Muse Spark 1.3", "818 ms", "1200 in", "Steps"):
        if need not in panel:
            raise AssertionError(f"{need!r} missing from Details")
    if "route mock" in panel or "STEPS" in panel:
        raise AssertionError("a test-mock note or an all-caps heading is shown in Details")
    tall = env.page.evaluate(
        "Math.max(...[...document.querySelectorAll('[data-testid=answer-details] .ans-step')]"
        ".map(e => e.getBoundingClientRect().height / parseFloat(getComputedStyle(e).lineHeight || '21')))"
    )
    if float(tall) > 2.6:
        raise AssertionError(f"a step row takes {tall:.1f} lines")
    panel_el = ans.get_by_test_id("answer-details")
    panel_el.scroll_into_view_if_needed()
    env.shot("v2-details-open")
    ans.get_by_test_id("action-copy").focus()  # focus elsewhere in the answer first
    env.page.keyboard.press("Escape")
    env.page.wait_for_timeout(200)
    if ans.get_by_test_id("answer-details").count():
        raise AssertionError("Escape did not close Details")
    focused = env.page.evaluate("document.activeElement?.getAttribute('data-testid')")
    if focused != "details-toggle":
        raise AssertionError(f"focus went to {focused!r}, not the Details toggle")
    return "closed by default; Enter opens with route, steps (2 lines max), time, tokens; Escape closes, focus back on toggle"


def s_v2_copy(env: Env) -> str:
    """Copy puts the answer and its FDA link on the clipboard, never the question (chromium reads it back)."""
    if env.engine != "chromium":
        raise SkipError(KNOWN_GAP, "clipboard read-back needs chromium permissions")
    env.page.context.grant_permissions(["clipboard-read", "clipboard-write"])
    mock_ask(env, v2_live_body())
    open_v2(env)
    env.ask(V2_QUESTION)
    ans = v2_answer(env)
    ans.get_by_test_id("action-copy").click()
    env.page.wait_for_timeout(300)
    got = str(env.page.evaluate("navigator.clipboard.readText()"))
    if V2_LIVE_TEXT not in got or _MOCK_LINK["url"] not in got:
        raise AssertionError(f"clipboard is {got[:160]!r}")
    if V2_QUESTION in got:
        raise AssertionError("the question was copied")
    if ans.get_by_test_id("action-copy").get_attribute("aria-label") != "Copied":
        raise AssertionError("no 'Copied' feedback")
    return f"clipboard holds the answer and its link ({len(got)} chars), not the question"


def s_v2_read_aloud(env: Env) -> str:
    """Read aloud (stubbed speechSynthesis): the Natural voice at 0.95, only the answer; Stop cancels."""
    mock_ask(env, v2_live_body())
    open_v2(env)
    env.ask(V2_QUESTION)
    ans = v2_answer(env)
    btn = ans.get_by_test_id("action-read")
    btn.wait_for(timeout=5_000)
    if btn.get_attribute("aria-label") != "Read aloud":
        raise AssertionError(f"label is {btn.get_attribute('aria-label')!r}")
    btn.click()
    spoken = env.page.evaluate("window.__spoken")
    if len(spoken) < 2 or any(
        u.get("voice") != "Microsoft Jenny (Natural) - English (United States)"
        or u.get("rate") != 0.95
        for u in spoken
    ):
        raise AssertionError(f"expected one on-device Natural utterance per sentence: {spoken!r}")
    said = " ".join(u["text"] for u in spoken)
    if "http" in said or V2_QUESTION in said:
        raise AssertionError("a link or the question was read")
    if btn.get_attribute("aria-label") != "Stop reading aloud":
        raise AssertionError("no Stop state")
    before = int(env.page.evaluate("window.__cancels"))
    btn.click()
    if int(env.page.evaluate("window.__cancels")) <= before:
        raise AssertionError("Stop did not cancel")
    if btn.get_attribute("aria-label") != "Read aloud":
        raise AssertionError("button did not return to Read aloud")
    return f"{len(spoken)} sentences read with {spoken[0]['voice']!r} (on-device) at 0.95; Stop cancelled"


def s_v2_rating(env: Env) -> str:
    """Thumbs down opens a reason box and posts {kind, answer_id, rating 1, reason}; one rating per answer."""
    posted: list[dict[str, Any]] = []

    def feedback(route: Any) -> None:
        with contextlib.suppress(ValueError):
            posted.append(json.loads(route.request.post_data or "{}"))
        route.fulfill(
            status=201,
            content_type="application/json",
            headers={"access-control-allow-origin": "*"},
            body='{"status": "received", "id": "x"}',
        )

    env.page.route("**/v1/feedback", feedback)
    mock_ask(env, v2_live_body())
    open_v2(env)
    env.ask(V2_QUESTION)
    ans = v2_answer(env)
    for tid in ("action-copy", "action-read", "action-up", "action-down", "details-toggle"):
        box_ = ans.get_by_test_id(tid).bounding_box() or {}
        if min(box_.get("width", 0), box_.get("height", 0)) < 44:
            raise AssertionError(f"{tid} hit area is smaller than 44 px: {box_}")
    time_shown = ans.get_by_test_id("answer-time").is_visible()
    if env.width < 480 and time_shown:
        raise AssertionError("the timestamp is shown below 480 px")
    down = ans.get_by_test_id("action-down")
    up = ans.get_by_test_id("action-up")
    down.click()
    box = ans.locator("[data-testid=rating-reason] textarea")
    box.wait_for(timeout=5_000)
    if down.get_attribute("aria-expanded") != "true" or box.get_attribute("maxlength") != "300":
        raise AssertionError("reason box not opened, or no 300-character limit")
    if down.get_attribute("aria-pressed") is not None:
        raise AssertionError("thumbs down should use aria-expanded only")
    if "ans-ib--chosen" in (down.get_attribute("class") or "") + (up.get_attribute("class") or ""):
        raise AssertionError("a thumb looks chosen before a rating was sent")
    box.fill("The second sentence was not useful.")
    box.scroll_into_view_if_needed()
    env.shot("v2-thumbs-down-reason")
    ans.get_by_test_id("rating-send").click()
    env.page.wait_for_selector(f"{V2_ANSWER} [data-testid=rating-status]", timeout=5_000)
    focused = env.page.evaluate("document.activeElement?.getAttribute('data-testid')")
    if focused != "action-down":
        raise AssertionError(f"focus went to {focused!r}, not the thumbs-down button")
    if "ans-ib--chosen" not in (down.get_attribute("class") or "") or "ans-ib--chosen" in (
        up.get_attribute("class") or ""
    ):
        raise AssertionError("only the chosen thumb (down) should look selected")
    env.shot("v2-thumbs-down-sent")
    up.click(force=True)  # aria-disabled: Playwright would wait for it to be enabled
    env.page.wait_for_timeout(500)
    if len(posted) != 1:
        raise AssertionError(f"{len(posted)} rating requests, expected 1 (one rating per answer)")
    [dn] = posted
    blob = json.dumps(dn)
    if V2_QUESTION in blob or V2_LIVE_TEXT in blob:
        raise AssertionError("a rating carried question or answer text")
    if dn.get("kind") != "answer_rating" or not re.fullmatch(
        r"[A-Za-z0-9_-]{8,64}", str(dn.get("answer_id"))
    ):
        raise AssertionError(f"bad rating body {dn!r}")
    if dn.get("rating") != 1 or dn.get("comment") != "The second sentence was not useful.":
        raise AssertionError(f"rating {dn.get('rating')}, reason {dn.get('comment')!r}")
    return (
        "down (1) with reason posted once, focus back on the thumb, only it selected; a later "
        f"thumbs-up sends nothing; 44 px hit areas; timestamp {'shown' if time_shown else 'hidden'}"
    )


def s_v2_rating_old_api(env: Env) -> str:
    """An API without answer ratings (422 on kind / answer_id): the page says only 'Rating not saved.'."""

    def old_api(route: Any) -> None:
        route.fulfill(
            status=422,
            content_type="application/json",
            headers={"access-control-allow-origin": "*"},
            body='{"error": {"code": "invalid_input", "message": "Invalid input: answer_id, kind."}}',
        )

    env.page.route("**/v1/feedback", old_api)
    mock_ask(env, v2_live_body())
    open_v2(env)
    env.ask(V2_QUESTION)
    ans = v2_answer(env)
    ans.get_by_test_id("action-up").click()
    st = env.page.wait_for_selector(f"{V2_ANSWER} [data-testid=rating-status]", timeout=5_000)
    said = st.inner_text().strip() if st else ""
    if said != "Rating not saved." or "Invalid input" in visible_text(env):
        raise AssertionError(f"status is {said!r}")
    return "older API: quiet 'Rating not saved.', no validation text shown"


V2_ANSWER_SCENARIOS: tuple[tuple[str, Callable[[Env], str]], ...] = (
    ("v2: live answer chip, no cost line (mocked)", s_v2_live_chip),
    ("v2: greeting is an Instant answer, no cost line", s_v2_greeting),
    ("v2: recorded answer chip with date (mocked)", s_v2_recorded),
    ("v2: Details toggle (mouse and keyboard)", s_v2_details),
    ("v2: Copy answer and links", s_v2_copy),
    ("v2: Read aloud start / stop (stubbed speech)", s_v2_read_aloud),
    ("v2: thumbs down with reason, one rating per answer", s_v2_rating),
    ("v2: older API without answer ratings", s_v2_rating_old_api),
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
    *V2_ANSWER_SCENARIOS,
)
SMOKE = (
    "chat (recorded mode, two turns)",
    "camera upload, matches, confirm",
    "alert bell, alert panel",
)
# Scenarios that call a live model: in the smoke suite they run at the first width only, so the
# browser pass is mocked in the smoke suite (``--mock-live``), so these cost $0.
SMOKE_LIVE = ("chat (recorded mode, two turns)", "camera upload, matches, confirm")


# --- v2 layout (``--layout v2``: the chat-app shell at ?layout=v2) ------------------------------
#
# Every v2 scenario answers /v1/live/* from the browser with a recorded body (route mocking, $0, no
# model call) and blocks /v1/visit pings (their bodies are kept to check the ref). Chats are saved in
# the browser's localStorage only; each scenario starts in a fresh context, so with no saved chats.

V2_MUSE_STATUS = "Submitted to Meta's Muse Connector Program — pending review"
V2_PAGES = (
    ("signals", ("ranked", "trend", "unfiled", "alerts")),
    ("devices", ("apply", "yours")),
    ("evidence", ("capa", "review", "approve", "audit")),
    ("connect", ("muse", "claude", "api")),
)
V2_THEMES = ("contrast", "black", "pink")


def v2_url(env: Env, path: str = "", extra: str = "") -> str:
    """The app address of a v2 page, with ?layout=v2 (and ``extra`` query parameters)."""
    base = env.args.url.rstrip("/")
    query = "layout=v2" + (f"&{extra}" if extra else "")
    return f"{base}/{path}?{query}"


def v2_mock_answer_body(question: str, remaining: int | None) -> dict[str, Any]:
    """A recorded-mode answer that repeats the question (so chat search can find it), no figures."""
    text = f"Recorded sample answer for: {question[:80]}"
    return {
        "mode": "recorded",
        "not_medical_advice": True,
        "recorded_note": RECORDED_NOTE,
        "trace": _MOCK_TRACE,
        "cost_usd": None,
        "limits": {"remaining_today": remaining},
        "answer": {
            "speakable": [{"text": text, "links": [_MOCK_LINK]}],
            "withheld": [],
            "spoken_text": text,
        },
        "suggestions": ["A follow-up question?"],
    }


def v2_prepare(env: Env, remaining: int | None = 29) -> None:
    """Mock the live routes and /v1/health; keep the visit pings (blocked)."""

    def ask(route: Any) -> None:
        try:
            q = str(json.loads(route.request.post_data or "{}").get("question", ""))
        except ValueError:
            q = ""
        env.live_calls.append(
            {"path": "ask", "status": 200, "mode": "recorded", "cost_usd": 0.0, "mocked": True}
        )
        route.fulfill(
            status=200,
            headers=CORS_ANY,
            content_type="application/json",
            body=json.dumps(v2_mock_answer_body(q, remaining)),
        )

    env.page.context.route(ASK_PATH, ask)
    env.page.context.route(
        HEALTH_ROUTE,
        lambda r: r.fulfill(
            status=200,
            headers=CORS_ANY,
            content_type="application/json",
            body=json.dumps({"status": "ok", "features": {}}),
        ),
    )
    env.block_visits()


def v2_open(env: Env, path: str = "", extra: str = "", remaining: int | None = 29) -> None:
    """Load a v2 page (live routes mocked) and wait for the shell."""
    if not getattr(env, "v2_ready", False):
        v2_prepare(env, remaining)
        env.v2_ready = True  # type: ignore[attr-defined]
    env.page.goto(v2_url(env, path, extra), wait_until="load")
    env.page.wait_for_selector("[data-testid=topbar-v2]", timeout=30_000)
    env.page.wait_for_selector("#main-v2 h1, [data-testid=chat-screen]", timeout=30_000)


def v2_sidebar(env: Env) -> Any:
    """The sidebar, opening the phone drawer first when it is closed."""
    side = env.page.locator("#sidebar")
    if not env.page.get_by_test_id("new-chat").is_visible():
        env.page.get_by_test_id("sidebar-toggle").click()
        env.page.wait_for_timeout(300)
    return side


def v2_side_click(env: Env, testid: str) -> None:
    """Click a sidebar entry by its test id (drawer opened first on a phone)."""
    v2_sidebar(env)
    env.page.get_by_test_id(testid).first.click()
    env.page.wait_for_timeout(300)


def v2_ask(env: Env, text: str) -> None:
    """Ask in the message box and wait for the answer to be written."""
    env.ask(text)
    env.page.wait_for_selector("[data-testid=answer-sentence]", timeout=30_000)
    env.page.wait_for_timeout(300)


def v2_recents(env: Env) -> list[str]:
    """Titles in Recents, newest first."""
    v2_sidebar(env)
    return [t.strip() for t in env.page.get_by_test_id("recent-chat").all_inner_texts()]


def v2_close_drawer(env: Env) -> None:
    """Close the phone drawer if it is open."""
    if env.width < 768 and env.page.get_by_test_id("new-chat").is_visible():
        env.page.keyboard.press("Escape")
        env.page.wait_for_timeout(300)


def v2_path(env: Env) -> str:
    """The page's path (no origin, no query)."""
    return str(env.page.evaluate("location.pathname"))


def v2_s_home(env: Env) -> str:
    """Home: top 3 real FDA alerts, "View all N" opens Signals · All alerts with N, a separate simulated card."""
    v2_open(env)
    home = env.page.get_by_test_id("home-alerts")
    rows = home.locator("li").count()
    if rows != 3:
        raise AssertionError(f"Home shows {rows} alerts, not the top 3")
    if re.search(r"simulated|needs review", home.inner_text(), re.I):
        raise AssertionError("a simulated device is in the real-alert list on Home")
    m = re.search(r"View all\s+(\d+)", env.page.get_by_test_id("home-view-all").inner_text())
    if not m:
        raise AssertionError("no 'View all N' link")
    n = int(m.group(1))
    sim = env.page.get_by_test_id("home-devices").inner_text()
    if "simulated" not in sim.lower() or "to review" not in sim:
        raise AssertionError(f"the simulated devices card is not labelled: {sim[:80]!r}")
    for tid, words in (
        ("home-sweep", r"\d+ flagged of \d+"),
        ("home-sweep-label", r"Stored"),
        ("home-trust", r"Claims verified"),
    ):
        if not re.search(words, env.page.get_by_test_id(tid).inner_text()):
            raise AssertionError(f"{tid} does not show {words!r}")
    env.shot("v2-home")
    env.page.get_by_test_id("home-view-all").click()
    env.page.wait_for_selector("[data-testid=all-alerts]", timeout=10_000)
    if not v2_path(env).endswith("/signals/alerts"):
        raise AssertionError(f"View all opened {v2_path(env)}")
    listed = env.page.get_by_test_id("all-alerts").locator("li").count()
    if listed != n:
        raise AssertionError(f"View all {n} but the list has {listed}")
    if re.search(r"simulated", env.page.get_by_test_id("all-alerts").inner_text(), re.I):
        raise AssertionError("a simulated device is in All alerts")
    return f"top 3 of {n} real alerts; View all -> {listed}; simulated card separate"


def v2_s_new_chat(env: Env) -> str:
    """New chat saves the chat before it and starts an empty one (greeting and chips, no extra chrome)."""
    v2_open(env, "chat")
    v2_ask(env, "Which recalls are on file for LLZ devices?")
    first = v2_path(env)
    if not re.search(r"/chat/[a-z0-9]+$", first):
        raise AssertionError(f"the chat has no address of its own: {first}")
    v2_side_click(env, "new-chat")
    env.page.wait_for_selector("[data-testid=chat-empty]", timeout=10_000)
    if not v2_path(env).endswith("/chat"):
        raise AssertionError(f"New chat opened {v2_path(env)}")
    chips = env.page.get_by_test_id("empty-chip").count()
    if not 3 <= chips <= 4:
        raise AssertionError(f"{chips} suggestion chips (3 or 4 expected)")
    main = env.page.locator("#main-v2").inner_text()
    for gone in ("Speaker on", "Speaker off", "Clear conversation", "Audio is sent once"):
        if gone in main:
            raise AssertionError(f"{gone!r} is still on the chat screen")
    env.shot("v2-empty-chat")
    titles = v2_recents(env)
    if not titles or not titles[0].startswith("Which recalls are on file"):
        raise AssertionError(f"the first chat was not saved: {titles}")
    v2_close_drawer(env)
    env.page.get_by_test_id("empty-chip").first.click()
    env.page.wait_for_selector("[data-testid=answer-sentence]", timeout=30_000)
    env.page.wait_for_timeout(300)
    second = v2_path(env)
    titles = v2_recents(env)
    if second == first or len(titles) != 2:
        raise AssertionError(f"second chat: {second} (first {first}); recents {titles}")
    env.shot("v2-chat-with-recents")
    v2_close_drawer(env)
    return f"2 chats saved, newest first: {[t[:24] for t in titles]}"


def v2_s_recents(env: Env) -> str:
    """Recents: reopen exactly, rename inline (kept after reload), delete with confirm."""
    v2_open(env, "chat")
    v2_ask(env, "First saved question about MHRA alerts")
    first = v2_path(env)
    v2_ask(env, "And a second turn in the same chat")
    v2_side_click(env, "new-chat")
    v2_ask(env, "Another chat about QIH reports")
    v2_sidebar(env)
    env.page.get_by_test_id("recent-chat").nth(1).click()
    env.page.wait_for_function(f"location.pathname === {json.dumps(first)}", timeout=10_000)
    env.page.wait_for_function(
        "[...document.querySelectorAll('[data-testid=user-bubble]')].some(b => b.innerText.includes('MHRA'))",
        timeout=10_000,
    )
    bubbles = env.page.get_by_test_id("user-bubble").all_inner_texts()
    if [b.strip() for b in bubbles] != [
        "First saved question about MHRA alerts",
        "And a second turn in the same chat",
    ]:
        raise AssertionError(f"reopened chat shows {bubbles}")
    env.page.wait_for_selector("[data-testid=suggestion-chip]", timeout=15_000)
    if (
        env.page.get_by_test_id("model-chip").count() != 2
        or env.page.get_by_test_id("recorded-note").count() != 2
    ):
        raise AssertionError("the reopened answers lost their Recorded label")
    v2_sidebar(env)
    env.page.get_by_test_id("recent-more").nth(1).click()
    env.page.get_by_test_id("recent-rename").click()
    box = env.page.get_by_test_id("rename-input")
    box.fill("Renamed MHRA chat")
    box.press("Enter")
    env.page.wait_for_timeout(200)
    env.page.reload(wait_until="load")
    env.page.wait_for_selector("[data-testid=answer-sentence]", timeout=30_000)
    titles = v2_recents(env)
    if "Renamed MHRA chat" not in titles:
        raise AssertionError(f"rename was not kept after reload: {titles}")
    env.page.get_by_test_id("recent-more").nth(0).click()
    env.page.get_by_test_id("recent-delete").click()
    env.page.get_by_test_id("delete-no").click()
    if len(v2_recents(env)) != 2:
        raise AssertionError("Cancel deleted the chat")
    v2_sidebar(env)
    env.page.get_by_test_id("recent-more").nth(1).click()
    env.page.get_by_test_id("recent-delete").click()
    env.page.get_by_test_id("delete-yes").click()
    env.page.wait_for_timeout(300)
    left = v2_recents(env)
    if len(left) != 1 or "Renamed MHRA chat" in left:
        raise AssertionError(f"delete did not remove the chat: {left}")
    if env.page.get_by_test_id("chat-empty").count() == 0:
        raise AssertionError("deleting the open chat did not leave an empty chat")
    stored = env.page.evaluate("localStorage.getItem('ms-chats-v1') || ''")
    if "MHRA" in stored:
        raise AssertionError("the deleted chat is still in localStorage")
    v2_close_drawer(env)
    return "reopened 2 turns with badges and chips; rename kept after reload; Cancel kept, Delete removed"


def v2_s_search(env: Env) -> str:
    """Ctrl K searches chat titles and text, and the pages."""
    v2_open(env, "chat")
    v2_ask(env, "Tell me about zebrafish imaging software")
    target = v2_path(env)
    v2_side_click(env, "new-chat")
    v2_ask(env, "Something else entirely")
    v2_close_drawer(env)
    env.page.locator("body").press("Control+k")
    env.page.wait_for_selector("[data-testid=search-input]", timeout=5_000)
    env.page.get_by_test_id("search-input").fill("zebrafish")
    hits = env.page.get_by_test_id("search-chat").count()
    if hits != 1:
        raise AssertionError(f"{hits} chat results for a word in one chat")
    env.page.get_by_test_id("search-input").press("Enter")
    env.page.wait_for_function(f"location.pathname === {json.dumps(target)}", timeout=10_000)
    env.page.locator("body").press("Control+k")
    env.page.get_by_test_id("search-input").fill("Sample answer for: something else")
    if env.page.get_by_test_id("search-chat").count() != 1:
        raise AssertionError("answer text is not searched")
    env.page.get_by_test_id("search-input").fill("trend")
    env.page.get_by_test_id("search-input").press("Enter")
    env.page.wait_for_selector("[data-testid=trend-list]", timeout=10_000)
    if not v2_path(env).endswith("/signals/trend"):
        raise AssertionError(f"page search opened {v2_path(env)}")
    env.page.locator("body").press("Control+k")
    env.page.wait_for_selector("[data-testid=search-input]")
    env.page.keyboard.press("Escape")
    env.page.wait_for_function(
        "!document.querySelector('[data-testid=search-input]')", timeout=5_000
    )
    return "title/text hit opened the chat; 'trend' opened Signals · Trend; Escape closes"


def v2_s_refresh_back(env: Env) -> str:
    """Refresh on /chat/<id> reopens the chat; Back and Forward move between chats and pages."""
    v2_open(env, "chat")
    v2_ask(env, "Refresh test question one")
    one = v2_path(env)
    v2_side_click(env, "new-chat")
    v2_ask(env, "Refresh test question two")
    two = v2_path(env)
    env.page.reload(wait_until="load")
    env.page.wait_for_selector("[data-testid=answer-sentence]", timeout=30_000)
    if (
        v2_path(env) != two
        or env.page.get_by_test_id("user-bubble").first.inner_text().strip()
        != "Refresh test question two"
    ):
        raise AssertionError("refresh did not reopen the chat")
    if "layout=v2" not in env.page.url:
        raise AssertionError("the query string was dropped")
    v2_side_click(env, "nav-signals")
    env.page.wait_for_selector("[data-testid=signals-tabs]", state="attached")
    env.page.go_back()
    env.page.wait_for_function(f"location.pathname === {json.dumps(two)}", timeout=10_000)
    env.page.wait_for_selector("[data-testid=user-bubble]", timeout=10_000)
    if (
        env.page.get_by_test_id("user-bubble").first.inner_text().strip()
        != "Refresh test question two"
    ):
        raise AssertionError("Back did not show chat two")
    env.page.go_back()
    env.page.wait_for_function(f"location.pathname === {json.dumps(one)}", timeout=10_000)
    env.page.wait_for_function(
        "[...document.querySelectorAll('[data-testid=user-bubble]')].some(b => b.innerText.includes('question one'))",
        timeout=10_000,
    )
    env.page.go_forward()
    env.page.wait_for_function(f"location.pathname === {json.dumps(two)}", timeout=10_000)
    # A direct load of a saved chat's address in a new tab of the same browser.
    p2 = env.page.context.new_page()
    p2.goto(env.args.url.rstrip("/") + one + "?layout=v2", wait_until="load")
    p2.wait_for_selector("[data-testid=user-bubble]", timeout=30_000)
    ok = "question one" in p2.get_by_test_id("user-bubble").first.inner_text()
    p2.close()
    if not ok:
        raise AssertionError("a direct load of /chat/<id> did not open the chat")
    # Without ?layout the address still opens v2 (a /chat/ path is v2 only).
    p3 = env.page.context.new_page()
    p3.goto(env.args.url.rstrip("/") + one, wait_until="load")
    p3.wait_for_selector("[data-testid=topbar-v2]", timeout=30_000)
    p3.close()
    return "refresh, Back, Back, Forward and a direct load all show the right chat"


def v2_s_sections(env: Env) -> str:
    """Every section and subtab opens (ARIA tabs, one panel, own address); key facts are from the data."""
    v2_open(env)
    seen: list[str] = []
    for section, tabs in V2_PAGES:
        v2_side_click(env, f"nav-{section}")
        env.page.wait_for_selector(
            f"[data-testid={section}-tabs]", state="attached", timeout=10_000
        )
        phone_menu = env.page.get_by_test_id(f"{section}-viewpick")
        if env.width < 480 and not phone_menu.is_visible():
            raise AssertionError(f"{section}: no View menu below 480 px")
        if env.page.locator("#main-v2 h1").count() < 1:
            raise AssertionError(f"{section} has no page heading")
        env.shot(f"v2-{section}")
        for t in tabs:
            tab = env.page.get_by_test_id(f"tab-{t}")
            if env.width < 480:  # the View menu: every subtab reachable on a phone
                phone_menu.select_option(t)
            else:
                tab.click()
            env.page.wait_for_timeout(250)
            if tab.get_attribute("aria-selected") != "true":
                raise AssertionError(f"{section}/{t} is not selected after a click")
            if env.page.locator("[role=tab][aria-selected=true]").count() != 1:
                raise AssertionError(f"{section}: more than one tab open")
            if not v2_path(env).endswith(f"/{section}/{t}"):
                raise AssertionError(f"{section}/{t} address is {v2_path(env)}")
            panel = env.page.locator(f"#{section}-panel")
            if (
                panel.get_attribute("aria-labelledby") != f"{section}-tab-{t}"
                or len(panel.inner_text().strip()) < 20
            ):
                raise AssertionError(
                    f"{section}/{t}: the panel is empty or not labelled by its tab"
                )
            seen.append(f"{section}/{t}")
        if env.width >= 480:
            first = env.page.get_by_test_id(f"tab-{tabs[0]}")
            first.click()
            first.focus()
            before = env.page.evaluate("history.length")
            env.page.keyboard.press("ArrowRight")
            env.page.wait_for_timeout(200)
            if env.page.get_by_test_id(f"tab-{tabs[1]}").get_attribute("aria-selected") != "true":
                raise AssertionError(f"{section}: ArrowRight did not move to the next tab")
            if env.page.evaluate("history.length") != before:
                raise AssertionError(f"{section}: an arrow-key move added a history entry")
            focused = env.page.evaluate(
                "document.activeElement && document.activeElement.dataset.testid"
            )
            if focused != f"tab-{tabs[1]}":
                raise AssertionError(
                    f"{section}: focus left the tab row after ArrowRight ({focused})"
                )
    env.page.goto(v2_url(env, "signals/trend"), wait_until="load")
    env.page.wait_for_selector("[data-testid=trend-row][data-code=LLZ]", timeout=10_000)
    llz = env.page.locator("[data-testid=trend-row][data-code=LLZ]").inner_text()
    if "33" not in llz or "8.75" not in llz or "Stored" not in llz:
        raise AssertionError(f"Trend LLZ row is not 33 vs 8.75 labelled stored: {llz[:120]!r}")
    env.page.goto(v2_url(env, "connect/muse"), wait_until="load")
    env.page.wait_for_selector("[data-testid=connect-view]", timeout=10_000)
    if V2_MUSE_STATUS not in env.page.locator("#main-v2").inner_text():
        raise AssertionError("the Muse connector status is not the exact text")
    env.page.goto(v2_url(env, "devices/apply"), wait_until="load")
    env.page.wait_for_selector("[data-testid=company-banner]", timeout=10_000)
    bg = env.page.evaluate(
        "getComputedStyle(document.querySelector('[data-testid=company-banner]')).borderTopStyle"
    )
    if bg != "dashed":
        raise AssertionError(f"the simulated banner is not the neutral dashed style ({bg})")
    # Evidence · Muse Wonder review: the dossier PDF renders on a v2 address (pdf.js got a relative URL before).
    env.page.goto(v2_url(env, "evidence/review"), wait_until="load")
    env.page.wait_for_selector(
        ".ms2-dossier canvas, [data-testid=pdf-unavailable]", state="attached", timeout=30_000
    )
    if env.page.get_by_test_id("pdf-unavailable").count():
        raise AssertionError("the dossier PDF did not render on /evidence/review")
    made = env.page.get_by_test_id("how-made")
    made.locator("summary").click()
    made_text = made.inner_text()
    if "Muse Spark" not in made_text or "Muse Wonder" not in made_text or "muse-spark" in made_text:
        raise AssertionError(f"How this was made: {made_text[:160]!r}")
    env.shot("v2-evidence-review")
    return (
        f"{len(seen)} subtabs: {', '.join(seen)}; LLZ 33 vs 8.75 (stored); Muse status exact; "
        "simulated banner neutral; dossier PDF renders; plain model names"
    )


def v2_s_bell(env: Env) -> str:
    """The bell lists real alerts only; the simulated devices are a separate, labelled link."""
    v2_open(env)
    env.page.get_by_test_id("alert-bell").click()
    env.page.wait_for_selector("#alert-list", timeout=5_000)
    groups = env.page.get_by_test_id("alert-group")
    if groups.count() != 1:
        raise AssertionError(f"{groups.count()} groups in the bell (only the real alerts expected)")
    real = groups.first.inner_text()
    n_real = groups.first.locator("li").count()
    if re.search(r"simulated|needs review", real, re.I):
        raise AssertionError("a simulated device is in the bell's real-alert list")
    sim = env.page.get_by_test_id("bell-simulated").inner_text()
    if "simulated" not in sim.lower():
        raise AssertionError("the simulated link is not labelled")
    env.shot("v2-bell")
    groups.first.locator("li button").first.click()
    env.page.wait_for_selector("[data-testid=open-in-chat]", timeout=10_000)
    env.page.keyboard.press("Escape")
    env.page.wait_for_function(
        "!document.querySelector('[data-testid=open-in-chat]')", timeout=5_000
    )
    return f"{n_real} real alerts; simulated link separate; alert panel opens and closes"


def v2_s_ref(env: Env) -> str:
    """?r=TEST1 is kept on every move and sent with every visit ping."""
    v2_open(env, extra="r=TEST1")
    v2_side_click(env, "nav-signals")
    env.page.wait_for_selector("[data-testid=signals-tabs]", state="attached")
    v2_side_click(env, "new-chat")
    env.page.wait_for_selector("[data-testid=chat-empty]")
    env.page.wait_for_timeout(500)
    if "r=TEST1" not in env.page.url:
        raise AssertionError(f"the ref code was dropped from the address: {env.page.url}")
    ok, why = visits_all_test(env.visit_bodies, "TEST1")
    if not env.visit_bodies:
        raise AssertionError("no visit ping was sent")
    if not ok:
        raise AssertionError(why)
    pages = sorted({json.loads(b or "{}").get("page", "") for b in env.visit_bodies})
    if any(re.search(r"chat:.+|/chat/", p) for p in pages):
        raise AssertionError(f"a chat id is in a visit ping: {pages}")
    return f"{why}; pages {pages}"


def v2_s_chat_chrome(env: Env) -> str:
    """Questions left shows only from 5 down; Live/Recorded badge and the + menu are kept."""
    v2_open(env, "chat", remaining=29)
    v2_ask(env, "Many questions left?")
    if env.page.get_by_test_id("questions-left").count():
        raise AssertionError("'questions left' is shown with 29 left")
    if not env.page.get_by_test_id("model-chip").first.inner_text().strip():
        raise AssertionError("no model chip (Live / Recorded)")
    if env.page.locator(PLUS).count() == 0:
        raise AssertionError("the + menu is missing")
    if env.page.get_by_test_id("voice-note").count():
        raise AssertionError("the audio note is shown while not recording")
    env.page.context.unroute(ASK_PATH)
    env.page.context.route(
        ASK_PATH,
        lambda r: r.fulfill(
            status=200,
            headers=CORS_ANY,
            content_type="application/json",
            body=json.dumps(v2_mock_answer_body("few", 3)),
        ),
    )
    v2_ask(env, "Few questions left?")
    env.page.wait_for_selector("[data-testid=questions-left]", timeout=5_000)
    left = env.page.get_by_test_id("questions-left").inner_text()
    if "3" not in left:
        raise AssertionError(f"questions left reads {left!r}")
    return f"hidden at 29, shown at 3 ({left!r}); badge and + menu kept; no audio note"


def v2_s_keyboard_a11y(env: Env) -> str:
    """Keyboard and screen-reader labels: skip link first, every control named, axe on the v2 pages."""
    v2_open(env)
    env.page.keyboard.press("Tab")
    first = env.page.evaluate("document.activeElement && document.activeElement.textContent.trim()")
    if first != "Skip to content":
        raise AssertionError(f"first Tab stop is {first!r}, not the skip link")
    url = env.page.url
    env.page.keyboard.press("Enter")
    env.page.wait_for_timeout(200)
    if env.page.url != url or env.page.get_by_test_id("topbar-v2").count() == 0:
        raise AssertionError("the skip link left the page")
    if env.page.evaluate("document.activeElement && document.activeElement.id") != "main-v2":
        raise AssertionError("the skip link did not move focus to the page")
    unnamed = env.page.evaluate(
        """[...document.querySelectorAll('button, a[href], select, input, textarea, [role=tab]')]
        .filter(e => e.offsetParent !== null && !e.closest('[aria-hidden=true]'))
        .filter(e => !(e.getAttribute('aria-label') || e.textContent.trim() || e.getAttribute('title')
          || (e.id && document.querySelector('label[for=\"' + e.id + '\"]')) || e.closest('label')))
        .map(e => e.outerHTML.slice(0, 80))"""
    )
    if unnamed:
        raise AssertionError(f"controls without a name: {unnamed[:3]}")
    axe = Path(env.args.axe)
    if not axe.is_file():
        raise SkipError(NOT_PRESENT, f"axe-core not found at {axe}", required=False)
    totals = {"minor": 0, "moderate": 0, "serious": 0, "critical": 0, "unknown": 0}
    worst: list[str] = []
    for path in (
        "",
        "chat",
        "signals/ranked",
        "signals/trend",
        "signals/unfiled",
        "devices/apply",
        "evidence/approve",
        "connect/claude",
    ):
        env.page.goto(v2_url(env, path), wait_until="load")
        env.page.wait_for_selector("#main-v2 h1", timeout=15_000)
        env.page.wait_for_timeout(300)
        env.page.add_script_tag(path=str(axe))
        results = env.page.evaluate("axe.run(document, {resultTypes: ['violations']})")
        for k, v in count_axe(results).items():
            totals[k] += v
        for v in results.get("violations", []):
            if v.get("impact") in ("serious", "critical"):
                worst.append(
                    f"{path or 'home'}: {v.get('id')} ({v.get('impact')}, {len(v.get('nodes', []))} nodes)"
                )
    env.axe_totals = totals  # type: ignore[attr-defined]
    if axe_blocks(totals):
        raise AssertionError("; ".join(worst[:6]) + f" | totals {totals}")
    return f"skip link first; all controls named; axe totals {totals}"


def v2_s_layout_and_drawer(env: Env) -> str:
    """No sideways scroll on any v2 page; the phone drawer opens and closes; the desktop sidebar collapses."""
    bad: list[str] = []
    for path in ("", "chat", *(f"{s}/{t}" for s, tabs in V2_PAGES for t in tabs)):
        v2_open(env, path)
        if env.overflow() > 0:
            bad.append(f"{path or 'home'} +{env.overflow()}px")
    if bad:
        raise AssertionError("sideways scroll: " + ", ".join(bad))
    v2_open(env)
    toggle = env.page.get_by_test_id("sidebar-toggle")
    if env.width < 768:
        if env.page.get_by_test_id("new-chat").is_visible():
            raise AssertionError("the drawer is open on load")
        toggle.click()
        env.page.wait_for_timeout(350)
        if (
            toggle.get_attribute("aria-expanded") != "true"
            or not env.page.get_by_test_id("recents").count()
            and not env.page.get_by_test_id("saved-note").is_visible()
        ):
            raise AssertionError("the drawer did not open")
        env.shot("v2-phone-drawer")
        if (
            env.page.evaluate("document.getElementById('main-v2').hasAttribute('inert')")
            is not True
        ):
            raise AssertionError("the page behind the drawer is not inert")
        for _ in range(14):
            env.page.keyboard.press("Tab")
            inside = env.page.evaluate(
                "!!(document.activeElement && document.activeElement.closest('#sidebar'))"
            )
            if not inside:
                raise AssertionError("Tab left the open drawer")
        env.page.keyboard.press("Escape")
        env.page.wait_for_timeout(350)
        if env.page.get_by_test_id("new-chat").is_visible():
            raise AssertionError("Escape did not close the drawer")
    else:
        toggle.click()
        env.page.wait_for_timeout(200)
        if env.page.get_by_test_id("new-chat").is_visible():
            raise AssertionError("the sidebar did not collapse")
        toggle.click()
    return "0 px sideways on every page; drawer / collapse work"


def v2_pick_theme(env: Env, opener: str, theme: str) -> None:
    """Choose a theme from the one theme menu (sidebar row or top-bar button)."""
    if opener == "side-theme":
        v2_sidebar(env)
    env.page.get_by_test_id(opener).click()
    env.page.get_by_test_id(f"theme-{theme}").click()
    env.page.wait_for_timeout(150)


def v2_s_themes(env: Env) -> str:
    """Every theme applies (smoke) from the one theme control (the sidebar) and is kept after reload."""
    v2_open(env)
    for t in V2_THEMES:
        v2_pick_theme(env, "side-theme", t)
        got = env.page.evaluate("document.documentElement.getAttribute('data-theme')")
        if got != t:
            raise AssertionError(f"theme {t} gave data-theme={got}")
        v2_close_drawer(env)
        env.shot(f"v2-theme-{t}")
    if env.page.get_by_test_id("top-theme").count():
        raise AssertionError("a second theme control is in the top bar")
    v2_pick_theme(env, "side-theme", "light")
    if env.page.evaluate("document.documentElement.getAttribute('data-theme')") != "light":
        raise AssertionError("the theme menu did not apply Paper")
    v2_sidebar(env)
    env.page.get_by_test_id("side-theme").click()
    env.page.keyboard.press("Escape")
    if env.page.locator("[role=menu][aria-label=Theme]").count():
        raise AssertionError("Escape did not close the theme menu")
    v2_close_drawer(env)
    env.page.reload(wait_until="load")
    env.page.wait_for_selector("[data-testid=topbar-v2]")
    if env.page.evaluate("document.documentElement.getAttribute('data-theme')") != "light":
        raise AssertionError("the theme was not kept after reload")
    v2_pick_theme(env, "side-theme", "pink")
    env.page.goto(env.args.url.rstrip("/") + "/?layout=classic", wait_until="load")
    env.page.wait_for_selector(COMPOSER, timeout=30_000)
    classic = env.page.evaluate("document.documentElement.getAttribute('data-theme')")
    if classic in V2_THEMES:
        raise AssertionError(f"the classic layout shows the v2-only theme {classic}")
    return f"themes {', '.join(V2_THEMES)} applied from the one sidebar control; kept; classic never shows them"


def v2_s_fonts(env: Env) -> str:
    """The interface font (Geist) is really loaded and used by the shell."""
    v2_open(env)
    env.page.evaluate("document.fonts.ready")
    loaded = env.page.evaluate("document.fonts.check('16px Geist')")
    family = env.page.evaluate(
        "getComputedStyle(document.querySelector('.ms2-navitem, .ms2-h1')).fontFamily"
    )
    if not loaded or not str(family).startswith("Geist"):
        raise AssertionError(f"Geist loaded={loaded}, family={family}")
    return f"Geist loaded; shell font {family}"


OLD_SHAPE_CHAT = {
    "v": 1,
    "fmt": 1,
    "chats": [
        {
            "id": "coldshape1",
            "title": "Old saved chat",
            "createdAt": 1,
            "updatedAt": 1,
            "turns": [
                {
                    "id": 1,
                    "via": "text",
                    "question": "Old saved question",
                    "status": "done",
                    "resp": {"answer": {"speakable": [{"text": "Old saved answer."}]}},
                }
            ],
        }
    ],
}


def v2_s_saved_edge_cases(env: Env) -> str:
    """A saved answer in an old shape still opens (never a blank page); storage refused says "Not saved"."""
    seed = json.dumps(json.dumps(OLD_SHAPE_CHAT))
    env.page.add_init_script(
        f"if (!sessionStorage.getItem('seeded')) {{ localStorage.setItem('ms-chats-v1', {seed}); sessionStorage.setItem('seeded', '1') }}"
    )
    v2_open(env, "chat/coldshape1")
    env.page.wait_for_selector("[data-testid=user-bubble]", timeout=15_000)
    if (
        env.page.get_by_test_id("chat-broken").count()
        or "Old saved question" not in env.page.locator("#main-v2").inner_text()
    ):
        raise AssertionError("an old-shape saved chat did not open")
    # Storage refused: a new chat is kept in the page and the sidebar says it is not saved.
    p2 = env.page.context.new_page()
    p2.add_init_script(
        "const _set = Storage.prototype.setItem; Storage.prototype.setItem = function (k, v) {"
        " if (k === 'ms-chats-v1') throw new DOMException('full', 'QuotaExceededError'); return _set.call(this, k, v) }"
    )
    env_page = env.page
    env.page = p2
    try:
        env.page.goto(v2_url(env, "chat"), wait_until="load")
        env.page.wait_for_selector("[data-testid=chat-screen]", timeout=30_000)
        v2_ask(env, "Will this be saved?")
        v2_sidebar(env)
        note = env.page.get_by_test_id("saved-note").inner_text()
        if "Not saved" not in note:
            raise AssertionError(f"storage refused but the note says {note!r}")
        v2_close_drawer(env)
    finally:
        env.page = env_page
        p2.close()
    # Opened from a v2 path without ?layout, Home and a refresh stay in v2.
    p3 = env.page.context.new_page()
    p3.goto(env.args.url.rstrip("/") + "/signals/trend", wait_until="load")
    p3.wait_for_selector("[data-testid=topbar-v2]", timeout=30_000)
    p3.locator(".ms2-topbar a").first.click()
    p3.wait_for_timeout(300)
    if "layout=v2" not in p3.url:
        p3.close()
        raise AssertionError(f"Home from a v2 path lost the layout: {p3.url}")
    p3.reload(wait_until="load")
    ok = p3.get_by_test_id("topbar-v2").count() == 1
    p3.close()
    if not ok:
        raise AssertionError("a refresh of Home left v2")
    return "old-shape chat opens; refused storage says 'Not saved'; Home and refresh stay in v2"


HEADLINE = (
    "MaudeSignal cuts the time to investigate a complaint against FDA data and to prepare "
    "PMS evidence, and keeps every fact traceable for audit."
)


def v2_axe_page(env: Env, label: str) -> str:
    """axe-core on the open page; serious or critical violations fail. Empty when axe is absent."""
    axe = Path(env.args.axe)
    if not axe.is_file():
        return ""
    env.page.add_script_tag(path=str(axe))
    results = env.page.evaluate("axe.run(document, {resultTypes: ['violations']})")
    counts = count_axe(results)
    if axe_blocks(counts):
        ids = [v.get("id") for v in results.get("violations", [])]
        raise AssertionError(f"axe on {label}: {ids} {counts}")
    return f"; axe {label} {counts}"


def v2_s_positioning(env: Env) -> str:
    """Headline on Home; /pms-workflow map (8 steps, four fields, stacked on a phone); /roi shows no figure."""
    v2_open(env)
    head = env.page.get_by_test_id("home-headline").inner_text().strip()
    if head != HEADLINE:
        raise AssertionError(f"Home headline is {head!r}")
    env.shot("v2-home-headline")
    env.page.get_by_test_id("home-pms-link").click()
    env.page.wait_for_selector("[data-testid=pms-page]", timeout=10_000)
    if not v2_path(env).endswith("/pms-workflow"):
        raise AssertionError(f"the workflow link opened {v2_path(env)}")
    steps = env.page.get_by_test_id("pms-steps").locator("> li")
    if steps.count() != 8:
        raise AssertionError(f"{steps.count()} steps, not 8")
    fields = [t.strip() for t in steps.nth(1).locator("h3").all_text_contents()]
    if fields != ["Manual today", "What MaudeSignal does", "What stays human", "Related clauses"]:
        raise AssertionError(f"step fields: {fields}")
    if (
        "Stays human — MaudeSignal does not decide."
        not in env.page.get_by_test_id("pms-step-decision").inner_text()
    ):
        raise AssertionError("the decision step does not say it stays human")
    boxes = [steps.nth(1).locator("h3").nth(i).bounding_box() for i in (0, 1)]
    if None in boxes:
        raise AssertionError("step fields have no box")
    same_col = abs(boxes[0]["x"] - boxes[1]["x"]) < 2  # type: ignore[index]
    if (env.width < 768) != same_col:
        raise AssertionError(f"fields {'stacked' if same_col else 'side by side'} at {env.width}px")
    if env.overflow() > 0:
        raise AssertionError(f"workflow page scrolls sideways by {env.overflow()}px")
    env.shot("v2-pms-workflow")
    axe_note = v2_axe_page(env, "workflow")
    env.page.reload(wait_until="load")
    env.page.wait_for_selector("[data-testid=pms-page]", timeout=30_000)
    v2_open(env, "roi")
    env.page.wait_for_selector("[data-testid=roi-page]", timeout=10_000)
    pending = env.page.locator(
        "[data-testid^=roi-pending-]:not([data-testid=roi-pending-chip])"
    ).all_inner_texts()
    if pending != ["Measurement pending"] * 3:
        raise AssertionError(f"pending rows: {pending}")
    body = env.page.get_by_test_id("roi-page").inner_text()
    if re.search(r"\d[\d.,]*\s*(%|x\b|hours?\b|minutes?\b)|[$]\s*\d", body, re.I):
        raise AssertionError("a time or cost figure is on the empty ROI page")
    if not env.page.get_by_test_id("roi-use-recorded").is_disabled():
        raise AssertionError("'Use recorded measurements' is enabled with no measurements")
    if env.overflow() > 0:
        raise AssertionError(f"ROI page scrolls sideways by {env.overflow()}px")
    env.shot("v2-roi-pending")
    if env.page.get_by_test_id("roi-pending-chip").count() != 1:
        raise AssertionError("the empty ROI page has no single Pending chip")
    for field, value in (("complaints", "10"), ("complaintManual", "60"), ("complaintTool", "30")):
        env.page.get_by_test_id(f"roi-in-{field}").fill(value)
    label = env.page.get_by_test_id("roi-result-label").inner_text().strip()
    if label != "from your assumptions":
        raise AssertionError(f"result label is {label!r}")
    for field in ("complaints", "complaintManual", "complaintTool"):
        env.page.get_by_test_id(f"roi-in-{field}").fill("")
    axe_note += v2_axe_page(env, "roi")
    # With two recorded entries (measurements.json route-mocked) the page must still fit the viewport: every card's
    # right edge is inside it and nothing scrolls sideways (a clipped column would fail here).
    seeded = {
        "schema": 1,
        "measurements": [
            {
                "id": "t1",
                "task": "similar-events",
                "who": "Test person with a rather long name to check wrapping",
                "when": "2026-01-02",
                "how": "Stopwatch on a sample complaint, written out in full so the line has to wrap",
                "manual_minutes": 40,
                "maudesignal_minutes": 10,
                "notes": "",
            },
            {
                "id": "t2",
                "task": "weekly-trend",
                "who": "Second person",
                "when": "2026-01-03",
                "how": "Screen recording",
                "manual_minutes": 20,
                "maudesignal_minutes": 30,
                "notes": "",
            },
        ],
    }
    env.page.route(
        "**/data/measurements.json",
        lambda r: r.fulfill(status=200, content_type="application/json", body=json.dumps(seeded)),
    )
    v2_open(env, "roi")
    env.page.wait_for_selector("[data-testid=roi-record]", timeout=10_000)
    if env.page.get_by_test_id("roi-record").count() != 2:
        raise AssertionError("the seeded measurements are not shown")
    if env.page.get_by_test_id("roi-use-recorded").is_disabled():
        raise AssertionError("'Use recorded measurements' is disabled with recorded entries")
    if env.page.get_by_test_id("roi-slower").count() != 1:
        raise AssertionError("the slower recording is not flagged")
    vw = int(env.page.evaluate("document.documentElement.clientWidth"))
    rights = env.page.evaluate(
        "[...document.querySelectorAll("
        "'[data-testid=roi-page] .ms2-card, [data-testid=roi-page] .ms2-roi-rec')]"
        ".map(e => Math.round(e.getBoundingClientRect().right))"
    )
    if any(r > vw for r in rights) or env.overflow() > 0:
        raise AssertionError(
            f"ROI page with measurements overflows: rights {rights}, viewport {vw}"
        )
    env.shot("v2-roi-recorded")
    env.page.unroute("**/data/measurements.json")
    return f"headline on Home; 8 steps, fields {'stacked' if env.width < 768 else 'in 4 columns'}; ROI pending x3{axe_note}"


# --- v2 simulated device lifecycle profiles (/devices/<id>) ------------------------------------

PROFILE_TABS = ("overview", "design", "vv", "regulatory", "market", "postmarket", "people")
SIM_LABEL = "SIMULATED — sample data"
PROFILE_THEMES = ("light", "dark", "contrast", "black", "pink")


def profile_ids() -> list[str]:
    """The simulated device ids, read from the stored company.json the build serves."""
    data = json.loads((HERE.parent.parent / "web" / "public" / "data" / "company.json").read_text())
    return [str(d["id"]) for d in data["devices"]]


def profile_tab(env: Env, tab: str) -> None:
    """Open a profile tab: a click on a computer, the View menu below 480 px."""
    if env.width < 480:
        menu = env.page.get_by_test_id("profile-viewpick")
        if not menu.is_visible():
            raise AssertionError("no View menu on the profile below 480 px")
        menu.select_option(tab)
    else:
        env.page.get_by_test_id(f"tab-{tab}").click()
    env.page.wait_for_timeout(120)


def profile_check(env: Env, did: str, tab: str) -> None:
    """The open tab is the one asked for, labelled SIMULATED on screen and in the title, no sideways scroll."""
    sel = env.page.get_by_test_id(f"tab-{tab}")
    if sel.get_attribute("aria-selected") != "true":
        raise AssertionError(f"{did}/{tab} is not selected")
    if env.page.locator("[role=tab][aria-selected=true]").count() != 1:
        raise AssertionError(f"{did}: more than one tab open")
    banner = env.page.get_by_test_id("profile-banner")
    if banner.count() != 1 or not banner.is_visible() or SIM_LABEL not in banner.inner_text():
        raise AssertionError(f"{did}/{tab}: no single visible SIMULATED banner")
    small = env.page.evaluate(
        "[...document.querySelectorAll('#main-v2 *')].filter(e => [...e.childNodes].some(n => n.nodeType === 3 && n.textContent.trim())"
        " && getComputedStyle(e).fontSize && parseFloat(getComputedStyle(e).fontSize) < 14 && e.getClientRects().length).map(e => e.tagName + ':' + e.textContent.trim().slice(0, 30))"
    )
    if small:
        raise AssertionError(f"{did}/{tab}: text under 14 px: {small[:4]}")
    title = env.page.title()
    if SIM_LABEL not in title:
        raise AssertionError(f"{did}/{tab}: the document title has no SIMULATED label ({title!r})")
    want = f"/devices/{did}" if tab == "overview" else f"/devices/{did}/{tab}"
    if not v2_path(env).endswith(want):
        raise AssertionError(f"{did}/{tab} address is {v2_path(env)}")
    if len(env.page.locator("#profile-panel").inner_text().strip()) < 60:
        raise AssertionError(f"{did}/{tab}: the panel is empty")
    if env.overflow() > 0:
        raise AssertionError(f"{did}/{tab}: {env.overflow()} px sideways scroll")
    text = env.page.locator("#main-v2").inner_text()
    sim = text.split("Real FDA data · MAUDE")[0]
    if re.search(
        r"fda[- ]approved|\bvalidated\b|\bsafe\b|\bunsafe\b|draft capa|\btool (determined|decided)\b",
        sim,
        re.I,
    ):
        raise AssertionError(f"{did}/{tab}: banned wording on a simulated page")
    if re.search(r"\bK\d{6}\b", sim):
        raise AssertionError(f"{did}/{tab}: a real-looking K-number is shown")


def v2_s_profiles_all(env: Env) -> str:
    """Every simulated device's profile opens at /devices/<id>, and every tab carries the SIMULATED label."""
    ids = profile_ids()
    for did in ids:
        v2_open(env, f"devices/{did}")
        env.page.wait_for_selector(f"[data-testid=device-profile][data-id='{did}']", timeout=15_000)
        if not env.page.get_by_test_id("profile-banner").is_visible():
            raise AssertionError(f"{did}: no SIMULATED banner")
        for tab in PROFILE_TABS:
            if tab != "overview":
                profile_tab(env, tab)
            profile_check(env, did, tab)
        if did == ids[0]:
            env.shot("v2-profile-people")
    return f"{len(ids)} profiles x {len(PROFILE_TABS)} tabs open, labelled SIMULATED in the panel and title, 0 px sideways"


def v2_s_profiles_nav(env: Env) -> str:
    """Our devices tiles; a row opens /devices/<id> keeping ?r= and the layout; Back and refresh work."""
    v2_open(env, "devices/apply", "r=TEST1")
    env.page.wait_for_selector("[data-testid=device-tiles]", timeout=15_000)
    tiles = env.page.get_by_test_id("device-tiles").inner_text()
    if "(simulated)" not in tiles or "Under FDA review" not in tiles or "Open CAPAs" not in tiles:
        raise AssertionError(f"the device tiles are missing or unlabelled: {tiles[:160]!r}")
    env.shot("v2-devices-dashboard")
    rows = env.page.locator("#main-v2 button[aria-label$='Open.']")
    if rows.count() != 12:
        raise AssertionError(f"{rows.count()} device rows, not 12")
    if "(simulated)" in " ".join(rows.all_inner_texts()):
        raise AssertionError("a device row repeats '(simulated)'")
    if env.page.locator("#main-v2 :text-is('Make it yours'):visible").count() > 1:
        raise AssertionError("'Make it yours' is shown twice on Our devices")
    if env.page.get_by_test_id("device-alert-details").count():
        raise AssertionError("a device row still has a second 'Alert details' button")
    if env.width >= 480:  # a click on the row away from the name opens the profile, too
        env.page.locator("#main-v2 tbody tr").first.locator("td").nth(1).click()
        env.page.wait_for_selector("[data-testid=device-profile]", timeout=15_000)
        env.page.go_back(wait_until="load")
        env.page.wait_for_selector("[data-testid=device-tiles]", timeout=15_000)
    rows.first.click()
    env.page.wait_for_selector("[data-testid=device-profile]", timeout=15_000)
    did = str(env.page.get_by_test_id("device-profile").get_attribute("data-id"))
    if not v2_path(env).endswith(f"/devices/{did}"):
        raise AssertionError(f"a device row opened {v2_path(env)}, not /devices/{did}")
    q = str(env.page.evaluate("location.search"))
    if "r=TEST1" not in q or "layout=v2" not in q:
        raise AssertionError(f"the query string was not kept: {q}")
    profile_check(env, did, "overview")
    profile_tab(env, "regulatory")
    profile_tab(env, "postmarket")
    profile_check(env, did, "postmarket")
    real = env.page.get_by_test_id("real-patterns")
    if real.count() != 1 or "Real FDA data" not in real.inner_text():
        raise AssertionError("Post-market has no separate real FDA data box")
    env.page.reload(wait_until="load")
    env.page.wait_for_selector("[data-testid=device-profile]", timeout=15_000)
    profile_check(env, did, "postmarket")
    env.page.go_back(wait_until="load")
    env.page.wait_for_timeout(300)
    profile_check(env, did, "regulatory")
    env.page.go_back(wait_until="load")
    env.page.go_back(wait_until="load")
    env.page.wait_for_timeout(300)
    if not v2_path(env).endswith("/devices/apply"):
        raise AssertionError(f"Back did not return to Our devices: {v2_path(env)}")
    env.page.wait_for_selector("[data-testid=device-tiles]", timeout=10_000)
    # A fresh tab on the bare address opens the profile in v2 (the Vercel rewrite covers /devices/:path*).
    p2 = env.page.context.new_page()
    p2.goto(env.args.url.rstrip("/") + f"/devices/{did}/vv", wait_until="load")
    p2.wait_for_selector("[data-testid=device-profile]", timeout=30_000)
    ok = p2.get_by_test_id("tab-vv").get_attribute("aria-selected") == "true"
    p2.close()
    if not ok:
        raise AssertionError("a fresh tab on /devices/<id>/vv did not open that tab")
    return f"tiles labelled; row -> /devices/{did} with ?r= kept; refresh and Back keep the tab; bare address opens v2"


def v2_s_profiles_themes(env: Env) -> str:
    """A profile in every theme (light, dark, contrast, black, pink): labelled, readable, no sideways scroll."""
    ids = profile_ids()
    did = next((i for i in ids if i == "DMC-06"), ids[0])
    v2_open(env, f"devices/{did}")
    env.page.wait_for_selector("[data-testid=device-profile]", timeout=15_000)
    for t in PROFILE_THEMES:
        v2_pick_theme(env, "side-theme", t)
        v2_close_drawer(env)
        got = env.page.evaluate("document.documentElement.getAttribute('data-theme')")
        if got != t:
            raise AssertionError(f"theme {t} gave data-theme={got}")
        for tab in ("overview", "vv", "postmarket"):
            profile_tab(env, tab)
            profile_check(env, did, tab)
        same = env.page.evaluate(
            "(() => { const e = document.querySelector('[data-testid=profile-banner]');"
            " const s = getComputedStyle(e); return s.color === s.backgroundColor })()"
        )
        if same:
            raise AssertionError(f"theme {t}: the SIMULATED label is unreadable")
        env.shot(f"v2-profile-theme-{t}")
        profile_tab(env, "overview")
    return f"{did} in {', '.join(PROFILE_THEMES)}: labelled, 0 px sideways"


def profile_paths() -> dict[str, list[dict[str, Any]]]:
    """Device id -> its simulated decision paths, read from the stored company_profiles.json."""
    data = json.loads(
        (HERE.parent.parent / "web" / "public" / "data" / "company_profiles.json").read_text()
    )
    return {k: list(v["decision"]["paths"]) for k, v in data["profiles"].items()}


def open_all_paths(env: Env) -> None:
    """Open every decision-path card (they are <details>) with a click on its summary."""
    for i in range(env.page.get_by_test_id("decision-path").count()):
        card = env.page.get_by_test_id("decision-path").nth(i)
        if card.get_attribute("open") is None:
            card.locator(":scope > summary").click()
    details = env.page.locator(".ms2-more > summary")
    for i in range(details.count()):
        item = details.nth(i)
        if item.locator("xpath=..").get_attribute("open") is None:
            item.click()
    env.page.wait_for_timeout(100)


def check_path_steps(env: Env, did: str, path: dict[str, Any], card: Any) -> None:
    """Step through one path: four steps, clause chips with reasons, real evidence apart, outcome and risk."""
    steps = card.get_by_test_id("dp-step")
    if steps.count() != 4:
        raise AssertionError(f"{did}/{path['id']}: {steps.count()} steps, not 4")
    for i, name in enumerate(("triage", "board", "outcome", "risk")):
        step = steps.nth(i)
        step.scroll_into_view_if_needed()
        if step.get_attribute("data-step") != name or not step.is_visible():
            raise AssertionError(f"{did}/{path['id']}: step {i + 1} is not {name} or is hidden")
        chips = step.get_by_test_id("clause-chip")
        if chips.count() < 1:
            if name in ("outcome", "risk") and path["state"] == "open":
                continue  # not reached yet: no outcome, so no clauses
            raise AssertionError(f"{did}/{path['id']}/{name}: no compliance chip")
        for j in range(chips.count()):
            if len(str(chips.nth(j).get_attribute("title"))) < 20:
                raise AssertionError(f"{did}/{path['id']}/{name}: a chip has no reason on hover")
        why = step.locator(".ms2-why > summary")
        why.click()
        if len(step.locator(".ms2-why li").all_inner_texts()) != chips.count():
            raise AssertionError(
                f"{did}/{path['id']}/{name}: 'Why these clauses' lists another count"
            )
    board = steps.nth(1)
    real = board.get_by_test_id("dp-real").inner_text()
    sim = board.get_by_test_id("dp-company").inner_text()
    if "Real FDA data" not in real or "SIMULATED" in real:
        raise AssertionError(f"{did}/{path['id']}: the real evidence panel is not labelled real")
    if "Simulated — sample data" not in sim:
        raise AssertionError(f"{did}/{path['id']}: the company side is not labelled simulated")
    if path["state"] == "decided":
        out = steps.nth(2).inner_text()
        kind = path["outcome"]["kind"]
        want = {
            "ntf": "Note to file",
            "capa": "CAPA opened",
            "escalation": "Assessed by the board",
        }[kind]
        if want not in out:
            raise AssertionError(f"{did}/{path['id']}: outcome step lacks {want!r}")
        if steps.nth(3).get_by_test_id("risk-grid").count() != 1:
            raise AssertionError(f"{did}/{path['id']}: no risk grid")
        reportable = kind == "escalation" and path["outcome"]["mdr"]["result"] == "reportable"
        if reportable and ("30-day clock" not in out or "became aware" not in out):
            raise AssertionError(f"{did}/{path['id']}: the 30-day clock is not explained")
    elif "No outcome yet" not in steps.nth(2).inner_text():
        raise AssertionError(f"{did}/{path['id']}: an open path shows an outcome")
    banned = r"maudesignal (determined|decided)|\btool (determined|decided)\b|fda[- ]approved|\bvalidated\b|\bsafe\b|\bunsafe\b|draft capa"
    if re.search(banned, card.inner_text(), re.I):
        raise AssertionError(f"{did}/{path['id']}: banned wording in a decision path")


def v2_s_profiles_paths(env: Env) -> str:
    """Every device with decision paths: open Post-market, step through each path; the investigate link; the tile."""
    by_dev = profile_paths()
    total = 0
    for did, paths in by_dev.items():
        v2_open(env, f"devices/{did}/postmarket", "r=TEST1")
        env.page.wait_for_selector("[data-testid=device-profile]", timeout=15_000)
        profile_check(env, did, "postmarket")
        link = env.page.get_by_test_id("investigate-link")
        href = str(link.get_attribute("href"))
        code = str(
            env.page.evaluate("document.querySelector('.ms2-lead .ms-code').textContent")
        ).strip()
        if not href.startswith(f"/investigate?code={code}&device={did}"):
            raise AssertionError(f"{did}: investigate href is {href}")
        if "r=TEST1" not in href or "layout=v2" not in href:
            raise AssertionError(f"{did}: investigate href lost ?r= or ?layout: {href}")
        if not paths:
            if env.page.get_by_test_id("no-decision-path").count() != 1:
                raise AssertionError(f"{did}: no reason given for a missing decision path")
            continue
        cards = env.page.get_by_test_id("decision-path")
        if cards.count() != len(paths):
            raise AssertionError(f"{did}: {cards.count()} paths shown, {len(paths)} stored")
        expanded = env.page.locator("[data-testid=decision-path][open]").count()
        want_open = sum(1 for x in paths if x["state"] == "open")
        if expanded != want_open:
            raise AssertionError(f"{did}: {expanded} paths expanded by default, not {want_open}")
        open_all_paths(env)
        for i, path in enumerate(
            sorted(paths, key=lambda x: (x["state"] != "open", x["triage"]["date"]))
        ):
            check_path_steps(env, did, path, cards.nth(i))
            total += 1
        if env.overflow() > 0:
            raise AssertionError(f"{did}: {env.overflow()} px sideways scroll with the paths open")
        # The link from the history opens the first path.
        env.page.get_by_test_id("open-decision-path").click()
        if cards.first.get_attribute("open") is None:
            raise AssertionError(f"{did}: the history link did not open the decision path")
    env.shot("v2-decision-path")
    v2_open(env, "devices/apply")
    env.page.wait_for_selector("[data-testid=device-tiles]", timeout=15_000)
    tile = env.page.get_by_test_id("tile-decision").inner_text()
    open_paths = sum(1 for ps in by_dev.values() for x in ps if x["state"] == "open")
    open_devs = sum(1 for ps in by_dev.values() if any(x["state"] == "open" for x in ps))
    if (
        f"{open_paths}" not in tile
        or "Decisions due" not in tile
        or f"on {open_devs} devices" not in tile
    ):
        raise AssertionError(f"the Decisions due tile is {tile!r}, not {open_paths} on {open_devs}")
    return f"{total} decision paths on {len(by_dev)} devices stepped through (4 steps, chips, real vs simulated); investigate href kept ?r= and layout; tile {open_paths} on {open_devs} devices"


CONTRAST_JS = """(() => {
  const rgb = (c) => (c.match(/[\\d.]+/g) || []).slice(0, 4).map(Number);
  const lum = ([r, g, b]) => { const f = (v) => { v /= 255; return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4 }; return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b) };
  const ratio = (a, b) => { const x = lum(a), y = lum(b); return (Math.max(x, y) + 0.05) / (Math.min(x, y) + 0.05) };
  const bad = [];
  document.querySelectorAll('.ms2-rg-num, .ms2-rg-axis').forEach((t) => {
    const cell = t.previousElementSibling && t.previousElementSibling.classList.contains('ms2-rg-cell') ? t.previousElementSibling : null;
    const bg = cell ? rgb(getComputedStyle(cell).fill) : rgb(getComputedStyle(document.body).backgroundColor);
    const r = ratio(rgb(getComputedStyle(t).fill), bg);
    if (r < 4.5) bad.push('grid ' + t.textContent + ' ' + r.toFixed(2));
  });
  document.querySelectorAll('.ms2-pill, .ms2-tile--attn[data-attn=on] .ms2-tile-n, .ms2-step-n').forEach((e) => {
    const s = getComputedStyle(e);
    const bgc = rgb(s.backgroundColor);
    if (!bgc.length || (bgc.length === 4 && bgc[3] === 0)) return;
    const r = ratio(rgb(s.color), bgc);
    if (r < 4.5) bad.push(e.className + ' ' + e.textContent.trim().slice(0, 20) + ' ' + r.toFixed(2));
  });
  return bad;
})()"""


def v2_s_profiles_path_themes(env: Env) -> str:
    """The decision path in every theme: step numbers, chips and the real box stay readable; no sideways scroll."""
    by_dev = profile_paths()
    did = "DMC-06"
    v2_open(env, f"devices/{did}/postmarket")
    env.page.wait_for_selector("[data-testid=decision-path]", timeout=15_000)
    for t in PROFILE_THEMES:
        v2_pick_theme(env, "side-theme", t)
        v2_close_drawer(env)
        open_all_paths(env)
        profile_check(env, did, "postmarket")
        bad = env.page.evaluate(
            "[...document.querySelectorAll('.ms2-step-n, [data-testid=clause-chip], .ms2-simtag')]"
            ".filter(e => { const s = getComputedStyle(e); return s.color === s.backgroundColor }).length"
        )
        if bad:
            raise AssertionError(
                f"theme {t}: {bad} decision-path elements have text the colour of their background"
            )
        low = env.page.evaluate(CONTRAST_JS)
        if low:
            raise AssertionError(f"theme {t}: contrast under 4.5:1 for {low[:4]}")
        env.shot(f"v2-decision-path-{t}")
    return (
        f"{did} paths ({len(by_dev[did])}) in {', '.join(PROFILE_THEMES)}: readable, 0 px sideways"
    )


V2_SCENARIOS: tuple[tuple[str, Callable[[Env], str]], ...] = (
    ("v2 Home: top 3 real alerts, view all, simulated apart", v2_s_home),
    ("v2 new chat saves the old one", v2_s_new_chat),
    ("v2 Recents: reopen, rename, delete", v2_s_recents),
    ("v2 Ctrl K search", v2_s_search),
    ("v2 refresh and Back on /chat/<id>", v2_s_refresh_back),
    ("v2 every section and subtab", v2_s_sections),
    ("v2 bell: real alerts only", v2_s_bell),
    ("v2 ?r=TEST1 kept and sent", v2_s_ref),
    ("v2 chat chrome: questions left, badge, + menu", v2_s_chat_chrome),
    ("v2 keyboard, labels, axe", v2_s_keyboard_a11y),
    ("v2 no sideways scroll, drawer", v2_s_layout_and_drawer),
    ("v2 themes smoke", v2_s_themes),
    ("v2 interface font", v2_s_fonts),
    ("v2 saved-chat edge cases, staying in v2", v2_s_saved_edge_cases),
    ("v2 headline, PMS workflow map, time and cost", v2_s_positioning),
    ("v2 device profiles: all 12, every tab, SIMULATED", v2_s_profiles_all),
    ("v2 device profiles: tiles, row, Back and refresh", v2_s_profiles_nav),
    ("v2 device profiles: every theme", v2_s_profiles_themes),
    ("v2 device profiles: decision paths, step through", v2_s_profiles_paths),
    ("v2 device profiles: decision paths in every theme", v2_s_profiles_path_themes),
)

# F25 Investigate a complaint: its scenarios live in e2e_investigate.py (bound to this module's helpers).
from e2e_investigate import make_scenarios as _investigate_scenarios  # noqa: E402

V2_SCENARIOS = V2_SCENARIOS + _investigate_scenarios(sys.modules[__name__])


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
        "--layout",
        choices=("classic", "v2"),
        default="classic",
        help="classic: the existing scenarios at the plain address; v2: the v2 layout scenarios at ?layout=v2",
    )
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
    ap.add_argument(
        "--only",
        default="",
        help="comma-separated parts of scenario names to run (for example 'v2:'); "
        "error states are skipped when set",
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
    rep.metrics.update(url=args.url, api=args.api, suite=args.suite, layout=args.layout)
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
                    if args.only:
                        parts = [x.strip() for x in args.only.split(",") if x.strip()]
                        scenarios = [s for s in scenarios if any(x in s[0] for x in parts)]
                    if smoke and width != first_width:  # live-spending scenarios: one width only
                        scenarios = [s for s in scenarios if s[0] not in SMOKE_LIVE]
                    todo = [("scenario", n, f) for n, f in scenarios]
                    if args.suite == "full" and not args.only:
                        todo += [("error state", n, f) for n, f in ERROR_SCENARIOS]
                    if (
                        args.layout == "v2"
                    ):  # the v2 shell: its own scenarios, each opens its own page
                        todo = [("v2 layout", n, f) for n, f in V2_SCENARIOS]
                        if args.only:  # --only narrows the v2 scenarios too
                            parts = [x.strip() for x in args.only.split(",") if x.strip()]
                            todo = [t for t in todo if any(x in t[1] for x in parts)]
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
