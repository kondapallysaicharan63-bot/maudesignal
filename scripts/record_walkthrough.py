# ruff: noqa: E501 — the embedded cursor script and card CSS are kept on readable lines.
"""Record a slow, narrated 3-minute walkthrough of the keyless demo app (video script v4).

HACKATHON-BUILT — Meta Global AI Developer Hackathon (Oct 26 – Nov 4, 2026).

Drives the running app with Playwright and records the screen. A visible cursor
glides to each control and pauses before every click, so the video can be
narrated at an easy pace. Writes, in ``--out``:

* ``walkthrough.mp4``           — the screen recording (no captions)
* ``walkthrough-captions.mp4``  — the same with the voiceover lines as subtitles
* ``walkthrough.srt``           — the voiceover lines, timed to the recording
* ``walkthrough-script.md``     — what to say, beat by beat, with start times

Every figure on the title and stat cards comes from a recorded source
(``docs/hackathon/SOURCE_COUNTS.md``); every figure on the app screens is the app's.

    streamlit run streamlit_app.py --server.port 8501 &
    python scripts/record_walkthrough.py --url http://localhost:8501 --out /tmp/walkthrough
"""

from __future__ import annotations

import argparse
import html
import re
import shutil
import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

W, H = 1440, 900
CURSOR_JS = """
(() => {
  if (document.getElementById('ms-cursor')) return;
  const c = document.createElement('div');
  c.id = 'ms-cursor';
  c.innerHTML = '<svg width="26" height="26" viewBox="0 0 24 24"><path d="M3 2l7 19 2.6-7.4L20 11z" '
    + 'fill="#16130f" stroke="#fff" stroke-width="1.6" stroke-linejoin="round"/></svg>';
  Object.assign(c.style, {position:'fixed', left:'720px', top:'450px', zIndex:2147483647,
    pointerEvents:'none', transition:'left 1.1s cubic-bezier(.4,0,.2,1), top 1.1s cubic-bezier(.4,0,.2,1)'});
  const r = document.createElement('div');
  r.id = 'ms-ripple';
  Object.assign(r.style, {position:'fixed', width:'34px', height:'34px', borderRadius:'50%',
    border:'3px solid #1d3fbf', opacity:0, zIndex:2147483646, pointerEvents:'none',
    transform:'translate(-50%,-50%) scale(.4)', transition:'opacity .5s, transform .5s'});
  document.documentElement.append(c, r);
  window.__msMove = (x, y) => { c.style.left = x + 'px'; c.style.top = y + 'px'; };
  window.__msRipple = (x, y) => {
    Object.assign(r.style, {left: x + 'px', top: y + 'px', opacity: 1, transform: 'translate(-50%,-50%) scale(1)'});
    setTimeout(() => Object.assign(r.style, {opacity: 0, transform: 'translate(-50%,-50%) scale(1.6)'}), 450);
  };
})();
"""

CARD_CSS = """
@import url('https://fonts.googleapis.com/css2?family=Newsreader:opsz,wght@6..72,500&family=Geist:wght@400;600&display=swap');
html,body{margin:0;height:100%;background:#f6f3ec;color:#16130f;font-family:Geist,system-ui,sans-serif}
.card{height:100%;display:flex;flex-direction:column;justify-content:center;padding:0 120px;box-sizing:border-box}
.card .kicker{margin-bottom:22px}
.kicker{font:600 15px/1.4 Geist,sans-serif;letter-spacing:.12em;text-transform:uppercase;color:#5e574c}
h1{font:500 96px/1 Newsreader,Georgia,serif;letter-spacing:-3px;margin:18px 0 22px}
h1 em{color:#1d3fbf}
h2{font:500 60px/1.08 Newsreader,Georgia,serif;letter-spacing:-1.5px;margin:18px 0 22px;max-width:22ch}
p{font:400 26px/1.45 Geist,sans-serif;color:#4a443b;max-width:46ch;margin:0 0 14px}
.fig{font:500 150px/.9 Newsreader,Georgia,serif;letter-spacing:-5px;color:#16130f}
.rule{border-top:3px double #8f8676;margin:28px 0;width:100%}
.src{font:400 17px/1.4 Geist,sans-serif;color:#5e574c}
"""


@dataclass
class Beat:
    """One narrated step: what is on screen, what to say, and how to drive it."""

    title: str
    say: str
    act: Callable[[Any], None]
    start: float = 0.0
    end: float = 0.0
    extra: dict[str, Any] = field(default_factory=dict)


class Driver:
    """Slow, visible browser actions."""

    def __init__(self, page: Any, base: str) -> None:
        """Drive ``page``; app paths are relative to ``base``."""
        self.page = page
        self.base = base

    def pause(self, s: float) -> None:
        """Hold the current screen for ``s`` seconds."""
        self.page.wait_for_timeout(int(s * 1000))

    def cursor(self) -> None:
        """(Re)insert the visible cursor after a page load."""
        self.page.evaluate(CURSOR_JS)

    def open(self, path: str, wait_for: str) -> None:
        """Load an app page and wait until ``wait_for`` is on screen."""
        self.page.goto(self.base + path)
        self.page.wait_for_selector(wait_for, timeout=90_000)
        self.pause(2.0)
        self.cursor()

    def card(self, body: str) -> None:
        """Show a full-screen title card in the design-system look."""
        self.page.set_content(
            f"<html><head><style>{CARD_CSS}</style></head><body>{body}</body></html>"
        )
        self.page.wait_for_timeout(1500)  # web fonts
        self.cursor()

    def show(self, loc: Any, settle: float = 0.8) -> None:
        """Scroll the element into the middle of the screen, smoothly."""
        loc.first.evaluate("e => e.scrollIntoView({behavior: 'smooth', block: 'center'})")
        self.pause(settle)

    def glide(self, loc: Any, pause: float = 0.6) -> tuple[float, float]:
        """Move the cursor slowly onto ``loc`` and rest there."""
        self.show(loc)
        box = loc.first.bounding_box()
        assert box, "element not visible"
        x, y = box["x"] + min(box["width"] / 2, 60), box["y"] + box["height"] / 2
        self.cursor()
        self.page.evaluate(f"window.__msMove({x}, {y})")
        self.pause(1.15 + pause)
        return x, y

    def click(self, loc: Any, after: float = 2.0) -> None:
        """Glide to ``loc``, show a click ripple, click, then hold."""
        x, y = self.glide(loc)
        self.page.evaluate(f"window.__msRipple({x}, {y})")
        loc.first.click()
        self.pause(after)
        self.cursor()

    def top_nav(self, name: str) -> None:
        """Open a page from the top bar."""
        self.click(self.page.locator(".st-key-top_nav").get_by_role("radio", name=name), 3)

    def tab(self, name: str) -> None:
        """Open a tab by its label."""
        self.click(self.page.get_by_role("tab", name=name), 2.5)

    def select(self, label: str, option: str) -> None:
        """Open the selectbox labelled ``label`` and pick ``option``."""
        box = self.page.locator("[data-testid='stSelectbox']").filter(has_text=label).first
        self.click(box.get_by_role("button", name="Open"), 1.0)
        self.click(self.page.get_by_role("option", name=option, exact=True), 2)

    def scroll_main(self, dy: int, settle: float = 2.0) -> None:
        """Scroll the page body smoothly by ``dy`` pixels."""
        self.page.locator("[data-testid='stMain']").evaluate(
            f"e => e.scrollBy({{top: {dy}, behavior: 'smooth'}})"
        )
        self.pause(settle)


def beats(live_url: str, repo_url: str) -> list[Beat]:
    """The 3-minute cut (video script v4), in order, with what to say and how to drive each."""

    def title(d: Driver) -> None:
        d.card(
            '<div class="card"><div class="kicker">Meta Global AI Developer Hackathon · '
            "Solo Indie Dev · Build for Your World</div><h1>Maude<em>Signal</em></h1><p>A "
            "safety copilot for medical-device quality and regulatory teams, on public FDA "
            'data.</p><div class="rule"></div><p class="src">Triage aid · not medical advice · '
            "a named person makes every decision · nothing is filed with FDA</p></div>"
        )
        d.pause(6)

    def stat(d: Driver) -> None:
        d.card(
            '<div class="card"><div class="kicker">The problem</div>'
            '<div class="fig">2,000,000+</div><h2>device reports reach FDA every year. '
            "FDA's list of AI-enabled devices has 1,614 entries.</h2><p>MAUDE has no field "
            "for an AI failure. For one AI product code alone (LLZ) there are 19,970 reports, "
            '99.3% filed by the manufacturers themselves.</p><div class="rule"></div><p '
            'class="src">Sources: FDA / openFDA; FDA AI-Enabled Medical Device List, read 29 '
            "Oct 2026 (docs/hackathon/AI_SWEEP.md); openFDA report-source counts, 28 Oct 2026 "
            "(docs/hackathon/SOURCE_COUNTS.md)"
            "</p></div>"
        )
        d.pause(11)

    def signals(d: Driver) -> None:
        p = d.page
        d.open("/?theme=light&tools=demo", ".st-key-ms_siglist")
        d.click(p.get_by_text("Across FDA's AI device list", exact=False), 2)
        d.glide(p.locator("[data-testid='stExpander'] [data-testid='stDataFrame']").first, 3)
        d.glide(p.locator(".ms-sig-head"), 1.5)
        cards = p.locator(".st-key-ms_siglist label[data-testid='stRadioOption']")
        d.click(cards.filter(has_text="MYN"), 2)
        d.click(p.get_by_role("radio", name="Not filed by a manufacturer"), 3)

    def voice(d: Driver) -> None:
        p = d.page
        d.top_nav("Copilot")
        items = p.locator(".st-key-ms_qlist label[data-testid='stRadioOption']")
        d.click(items.filter(has_text=re.compile(r"last week\. Confirm")), 3.5)
        d.glide(p.get_by_text("Heard:"), 1)
        d.glide(p.get_by_text("That claim is not correct", exact=False), 3)

    def repair(d: Driver) -> None:
        p = d.page
        items = p.locator(".st-key-ms_qlist label[data-testid='stRadioOption']")
        d.click(items.filter(has_text="that we must open"), 3.5)
        d.glide(p.get_by_text("after a repair turn", exact=False), 2)
        d.click(p.get_by_text("What the gate blocked on the first pass"), 2.5)
        d.glide(p.get_by_text("all malfunction", exact=False).first, 4)

    def gate(d: Driver) -> None:
        p = d.page
        d.page.locator("[data-testid='stMain']").evaluate("e => e.scrollTo({top: 0})")
        d.tab("Try to fool the gate")
        d.select("Claim type", "CFR section")
        d.glide(p.get_by_text("superseded by QMSR"), 4)

    def vision(d: Driver) -> None:
        p = d.page
        d.top_nav("Vision")
        d.glide(p.get_by_text("TWO-READ AGREEMENT", exact=False), 1.5)
        d.tab("Device label camera")
        d.show(p.get_by_text("label-thermometer-1.jpg"), 2)
        d.glide(p.get_by_text("Signals for product code FLL").first, 3)

    def evidence(d: Driver) -> None:
        p = d.page
        d.top_nav("Signals")
        d.tab("Evidence pack")
        d.pause(1)
        d.glide(p.get_by_text("Independent reviewer", exact=False), 1)
        d.top_nav("Audit")
        d.glide(p.get_by_text("Hash chain intact", exact=False), 2)

    def close(d: Driver) -> None:
        d.card(
            '<div class="card"><div class="kicker">Built this week on four Meta models</div>'
            "<h2>It shows you which of its own sentences it refused to say, and why.</h2>"
            "<p>Muse Spark · Muse Wonder · Voice Transcribe · SAM 3.1, on the open-source "
            'MaudeSignal pipeline.</p><div class="rule"></div>'
            f'<p class="src">Live demo: {html.escape(live_url)}<br>'
            f"Code: {html.escape(repo_url)}</p></div>"
        )
        d.pause(7)

    return [
        Beat(
            "Title",
            "I'm Charan. MaudeSignal helps medical-device safety teams watch FDA data. "
            "Not medical advice: a person makes every decision.",
            title,
        ),
        Beat(
            "Problem",
            "FDA gets over two million device reports a year, and its list of AI devices has "
            "1,614 entries. MAUDE has no field for an AI failure.",
            stat,
        ),
        Beat(
            "Signals",
            "Monday morning. Across all 181 AI device types on FDA's list, 6 were flagged in "
            "openFDA's latest week. For the types I chose, LLZ reports suddenly increased: 33 "
            "against a normal 9. And here are the reports the manufacturer didn't file.",
            signals,
        ),
        Beat(
            "Voice",
            "I can just ask. Meta's Voice Transcribe hears the question; Muse Spark calls "
            "tools over the stored FDA records. A colleague's claim of 50 injuries? The "
            "records say otherwise.",
            voice,
        ),
        Beat(
            "Repair",
            "Every sentence passes a gate that recomputes each number from the records. Here "
            "Spark itself said something the records didn't support. The gate withheld it and "
            "showed why; Spark got one repair turn, and anything still unmatched stays struck "
            "out.",
            repair,
        ),
        Beat(
            "Gate",
            "You can try to fool it yourself: cite 21 CFR 820.100, and it's blocked, because "
            "QMSR replaced it this February.",
            gate,
        ),
        Beat(
            "Vision",
            "Muse Spark reads scanned 510(k) summaries twice and compares the reads. Point a "
            "camera at a device label: SAM finds it, Spark reads it, and you land on that "
            "device's signals. Anything unclear goes to a person.",
            vision,
        ),
        Beat(
            "Evidence pack",
            "It drafts a CAPA-need evidence pack, Muse Wonder reviews it independently, and "
            "every step goes into an audit trail that shows if anything was changed.",
            evidence,
        ),
        Beat(
            "Close",
            "AI tools that summarize MAUDE already exist. MaudeSignal shows you which of its "
            "own sentences it refused to say, and why.",
            close,
        ),
    ]


def _ts(s: float) -> str:
    ms = int(round(s * 1000))
    return f"{ms // 3_600_000:02d}:{ms // 60_000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"


def _mmss(s: float) -> str:
    return f"{int(s) // 60}:{int(s) % 60:02d}"


def write_srt(bs: list[Beat], path: Path) -> None:
    """One subtitle per beat, split into two-line chunks shown in turn."""
    out, n = [], 1
    for b in bs:
        words = b.say.split()
        chunks, cur = [], []
        for w in words:
            cur.append(w)
            if len(" ".join(cur)) > 84:
                chunks.append(" ".join(cur))
                cur = []
        if cur:
            chunks.append(" ".join(cur))
        span = (b.end - b.start) / max(len(chunks), 1)
        for i, c in enumerate(chunks):
            a, z = b.start + i * span, b.start + (i + 1) * span - 0.1
            out.append(f"{n}\n{_ts(a)} --> {_ts(z)}\n{c}\n")
            n += 1
    path.write_text("\n".join(out), encoding="utf-8")


def write_script(bs: list[Beat], path: Path, total: float) -> None:
    """Markdown read-along script with each beat's start time."""
    lines = [
        "# Walkthrough voiceover (read along with walkthrough.mp4)",
        "",
        f"Length {_mmss(total)}. Each line starts when its screen appears; take your time —",
        "the video pauses on every screen. The voice clip in the Copilot beat is",
        'text-to-speech, so say "Voice Transcribe hears the question", not that a person asked.',
        "",
        "| Starts | Screen | Say |",
        "|---|---|---|",
    ]
    lines += [f"| {_mmss(b.start)} | {b.title} | {b.say} |" for b in bs]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    """Record, encode, caption."""
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--url", default="http://localhost:8501")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument(
        "--live-url", default="https://maudesignal-4vniqswm9ptaxqtf2iawox.streamlit.app"
    )
    ap.add_argument("--repo-url", default="github.com/kondapallysaicharan63-bot/maudesignal")
    args = ap.parse_args()
    from playwright.sync_api import sync_playwright

    out: Path = args.out
    out.mkdir(parents=True, exist_ok=True)
    raw = out / "raw"
    shutil.rmtree(raw, ignore_errors=True)
    bs = beats(args.live_url, args.repo_url)
    with sync_playwright() as p:
        browser = p.chromium.launch()
        ctx = browser.new_context(
            viewport={"width": W, "height": H},
            record_video_dir=str(raw),
            record_video_size={"width": W, "height": H},
        )
        page = ctx.new_page()
        t0 = time.monotonic()
        d = Driver(page, args.url.rstrip("/"))
        for b in bs:
            b.start = time.monotonic() - t0
            print(f"[walkthrough] {_mmss(b.start)} {b.title}", flush=True)
            b.act(d)
            b.end = time.monotonic() - t0
        page.wait_for_timeout(1500)
        total = time.monotonic() - t0
        video = page.video.path() if page.video else None
        ctx.close()
        browser.close()
    if not video:
        raise SystemExit("no video recorded")
    mp4 = out / "walkthrough.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-loglevel",
            "error",
            "-i",
            str(video),
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-crf",
            "20",
            "-movflags",
            "+faststart",
            str(mp4),
        ],
        check=True,
    )
    srt = out / "walkthrough.srt"
    write_srt(bs, srt)
    write_script(bs, out / "walkthrough-script.md", total)
    style = "FontName=DejaVu Sans,FontSize=11,PrimaryColour=&H00FFFFFF,BackColour=&H99000000,BorderStyle=3,Outline=4,MarginV=14"
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-loglevel",
            "error",
            "-i",
            str(mp4),
            "-vf",
            f"subtitles={srt}:force_style='{style}'",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-crf",
            "20",
            "-movflags",
            "+faststart",
            str(out / "walkthrough-captions.mp4"),
        ],
        check=True,
    )
    shutil.rmtree(raw, ignore_errors=True)
    print(f"[walkthrough] {_mmss(total)} → {mp4}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
