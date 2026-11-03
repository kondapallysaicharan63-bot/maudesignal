"""A tiny text-only PDF writer (Helvetica, A4/Letter, wrapped lines, page numbers).

HACKATHON-BUILT — Meta Global AI Developer Hackathon (Oct 26 – Nov 4, 2026), 2026-11-03.

Used for the note-to-file and evidence-pack exports so they render without WeasyPrint
(which the Vercel function does not ship). The web app has the same writer in
``web/src/pms/pdf.ts``. Only the 14 standard fonts are used, so nothing is embedded;
text outside Latin-1 is replaced with ``?``.
"""

from __future__ import annotations

import textwrap

PAGE_W, PAGE_H = 612, 792  # US Letter, points
MARGIN = 54
BODY_SIZE = 10
LEADING = 13
WRAP = 95


def _esc(s: str) -> str:
    s = s.encode("latin-1", "replace").decode("latin-1")
    return s.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def _lines(paragraphs: list[tuple[str, str]]) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for style, text in paragraphs:
        if not text:
            out.append(("body", ""))
            continue
        width = 70 if style == "h1" else 85 if style == "h2" else WRAP
        for raw in text.split("\n"):
            wrapped = textwrap.wrap(raw, width=width, break_long_words=True) or [""]
            out.extend((style, w) for w in wrapped)
    return out


def render_pdf(title: str, paragraphs: list[tuple[str, str]], footer: str) -> bytes:
    """Render paragraphs to PDF bytes.

    Args:
        title: Document title (PDF metadata).
        paragraphs: ``(style, text)`` with style ``h1`` / ``h2`` / ``body`` / ``mono``.
        footer: Printed at the bottom of every page with "Page X of Y".

    Returns:
        A complete PDF file.
    """
    sizes = {"h1": 16, "h2": 12, "body": BODY_SIZE, "mono": 9}
    fonts = {"h1": "F2", "h2": "F2", "body": "F1", "mono": "F3"}
    lines = _lines(paragraphs)
    per_page = (PAGE_H - 2 * MARGIN - 20) // LEADING
    pages = [lines[i : i + per_page] for i in range(0, len(lines), per_page)] or [[]]
    objs: list[bytes] = []

    def add(b: str | bytes) -> int:
        objs.append(b.encode("latin-1") if isinstance(b, str) else b)
        return len(objs)

    add("<< /Type /Catalog /Pages 2 0 R >>")
    add("PAGES")  # placeholder
    add("<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>")
    add("<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>")
    add("<< /Type /Font /Subtype /Type1 /BaseFont /Courier /Encoding /WinAnsiEncoding >>")
    kids: list[int] = []
    for n, page in enumerate(pages, start=1):
        y = PAGE_H - MARGIN
        ops = ["BT"]
        for style, text in page:
            ops.append(
                f"/{fonts[style]} {sizes[style]} Tf 1 0 0 1 {MARGIN} {y} Tm ({_esc(text)}) Tj"
            )
            y -= LEADING + (4 if style == "h1" else 0)
        ops.append(
            f"/F1 8 Tf 1 0 0 1 {MARGIN} {MARGIN - 20} Tm "
            f"({_esc(f'{footer} | Page {n} of {len(pages)}')}) Tj"
        )
        ops.append("ET")
        stream = "\n".join(ops).encode("latin-1")
        content = add(b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream")
        kids.append(
            add(
                f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {PAGE_W} {PAGE_H}] "
                f"/Resources << /Font << /F1 3 0 R /F2 4 0 R /F3 5 0 R >> >> "
                f"/Contents {content} 0 R >>"
            )
        )
    objs[1] = (
        f"<< /Type /Pages /Kids [{' '.join(f'{k} 0 R' for k in kids)}] /Count {len(kids)} >>"
    ).encode("latin-1")
    info = add(f"<< /Title ({_esc(title)}) /Producer (MaudeSignal simple_pdf) >>")
    out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = []
    for i, body in enumerate(objs, start=1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode() + body + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode()
    for off in offsets:
        out += f"{off:010d} 00000 n \n".encode()
    out += (
        f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R /Info {info} 0 R >>\n"
        f"startxref\n{xref}\n%%EOF\n"
    ).encode()
    return bytes(out)


def pdf_text(pdf: bytes) -> str:
    """All text shown with ``Tj`` in a PDF made by :func:`render_pdf` (for tests)."""
    import re

    parts = re.findall(rb"\((.*?)(?<!\\)\) Tj", pdf, flags=re.S)
    return "\n".join(
        p.decode("latin-1").replace("\\(", "(").replace("\\)", ")").replace("\\\\", "\\")
        for p in parts
    )
