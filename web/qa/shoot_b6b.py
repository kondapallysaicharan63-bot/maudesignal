"""B6b screenshots: agent trace, camera + mic (recorded fallback), composer type-ahead.

    cd web && npm run build && python3 qa/shoot_b6b.py

Serves ``dist/`` locally with the network blocked (so no live API answers and the recorded fallback shows)
and writes ``qa/screenshots/B6-<view>-<width>-<theme>.png``. Prints, as JSON, the overflow numbers of every
shot and the checks on the trace, the type-ahead keys and the camera / mic flows.
"""

# ruff: noqa: E501
from __future__ import annotations

import base64
import io
import json
import wave

from playwright.sync_api import Page, sync_playwright
from shoot_b1 import OUT, SCRATCH, local_only, serve
from shoot_b6a import overflow

PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)


def wav_bytes() -> bytes:
    """A short silent WAV (a stand-in file for the upload control; it is never sent anywhere here)."""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(8000)
        w.writeframes(b"\x00\x00" * 800)
    return buf.getvalue()


def shot(page: Page, r: dict[str, object], tag: str, name: str) -> None:
    """Record the overflow numbers and save ``B6-<name>-<tag>.png``."""
    page.wait_for_timeout(250)
    r[f"overflow_{name}"] = overflow(page)
    page.screenshot(path=str(OUT / f"B6-{name}-{tag}.png"))


def open_by_typing(page: Page, query: str, option_text: str) -> None:
    """Type in the composer and choose the suggestion that contains ``option_text``."""
    box = page.get_by_role("combobox")
    box.click()
    box.fill(query)
    page.get_by_role("option").filter(has_text=option_text).first.click()
    page.wait_for_timeout(300)


def main() -> None:
    """Take the B6b screenshots and print the checks."""
    OUT.mkdir(parents=True, exist_ok=True)
    SCRATCH.mkdir(parents=True, exist_ok=True)
    png = SCRATCH / "sample-label.png"
    png.write_bytes(PNG)
    wav = SCRATCH / "sample-question.wav"
    wav.write_bytes(wav_bytes())
    threads = json.loads((OUT.parents[1] / "public" / "data" / "threads.json").read_text())[
        "threads"
    ]
    blocked = next(t for t in threads if any(s["status"] == "block" for s in t["sentences"]))
    voice = next(t for t in threads if t["voice"] and t["tool_steps"])
    srv, port = serve()
    url = f"http://127.0.0.1:{port}/"
    report: dict[str, object] = {"blocked_thread": blocked["id"], "voice_thread": voice["id"]}
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        for width, height in ((1440, 900), (390, 844)):
            for scheme in ("light", "dark"):
                tag = f"{width}-{scheme}"
                r: dict[str, object] = {}
                ctx = browser.new_context(
                    viewport={"width": width, "height": height},
                    color_scheme=scheme,  # type: ignore[arg-type]
                    reduced_motion="no-preference",
                )
                page = ctx.new_page()
                page.route("**/*", local_only)
                page.goto(url, wait_until="load")
                page.wait_for_selector("text=claims verified")
                page.evaluate("document.fonts.ready")
                page.wait_for_timeout(300)

                # type-ahead: questions
                box = page.get_by_role("combobox")
                box.click()
                box.fill("recall")
                page.wait_for_selector("[role=option]")
                r["typeahead_q_options"] = page.get_by_role("option").count()
                r["typeahead_q_expanded"] = box.get_attribute("aria-expanded")
                r["typeahead_q_texts"] = page.get_by_role("option").all_inner_texts()
                r["typeahead_hint"] = page.get_by_test_id("typeahead-hint").inner_text()
                r["typeahead_marks"] = page.locator("[role=option] mark").all_inner_texts()
                r["typeahead_list_box"] = page.locator("[role=listbox]").bounding_box()
                r["typeahead_scrim"] = page.get_by_test_id("typeahead-scrim").count()
                shot(page, r, tag, "typeahead-questions")
                # keyboard: ArrowDown highlights, ArrowUp wraps to the last, Esc closes
                box.press("ArrowDown")
                r["typeahead_active_after_down"] = box.get_attribute("aria-activedescendant")
                box.press("ArrowUp")
                r["typeahead_active_after_up"] = box.get_attribute("aria-activedescendant")
                shot(page, r, tag, "typeahead-selected")
                box.press("Escape")
                r["typeahead_closed_on_esc"] = box.get_attribute("aria-expanded")
                # type-ahead: codes
                box.fill("ll")
                page.wait_for_selector("[role=option]")
                r["typeahead_code_options"] = page.get_by_role("option").all_inner_texts()
                shot(page, r, tag, "typeahead-codes")
                # Enter on a highlighted code opens Check any device type with it filled in
                box.press("ArrowDown")
                opts = page.get_by_role("option").all_inner_texts()
                idx = next(
                    (i for i, t in enumerate(opts) if "Check any device type" in t and "LLZ" in t),
                    0,
                )
                for _ in range(idx):
                    box.press("ArrowDown")
                box.press("Enter")
                page.wait_for_selector("#live-code")
                r["code_prefilled"] = page.locator("#live-code").input_value()
                r["code_view_title"] = page.locator("main h1").inner_text()
                shot(page, r, tag, "typeahead-code-opened")

                # thread with the trace (a repaired / withheld answer)
                q = blocked["question"]
                open_by_typing(page, " ".join(q.split()[:4]), q[:40])
                page.wait_for_selector("[data-testid=trace-run]", state="attached", timeout=15000)
                page.wait_for_timeout(500)
                r["trace_steps"] = page.locator("[data-testid=trace] li[data-step]").evaluate_all(
                    "els => els.map(e => e.getAttribute('data-step'))"
                )
                r["trace_summary"] = page.get_by_test_id("trace-summary").inner_text()
                page.locator("main div.overflow-y-auto").first.evaluate("e => e.scrollTo(0, 0)")
                shot(page, r, tag, "trace-thread")
                page.get_by_test_id("trace").locator("summary").click()
                page.wait_for_timeout(250)
                r["trace_text"] = page.locator("[data-testid=trace]").inner_text()
                page.get_by_test_id("trace").scroll_into_view_if_needed()
                shot(page, r, tag, "trace-open")
                page.locator("main div.overflow-y-auto").first.evaluate("e => e.scrollTo(0, 0)")
                shot(page, r, tag, "trace-thread-top")

                # camera flow: warning first, recorded example, then a chosen file falls back with the reason
                page.get_by_test_id("composer-camera").click()
                page.wait_for_selector("[data-testid=patient-warning]")
                r["warning_text"] = page.locator("[data-testid=patient-warning]").inner_text()
                r["capture_on_label"] = page.get_by_test_id("capture-on").inner_text()
                r["camera_btn_pressed"] = page.get_by_test_id("composer-camera").get_attribute(
                    "aria-pressed"
                )
                r["take_photo_y"] = page.get_by_text("Take a photo").bounding_box()["y"]
                r["recorded_tag_present"] = page.locator("text=Recorded run").count()
                shot(page, r, tag, "camera")
                page.get_by_test_id("image-input").set_input_files(str(png))
                page.get_by_role("button", name="Send photo").click()
                page.wait_for_selector("[data-testid=fallback-reason]")
                r["camera_fallback"] = page.locator("[data-testid=fallback-reason]").inner_text()
                page.locator("[data-testid=fallback-reason]").scroll_into_view_if_needed()
                shot(page, r, tag, "camera-fallback")
                page.locator("[data-testid=label-recorded]").scroll_into_view_if_needed()
                shot(page, r, tag, "camera-recorded")

                # mic flow
                page.get_by_test_id("composer-mic").click()
                page.wait_for_selector("[data-testid=patient-warning]")
                shot(page, r, tag, "mic")
                page.get_by_test_id("audio-input").set_input_files(str(wav))
                page.get_by_role("button", name="Send recording").click()
                page.wait_for_selector("[data-testid=fallback-reason]")
                r["mic_fallback"] = page.locator("[data-testid=fallback-reason]").inner_text()
                shot(page, r, tag, "mic-fallback")
                page.locator("[data-testid=voice-recorded]").scroll_into_view_if_needed()
                shot(page, r, tag, "mic-recorded")
                # the recorded voice answer: the trace starts with the Voice Transcribe "Heard" step
                page.get_by_role("button", name="Open the recorded answer").click()
                page.wait_for_selector("[data-testid=trace-run]", state="attached", timeout=15000)
                page.wait_for_timeout(300)
                page.get_by_test_id("trace").locator("summary").click()
                page.wait_for_timeout(200)
                r["voice_trace_first_step"] = page.locator(
                    "[data-testid=trace] li[data-step]"
                ).first.inner_text()
                shot(page, r, tag, "trace-voice")

                report[tag] = r
                ctx.close()
        browser.close()
    srv.shutdown()
    print(json.dumps(report, indent=2))  # noqa: T201


if __name__ == "__main__":
    main()
