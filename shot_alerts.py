from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page(viewport={"width": 1400, "height": 900})
    page.goto("http://localhost:8501", wait_until="networkidle", timeout=20000)
    page.wait_for_timeout(5000)
    sidebar = page.locator("section[data-testid='stSidebar']")
    btn = sidebar.get_by_role("button", name="Alerts", exact=False).first
    btn.click()
    page.locator("h1").filter(has_text="Alerts").wait_for(timeout=10000)
    page.wait_for_timeout(3000)
    page.screenshot(path="screenshots/06_alerts_new.png")
    browser.close()
    print("done")
