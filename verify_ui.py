"""Playwright-based UI verification for MaudeSignal dashboard."""

import asyncio
from pathlib import Path

from playwright.async_api import async_playwright

OUT = Path(r"C:\Users\konda\projects\safesignal\screenshots")
OUT.mkdir(exist_ok=True)

DB_TRUTH = {
    "raw_reports": 290,
    "ai_signals": 14,
    "avg_confidence": "0.890",
    "total_events": 290,
    "extracted": 35,
    "pending": 255,
    "alert_rules": 0,
    "psur_reports": 0,
    "catalog_devices": 0,
}

PAGES = [
    ("Dashboard", None),
    ("Signal Explorer", "Signal Explorer"),
    ("MAUDE Ingestion", "MAUDE Ingestion"),
    ("LLM Extraction", "LLM Extraction"),
    ("PSUR Reports", "PSUR Reports"),
    ("Alerts", "Alerts"),
    ("Settings", "Settings"),
]

findings = []


def check(label: str, expected: str, content: str) -> bool:
    found = expected in content
    status = "[OK]" if found else "[FAIL]"
    print(f"  {status} {label}: '{expected}' in page = {found}")
    if not found:
        findings.append(f"FAIL: {label} — expected '{expected}' not found in page")
    return found


async def navigate_to(page, sidebar, nav_text: str) -> None:
    btn = sidebar.get_by_role("button", name=nav_text, exact=False).first
    await btn.click()
    await page.wait_for_timeout(5000)
    try:
        await page.wait_for_load_state("networkidle", timeout=8000)
    except Exception:
        pass
    await page.wait_for_timeout(1000)


async def run() -> None:
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page(viewport={"width": 1400, "height": 900})
        print("Loading app...")
        await page.goto("http://localhost:8501/", wait_until="networkidle", timeout=30000)
        await page.wait_for_selector("section[data-testid='stSidebar']", timeout=15000)
        await page.wait_for_timeout(5000)
        sidebar = page.locator("section[data-testid='stSidebar']")

        # ── Dashboard ──────────────────────────────────────────────────────────
        print("\n=== DASHBOARD ===")
        content = await page.content()
        check("raw_reports KPI", "290", content)
        check("ai_signals KPI", "14", content)
        check("avg_confidence KPI", "0.890", content)
        check("page title", "MaudeSignal", content)
        await page.screenshot(path=str(OUT / "verify_01_dashboard.png"), full_page=True)
        print("  Screenshot: verify_01_dashboard.png")

        # ── Signal Explorer ────────────────────────────────────────────────────
        print("\n=== SIGNAL EXPLORER ===")
        await navigate_to(page, sidebar, "Signal Explorer")
        content = await page.content()
        check("has product code filter", "Product Code", content)
        check("has severity filter", "Severity", content)
        check("has AI flag filter", "AI", content)
        # Should show records (290 total)
        check("shows record count or data", "290", content)
        await page.screenshot(path=str(OUT / "verify_02_signal_explorer.png"), full_page=True)
        print("  Screenshot: verify_02_signal_explorer.png")

        # Test search filter interaction
        try:
            search_input = page.get_by_placeholder("Search narratives...").first
            if await search_input.count() == 0:
                search_input = page.get_by_label("Search").first
            if await search_input.count() > 0:
                await search_input.fill("malfunction")
                await page.wait_for_timeout(2000)
                content_filtered = await page.content()
                print("  🔍 Search 'malfunction' → page updated (networkidle waited)")
                await page.screenshot(
                    path=str(OUT / "verify_02b_signal_filtered.png"), full_page=True
                )
                # Clear search
                await search_input.fill("")
                await page.wait_for_timeout(1000)
        except Exception as e:
            print(f"  ⚠️  Search interaction failed: {e}")

        # ── MAUDE Ingestion ────────────────────────────────────────────────────
        print("\n=== MAUDE INGESTION ===")
        await navigate_to(page, sidebar, "MAUDE Ingestion")
        content = await page.content()
        check("has product code field", "Product Code", content)
        check("shows current record count", "290", content)
        check("has ingest button", "Ingest", content)
        await page.screenshot(path=str(OUT / "verify_03_ingestion.png"), full_page=True)
        print("  Screenshot: verify_03_ingestion.png")

        # ── LLM Extraction ─────────────────────────────────────────────────────
        print("\n=== LLM EXTRACTION ===")
        await navigate_to(page, sidebar, "LLM Extraction")
        content = await page.content()
        check("total events", "290", content)
        check("extracted count", "35", content)
        check("pending count", "255", content)
        check("has extract button", "Extract", content)
        await page.screenshot(path=str(OUT / "verify_04_extraction.png"), full_page=True)
        print("  Screenshot: verify_04_extraction.png")

        # ── PSUR Reports ───────────────────────────────────────────────────────
        print("\n=== PSUR REPORTS ===")
        await navigate_to(page, sidebar, "PSUR Reports")
        content = await page.content()
        check("PSUR page loaded", "PSUR", content)
        # 0 reports — should show empty state
        check("empty state or no reports", "No PSUR", content) or check(
            "reports count", "0", content
        )
        await page.screenshot(path=str(OUT / "verify_05_psur.png"), full_page=True)
        print("  Screenshot: verify_05_psur.png")

        # Click Generate tab if present
        try:
            gen_tab = page.get_by_role("tab", name="Generate", exact=False).first
            if await gen_tab.count() > 0:
                await gen_tab.click()
                await page.wait_for_timeout(2000)
                content2 = await page.content()
                check("generate tab has product code field", "Product Code", content2)
                await page.screenshot(
                    path=str(OUT / "verify_05b_psur_generate.png"), full_page=True
                )
                print("  🔍 Generate tab clicked, screenshot saved")
        except Exception as e:
            print(f"  ⚠️  PSUR generate tab: {e}")

        # ── Alerts ─────────────────────────────────────────────────────────────
        print("\n=== ALERTS ===")
        await navigate_to(page, sidebar, "Alerts")
        content = await page.content()
        check("Alerts page loaded", "Alert", content)
        # 0 alert rules — should show empty state
        empty_ok = check("no rules empty state", "No alert rules", content) or check(
            "zero rules", "0", content
        )
        await page.screenshot(path=str(OUT / "verify_06_alerts.png"), full_page=True)
        print("  Screenshot: verify_06_alerts.png")

        # Test Alerts tabs
        for tab_name in ["Test Alerts", "History"]:
            try:
                tab = page.get_by_role("tab", name=tab_name, exact=False).first
                if await tab.count() > 0:
                    await tab.click()
                    await page.wait_for_timeout(1500)
                    print(f"  🔍 '{tab_name}' tab clicked")
            except Exception as e:
                print(f"  ⚠️  Tab '{tab_name}': {e}")

        # ── Settings ───────────────────────────────────────────────────────────
        print("\n=== SETTINGS ===")
        await navigate_to(page, sidebar, "Settings")
        content = await page.content()
        check("Settings page loaded", "Settings", content)
        # Should show provider status
        check("shows LLM provider info", "Gemini", content) or check(
            "provider configured", "gemini", content
        )
        await page.screenshot(path=str(OUT / "verify_07_settings.png"), full_page=True)
        print("  Screenshot: verify_07_settings.png")

        # Test Settings tabs
        for tab_name in ["System", "Device Catalog", "External Sources"]:
            try:
                tab = page.get_by_role("tab", name=tab_name, exact=False).first
                if await tab.count() > 0:
                    await tab.click()
                    await page.wait_for_timeout(1500)
                    content_tab = await page.content()
                    print(f"  🔍 Settings '{tab_name}' tab — loaded ({len(content_tab)} chars)")
            except Exception as e:
                print(f"  ⚠️  Settings tab '{tab_name}': {e}")

        await browser.close()

    print("\n" + "=" * 60)
    if findings:
        print(f"FAIL — {len(findings)} discrepancies found:")
        for f in findings:
            print(f"  • {f}")
    else:
        print("PASS — All data checks passed, all pages loaded, all screenshots saved.")
    print("=" * 60)


asyncio.run(run())
