"""Live web run (task L-web): the real built page against a local stub of the live API.

    cd web && python3 qa/e2e_live.py

Builds the site twice (with VITE_MAUDESIGNAL_API_BASE pointing at the stub, and without), serves both, and drives Chromium
with a fake camera and a fake microphone. It checks a two-turn chat, a voice question (the stub receives a valid 16 kHz
WAV), a camera capture (the stub receives a JPEG with no EXIF; three possible matches with Confirm buttons), an upload that
carries EXIF, the recorded fallback on 429, denied permissions, keyboard and names, and horizontal scroll at 390 and
1440 in light and dark. Screenshots go to qa/screenshots/L-*.png. Prints one JSON report; exits 1 if any check failed.
"""

# ruff: noqa: E501, T201
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

from live_stub import Stub
from playwright.sync_api import Browser, Page, sync_playwright

WEB = Path(__file__).resolve().parents[1]
OUT = WEB / "qa" / "screenshots"
# Ports can be moved with LIVE_E2E_PORT_BASE (stub, live page, stored page = base, base+1, base+2) when another run holds them.
_BASE = int(os.environ.get("LIVE_E2E_PORT_BASE", "0"))
STUB_PORT, LIVE_PORT, STORED_PORT = (_BASE, _BASE + 1, _BASE + 2) if _BASE else (8765, 4173, 4174)
LIVE_URL = f"http://127.0.0.1:{LIVE_PORT}/"
STORED_URL = f"http://127.0.0.1:{STORED_PORT}/"

results: list[dict[str, object]] = []


def check(name: str, ok: bool, detail: object = "") -> None:
    """Record one check."""
    results.append({"check": name, "ok": bool(ok), "detail": detail if not ok else (detail or "")})
    print(
        ("PASS " if ok else "FAIL ") + name + ("" if ok or not detail else f"  <- {detail}"),
        flush=True,
    )


def run(cmd: list[str], env: dict[str, str] | None = None) -> None:
    """Run a build command in web/."""
    subprocess.run(
        cmd, cwd=WEB, env={**os.environ, **(env or {})}, check=True, capture_output=True, text=True
    )


def build() -> None:
    """Build dist-live (with the stub's address) and dist-stored (without any API address)."""
    run(["node", "scripts/copy-design-system.mjs"])
    run(["npx", "tsc", "-b"])
    run(
        ["npx", "vite", "build", "--outDir", "dist-live"],
        {"VITE_MAUDESIGNAL_API_BASE": f"http://127.0.0.1:{STUB_PORT}"},
    )
    run(["npx", "vite", "build", "--outDir", "dist-stored"], {"VITE_MAUDESIGNAL_API_BASE": ""})


def preview(outdir: str, port: int) -> subprocess.Popen[bytes]:
    """Serve a built folder with vite preview."""
    p = subprocess.Popen(
        [
            "npx",
            "vite",
            "preview",
            "--outDir",
            outdir,
            "--port",
            str(port),
            "--strictPort",
            "--host",
            "127.0.0.1",
        ],
        cwd=WEB,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    for _ in range(60):
        try:
            import urllib.request

            urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=1)
            return p
        except Exception:
            time.sleep(0.5)
    raise RuntimeError(f"preview on {port} did not start")


def jpeg_with_exif() -> bytes:
    """A real label photo with an EXIF segment (a camera serial and a GPS-looking string) inserted after the SOI marker."""
    src = (WEB / "public" / "data" / "vision" / "label-caresens-n.jpg").read_bytes()
    exif = b"Exif\x00\x00" + b"CAMERA-SERIAL-12345 GPS 40.7128N 74.0060W" + b"\x00" * 8
    seg = b"\xff\xe1" + (len(exif) + 2).to_bytes(2, "big") + exif
    return src[:2] + seg + src[2:]


def big_noisy_jpeg() -> bytes:
    """A 4000 x 3000 noisy JPEG over 4 MB, with EXIF, like a phone photo."""
    import io

    from PIL import Image

    img = Image.frombytes("RGB", (4000, 3000), os.urandom(4000 * 3000 * 3))
    out = io.BytesIO()
    img.save(out, format="JPEG", quality=92, exif=Image.Exif())
    return out.getvalue()


def overflow(page: Page) -> int:
    """Document scrollWidth minus the viewport width (0 = no sideways scroll)."""
    return int(
        page.evaluate("document.documentElement.scrollWidth - document.documentElement.clientWidth")
    )


def new_page(
    browser: Browser, width: int, height: int, scheme: str, init: str | None = None
) -> Page:
    """A page with the fake-media permissions granted and speech synthesis recorded."""
    ctx = browser.new_context(viewport={"width": width, "height": height}, color_scheme=scheme, permissions=["microphone", "camera"])  # type: ignore[arg-type]
    page = ctx.new_page()
    page.add_init_script("""
        window.__spoken = [];
        if ('speechSynthesis' in window) {
          const orig = window.speechSynthesis.speak.bind(window.speechSynthesis);
          window.speechSynthesis.speak = (u) => { window.__spoken.push(u.text); try { orig(u) } catch (e) {} };
        }
        """)
    if init:
        page.add_init_script(init)
    return page


def open_live(page: Page) -> None:
    """Open the live page and wait until the composer is there."""
    page.goto(LIVE_URL, wait_until="load")
    page.wait_for_selector("textarea[aria-label='Ask a question']")
    page.evaluate("document.fonts.ready")


def ask(page: Page, text: str) -> None:
    """Type a question and press Enter."""
    box = page.locator("textarea[aria-label='Ask a question']")
    box.click()
    box.fill(text)
    box.press("Enter")


def shot(page: Page, name: str, report: dict[str, object]) -> None:
    """Save L-<name>.png and record the overflow."""
    page.wait_for_timeout(300)
    report[f"overflow_{name}"] = overflow(page)
    page.screenshot(path=str(OUT / f"L-{name}.png"))


def stub_log(page: Page) -> list[dict[str, object]]:
    """The requests the stub has seen so far."""
    return json.loads(page.request.get(f"http://127.0.0.1:{STUB_PORT}/__log").text())["log"]


def main() -> int:
    """Run everything and print the report."""
    OUT.mkdir(parents=True, exist_ok=True)
    print("building...", flush=True)
    build()
    stub = Stub(port=STUB_PORT, origins={f"http://127.0.0.1:{LIVE_PORT}"})
    stub.start()
    servers = [preview("dist-live", LIVE_PORT), preview("dist-stored", STORED_PORT)]
    report: dict[str, object] = {}
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(
                args=["--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream"]
            )
            report["chromium"] = browser.version

            # 1. chat: two turns, desktop light
            page = new_page(browser, 1440, 900, "light")
            requests_seen: list[str] = []
            page.on("request", lambda r: requests_seen.append(r.url))
            open_live(page)
            ask(page, "What changed this week?")
            page.wait_for_selector("[data-testid=user-bubble]")
            check(
                "chat: question appears as a bubble",
                "What changed this week?"
                in page.locator("[data-testid=user-bubble]").first.inner_text(),
            )
            page.wait_for_selector("[data-testid=answer-sentences] li", timeout=15000)
            page.wait_for_function(
                "document.querySelector('[data-testid=held-back]')", timeout=15000
            )
            body = page.locator("[data-testid=live-turn]").first.inner_text()
            check(
                "chat: answer, trace with ms, held-back line, advice line",
                "Stub answer 1" in body
                and "812 ms" in body
                and "1 sentence held back: a number did not match" in body
                and "Not medical advice" in body,
                body[:300],
            )
            check(
                "chat: links under the sentence",
                page.locator("[data-testid=sentence-links] a").count() == 1,
            )
            check(
                "chat: focus returns to the input",
                page.evaluate(
                    "document.activeElement && document.activeElement.getAttribute('aria-label')"
                )
                == "Ask a question",
            )
            ask(page, "And which device types?")
            page.wait_for_function(
                "document.querySelectorAll('[data-testid=live-turn]').length === 2"
            )
            page.wait_for_function(
                "document.body.innerText.includes('Stub answer 2')", timeout=15000
            )
            asks = [e for e in stub_log(page) if e["path"] == "/v1/live/ask"]
            check(
                "chat: second request carries one history turn",
                len(asks) == 2
                and "history" not in asks[0]["body"]
                and len(asks[1]["body"]["history"]) == 1
                and asks[1]["body"]["history"][0]["question"] == "What changed this week?",
                asks,
            )
            ask(page, "x")
            check(
                "chat: too-short question is refused before sending",
                page.locator("[data-testid=ask-error]").count() == 1
                and len([e for e in stub_log(page) if e["path"] == "/v1/live/ask"]) == 2,
            )
            box = page.locator("textarea[aria-label='Ask a question']")
            box.fill("")
            box.fill("line one")
            box.press("Shift+Enter")
            check(
                "chat: Shift+Enter adds a line and does not send",
                box.input_value() == "line one\n"
                and len([e for e in stub_log(page) if e["path"] == "/v1/live/ask"]) == 2,
            )
            box.fill("")
            shot(page, "chat-1440-light", report)
            check(
                "chat 1440 light: no sideways scroll",
                report["overflow_chat-1440-light"] == 0,
                report["overflow_chat-1440-light"],
            )

            # security: nothing about the questions in browser storage; only the stub and the page were contacted
            stored = page.evaluate(
                "JSON.stringify([Object.entries(localStorage), Object.entries(sessionStorage)])"
            )
            check(
                "security: no question text in localStorage or sessionStorage",
                "What changed" not in stored and "device types" not in stored,
                stored[:200],
            )
            hosts = {r.split("/")[2] for r in requests_seen}
            # (Google Fonts is the app's existing stylesheet host; no other third party may be contacted.)
            check(
                "security: the page contacted only the page host, the stub and the font host",
                hosts
                <= {
                    f"127.0.0.1:{LIVE_PORT}",
                    f"127.0.0.1:{STUB_PORT}",
                    "fonts.googleapis.com",
                    "fonts.gstatic.com",
                },
                sorted(hosts),
            )
            log = stub_log(page)
            check(
                "security: no cookies or credentials were sent to the API",
                all(not e["credentials_sent"] for e in log),
            )
            check(
                "security: requests came from the page origin only",
                all(e["origin"] == f"http://127.0.0.1:{LIVE_PORT}" for e in log),
            )

            # exploratory: a question that looks like patient data -> the server message
            ask(page, "What happened to patient name John, MRN 12345?")
            page.wait_for_selector("[data-testid=turn-error]")
            check(
                "422 patient_data: shows the server message",
                "patient details" in page.locator("[data-testid=turn-error]").inner_text(),
            )

            # 2. voice
            page.reload()
            page.wait_for_selector("textarea[aria-label='Ask a question']")
            n_voice = len([e for e in stub_log(page) if e["path"] == "/v1/live/voice"])
            page.get_by_test_id("composer-mic").click()
            page.wait_for_selector("[data-testid=recording-bar]")
            page.wait_for_timeout(1600)
            check(
                "voice: timer and level meter while recording",
                page.get_by_test_id("rec-timer").inner_text().startswith("0:0")
                and page.get_by_test_id("rec-meter").get_attribute("aria-valuenow") is not None,
                page.get_by_test_id("rec-timer").inner_text(),
            )
            shot(page, "voice-recording-1440-light", report)
            page.get_by_test_id("composer-mic").click()
            page.wait_for_function("document.body.innerText.includes('Heard:')", timeout=20000)
            page.wait_for_function("document.body.innerText.includes('Stub answer')", timeout=20000)
            text = page.locator("[data-testid=live-chat]").inner_text()
            check(
                "voice: page shows Heard before the answer",
                "Heard:" in text and text.index("Heard:") < text.index("Stub answer"),
                text[:200],
            )
            voices = [e for e in stub_log(page) if e["path"] == "/v1/live/voice"][n_voice:]
            a = voices[0]["audio"] if voices else {}
            check(
                "voice: stub received a valid 16 kHz mono PCM16 WAV",
                bool(voices)
                and a.get("valid") is True
                and a.get("sample_rate") == 16000
                and a.get("channels") == 1
                and a.get("bits") == 16
                and a.get("seconds", 0) > 0.8,
                a,
            )
            check(
                "voice: WAV is under 4 MB and 60 s",
                a.get("bytes", 9e9) < 4 * 1024 * 1024 and a.get("seconds", 99) <= 60,
                a,
            )
            spoken = page.evaluate("window.__spoken")
            check(
                "voice: answer is read aloud (spoken_text only)",
                spoken
                == [
                    "Stub answer 1: 33 reports were stored for the week. Two device types had more serious reports than usual."
                ],
                spoken,
            )
            check(
                "voice: stop button / speaker toggle exist",
                page.get_by_test_id("speaker-toggle").count() == 1,
            )
            shot(page, "voice-answer-1440-light", report)
            page.get_by_test_id(
                "composer-mic"
            ).click()  # a second recording, left running, to prove the bar closes on stop
            page.wait_for_timeout(500)
            page.get_by_test_id("composer-mic").click()
            page.wait_for_function(
                "document.querySelectorAll('[data-testid=live-turn]').length === 2", timeout=20000
            )

            # 3. camera: live preview and capture
            page.get_by_test_id("composer-camera").click()
            page.get_by_test_id("use-camera").click()
            page.wait_for_selector("[data-testid=camera-preview] video")
            page.wait_for_function("document.querySelector('video').videoWidth > 0", timeout=10000)
            check("camera: live preview is playing", True)
            shot(page, "camera-preview-1440-light", report)
            t0 = time.time()
            page.get_by_test_id("capture").click()
            page.wait_for_selector("[data-testid=match-card]", timeout=20000)
            took = time.time() - t0
            imgs = [e for e in stub_log(page) if e["path"] == "/v1/live/label"]
            img = imgs[-1]["image"] if imgs else {}
            check(
                "camera: stub received a JPEG with no EXIF",
                img.get("jpeg") is True
                and img.get("exif") is False
                and img["bytes"] < 4 * 1024 * 1024
                and max(img.get("width", 99999), img.get("height", 99999)) <= 1600,
                img,
            )
            check(
                "camera: three possible matches with Confirm buttons",
                page.locator("[data-testid=match-card]").count() == 3
                and page.get_by_role("button", name="Confirm this match").count() == 3,
            )
            check(
                "camera: reading shows legibility banner and unreadable fields as not read",
                page.get_by_test_id("legibility-banner").count() == 1
                and page.get_by_test_id("reading-fields").inner_text().count("not read") == 4
                and page.get_by_test_id("reading-fields").inner_text().count("value withheld") == 0
                and page.get_by_test_id("lot-serial-note").count() == 1,
                [page.get_by_test_id("legibility-banner").count(), page.get_by_test_id("lot-serial-note").count()],
            )
            steps = [s.inner_text() for s in page.locator("[data-testid=trace-step]").all()]
            check(
                "camera: trace shows re-encode -> SAM -> Spark -> openFDA with ms",
                len(steps) == 4
                and "Re-encode" in steps[0]
                and "SAM 3.1" in steps[1]
                and "1.4 s" in steps[1]
                and "openFDA" in steps[3],
                steps,
            )
            check(
                "performance: capture to matches shown well under 55 s", took < 55, f"{took:.2f}s"
            )
            page.wait_for_function("!document.querySelector('video')")
            check(
                "camera: stream is stopped after capture",
                page.evaluate("navigator.mediaDevices.enumerateDevices().then(() => true)") is True
                and page.locator("video").count() == 0,
            )
            check(
                "camera: never auto-picks a match",
                page.locator("[data-confirmed=true]").count() == 0,
            )
            page.get_by_role("button", name="Confirm this match").nth(1).click()
            check(
                "camera: Confirm marks only the chosen card, nothing is sent",
                page.locator("[data-confirmed=true]").count() == 1
                and len([e for e in stub_log(page) if e["path"] == "/v1/live/label"]) == len(imgs),
            )
            shot(page, "camera-result-1440-light", report)

            # upload with EXIF -> canvas re-encode removes it
            big_path = WEB / "qa" / "tmp" / "big-phone.jpg"
            big_path.parent.mkdir(parents=True, exist_ok=True)
            big_path.write_bytes(big_noisy_jpeg())
            page.get_by_test_id("image-input").set_input_files(str(big_path))
            for _ in range(60):  # wait for the stub to receive the shrunk photo
                imgs_big = [e for e in stub_log(page) if e["path"] == "/v1/live/label"]
                if len(imgs_big) > len(imgs):
                    break
                page.wait_for_timeout(500)
            sent = imgs_big[-1]["image"]
            check(
                "upload: a 4000 x 3000 photo over 4 MB is shrunk to 1600 px and under 4 MB before upload",
                big_path.stat().st_size > 4 * 1024 * 1024
                and max(sent["width"], sent["height"]) == 1600
                and sent["bytes"] < 4 * 1024 * 1024
                and sent["exif"] is False,
                {"original": big_path.stat().st_size, "sent": sent},
            )
            check(
                "upload: the bytes sent are not the original file",
                sent["bytes"] != big_path.stat().st_size,
            )
            exif_path = WEB / "qa" / "tmp" / "with-exif.jpg"
            exif_path.parent.mkdir(parents=True, exist_ok=True)
            exif_path.write_bytes(jpeg_with_exif())
            check(
                "upload: the test file really carries EXIF",
                b"Exif\x00\x00" in exif_path.read_bytes()[:200],
            )
            page.get_by_test_id("image-input").set_input_files(str(exif_path))
            page.wait_for_timeout(1500)
            imgs2 = [e for e in stub_log(page) if e["path"] == "/v1/live/label"]
            check(
                "upload: EXIF is gone before it leaves the page, long side at most 1600",
                len(imgs2) == len(imgs_big) + 1
                and max(imgs2[-1]["image"]["width"], imgs2[-1]["image"]["height"]) <= 1600
                and imgs2[-1]["image"]["exif"] is False
                and imgs2[-1]["image"]["jpeg"] is True,
                imgs2[-1]["image"],
            )

            # exploratory: wrong type, empty file, huge file
            bad = WEB / "qa" / "tmp" / "not-an-image.txt"
            bad.write_text("hello")
            page.get_by_test_id("image-input").set_input_files(str(bad))
            page.wait_for_selector("[data-testid=camera-problem]")
            check(
                "exploratory: a text file is refused with a message",
                "not an image" in page.get_by_test_id("camera-problem").inner_text(),
            )
            empty = WEB / "qa" / "tmp" / "empty.jpg"
            empty.write_bytes(b"")
            page.get_by_test_id("image-input").set_input_files(str(empty))
            page.wait_for_function(
                "document.querySelector('[data-testid=camera-problem]')?.innerText.includes('empty')"
            )
            check("exploratory: an empty file is refused", True)
            before = len([e for e in stub_log(page) if e["path"] == "/v1/live/label"])
            huge = WEB / "qa" / "tmp" / "huge.jpg"
            huge.write_bytes(b"\xff\xd8\xff" + b"0" * (31 * 1024 * 1024))
            page.get_by_test_id("image-input").set_input_files(str(huge))
            page.wait_for_function(
                "document.querySelector('[data-testid=camera-problem]')?.innerText.includes('too large')"
            )
            check(
                "exploratory: a huge file is refused before sending",
                len([e for e in stub_log(page) if e["path"] == "/v1/live/label"]) == before,
            )
            page.close()

            # 4. 429: chat, label, voice all fall back to the recorded runs
            stub.mode = "429"
            page = new_page(browser, 1440, 900, "light")
            open_live(page)
            ask(page, "What changed this week?")
            page.wait_for_selector("[data-testid=limit-banner]")
            check(
                "429 chat: limit banner and recorded run badge",
                page.get_by_test_id("limit-banner").inner_text()
                == "Daily live limit reached - showing recorded runs"
                and page.get_by_test_id("mode-badge").inner_text() == "Recorded run",
            )
            check(
                "429 chat: recorded note names the stored run",
                "Showing the stored run" in page.get_by_test_id("recorded-note").inner_text(),
                page.get_by_test_id("recorded-note").inner_text(),
            )
            n = len(stub_log(page))
            ask(page, "What changed this week?")
            page.wait_for_function(
                "document.querySelectorAll('[data-testid=live-turn]').length === 2"
            )
            check(
                "429 chat: later questions go straight to recorded runs (no request)",
                len(stub_log(page)) == n,
            )
            shot(page, "chat-429-1440-light", report)
            page.get_by_test_id("composer-camera").click()
            page.get_by_test_id("use-camera").click()
            page.wait_for_function("document.querySelector('video')?.videoWidth > 0", timeout=10000)
            page.get_by_test_id("capture").click()
            page.wait_for_selector("[data-testid=fallback-reason]")
            check(
                "429 camera: limit message and recorded label runs below",
                "Daily live limit reached" in page.get_by_test_id("fallback-reason").inner_text()
                and page.get_by_test_id("label-recorded").count() == 1,
            )
            page.close()
            stub.mode = "ok"

            # 4b. real-API shapes: openFDA not searched, searched with no match, recorded answers
            page = new_page(browser, 1440, 900, "light")
            open_live(page)
            page.get_by_test_id("composer-camera").click()
            stub.label_mode = "search_failed"
            page.get_by_test_id("image-input").set_input_files(str(WEB / "qa" / "tmp" / "with-exif.jpg"))
            page.wait_for_selector("[data-testid=search-failed-note]")
            body_text = page.get_by_test_id("label-live").inner_text()
            check(
                "label search_failed: the server's note is shown, with a retry hint",
                page.get_by_test_id("search-failed-note").inner_text()
                == "openFDA could not be searched, so there is no match result for this photo."
                and "try again" in page.get_by_test_id("search-failed-retry").inner_text().lower(),
            )
            check(
                "label search_failed: no 'No match found', no candidate cards",
                "No match found" not in body_text and page.locator("[data-testid=match-card]").count() == 0,
                body_text[:300],
            )
            shot(page, "label-search-failed-1440-light", report)
            stub.label_mode = "no_match"
            page.get_by_test_id("image-input").set_input_files(str(WEB / "qa" / "tmp" / "with-exif.jpg"))
            page.wait_for_selector("[data-testid=no-match]")
            check(
                "label no_match (searched, nothing found): says 'No match found', not the failure note",
                page.locator("[data-testid=search-failed]").count() == 0,
            )
            stub.label_mode = "ok"
            stub.mode = "recorded"
            ask(page, "What changed this week?")
            page.wait_for_selector("[data-testid=recorded-note]")
            check(
                "recorded answer with HTTP 200: Recorded run badge and the server's note, no daily-limit banner",
                page.get_by_test_id("mode-badge").last.inner_text() == "Recorded run"
                and "recorded run that answered" in page.get_by_test_id("recorded-note").inner_text()
                and page.locator("[data-testid=limit-banner]").count() == 0,
                page.get_by_test_id("recorded-note").inner_text(),
            )
            stub.mode = "ok"
            page.close()

            # 5. denied permissions: message + recorded runs
            deny = "navigator.mediaDevices.getUserMedia = () => Promise.reject(Object.assign(new Error('x'), {name: 'NotAllowedError'}));"
            page = new_page(browser, 1440, 900, "light", deny)
            open_live(page)
            page.get_by_test_id("composer-mic").click()
            page.wait_for_selector("[data-testid=mic-notice]")
            check(
                "mic denied: clear message and the recorded voice run",
                "permission was denied" in page.get_by_test_id("mic-notice").inner_text()
                and page.get_by_test_id("voice-recorded").count() == 1,
            )
            shot(page, "mic-denied-1440-light", report)
            page.get_by_test_id("composer-camera").click()
            page.get_by_test_id("use-camera").click()
            page.wait_for_selector("[data-testid=camera-problem]")
            check(
                "camera denied: clear message and the recorded label runs",
                "permission was denied" in page.get_by_test_id("camera-problem").inner_text()
                and page.get_by_test_id("label-recorded").count() == 1,
            )
            page.close()

            # 6. layouts: 390 and 1440, light and dark, with an answer and a camera result
            for width, height in ((390, 844), (1440, 900)):
                for scheme in ("light", "dark"):
                    page = new_page(browser, width, height, scheme)
                    open_live(page)
                    ask(page, "What changed this week?")
                    page.wait_for_function(
                        "document.querySelector('[data-testid=held-back]')", timeout=15000
                    )
                    shot(page, f"chat-{width}-{scheme}", report)
                    page.get_by_test_id("composer-camera").click()
                    page.get_by_test_id("use-camera").click()
                    page.wait_for_function(
                        "document.querySelector('video')?.videoWidth > 0", timeout=10000
                    )
                    page.get_by_test_id("capture").click()
                    page.wait_for_selector("[data-testid=match-card]", timeout=20000)
                    shot(page, f"camera-{width}-{scheme}", report)
                    page.get_by_test_id("composer-mic").click()
                    page.wait_for_selector("[data-testid=recording-bar]")
                    page.wait_for_timeout(700)
                    shot(page, f"recording-{width}-{scheme}", report)
                    page.get_by_test_id("composer-mic").click()
                    page.wait_for_function(
                        "document.body.innerText.includes('Heard:')", timeout=20000
                    )
                    shot(page, f"voice-{width}-{scheme}", report)
                    for k in ("chat", "camera", "recording", "voice"):
                        v = report[f"overflow_{k}-{width}-{scheme}"]
                        check(f"layout {k} {width} {scheme}: scrollWidth == viewport", v == 0, v)
                    if (width, scheme) == (390, "light"):
                        # accessibility basics: every control has a name; the mic, camera and send are reachable by keyboard
                        nameless = page.evaluate(
                            """() => [...document.querySelectorAll('button, a[href], input, textarea, select, [role=button]')]
                              .filter(e => e.offsetParent !== null || e.closest('label'))
                              .filter(e => !(e.getAttribute('aria-label') || e.getAttribute('title') || (e.textContent||'').trim() || (e.labels && e.labels.length) || e.getAttribute('aria-labelledby')))
                              .map(e => e.outerHTML.slice(0, 120))"""
                        )
                        check(
                            "accessibility: every visible control has a name",
                            nameless == [],
                            nameless,
                        )
                    page.close()

            # keyboard: Tab reaches the camera, mic and send controls
            page = new_page(browser, 1440, 900, "light")
            open_live(page)
            page.locator("textarea[aria-label='Ask a question']").focus()
            reached: list[str] = []
            for _ in range(5):
                page.keyboard.press("Tab")
                reached.append(
                    page.evaluate(
                        "document.activeElement.getAttribute('data-testid') || document.activeElement.innerText"
                    )
                )
            check(
                "keyboard: Tab from the input reaches camera, mic and Send",
                "composer-camera" in reached
                and "composer-mic" in reached
                and any("Send" in r for r in reached),
                reached,
            )
            page.close()

            # 4b. recorded stub mode: the camera answer is the recorded shape, labelled, and still counts against the daily counter
            stub.mode = "recorded"
            left_before = stub.live_left
            page = new_page(browser, 1440, 900, "light")
            open_live(page)
            page.get_by_test_id("composer-camera").click()
            page.get_by_test_id("use-camera").click()
            page.wait_for_function("document.querySelector('video') && document.querySelector('video').videoWidth > 0", timeout=10000)
            page.get_by_test_id("capture").click()
            page.wait_for_selector("[data-testid=label-live][data-mode=recorded]", timeout=20000)
            check(
                "recorded stub: label result carries the Recorded run badge and its note",
                page.get_by_test_id("mode-badge").last.inner_text() == "Recorded run"
                and page.get_by_test_id("recorded-note").count() >= 1
                and stub.live_left == left_before - 1,
                [stub.live_left, left_before],
            )
            page.close()
            stub.mode = "ok"

            # fonts / contrast spot check is covered by contrast_b7-style tests elsewhere; here only the live parts' tokens
            # 7. stored-first demo with no API address
            page = new_page(browser, 1440, 900, "light")
            page.goto(STORED_URL, wait_until="load")
            page.wait_for_selector("textarea[aria-label='Ask a question']")
            check(
                "stored-first: the send button still says Open and the note names recorded runs",
                page.get_by_role("button", name="Open", exact=True).count() >= 1
                and "recorded run until the live API answers"
                in page.get_by_test_id("disclaimer").inner_text().replace("\n", " "),
            )
            ask(page, "What changed this week?")
            page.wait_for_function("document.body.innerText.includes('Stored run')", timeout=15000)
            check(
                "stored-first: a typed question opens the closest recorded answer",
                page.locator("[data-testid=live-turn]").count() == 0,
            )
            page.get_by_test_id("composer-mic").click()
            page.wait_for_selector("[data-testid=voice-recorded]")
            check(
                "stored-first: mic opens the recorded voice run, labelled",
                "Recorded run" in page.locator("main").inner_text()
                and page.locator("[data-testid=recording-bar]").count() == 0,
            )
            page.get_by_test_id("composer-camera").click()
            page.wait_for_selector("[data-testid=label-recorded]")
            check(
                "stored-first: camera opens the recorded label run, no live controls",
                page.get_by_test_id("use-camera").count() == 0,
            )
            shot(page, "stored-first-1440-light", report)
            page.close()
            browser.close()
    finally:
        for s in servers:
            s.terminate()
        stub.stop()
    failed = [r for r in results if not r["ok"]]
    report["checks"] = {"total": len(results), "failed": len(failed)}
    report["failed"] = failed
    print(json.dumps(report, indent=2))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
