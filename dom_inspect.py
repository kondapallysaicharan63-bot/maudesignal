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
    page.wait_for_timeout(2000)

    # Get all elements matching the label text
    result = page.evaluate("""() => {
        const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
        const hits = [];
        let node;
        while ((node = walker.nextNode())) {
            if (node.textContent.trim() === 'Filter by Product Code') {
                const el = node.parentElement;
                const style = window.getComputedStyle(el);
                const grandparent = el.parentElement;
                hits.push({
                    tag: el.tagName,
                    testid: el.getAttribute('data-testid'),
                    cls: el.className.substring(0, 80),
                    color: style.color,
                    ptestid: grandparent ? grandparent.getAttribute('data-testid') : null,
                    pcls: grandparent ? grandparent.className.substring(0, 80) : null,
                });
            }
        }
        return hits;
    }""")
    print("Elements with 'Filter by Product Code':")
    for h in result:
        print(" ", h)

    # Also check the subtitle "ingested" text
    result2 = page.evaluate("""() => {
        const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
        const hits = [];
        let node;
        while ((node = walker.nextNode())) {
            if (node.textContent.includes('ingested')) {
                const el = node.parentElement;
                const style = window.getComputedStyle(el);
                hits.push({
                    text: node.textContent.trim().substring(0, 80),
                    tag: el.tagName,
                    testid: el.getAttribute('data-testid'),
                    cls: el.className.substring(0, 80),
                    color: style.color,
                });
            }
        }
        return hits;
    }""")
    print("\nElements containing 'ingested':")
    for h in result2:
        print(" ", h)

    browser.close()
    print("done")
