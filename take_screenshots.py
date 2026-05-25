import asyncio, os, sys

# Force UTF-8 output
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from playwright.async_api import async_playwright

async def main():
    os.makedirs("c:\\Users\\konda\\projects\\safesignal\\screenshots", exist_ok=True)
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(viewport={"width": 1280, "height": 900})

        await page.goto("http://localhost:8501", wait_until="networkidle", timeout=30000)
        await page.wait_for_timeout(4000)
        await page.screenshot(path="c:\\Users\\konda\\projects\\safesignal\\screenshots\\01_dashboard.png", full_page=True)
        print("Dashboard saved")

        content = await page.inner_text("body")
        # Write content to file to avoid encoding issues in console
        with open("c:\\Users\\konda\\projects\\safesignal\\screenshots\\01_dashboard_text.txt", "w", encoding="utf-8") as f:
            f.write(content)
        print("Dashboard text length:", len(content))

        try:
            await page.click("text=Signal Explorer", timeout=5000)
            await page.wait_for_timeout(4000)
            await page.screenshot(path="c:\\Users\\konda\\projects\\safesignal\\screenshots\\02_signal_explorer.png", full_page=True)
            print("Signal Explorer saved")
            content2 = await page.inner_text("body")
            with open("c:\\Users\\konda\\projects\\safesignal\\screenshots\\02_signal_explorer_text.txt", "w", encoding="utf-8") as f:
                f.write(content2)
            print("Signal Explorer text length:", len(content2))
        except Exception as e:
            print(f"Signal Explorer click failed: {e}")

        try:
            await page.click("text=LLM Extraction", timeout=5000)
            await page.wait_for_timeout(3000)
            await page.screenshot(path="c:\\Users\\konda\\projects\\safesignal\\screenshots\\03_llm_extraction.png", full_page=True)
            print("LLM Extraction saved")
            content3 = await page.inner_text("body")
            with open("c:\\Users\\konda\\projects\\safesignal\\screenshots\\03_llm_extraction_text.txt", "w", encoding="utf-8") as f:
                f.write(content3)
            print("LLM Extraction text length:", len(content3))
        except Exception as e:
            print(f"LLM Extraction click failed: {e}")

        await browser.close()
        print("DONE")

asyncio.run(main())
