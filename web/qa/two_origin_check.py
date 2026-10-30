"""Two-origin check of the visit ping against the real API's CORS preflight (no secrets, local only).

    VITE_MAUDESIGNAL_API_BASE=http://127.0.0.1:8101 npm run build
    PYTHONPATH=<track-c-feedback checkout>/src python3 qa/two_origin_check.py dist

Serves ``dist`` on :8100 and the real ``mount_feedback`` app (memory store, no-op notifier) on :8101,
opens ``?r=qa-code`` in Chromium and prints the requests the API saw.
"""

from __future__ import annotations

import http.server
import json
import sys
import threading
import time
from functools import partial
from pathlib import Path

import uvicorn
from fastapi import FastAPI
from maudesignal.connector.blob_store import MemoryStore
from maudesignal.connector.feedback import mount_feedback
from maudesignal.connector.notify import NoopNotifier
from maudesignal.connector.security import RateLimiter
from playwright.sync_api import sync_playwright

WEB, API = "http://127.0.0.1:8100", "http://127.0.0.1:8101"


def main() -> None:
    """Run the check and print the result."""
    dist = Path(sys.argv[1]).resolve()
    handler = partial(http.server.SimpleHTTPRequestHandler, directory=str(dist))
    handler.log_message = lambda *a, **k: None  # type: ignore[method-assign]
    web = http.server.ThreadingHTTPServer(("127.0.0.1", 8100), handler)
    threading.Thread(target=web.serve_forever, daemon=True).start()

    app = FastAPI()
    seen: list[str] = []

    @app.middleware("http")
    async def log(request, call_next):  # type: ignore[no-untyped-def]
        seen.append(f"{request.method} {request.url.path}")
        return await call_next(request)

    mount_feedback(
        app,
        store=MemoryStore(),
        notifier=NoopNotifier(),
        web_origins=frozenset({WEB}),
        client_address=lambda r: "test",
        failed_auth=RateLimiter(5),
        make_limiter=lambda name, limit, window: RateLimiter(limit, window_seconds=window),
        env={"MAUDESIGNAL_ADMIN_KEY": "x" * 24},
    )
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=8101, log_level="error"))
    threading.Thread(target=server.run, daemon=True).start()
    time.sleep(1.5)
    with sync_playwright() as p:
        b = p.chromium.launch()
        page = b.new_page()
        page.goto(f"{WEB}/?r=qa-code")
        page.wait_for_timeout(2500)
        b.close()
    print(json.dumps({"api_requests_seen": seen}, indent=1))
    ok = "POST /v1/visit" in seen
    print("VISIT POST REACHED API:", ok)
    server.should_exit = True
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
