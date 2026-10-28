"""Render a dossier to HTML (Jinja2) and PDF (WeasyPrint).

HACKATHON-BUILT — Meta Global AI Developer Hackathon (Oct 26 – Nov 4, 2026).

Same stack as the pre-existing PSUR generator (``maudesignal.report``):
Jinja2 → HTML → WeasyPrint. Page furniture (document ID, revision, status
stamp, "Page X of Y", confidentiality line) lives in CSS ``@page`` margin
boxes so it repeats on every page.
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any
from urllib.parse import quote

from jinja2 import Environment, FileSystemLoader, select_autoescape

from maudesignal.dossier.model import (
    CONFIDENTIALITY_LINE,
    DRAFT_STAMP,
    MDR_STAMP,
    TBC,
    DossierData,
)
from maudesignal.monitor.deterioration import (
    SEVERITY_ESCALATION_PP,
    SPIKE_MIN_REPORTS,
    SPIKE_MULTIPLIER,
)
from maudesignal.monitor.digest import CHANGE_LABELS

TEMPLATE_DIR = Path(__file__).resolve().parent / "templates"
_ENV = Environment(
    loader=FileSystemLoader(str(TEMPLATE_DIR)),
    autoescape=select_autoescape(["html", "j2"]),
    trim_blocks=True,
    lstrip_blocks=True,
)
_ENV.globals["change_labels"] = CHANGE_LABELS

STATUS_LABELS = {
    "no-capa": "Draft — signal evaluation evidence only",
    "draft": "Draft — CAPA-need evidence awaiting QA/RA review",
    "approved": "Evidence accepted by reviewer (CAPA need decided on the company's form)",
    "rejected": "Evidence rejected by reviewer",
}


def _css(text: str) -> str:
    """Make text safe inside a CSS string literal in the <style> block."""
    return "".join(ch for ch in text if ch not in '"\\<>\n\r')


def _watermark(lines: list[str], color: str = "#b3261e", opacity: float = 0.09) -> str:
    """Diagonal watermark as an SVG data URI ('' for no lines)."""
    if not lines:
        return ""
    size = 110 if len(lines) == 1 else 54
    tspans = "".join(
        f"<tspan x='400' dy='{0 if i == 0 else size * 1.15:.0f}'>{line}</tspan>"
        for i, line in enumerate(lines)
    )
    svg = (
        "<svg xmlns='http://www.w3.org/2000/svg' width='800' height='1000' viewBox='0 0 800 1000'>"
        f"<text x='400' y='{500 - (len(lines) - 1) * size * 0.55:.0f}' text-anchor='middle' "
        f"font-family='Helvetica, Arial, sans-serif' font-weight='bold' font-size='{size}' "
        f"fill='{color}' fill-opacity='{opacity}' transform='rotate(-35 400 500)'>{tspans}</text>"
        "</svg>"
    )
    return "data:image/svg+xml," + quote(svg)


def _iso(yyyymmdd: str) -> str:
    s = str(yyyymmdd)
    return f"{s[:4]}-{s[4:6]}-{s[6:]}" if len(s) == 8 and s.isdigit() else s


def template_context(d: DossierData) -> dict[str, Any]:
    """Everything the template needs besides the data itself."""
    approved = d.status == "approved"
    cover_stamp = (
        "APPROVED" if approved else ("REJECTED" if d.status == "rejected" else DRAFT_STAMP)
    )
    css = {
        "doc_line": _css(f"{d.doc_id} · Rev {d.revision}"),
        "header_stamp": _css(d.header_stamp),
        "stamp_color": "#1e7b3a" if approved else "#b3261e",
        "cover_stamp": _css(cover_stamp),
        "cover_stamp_color": "#1e7b3a" if approved else "#b3261e",
        "confidentiality": _css(CONFIDENTIALITY_LINE),
        "mdr_stamp": _css(MDR_STAMP),
        "wm_default": _watermark([d.watermark] if d.watermark else []),
        # The approval page drops the DRAFT stamp once a named human approved.
        "wm_cover": "" if approved else _watermark([d.watermark] if d.watermark else []),
        "wm_mdr": _watermark(["DRAFT WORKSHEET", "NOT FOR SUBMISSION"], opacity=0.10),
    }
    return {
        "d": d,
        "css": css,
        "status_label": STATUS_LABELS.get(d.status, d.status),
        "rules": {
            "spike_multiplier": SPIKE_MULTIPLIER,
            "spike_min": SPIKE_MIN_REPORTS,
            "severity_pp": SEVERITY_ESCALATION_PP,
        },
        "TBC": TBC,
        "DRAFT_STAMP": DRAFT_STAMP,
        "MDR_STAMP": MDR_STAMP,
        "iso": _iso,
    }


def render_html(d: DossierData) -> str:
    """Render the dossier HTML."""
    return _ENV.get_template("dossier.html.j2").render(**template_context(d))


def render_pdf(html: str) -> bytes:
    """Render HTML to PDF bytes with WeasyPrint.

    Raises:
        RuntimeError: WeasyPrint (or its system libraries) is unavailable.
    """
    try:
        from weasyprint import HTML
    except (ImportError, OSError) as exc:  # pragma: no cover - environment dependent
        raise RuntimeError(f"WeasyPrint unavailable: {exc}") from exc
    pdf: bytes = HTML(string=html, base_url=str(TEMPLATE_DIR)).write_pdf()
    return pdf


def pdf_page_png(pdf: bytes, page: int = 1, dpi: int = 110) -> bytes | None:
    """Rasterize one PDF page to PNG with ``pdftoppm`` (poppler), or None if unavailable."""
    exe = shutil.which("pdftoppm")
    if exe is None:
        return None
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "in.pdf"
        src.write_bytes(pdf)
        out = Path(tmp) / "page"
        argv = [exe, "-png", "-r", str(dpi), "-f", str(page), "-l", str(page), "-singlefile"]
        try:
            subprocess.run(  # fixed argv, no shell
                [*argv, str(src), str(out)], check=True, capture_output=True, timeout=60
            )
        except (subprocess.SubprocessError, OSError):
            return None
        png = out.with_suffix(".png")
        return png.read_bytes() if png.is_file() else None
