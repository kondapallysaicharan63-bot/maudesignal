"""Quick check: what text strings actually appear on each page."""

import asyncio

from playwright.async_api import async_playwright

SIDEBAR = "section[data-testid='stSidebar']"


async def run() -> None:
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page()
        await page.goto("http://localhost:8501/", wait_until="networkidle", timeout=20000)
        await page.wait_for_timeout(5000)

        sidebar = page.locator(SIDEBAR)
        sidebar_text = await sidebar.inner_text()
        print("--- SIDEBAR TEXT ---")
        print(repr(sidebar_text[:800]))

        # Dashboard checks
        content = await page.content()
        dashboard_checks = [
            "MaudeSignal",
            "MAUDE Records",
            "MAUDE RECORDS",
            "AI SIGNALS",
            "AI Signals",
            "AVG CONFIDENCE",
            "Avg Confidence",
            "LLM COST",
            "AI Failure Mode Breakdown",
            "Report ID",
            "Confidence",
        ]
        print("\n--- DASHBOARD ---")
        for c in dashboard_checks:
            print(f"  {c!r}: {c in content}")

        # Signal Explorer
        btn = sidebar.get_by_role("button", name="Signal Explorer", exact=False).first
        await btn.click()
        await page.wait_for_timeout(5000)
        content = await page.content()
        print("\n--- SIGNAL EXPLORER ---")
        for c in [
            "Product Code",
            "Severity",
            "AI Flag",
            "Date Range",
            "Filters",
            "Filter by",
            "records",
        ]:
            print(f"  {c!r}: {c in content}")

        # Settings
        btn2 = sidebar.get_by_role("button", name="Settings", exact=False).first
        await btn2.click()
        await page.wait_for_timeout(5000)
        content = await page.content()
        print("\n--- SETTINGS ---")
        for c in [
            "Active Provider",
            "Provider Status",
            "Key Set",
            "Not Configured",
            "LLM Providers",
            "Cost",
        ]:
            print(f"  {c!r}: {c in content}")

        await browser.close()


asyncio.run(run())
