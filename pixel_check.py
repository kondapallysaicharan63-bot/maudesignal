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

    # Get the bounding box of the Filter by Product Code text
    result = page.evaluate("""() => {
        const all = document.querySelectorAll('*');
        for (const el of all) {
            const ownText = Array.from(el.childNodes)
                .filter(n => n.nodeType === 3)
                .map(n => n.textContent.trim())
                .join('');
            if (ownText === 'Filter by Product Code') {
                const rect = el.getBoundingClientRect();
                return { x: rect.x, y: rect.y, w: rect.width, h: rect.height };
            }
        }
        return null;
    }""")
    print("BBox of Filter by Product Code:", result)

    # Also get pixel color at that location using canvas
    if result:
        px, py = result["x"] + 5, result["y"] + result["h"] / 2
        color = page.evaluate(f"""() => {{
            const canvas = document.createElement('canvas');
            canvas.width = 1; canvas.height = 1;
            const ctx = canvas.getContext('2d');
            // Use document.elementFromPoint to check what's there
            const el = document.elementFromPoint({px}, {py});
            return {{
                tag: el ? el.tagName : null,
                testid: el ? el.getAttribute('data-testid') : null,
                color: el ? window.getComputedStyle(el).color : null,
            }};
        }}""")
        print(f"Element at ({px:.0f}, {py:.0f}):", color)

    # Check subtitle "ingested" element bbox too
    result2 = page.evaluate("""() => {
        const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
        let node;
        while ((node = walker.nextNode())) {
            if (node.textContent.trim() === 'Run AI extraction on ingested MAUDE records') {
                const el = node.parentElement;
                const rect = el.getBoundingClientRect();
                const style = window.getComputedStyle(el);
                return { x: rect.x, y: rect.y, color: style.color, tag: el.tagName };
            }
        }
        return null;
    }""")
    print("Subtitle element:", result2)

    browser.close()
    print("done")
