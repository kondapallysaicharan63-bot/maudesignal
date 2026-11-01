"""Browser scenarios for "Investigate a complaint" (F25), run by ``e2e_web.py --layout v2``.

HACKATHON-BUILT — Meta Global AI Developer Hackathon (Oct 26 – Nov 4, 2026).

``make_scenarios(m)`` takes the ``e2e_web`` module (so these scenarios use its ``v2_open``, ``v2_url``,
``Env`` and report helpers without importing it a second time) and returns the scenario tuple.
Everything is route-mocked ($0, no model call, no openFDA call): ``POST /v1/investigate`` is answered
from ``web/src/fixtures/investigateExample.json`` with ``mode: "live"``.

On a build without ``VITE_MAUDESIGNAL_API_BASE`` the page shows the recorded example instead; the
scenarios then check that and that no ``/v1/investigate`` request is made.
"""

# ruff: noqa: E501
from __future__ import annotations

import json
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

FIXTURE = (
    Path(__file__).resolve().parents[2] / "web" / "src" / "fixtures" / "investigateExample.json"
)
BANNER = "Do not enter patient data. Describe the device problem only."
NOTICE_START = "This is evidence assembled from public FDA data to attach to your complaint record"
DESCRIPTION = "The viewer froze when a clinician saved a study, and images came up unreadable."


def make_scenarios(m: Any) -> tuple[tuple[str, Callable[[Any], str]], ...]:
    """The investigate scenarios, bound to the helpers of the ``e2e_web`` module ``m``."""
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    answer = {**fixture["answer"], "mode": "live", "source_note": None}

    def mock_api(env: Any, status: int = 200, body: Any = None) -> list[dict[str, Any]]:
        """Answer POST /v1/investigate; returns the request bodies seen."""
        seen: list[dict[str, Any]] = []

        def handler(route: Any) -> None:
            if route.request.method == "OPTIONS":
                route.fulfill(
                    status=204,
                    headers={
                        **m.CORS_ANY,
                        "access-control-allow-methods": "POST, OPTIONS",
                        "access-control-allow-headers": "content-type",
                    },
                )
                return
            try:
                seen.append(json.loads(route.request.post_data or "{}"))
            except ValueError:
                seen.append({})
            route.fulfill(
                status=status,
                headers=m.CORS_ANY,
                content_type="application/json",
                body=json.dumps(answer if body is None else body),
            )

        env.page.context.route("**/v1/investigate", handler)
        return seen

    def is_live(env: Any) -> bool:
        return bool(env.page.get_by_test_id("inv-run").count())

    def no_overflow(env: Any, what: str) -> None:
        if env.overflow() > 0:
            raise AssertionError(f"{what}: sideways scroll of {env.overflow()}px")

    def fill_and_run(env: Any, code: str, text: str) -> None:
        env.page.get_by_test_id("inv-code").fill(code)
        env.page.get_by_test_id("inv-desc").fill(text)
        env.page.get_by_test_id("inv-run").click()
        env.page.wait_for_selector("[data-testid=inv-results]", timeout=15_000)

    def check_results(env: Any, *, recorded: bool) -> None:
        page = env.page
        badges = page.get_by_test_id("inv-badge")
        if badges.count() != 4:
            raise AssertionError(
                f"{badges.count()} provenance badges, not 4 (three sections and the evidence)"
            )
        prov = badges.first.inner_text()
        want = "Recorded example" if recorded else "Real FDA data"
        if want not in prov:
            raise AssertionError(f"provenance is {prov!r}, not {want!r}")
        if not recorded and "retrieved" not in prov:
            raise AssertionError("a live run does not say when it was retrieved")
        rows = page.locator("[data-testid=inv-months] tbody tr").count()
        if rows != 12:
            raise AssertionError(f"{rows} month rows, not 12")
        links = page.locator(
            "[data-testid=inv-months] tbody a[href^='https://api.fda.gov/']"
        ).count()
        if links < 4:
            raise AssertionError(f"only {links} month figures link to openFDA")
        if (
            not page.get_by_test_id("inv-total-code").inner_text().strip()
            or not page.get_by_test_id("inv-total-kw").inner_text().strip()
        ):
            raise AssertionError("a total is missing")
        quotes = page.get_by_test_id("inv-quote").count()
        if quotes < 1 or quotes > 5:
            raise AssertionError(f"{quotes} quotes")
        if "cannot be separated" not in page.get_by_test_id("inv-own-maker").inner_text():
            raise AssertionError("the own-company limit is not stated")
        zero = page.locator("[data-testid=inv-months] tr.ms2-inv-zero a").count()
        if zero:
            raise AssertionError(f"{zero} links on months with no reports")
        if (
            page.get_by_test_id("inv-summary").count() == 0
            or page.get_by_test_id("inv-jumps").locator("button").count() != 4
        ):
            raise AssertionError("the form did not collapse to a summary with jump links")
        if re.search(r"other makers|Similar MAUDE", page.locator("body").inner_text()):
            raise AssertionError("a heading says 'other makers' or 'Similar'")
        for tid in ("inv-sources", "inv-recalls", "inv-clearances", "inv-evidence"):
            if page.get_by_test_id(tid).count() == 0:
                raise AssertionError(f"{tid} is missing")
        text = page.get_by_test_id("inv-evidence-text").inner_text()
        for must in (
            "as entered by the user; not stored",
            NOTICE_START,
            "https://api.fda.gov/device/event.json?",
            "Product code: LLZ",
        ):
            if must not in text:
                raise AssertionError(f"the evidence text lacks {must!r}")
        if "MaudeSignal determined" in page.locator("body").inner_text():
            raise AssertionError("the page says MaudeSignal determined something")

    def check_copy(env: Any) -> int:
        if env.engine != "chromium":
            return 0
        env.page.context.grant_permissions(["clipboard-read", "clipboard-write"])
        env.page.get_by_test_id("inv-copy").click()
        env.page.wait_for_timeout(300)
        got = str(env.page.evaluate("navigator.clipboard.readText()"))
        shown = env.page.get_by_test_id("inv-evidence-text").inner_text()
        if " ".join(got.split()) != " ".join(shown.split()):
            raise AssertionError(
                f"the clipboard differs from the evidence text ({len(got)} vs {len(shown)} chars)"
            )
        if env.page.get_by_test_id("inv-copy-status").inner_text().strip() != "Copied.":
            raise AssertionError("no 'Copied.' feedback")
        return len(got)

    def s_flow(env: Any) -> str:
        """Home button -> form -> LLZ and a description -> results with the evidence section -> Copy and Download."""
        seen = mock_api(env)
        m.v2_open(env)
        card = env.page.get_by_test_id("home-investigate")
        if card.locator("button").count() != 1:
            raise AssertionError("the Home card must have exactly one button")
        env.shot("v2-home-investigate")
        card.get_by_test_id("home-investigate-open").click()
        env.page.wait_for_selector("[data-testid=investigate-page]", timeout=10_000)
        if not m.v2_path(env).endswith("/investigate"):
            raise AssertionError(f"the button opened {m.v2_path(env)}")
        if env.page.locator("#main-v2 h1").first.inner_text().strip() != "Investigate a complaint":
            raise AssertionError("wrong page title")
        if env.page.get_by_test_id("inv-banner").inner_text().strip() != BANNER:
            raise AssertionError("the patient-data banner is missing or changed")
        if is_live(env):
            if env.page.get_by_test_id("inv-run").is_enabled():
                raise AssertionError("Investigate is enabled with an empty form")
            env.shot("v2-investigate-form")
            fill_and_run(env, "llz", DESCRIPTION)
            if len(seen) != 1 or seen[0] != {"product_code": "LLZ", "description": DESCRIPTION}:
                raise AssertionError(f"request body was {seen}")
            check_results(env, recorded=False)
            where = "live (route-mocked)"
        else:
            if env.page.get_by_test_id("inv-recorded-note").count() == 0:
                raise AssertionError(
                    "no 'Recorded example' label on a build without an API address"
                )
            check_results(env, recorded=True)
            if any("/v1/investigate" in c for c in env.api_calls):
                raise AssertionError("the recorded example called the API")
            where = "recorded example"
        env.page.get_by_test_id("inv-evidence").scroll_into_view_if_needed()
        env.shot("v2-investigate-results")
        env.page.get_by_test_id("inv-evidence").screenshot(
            path=str(
                Path(env.args.out_dir)
                / "screenshots"
                / f"{env.tag.replace(' ', '-')}-v2-investigate-evidence.png"
            )
        )
        chars = check_copy(env)
        with env.page.expect_download(timeout=10_000) as dl:
            env.page.get_by_test_id("inv-download").click()
        name = dl.value.suggested_filename
        if not name.startswith("complaint-evidence-LLZ-") or not name.endswith(".txt"):
            raise AssertionError(f"download named {name!r}")
        url = env.page.url
        stored = env.page.evaluate(
            "JSON.stringify([localStorage, sessionStorage, document.cookie])"
        )
        if "froze" in url or "froze" in str(stored):
            raise AssertionError("the description reached the address, storage or a cookie")
        no_overflow(env, "results")
        return f"{where}: Home button, form, 12 months, quotes, evidence, Copy ({chars} chars), download {name}"

    def s_menu(env: Any) -> str:
        """The "+" menu item 'Investigate a complaint' opens the page; the other items stay put."""
        mock_api(env)
        m.v2_open(env, "chat")
        plus = env.page.locator(m.PLUS)
        if plus.count() == 0:
            raise m.SkipError(
                m.NOT_PRESENT, "this build has the earlier composer (no + menu)", required=False
            )
        plus.click()
        env.page.wait_for_selector("[role=menu]", timeout=5_000)
        items = env.page.locator("[role=menu] [role^=menuitem]")
        names = [items.nth(i).inner_text().split("\n")[0] for i in range(items.count())]
        if "Investigate a complaint" not in names:
            raise AssertionError(f"menu items: {names}")
        if names[0] != "Take photo" or names[-1] != "Ask by voice":
            raise AssertionError(f"the other items moved: {names}")
        env.shot("v2-investigate-menu")
        env.page.get_by_test_id("menu-investigate").click()
        env.page.wait_for_selector("[data-testid=investigate-page]", timeout=10_000)
        if not m.v2_path(env).endswith("/investigate"):
            raise AssertionError(f"the menu item opened {m.v2_path(env)}")
        return f"menu of {len(names)} items; the item opens /investigate"

    def s_deeplink(env: Any) -> str:
        """/investigate?code=LLZ&device=<id> fills the code and names the simulated device; ?layout and ?r are kept."""
        mock_api(env)
        m.v2_open(env, "investigate", "code=LLZ&device=sim-3&r=TEST-1")
        page = env.page
        if page.get_by_test_id("inv-code").input_value() != "LLZ":
            raise AssertionError("the code was not filled")
        if is_live(env) and "sim-3" not in page.get_by_test_id("inv-device-note").inner_text():
            raise AssertionError("the simulated device is not named")
        url = page.url
        if "layout=v2" not in url or "r=TEST-1" not in url:
            raise AssertionError(f"query lost: {url}")
        page.reload(wait_until="load")
        page.wait_for_selector("[data-testid=investigate-page]", timeout=15_000)
        if page.get_by_test_id("inv-code").input_value() != "LLZ":
            raise AssertionError("a refresh lost the code")
        return "code and device prefilled from the address, kept on refresh; ?layout and ?r kept"

    def s_patient(env: Any) -> str:
        """The server refuses patient details: the message is shown, no results, nothing invented."""
        mock_api(
            env,
            422,
            {
                "code": "patient_data",
                "message": "Please remove patient details (names, ages, email addresses, phone numbers, ID or record numbers, dates of birth) and send again. Nothing was answered or kept.",
            },
        )
        m.v2_open(env, "investigate", "code=LLZ")
        if not is_live(env):
            raise m.SkipError(
                m.NOT_PRESENT, "recorded build: the form is read-only", required=False
            )
        env.page.get_by_test_id("inv-desc").fill("The viewer froze for Mrs. Jane Smith")
        env.page.get_by_test_id("inv-run").click()
        env.page.wait_for_selector("[data-testid=inv-error-patient_data]", timeout=10_000)
        if env.page.get_by_test_id("inv-results").count():
            raise AssertionError("results shown after a refusal")
        if (
            "Nothing was answered or kept"
            not in env.page.get_by_test_id("inv-error-patient_data").inner_text()
        ):
            raise AssertionError("the explanation is missing")
        env.shot("v2-investigate-refused")
        no_overflow(env, "refusal")
        return "patient details refused with the server's explanation; no results"

    def s_a11y(env: Any) -> str:
        """Labels, no sideways scroll and axe on the form and on the results."""
        mock_api(env)
        m.v2_open(env, "investigate", "code=LLZ")
        if is_live(env):
            fill_and_run(env, "LLZ", DESCRIPTION)
        axe = Path(env.args.axe)
        if not axe.is_file():
            raise m.SkipError(m.NOT_PRESENT, f"axe-core not found at {axe}", required=False)
        env.page.add_script_tag(path=str(axe))
        results = env.page.evaluate("axe.run(document, {resultTypes: ['violations']})")
        counts = m.count_axe(results)
        no_overflow(env, "investigate")
        if m.axe_blocks(counts):
            ids = [
                f"{v['id']}({v.get('impact')})"
                for v in results.get("violations", [])
                if v.get("impact") in ("serious", "critical")
            ]
            raise AssertionError(f"axe: {ids} {counts}")
        return f"axe {counts}; no sideways scroll"

    def s_states(env: Any) -> str:
        """Limit, partial (time limit) and empty states: honest messages, no invented numbers."""
        mock_api(
            env,
            429,
            {
                "code": "rate_limited",
                "message": "Limit of 6 investigations per hour reached. Retry in 600 seconds.",
            },
        )
        m.v2_open(env, "investigate", "code=LLZ")
        if not is_live(env):
            raise m.SkipError(m.NOT_PRESENT, "recorded build: no requests are made", required=False)
        env.page.get_by_test_id("inv-desc").fill(DESCRIPTION)
        env.page.get_by_test_id("inv-run").click()
        env.page.wait_for_selector("[data-testid=inv-error-rate]", timeout=10_000)
        if env.page.get_by_test_id("inv-results").count():
            raise AssertionError("results after a limit")
        env.shot("v2-investigate-limit")
        partial = {
            **answer,
            "notes": [
                "The time limit of this search was reached, so some sections are missing. Run it again to fill them in."
            ],
            "recalls": {"total": None, "items": [], "note": "Recalls could not be read."},
            "clearances": {"total": None, "items": [], "note": "510(k)s could not be read."},
            "sources": None,
            "quotes": [],
        }
        env.page.context.unroute("**/v1/investigate")
        mock_api(env, 200, partial)
        env.page.get_by_test_id("inv-run").click()
        env.page.wait_for_selector("[data-testid=inv-results]", timeout=10_000)
        if "time limit" not in env.page.get_by_test_id("inv-note").first.inner_text():
            raise AssertionError("the partial note is missing")
        if "could not be read" not in env.page.get_by_test_id("inv-recalls").inner_text():
            raise AssertionError("a missing section is not said to be missing")
        env.shot("v2-investigate-partial")
        empty = {
            **answer,
            "keywords": [],
            "total_keyword_matched": None,
            "quotes": [],
            "months": [
                {**mo, "keyword_matched": None, "keyword_url": None, "code_wide": 0}
                for mo in answer["months"]
            ],
            "total_code_wide": {"value": 0, "url": answer["total_code_wide"]["url"]},
        }
        env.page.context.unroute("**/v1/investigate")
        mock_api(env, 200, empty)
        env.page.get_by_test_id("inv-edit").click()
        env.page.get_by_test_id("inv-run").click()
        env.page.wait_for_selector("[data-testid=inv-keywords]", timeout=10_000)
        if "no content words" not in env.page.get_by_test_id("inv-keywords").inner_text():
            raise AssertionError("the no-keywords state is not explained")
        env.shot("v2-investigate-empty")
        no_overflow(env, "states")
        return "limit, partial and empty states shown honestly"

    return (
        ("v2 investigate: Home button, form, results, evidence, Copy", s_flow),
        ("v2 investigate: + menu item", s_menu),
        ("v2 investigate: ?code and ?device", s_deeplink),
        ("v2 investigate: patient data refused", s_patient),
        ("v2 investigate: labels and axe", s_a11y),
        ("v2 investigate: limit, partial, empty states", s_states),
    )
