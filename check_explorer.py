"""Check Signal Explorer DOM details."""

import asyncio
import re

from playwright.async_api import async_playwright

SIDEBAR = "section[data-testid='stSidebar']"


async def run() -> None:
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page()
        await page.goto("http://localhost:8501/", wait_until="networkidle", timeout=20000)
        await page.wait_for_timeout(5000)
        sidebar = page.locator(SIDEBAR)
        btn = sidebar.get_by_role("button", name="Signal Explorer", exact=False).first
        await btn.click()
        await page.wait_for_timeout(5000)
        content = await page.content()

        # Find all input placeholders
        placeholders = re.findall(r'placeholder="([^"]+)"', content)
        print("Input placeholders:", placeholders)

        # Find date range elements
        date_idx = content.find("Date Range")
        if date_idx != -1:
            print("Date Range context:", repr(content[max(0, date_idx - 20) : date_idx + 120]))

        # Find search input context
        for ph in placeholders:
            idx = content.find(ph)
            print(f"Placeholder {ph!r} at {idx}: {repr(content[max(0,idx-50):idx+80])}")

        await browser.close()


asyncio.run(run())
