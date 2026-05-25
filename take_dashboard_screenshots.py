import asyncio
from playwright.async_api import async_playwright

async def take_shots():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(viewport={'width': 1280, 'height': 900})

        # Home page
        await page.goto('http://localhost:8501', wait_until='networkidle', timeout=30000)
        await page.wait_for_timeout(3000)
        await page.screenshot(path='screenshots/home.png', full_page=False)
        print('Home saved')

        # Click Signal Explorer in sidebar
        await page.click('text=Signal Explorer')
        await page.wait_for_timeout(3000)
        await page.screenshot(path='screenshots/signal_explorer.png', full_page=False)
        print('Signal Explorer saved')

        # Click LLM Extraction
        await page.click('text=LLM Extraction')
        await page.wait_for_timeout(3000)
        await page.screenshot(path='screenshots/llm_extraction.png', full_page=False)
        print('LLM Extraction saved')

        await browser.close()

asyncio.run(take_shots())
