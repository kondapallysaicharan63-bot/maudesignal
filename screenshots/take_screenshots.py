"""Take screenshots of all 7 MaudeSignal pages."""

import asyncio
from pathlib import Path

from playwright.async_api import async_playwright

PAGES = [
    ("Dashboard", None),
    ("Signal Explorer", "Signal Explorer"),
    ("MAUDE Ingestion", "MAUDE Ingestion"),
    ("LLM Extraction", "LLM Extraction"),
    ("PSUR Reports", "PSUR Reports"),
    ("Alerts", "Alerts"),
    ("Settings", "Settings"),
]

OUT = Path(r"C:\Users\konda\projects\safesignal\screenshots")
OUT.mkdir(exist_ok=True)


async def run() -> None:
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page(viewport={"width": 1400, "height": 900})
        print("Loading app...")
        await page.goto("http://localhost:8501/", wait_until="networkidle", timeout=30000)
        # Wait for Streamlit to fully hydrate
        await page.wait_for_selector("section[data-testid='stSidebar']", timeout=15000)
        await page.wait_for_timeout(5000)

        for name, nav_text in PAGES:
            if nav_text:
                print(f"  navigating to {name}...")
                sidebar = page.locator("section[data-testid='stSidebar']")
                btn = sidebar.get_by_role("button", name=nav_text, exact=False).first
                await btn.click()
                # Wait for the spinner to appear then disappear, or just wait
                await page.wait_for_timeout(4500)
                # Also wait for networkidle to ensure charts/data loaded
                try:
                    await page.wait_for_load_state("networkidle", timeout=8000)
                except Exception:
                    pass
                await page.wait_for_timeout(1000)

            fname = OUT / f"page_{name.replace(' ', '_').lower()}.png"
            await page.screenshot(path=str(fname), full_page=True)
            print(f"  saved {fname.name}")

        await browser.close()
        print("Done.")


asyncio.run(run())
