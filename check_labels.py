"""Inspect actual DOM text for KPI labels and sidebar."""

import asyncio
import re

from playwright.async_api import async_playwright


async def run() -> None:
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page()
        await page.goto("http://localhost:8501/", wait_until="networkidle", timeout=20000)
        await page.wait_for_timeout(5000)
        content = await page.content()

        # All .lbl elements (KPI labels)
        labels = re.findall(r'class="lbl">([^<]+)</div>', content)
        print("KPI labels found:", labels)

        # MaudeSignal in sidebar section
        sidx = content.find("stSidebar")
        sidebar_html = content[sidx : sidx + 2000]
        print("MaudeSignal in sidebar HTML:", "MaudeSignal" in sidebar_html)
        # Find brand text snippet
        brand_idx = sidebar_html.find("Maude")
        if brand_idx != -1:
            print("Brand snippet:", repr(sidebar_html[max(0, brand_idx - 20) : brand_idx + 60]))

        # Failure Mode
        fm_idx = content.find("Failure Mode")
        if fm_idx != -1:
            print("Failure Mode context:", repr(content[max(0, fm_idx - 60) : fm_idx + 80]))

        # Recent Signals columns
        col_search = ["Report ID", "Severity", "Confidence", "Skill"]
        for col in col_search:
            idx = content.find(col)
            if idx != -1:
                print(f"Column '{col}' context:", repr(content[max(0, idx - 20) : idx + 40]))
            else:
                print(f"Column '{col}': NOT FOUND")

        await browser.close()


asyncio.run(run())
