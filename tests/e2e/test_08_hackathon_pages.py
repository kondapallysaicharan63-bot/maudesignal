"""E2E tests for the hackathon pages: Signals (workspace), Copilot, Vision, Audit.

HACKATHON-BUILT — Meta Global AI Developer Hackathon (Oct 26 – Nov 4, 2026).

Run against the keyless public-demo setup (no ``MAUDESIGNAL_DB_PATH``, no
``META_MODEL_API_KEY``), so the dashboard opens the committed demo database:

    streamlit run streamlit_app.py --server.headless true
    pytest tests/e2e/test_08_hackathon_pages.py -m e2e --no-cov -v

Expected values are not typed in: they are computed here from the same demo
database with the package's own functions (detector, digest, gate, transcript
loader), so a test fails only when the page disagrees with the data. The tests
hold whether or not recorded Meta runs exist yet.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

import pytest
from playwright.sync_api import Locator, Page, expect

from maudesignal.copilot.audit_export import load_exports
from maudesignal.copilot.transcript import load_transcripts
from maudesignal.gate import CountClaim, RegulationClaim, verify_sentence
from maudesignal.gate.loader import store_from_database
from maudesignal.monitor.deterioration import detect_from_database
from maudesignal.monitor.digest import digest_from_database
from maudesignal.storage.database import Database
from maudesignal.vision import DEMO_K_NUMBERS
from maudesignal.vision.pipeline import DEMO_VISION_DIR
from tests.e2e.conftest import BASE_URL, SIDEBAR_SELECTOR, TOPBAR_SELECTOR, navigate

pytestmark = pytest.mark.e2e

ROOT = Path(__file__).resolve().parents[2]
DEMO_DB = ROOT / "data" / "demo" / "maudesignal_demo.db"
TRANSCRIPT_DIR = ROOT / "demo" / "transcripts"
FRAMING = "not medical advice"
EXCEPTION = "[data-testid='stException']"

keyless = pytest.mark.skipif(
    bool(os.environ.get("META_MODEL_API_KEY")),
    reason="stored-first checks assume the keyless public-demo setup",
)


@pytest.fixture(scope="module")
def db() -> Database:
    return Database(DEMO_DB)


def _main(page: Page) -> Locator:
    return page.locator("[data-testid='stMainBlockContainer']").first


def _open(page: Page, nav: str) -> Locator:
    navigate(page, nav)
    main = _main(page)
    expect(main).to_contain_text(FRAMING)
    assert page.locator(EXCEPTION).count() == 0, f"{nav} raised an exception"
    return main


# ---------------------------------------------------------------------------
# Navigation
# ---------------------------------------------------------------------------


class TestHackathonNav:
    def test_top_bar_lists_the_product_pages(self, ms_page: Page) -> None:
        bar = ms_page.locator(TOPBAR_SELECTOR)
        expect(bar).to_contain_text("MaudeSignal")
        for name in ("Signals", "Copilot", "Vision", "Audit"):
            expect(bar.get_by_role("radio", name=name, exact=False).first).to_be_visible()
        expect(bar.get_by_role("radio", name="Signals", exact=False)).to_have_attribute(
            "aria-checked", "true"
        )
        sidebar = ms_page.locator(SIDEBAR_SELECTOR)
        expect(sidebar).to_contain_text("More tools")
        expect(sidebar.get_by_role("button", name="PSUR Reports", exact=False)).to_be_visible()

    def test_demo_mode_has_no_sidebar(self, browser: Any) -> None:
        """With ?tools=demo (and without a key) only the product pages show."""
        ctx = browser.new_context()
        page = ctx.new_page()
        page.goto(f"{BASE_URL}/?tools=demo", wait_until="networkidle")
        page.wait_for_selector(TOPBAR_SELECTOR, timeout=30_000)
        page.wait_for_timeout(2_000)
        expect(page.locator(SIDEBAR_SELECTOR)).to_have_count(0)
        expect(page.get_by_text("More tools", exact=False)).to_have_count(0)
        ctx.close()

    def test_full_website_by_default(self, browser: Any) -> None:
        """Without a link choice every page is reachable: the sidebar lists More tools."""
        from maudesignal.dashboard.app import SHOW_ALL_PAGES_BY_DEFAULT

        ctx = browser.new_context()
        page = ctx.new_page()
        page.goto(BASE_URL, wait_until="networkidle")
        page.wait_for_selector(TOPBAR_SELECTOR, timeout=30_000)
        page.wait_for_timeout(2_000)
        want = 1 if SHOW_ALL_PAGES_BY_DEFAULT else 0
        expect(page.locator(SIDEBAR_SELECTOR)).to_have_count(want)
        ctx.close()

    @pytest.mark.parametrize("nav", ["Signals", "Copilot", "Vision", "Audit"])
    def test_page_loads_with_framing_and_no_exception(self, ms_page: Page, nav: str) -> None:
        _open(ms_page, nav)


# ---------------------------------------------------------------------------
# Signals workspace
# ---------------------------------------------------------------------------


def _rows(db: Database) -> list[Any]:
    from maudesignal.monitor.compare import compare_signals

    codes = sorted({e.product_code for e in db.list_normalized_events() if e.product_code})
    return list(compare_signals(db, codes).rows)


def _figure(r: Any) -> str:
    if r.change == "reports suddenly increased" and r.ratio_to_baseline is not None:
        return f"{r.ratio_to_baseline:.2f}×"
    return str(r.this_week)


def _pick(page: Page, code: str) -> None:
    page.locator(".st-key-ms_siglist label[data-testid='stRadioOption']", has_text=code).click()
    page.wait_for_timeout(3_000)


class TestSignals:
    def test_list_matches_the_detector(self, ms_page: Page, db: Database) -> None:
        _open(ms_page, "Signals")
        listing = ms_page.locator(".st-key-ms_siglist")
        for r in _rows(db):
            expect(listing).to_contain_text(f"{r.product_code} · {_figure(r)}")
            expect(listing).to_contain_text(f"{r.this_week} this week")

    def test_top_signal_is_selected_with_why_it_is_flagged(
        self, ms_page: Page, db: Database
    ) -> None:
        digest = digest_from_database(db, detect_from_database(db))
        main = _open(ms_page, "Signals")
        if not digest.ranked:
            return
        top = digest.ranked[0]
        head = main.locator(".ms-sig-head")
        expect(head).to_contain_text(top.product_code)
        device = digest.device_types.get(top.product_code)
        if device:
            expect(head).to_contain_text(device)
        expect(head).to_contain_text("Why it is flagged.")
        # Markdown renders ">=" as "≥"; compare on the text that survives rendering.
        expect(head).to_contain_text(digest.rank_reasons[top.product_code].replace(">=", "≥"))
        for brand, n in digest.window_brands.get(top.product_code, []):
            expect(head).to_contain_text(f"{brand} ({n})")

    def test_selecting_another_device_type_updates_the_detail(
        self, ms_page: Page, db: Database
    ) -> None:
        rows = _rows(db)
        main = _open(ms_page, "Signals")
        other = rows[-1]
        _pick(ms_page, other.product_code)
        head = main.locator(".ms-sig-head")
        expect(head).to_contain_text(other.product_code)
        expect(head).to_contain_text(other.change[:1].upper() + other.change[1:])
        expect(main.locator(".ms-stats")).to_contain_text(f"{other.stored_total}")

    def test_reports_tab_counts_match_the_records(self, ms_page: Page, db: Database) -> None:
        from maudesignal.monitor.sources import not_by_manufacturer, sourced_reports

        digest = digest_from_database(db, detect_from_database(db))
        if not digest.ranked:
            return
        top = digest.ranked[0]
        main = _open(ms_page, "Signals")
        expect(main).to_contain_text(f"{top.current_count} report(s)")
        mine = [r for r in sourced_reports(db) if r.product_code == top.product_code]
        others = not_by_manufacturer(mine)
        main.get_by_role("radio", name="Not filed by a manufacturer").click()
        ms_page.wait_for_timeout(2_000)
        expect(main).to_contain_text(f"{len(others)} report(s)")


# ---------------------------------------------------------------------------
# Copilot
# ---------------------------------------------------------------------------


class TestLiveCheck:
    """Check any device type: input validation here; the openFDA call where the network allows."""

    def _check(self, page: Page, code: str) -> Locator:
        main = _open(page, "Signals")
        panel = main.locator(".st-key-ms_livecheck")
        panel.get_by_label("Any FDA product code").fill(code)
        panel.get_by_role("button", name="Check on openFDA").click()
        return panel

    def test_a_bad_code_is_explained_and_nothing_is_called(self, ms_page: Page) -> None:
        panel = self._check(ms_page, "L1")
        expect(panel).to_contain_text("A product code is three letters")

    def test_a_real_code_shows_a_result_with_its_openfda_queries(self, ms_page: Page) -> None:
        panel = self._check(ms_page, "LLZ")
        outcome = panel.locator(".ms-sig-head, [data-testid='stAlert']").first
        expect(outcome).to_be_visible(timeout=60_000)
        text = outcome.inner_text()
        if "HTTP error contacting openFDA" in text:  # no network to openFDA (sandboxes)
            pytest.skip(f"openFDA not reachable from this runner: {text}")
        assert "could not be reached" not in text, text  # any other openFDA error is a bug
        expect(panel).to_contain_text("Live from openFDA · LLZ", ignore_case=True)
        expect(panel).to_contain_text("This week")
        panel.get_by_text("Where each number comes from").click()
        links = panel.locator("a[href^='https://api.fda.gov/device/event.json']")
        expect(links).to_have_count(5)


def _select(page: Page, label: str, option: str) -> None:
    box = page.locator("[data-testid='stSelectbox']").filter(has_text=label).first
    box.scroll_into_view_if_needed()
    box.get_by_role("button", name="Open").click()  # react-aria combobox opens from its button
    page.get_by_role("option", name=option, exact=True).first.click()
    page.wait_for_timeout(1_500)


class TestCopilot:
    def test_three_tabs(self, ms_page: Page) -> None:
        _open(ms_page, "Copilot")
        for tab in ("Recorded Muse Spark answers", "Try to fool the gate", "Ask live"):
            expect(ms_page.get_by_role("tab", name=tab)).to_be_visible()

    def test_recorded_runs_match_transcripts(self, ms_page: Page) -> None:
        main = _open(ms_page, "Copilot")
        transcripts = load_transcripts(TRANSCRIPT_DIR)
        if not transcripts:
            expect(main).to_contain_text("No recorded runs yet.")
            return
        listing = ms_page.locator(".st-key-ms_qlist")
        expect(main).to_contain_text(f"{len(transcripts)} recorded questions")
        for t in transcripts:
            expect(listing).to_contain_text(t["question"][:40])

    def test_gate_withholds_a_wrong_count_and_verifies_the_true_one(
        self, ms_page: Page, db: Database
    ) -> None:
        store = store_from_database(db)
        code = sorted({r.product_code for r in store.records})[0]
        true_count = sum(1 for r in store.records if r.product_code == code)
        _open(ms_page, "Copilot")
        ms_page.get_by_role("tab", name="Try to fool the gate").click()
        ms_page.wait_for_timeout(1_500)
        panel = ms_page.get_by_role("tabpanel").filter(has_text="Claim type").first

        # The page's default claim (50 reports) — expected verdict from the gate itself.
        expected = verify_sentence(f"{code} has 50 reports.", [CountClaim(code, 50)], store)
        assert expected.status == "block", "test premise: the default claim is wrong"
        expect(panel).to_contain_text("Withheld")
        expect(panel).to_contain_text(f"{code} has 50 reports.")

        box = panel.get_by_label("Claimed number of reports")
        box.fill(str(true_count))
        box.press("Enter")
        ms_page.wait_for_timeout(2_000)
        assert (
            verify_sentence(
                f"{code} has {true_count} reports.", [CountClaim(code, true_count)], store
            ).status
            == "pass"
        )
        expect(panel).to_contain_text("Verified")
        expect(panel).to_contain_text(f"{code} has {true_count} reports.")

    def test_gate_injury_count_shows_the_recomputed_number(
        self, ms_page: Page, db: Database
    ) -> None:
        store = store_from_database(db)
        code = sorted({r.product_code for r in store.records})[0]
        _open(ms_page, "Copilot")
        ms_page.get_by_role("tab", name="Try to fool the gate").click()
        ms_page.wait_for_timeout(1_500)
        _select(ms_page, "Event type", "Injury")
        panel = ms_page.get_by_role("tabpanel").filter(has_text="Claim type").first
        sentence = f"{code} has 50 Injury reports."
        verdict = verify_sentence(sentence, [CountClaim(code, 50, "Injury")], store)
        expect(panel).to_contain_text(sentence)
        expect(panel).to_contain_text("Verified" if verdict.status == "pass" else "Withheld")

    def test_gate_cfr_section_matches_gate_verdict(self, ms_page: Page, db: Database) -> None:
        store = store_from_database(db)
        _open(ms_page, "Copilot")
        ms_page.get_by_role("tab", name="Try to fool the gate").click()
        ms_page.wait_for_timeout(1_500)
        _select(ms_page, "Claim type", "CFR section")
        panel = ms_page.get_by_role("tabpanel").filter(has_text="Claim type").first
        verdict = verify_sentence("See 21 CFR 820.100.", [RegulationClaim("820.100")], store)
        expect(panel).to_contain_text("See 21 CFR 820.100.")
        expect(panel).to_contain_text("Verified" if verdict.status == "pass" else "Withheld")

    @keyless
    def test_ask_live_is_stored_first_without_a_key(self, ms_page: Page) -> None:
        _open(ms_page, "Copilot")
        ms_page.get_by_role("tab", name="Ask live").click()
        ms_page.wait_for_timeout(1_000)
        expect(ms_page.get_by_role("tabpanel").last).to_contain_text(
            "Live questions need a Meta Model API key"
        )


# ---------------------------------------------------------------------------
# Audit
# ---------------------------------------------------------------------------


class TestAudit:
    def test_audit_trail_shows_db_chain_or_recorded_trails(
        self, ms_page: Page, db: Database
    ) -> None:
        main = _open(ms_page, "Audit")
        rows = db.list_audit()
        if rows:
            expect(main).to_contain_text(f"Hash chain intact across {len(rows)} entries.")
            return
        exports = load_exports(TRANSCRIPT_DIR)
        if not exports:
            expect(main).to_contain_text("No audit entries yet.")
            return
        n = sum(len(d.get("entries", [])) for d in exports)
        if all(d["verified"][0] for d in exports):
            expect(main).to_contain_text(
                f"Hash chain intact in all {len(exports)} recorded runs ({n} entries)."
            )
        else:
            expect(main).to_contain_text("Hash chain broken")


# ---------------------------------------------------------------------------
# Evidence pack (Signals → Evidence pack tab)
# ---------------------------------------------------------------------------


def _open_pack(page: Page) -> Locator:
    main = _open(page, "Signals")
    page.get_by_role("tab", name="Evidence pack").click()
    page.wait_for_timeout(8_000)
    return main


class TestEvidencePack:
    def test_reverified_figures_and_chain(self, ms_page: Page) -> None:
        main = _open_pack(ms_page)
        stats = main.locator(".ms-stats--text")
        expect(stats).to_contain_text("Figures re-verified")
        text = stats.inner_text()
        m = re.search(r"(\d+)/(\d+)", text)
        assert m, f"no figures count in {text!r}"
        assert m[1] == m[2] and int(m[2]) > 0, f"not every figure re-verified: {m[0]}"
        expect(stats).to_contain_text("intact")

    def test_download_is_a_pdf(self, ms_page: Page, tmp_path: Path) -> None:
        main = _open_pack(ms_page)
        doc_id = main.locator(".ms-stats--text .ms-num").first.inner_text().strip()
        with ms_page.expect_download() as dl:
            main.get_by_role("button", name="Download PDF").click()
        out = tmp_path / dl.value.suggested_filename
        dl.value.save_as(out)
        assert out.read_bytes()[:5] == b"%PDF-"
        assert out.name.startswith(doc_id)


# ---------------------------------------------------------------------------
# Vision
# ---------------------------------------------------------------------------


class TestVision:
    def test_two_tabs(self, ms_page: Page) -> None:
        _open(ms_page, "Vision")
        for tab in ("510(k) summary reader", "Device label camera"):
            expect(ms_page.get_by_role("tab", name=tab)).to_be_visible()

    @keyless
    def test_summary_reader_lists_demo_k_numbers(self, ms_page: Page) -> None:
        main = _open(ms_page, "Vision")
        expect(main).to_contain_text("Live reading needs a Meta Model API key")
        box = main.locator("[data-testid='stSelectbox']").filter(has_text="510(k) number").first
        box.scroll_into_view_if_needed()
        ms_page.wait_for_timeout(500)
        box.get_by_role("button", name="Open").click()
        ms_page.get_by_role("option").first.wait_for()
        options = " ".join(ms_page.get_by_role("option").all_inner_texts())
        for k, _ in DEMO_K_NUMBERS:
            assert k in options, f"{k} missing from the 510(k) selector"
        ms_page.keyboard.press("Escape")

    def test_selected_k_shows_reading_or_says_none(self, ms_page: Page) -> None:
        main = _open(ms_page, "Vision")
        recorded = sorted(p.stem.removeprefix("510k-") for p in DEMO_VISION_DIR.glob("510k-*.json"))
        if recorded:
            expect(main).not_to_contain_text("No reading for this 510(k) yet.")
        else:
            expect(main).to_contain_text("No reading for this 510(k) yet.")

    @keyless
    def test_label_camera_is_stored_first(self, ms_page: Page) -> None:
        _open(ms_page, "Vision")
        ms_page.get_by_role("tab", name="Device label camera").click()
        ms_page.wait_for_timeout(1_500)
        panel = ms_page.get_by_role("tabpanel").last
        expect(panel).to_contain_text("Lot and serial numbers stay in this session")
        if not list((DEMO_VISION_DIR).glob("label-*.json")):
            expect(panel).to_contain_text("No recorded label runs yet")


# ---------------------------------------------------------------------------
# Themes (design-system tokens; top-bar picker)
# ---------------------------------------------------------------------------


def _css_var(page: Page, name: str) -> str:
    return str(
        page.evaluate(
            f"getComputedStyle(document.documentElement).getPropertyValue('--{name}').trim()"
        )
    ).lower()


def _bg(page: Page, selector: str) -> str:
    return str(
        page.evaluate(f'getComputedStyle(document.querySelector("{selector}")).backgroundColor')
    )


class TestThemes:
    @pytest.mark.parametrize("label", ["Light", "Dark", "Black", "Pink", "High contrast"])
    def test_theme_from_link_sets_design_tokens(self, page: Page, label: str) -> None:
        from maudesignal.dashboard.theme import THEME_IDS, theme_values

        tid = THEME_IDS[label]
        assert tid is not None
        page.goto(f"{BASE_URL}/?theme={tid}", wait_until="networkidle")
        page.wait_for_selector(TOPBAR_SELECTOR, timeout=20_000)
        page.wait_for_timeout(2_000)
        want = theme_values(tid)
        assert _css_var(page, "paper") == want["paper"].lower()
        assert _css_var(page, "ink") == want["ink"].lower()
        # The page itself is painted with the theme's paper colour.
        r, g, b = (int(want["paper"][i : i + 2], 16) for i in (1, 3, 5))
        assert _bg(page, ".stApp") == f"rgb({r}, {g}, {b})"
        main = _main(page)
        expect(main).to_contain_text(FRAMING)
        assert page.locator(EXCEPTION).count() == 0

    def test_system_follows_the_os(self, browser: Any) -> None:
        from maudesignal.dashboard.theme import theme_values

        for scheme, tid in (("light", "light"), ("dark", "dark")):
            ctx = browser.new_context(color_scheme=scheme)
            page = ctx.new_page()
            page.goto(f"{BASE_URL}/?theme=system", wait_until="networkidle")
            page.wait_for_selector(TOPBAR_SELECTOR, timeout=20_000)
            page.wait_for_timeout(2_000)
            assert _css_var(page, "paper") == theme_values(tid)["paper"].lower()
            ctx.close()

    def test_picker_switches_theme_and_link(self, ms_page: Page) -> None:
        from maudesignal.dashboard.theme import theme_values

        box = ms_page.locator(".st-key-theme_select")
        box.get_by_role("button", name="Open").click()
        ms_page.get_by_role("option", name="Pink", exact=True).first.click()
        ms_page.wait_for_timeout(2_500)
        assert _css_var(ms_page, "paper") == theme_values("pink")["paper"].lower()
        assert _css_var(ms_page, "surface") == "#ffffff"  # white solid cards
        assert "theme=pink" in ms_page.url


# ---------------------------------------------------------------------------
# Accessibility basics and screen sizes
# ---------------------------------------------------------------------------

_UNNAMED_CONTROLS_JS = """
() => [...document.querySelectorAll('button, [role=radio], input, select, textarea, a[href]')]
  .filter(el => el.offsetParent !== null)
  // Streamlit's date picker adds a hidden native helper (tabindex=-1, not keyboard
  // reachable); it is listed as a known Streamlit gap in TESTING.md, not counted here.
  .filter(el => el.getAttribute('tabindex') !== '-1')
  .filter(el => !(el.getAttribute('aria-label') || el.textContent.trim() ||
                  (el.labels && el.labels.length) || el.getAttribute('title')))
  .map(el => el.outerHTML.slice(0, 120))
"""


class TestAccessibility:
    @pytest.mark.parametrize("nav", ["Signals", "Copilot", "Vision", "Audit"])
    def test_every_visible_control_has_a_name(self, ms_page: Page, nav: str) -> None:
        _open(ms_page, nav)
        unnamed = ms_page.evaluate(_UNNAMED_CONTROLS_JS)
        assert unnamed == [], unnamed

    def test_top_bar_is_reachable_by_keyboard(self, ms_page: Page) -> None:
        ms_page.locator(".ms-wordmark").focus()
        names = []
        for _ in range(8):
            ms_page.keyboard.press("Tab")
            names.append(
                ms_page.evaluate(
                    "document.activeElement.getAttribute('role') + ':' + "
                    "document.activeElement.textContent.trim()"
                )
            )
        assert any(n.startswith("radio:") for n in names), names
        # Arrow keys move between pages inside the radio group (react-aria).
        ms_page.locator(".st-key-ms_topbar").get_by_role("radio", name="Signals").focus()
        ms_page.keyboard.press("ArrowRight")
        ms_page.keyboard.press("Enter")
        ms_page.wait_for_timeout(3_000)
        expect(_main(ms_page)).to_contain_text("Recorded Muse Spark answers")


class TestScreenSizes:
    @pytest.mark.parametrize(
        ("width", "height"), [(390, 844), (768, 1024), (1366, 768), (1920, 1080)]
    )
    def test_no_sideways_scroll_and_content_renders(
        self, browser: Any, width: int, height: int
    ) -> None:
        ctx = browser.new_context(viewport={"width": width, "height": height})
        page = ctx.new_page()
        page.goto(BASE_URL, wait_until="networkidle")
        page.wait_for_selector("text=MAUDE records on file", timeout=30_000)
        page.wait_for_timeout(2_000)
        expect(_main(page)).to_contain_text(FRAMING)
        overflow = page.evaluate(
            "document.documentElement.scrollWidth - document.documentElement.clientWidth"
        )
        assert overflow <= 1, f"{width}px wide page scrolls sideways by {overflow}px"
        ctx.close()
