"""E2E tests for the five hackathon pages: Overnight, Copilot, Actions & Audit, Dossier, Vision.

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

import pytest
from playwright.sync_api import Locator, Page, expect

from maudesignal.copilot.audit_export import load_exports
from maudesignal.copilot.transcript import load_transcripts
from maudesignal.gate import CountClaim, RegulationClaim, verify_sentence
from maudesignal.gate.loader import store_from_database
from maudesignal.monitor.deterioration import detect_from_database
from maudesignal.monitor.digest import RANKING_ORDER, digest_from_database
from maudesignal.storage.database import Database
from maudesignal.vision import DEMO_K_NUMBERS
from maudesignal.vision.pipeline import DEMO_VISION_DIR
from tests.e2e.conftest import SIDEBAR_SELECTOR, navigate

pytestmark = pytest.mark.e2e

ROOT = Path(__file__).resolve().parents[2]
DEMO_DB = ROOT / "data" / "demo" / "maudesignal_demo.db"
TRANSCRIPT_DIR = ROOT / "demo" / "transcripts"
FRAMING = "Not medical advice"
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
    def test_sidebar_labels_the_new_pages(self, ms_page: Page) -> None:
        sidebar = ms_page.locator(SIDEBAR_SELECTOR)
        expect(sidebar).to_contain_text("NEW — built during the Meta hackathon")
        for name in ("Overnight", "Copilot", "Actions & Audit", "Dossier", "Vision"):
            expect(sidebar.get_by_role("button", name=name, exact=False).first).to_be_visible()

    @pytest.mark.parametrize(
        "nav", ["Overnight", "Copilot", "Actions & Audit", "Dossier", "Vision"]
    )
    def test_page_loads_with_framing_and_no_exception(self, ms_page: Page, nav: str) -> None:
        _open(ms_page, nav)


# ---------------------------------------------------------------------------
# Overnight
# ---------------------------------------------------------------------------


class TestOvernight:
    def test_counts_match_the_detector(self, ms_page: Page, db: Database) -> None:
        digest = digest_from_database(db, detect_from_database(db))
        main = _open(ms_page, "Overnight")
        for label, value in (
            ("New signals", digest.new_count),
            ("Worsening", digest.worsening_count),
            ("Stable", digest.stable_count),
        ):
            metric = main.locator("[data-testid='stMetric']").filter(has_text=label).first
            expect(metric.locator("[data-testid='stMetricValue']")).to_have_text(str(value))
        w = digest.result.window
        expect(main).to_contain_text(f"As of {w.as_of.isoformat()}")

    def test_top_signal_and_why_it_is_ranked_first(self, ms_page: Page, db: Database) -> None:
        digest = digest_from_database(db, detect_from_database(db))
        main = _open(ms_page, "Overnight")
        if not digest.ranked:
            expect(main).to_contain_text("No product code crossed a rule threshold.")
            return
        top = digest.ranked[0]
        expect(main).to_contain_text(f"Top signal: {top.product_code}")
        device = digest.device_types.get(top.product_code)
        if device:
            expect(main).to_contain_text(device)
        expect(main).to_contain_text("Why it is ranked first.")
        # Markdown renders ">=" as "≥"; compare on the text that survives rendering.
        reason = digest.rank_reasons[top.product_code].replace(">=", "≥")
        expect(main).to_contain_text(reason)
        for brand, n in digest.window_brands.get(top.product_code, []):
            expect(main).to_contain_text(f"{brand} ({n} of {top.current_count} reports)")
        expect(main).to_contain_text(RANKING_ORDER[0])
        expect(main).to_contain_text("Deterministic — no model involved.")

    def test_digest_body_rendered(self, ms_page: Page, db: Database) -> None:
        digest = digest_from_database(db, detect_from_database(db))
        main = _open(ms_page, "Overnight")
        expect(main).to_contain_text(
            f"MaudeSignal overnight digest — data as of {digest.result.window.as_of.isoformat()}"
        )
        expect(main).to_contain_text(digest.headline)
        expect(main).to_contain_text("nothing is reported to FDA automatically")


# ---------------------------------------------------------------------------
# Copilot
# ---------------------------------------------------------------------------


def _select(page: Page, label: str, option: str) -> None:
    box = page.locator("[data-testid='stSelectbox']").filter(has_text=label).first
    box.click()
    page.get_by_role("option", name=option, exact=True).first.click()
    page.wait_for_timeout(1_500)


class TestCopilot:
    def test_three_tabs(self, ms_page: Page) -> None:
        _open(ms_page, "Copilot")
        for tab in ("Recorded Muse Spark runs", "Try to fool the gate", "Ask live"):
            expect(ms_page.get_by_role("tab", name=tab)).to_be_visible()

    def test_recorded_runs_match_transcripts(self, ms_page: Page) -> None:
        main = _open(ms_page, "Copilot")
        transcripts = load_transcripts(TRANSCRIPT_DIR)
        if not transcripts:
            expect(main).to_contain_text("No recorded runs yet.")
            return
        for t in transcripts:
            expect(main).to_contain_text(t["question"][:60])

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
        expect(panel).to_contain_text("WITHHELD")
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
        expect(panel).to_contain_text("VERIFIED")
        expect(panel).to_contain_text(f"{code} has {true_count} reports.")

    def test_gate_cfr_section_matches_gate_verdict(self, ms_page: Page, db: Database) -> None:
        store = store_from_database(db)
        _open(ms_page, "Copilot")
        ms_page.get_by_role("tab", name="Try to fool the gate").click()
        ms_page.wait_for_timeout(1_500)
        _select(ms_page, "Claim type", "CFR section")
        panel = ms_page.get_by_role("tabpanel").filter(has_text="Claim type").first
        verdict = verify_sentence("See 21 CFR 820.100.", [RegulationClaim("820.100")], store)
        expect(panel).to_contain_text("See 21 CFR 820.100.")
        expect(panel).to_contain_text("VERIFIED" if verdict.status == "pass" else "WITHHELD")

    @keyless
    def test_ask_live_is_stored_first_without_a_key(self, ms_page: Page) -> None:
        _open(ms_page, "Copilot")
        ms_page.get_by_role("tab", name="Ask live").click()
        ms_page.wait_for_timeout(1_000)
        expect(ms_page.get_by_role("tabpanel").last).to_contain_text(
            "Live questions need a Meta Model API key"
        )


# ---------------------------------------------------------------------------
# Actions & Audit
# ---------------------------------------------------------------------------


class TestActionsAudit:
    def test_capa_header_counts_drafts_awaiting_review(self, ms_page: Page, db: Database) -> None:
        waiting = sum(1 for d in db.list_capa_drafts() if d.status == "draft")
        main = _open(ms_page, "Actions & Audit")
        expect(main).to_contain_text(f"CAPA drafts ({waiting} awaiting review)")
        expect(main.get_by_label("Your name (recorded as the approver)")).to_be_visible()

    def test_audit_trail_shows_db_chain_or_recorded_trails(
        self, ms_page: Page, db: Database
    ) -> None:
        main = _open(ms_page, "Actions & Audit")
        expect(main).to_contain_text("Audit trail")
        rows = db.list_audit()
        if rows:
            expect(main).to_contain_text(f"Hash chain intact across {len(rows)} entries.")
            return
        exports = load_exports(TRANSCRIPT_DIR)
        if not exports:
            expect(main).to_contain_text("No audit entries yet.")
            return
        for doc in exports:
            ok, _ = doc["verified"]
            n = len(doc.get("entries", []))
            expect(main).to_contain_text(f"{n} entries")
            expect(main).to_contain_text("hash chain intact." if ok else "hash chain broken")


# ---------------------------------------------------------------------------
# Dossier
# ---------------------------------------------------------------------------


class TestDossier:
    def test_metrics_and_reverified_figures(self, ms_page: Page) -> None:
        main = _open(ms_page, "Dossier")
        expect(main).to_contain_text("Signal Evaluation & CAPA dossier")
        metric = main.locator("[data-testid='stMetric']").filter(has_text="Figures re-verified")
        value = metric.locator("[data-testid='stMetricValue']").inner_text()
        m = re.fullmatch(r"(\d+)/(\d+)", value.strip())
        assert m, f"unexpected figures metric {value!r}"
        assert m[1] == m[2] and int(m[2]) > 0, f"not every figure re-verified: {value}"
        chain = main.locator("[data-testid='stMetric']").filter(has_text="Audit chain")
        expect(chain.locator("[data-testid='stMetricValue']")).to_have_text("intact")

    def test_download_is_a_pdf(self, ms_page: Page, tmp_path: Path) -> None:
        main = _open(ms_page, "Dossier")
        doc_id = (
            main.locator("[data-testid='stMetric']")
            .filter(has_text="Document")
            .first.locator("[data-testid='stMetricValue']")
            .inner_text()
            .strip()
        )
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
        box.click()
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
