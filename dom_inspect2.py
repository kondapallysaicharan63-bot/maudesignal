from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page(viewport={"width": 1400, "height": 900})
    page.goto("http://localhost:8501", wait_until="networkidle", timeout=20000)
    page.wait_for_timeout(3000)

    sidebar = page.locator("section[data-testid='stSidebar']")
    btn = sidebar.get_by_role("button", name="LLM Extraction", exact=False).first
    btn.click()
    page.locator("h1").filter(has_text="LLM Extraction").wait_for(timeout=15000)
    page.wait_for_timeout(5000)

    # Comprehensive search for all elements containing the text
    result = page.evaluate("""() => {
        const all = document.querySelectorAll('*');
        const hits = [];
        for (const el of all) {
            // Check if this element directly contains the text (not via children)
            const ownText = Array.from(el.childNodes)
                .filter(n => n.nodeType === 3)
                .map(n => n.textContent.trim())
                .join('');
            if (ownText.includes('Filter by Product Code') || ownText === 'Filter by Product Code') {
                const style = window.getComputedStyle(el);
                hits.push({
                    tag: el.tagName,
                    ownText: ownText.substring(0, 50),
                    testid: el.getAttribute('data-testid'),
                    cls: el.className.substring(0, 60),
                    color: style.color,
                    display: style.display,
                    visibility: style.visibility,
                    for_attr: el.getAttribute('for'),
                });
            }
        }
        return hits;
    }""")
    print("All elements with 'Filter by Product Code' text:")
    for h in result:
        print(" ", h)

    # Take a screenshot right now for comparison
    page.screenshot(path="screenshots/llm_debug.png")
    print("Screenshot saved to screenshots/llm_debug.png")

    browser.close()
    print("done")
