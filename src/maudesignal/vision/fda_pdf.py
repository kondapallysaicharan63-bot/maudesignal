"""Download, inspect and rasterize FDA 510(k) summary PDFs.

HACKATHON-BUILT — Meta Global AI Developer Hackathon (Oct 26 – Nov 4, 2026).

510(k) summaries are public PDFs at
``https://www.accessdata.fda.gov/cdrh_docs/pdf{YY}/K{NNNNNN}.pdf`` (the server may
redirect). Many older ones are scanned paper with no text layer, which is exactly
why they are read as images.

Rasterizing uses poppler's ``pdftoppm`` / ``pdftotext`` / ``pdfinfo`` command-line
tools (``apt install poppler-utils``; ``packages.txt`` installs them on Streamlit
Community Cloud). No Python PDF library is required.

Pages are rasterized locally and sent as images (Chat Completions). Meta's own
PDF input converts a PDF to text plus page images (https://dev.meta.ai/docs/file-handling),
which would hand the model the text layer; sending only images keeps the
text-layer check (``verify.py``) independent of the read.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

import httpx

from maudesignal.common.exceptions import MaudeSignalError

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_CACHE_DIR = PROJECT_ROOT / "data" / "demo" / "510k"
FDA_PDF_URL = "https://www.accessdata.fda.gov/cdrh_docs/{folder}/{k}.pdf"
MAX_PDF_BYTES = 40_000_000
DEFAULT_MAX_PAGES = 8
DEFAULT_DPI = 150
MIN_TEXT_CHARS_PER_PAGE = 80  # alphanumerics on a page before it counts as "has text"

_K_RE = re.compile(r"^K\d{6}$")
_K_FIND = re.compile(r"\bK\s?(\d{6})\b", re.IGNORECASE)


class FdaPdfError(MaudeSignalError):
    """The PDF could not be downloaded, read or rasterized."""


class RasterizerUnavailableError(FdaPdfError):
    """poppler-utils (``pdftoppm``) is not installed."""


def normalize_k_number(value: str) -> str:
    """Return ``K`` + 6 digits, or raise.

    Raises:
        ValueError: Not a 510(k) number.
    """
    k = re.sub(r"[\s\-]", "", value or "").upper()
    if not _K_RE.match(k):
        raise ValueError(f"not a 510(k) number: {value!r}")
    return k


def is_k_number(value: str) -> bool:
    """True when ``value`` normalizes to ``K`` + 6 digits."""
    try:
        normalize_k_number(value)
    except ValueError:
        return False
    return True


def find_k_numbers(text: str) -> list[str]:
    """All ``K######`` tokens in free text, normalized, in order, de-duplicated."""
    seen: list[str] = []
    for m in _K_FIND.finditer(text or ""):
        k = "K" + m.group(1)
        if k not in seen:
            seen.append(k)
    return seen


def pdf_folder(k_number: str) -> str:
    """FDA folder for a K-number: ``pdf{YY}`` from the 2-digit year (``pdf3`` = 2003).

    Submissions from 2001 and earlier live under plain ``pdf/`` (UNVERIFIED for
    every year; the demo uses 2002+ numbers).
    """
    yy = int(normalize_k_number(k_number)[1:3])
    return "pdf" if yy >= 76 or yy <= 1 else f"pdf{yy}"


def pdf_url(k_number: str) -> str:
    """Public URL of a 510(k) summary / statement PDF."""
    k = normalize_k_number(k_number)
    return FDA_PDF_URL.format(folder=pdf_folder(k), k=k)


def download_510k_pdf(
    k_number: str,
    cache_dir: Path = DEFAULT_CACHE_DIR,
    *,
    transport: httpx.BaseTransport | None = None,
    timeout_s: float = 60.0,
) -> Path:
    """Return the cached PDF path, downloading it on a cache miss.

    Args:
        k_number: 510(k) number.
        cache_dir: Cache folder (``data/demo/510k`` by default; the demo PDFs are committed there).
        transport: Injected HTTP transport (tests).
        timeout_s: Request timeout.

    Raises:
        FdaPdfError: HTTP error, a non-PDF answer (e.g. FDA's bot-protection
            "apology" page), or an oversized file.
    """
    k = normalize_k_number(k_number)
    path = cache_dir / f"{k}.pdf"
    if path.is_file() and path.read_bytes()[:5] == b"%PDF-":
        return path
    url = pdf_url(k)
    try:
        with httpx.Client(follow_redirects=True, timeout=timeout_s, transport=transport) as client:
            resp = client.get(url)
    except httpx.HTTPError as exc:
        raise FdaPdfError(f"download of {k} failed ({type(exc).__name__})") from exc
    final = str(resp.url)
    if "apology" in final:
        raise FdaPdfError(
            f"FDA served its access-denied page instead of {k}.pdf (automated-traffic "
            f"protection). Download {url} in a browser and save it as {path}."
        )
    if resp.status_code != 200:
        raise FdaPdfError(f"{url} returned HTTP {resp.status_code}")
    data = resp.content
    if data[:5] != b"%PDF-":
        raise FdaPdfError(f"{url} did not return a PDF")
    if len(data) > MAX_PDF_BYTES:
        raise FdaPdfError(f"{k}.pdf is {len(data) / 1e6:.1f} MB (limit {MAX_PDF_BYTES / 1e6} MB)")
    cache_dir.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".part")
    tmp.write_bytes(data)
    tmp.replace(path)
    return path


def _tool(name: str) -> str:
    exe = shutil.which(name)
    if exe is None:
        raise RasterizerUnavailableError(
            f"{name} not found; install poppler-utils (apt install poppler-utils)"
        )
    return exe


def _run(args: list[str], timeout_s: float = 120.0) -> subprocess.CompletedProcess[bytes]:
    try:
        return subprocess.run(args, capture_output=True, timeout=timeout_s, check=True)
    except subprocess.CalledProcessError as exc:
        msg = exc.stderr.decode("utf-8", "replace").strip()[:200]
        raise FdaPdfError(f"{Path(args[0]).name} failed: {msg}") from exc
    except subprocess.TimeoutExpired as exc:
        raise FdaPdfError(f"{Path(args[0]).name} timed out") from exc


def page_count(pdf: Path) -> int:
    """Number of pages (``pdfinfo``)."""
    out = _run([_tool("pdfinfo"), str(pdf)]).stdout.decode("utf-8", "replace")
    m = re.search(r"^Pages:\s+(\d+)", out, re.MULTILINE)
    if not m:
        raise FdaPdfError("pdfinfo did not report a page count")
    return int(m.group(1))


def extract_text_pages(pdf: Path, max_pages: int = DEFAULT_MAX_PAGES) -> list[str]:
    """Text layer of the first ``max_pages`` pages (empty strings for image-only pages)."""
    n = min(max_pages, page_count(pdf))
    out = _run([_tool("pdftotext"), "-layout", "-f", "1", "-l", str(n), str(pdf), "-"]).stdout
    pages = out.decode("utf-8", "replace").split("\f")
    pages = (pages + [""] * n)[:n]
    return pages


def page_has_text(text: str) -> bool:
    """A page has a usable text layer when it carries enough alphanumerics."""
    return sum(ch.isalnum() for ch in text) >= MIN_TEXT_CHARS_PER_PAGE


def has_text_layer(text_pages: list[str]) -> bool:
    """True when at least half of the pages read have a usable text layer."""
    if not text_pages:
        return False
    with_text = sum(page_has_text(t) for t in text_pages)
    return with_text * 2 >= len(text_pages)


@dataclass(frozen=True)
class PageImage:
    """One rasterized page."""

    page: int  # 1-based source page number
    png: bytes
    width: int
    height: int


def rasterize(
    pdf: Path, *, max_pages: int = DEFAULT_MAX_PAGES, dpi: int = DEFAULT_DPI
) -> list[PageImage]:
    """Render the first ``max_pages`` pages to PNG with ``pdftoppm``."""
    from PIL import Image  # local: keeps module import light for the dashboard

    n = min(max_pages, page_count(pdf))
    exe = _tool("pdftoppm")
    pages: list[PageImage] = []
    with tempfile.TemporaryDirectory() as tmp:
        prefix = Path(tmp) / "p"
        _run([exe, "-r", str(dpi), "-f", "1", "-l", str(n), "-png", str(pdf), str(prefix)])
        files = sorted(Path(tmp).glob("p-*.png"), key=lambda p: int(p.stem.rsplit("-", 1)[1]))
        for f in files:
            data = f.read_bytes()
            with Image.open(f) as im:
                w, h = im.size
            pages.append(PageImage(int(f.stem.rsplit("-", 1)[1]), data, w, h))
    if not pages:
        raise FdaPdfError("pdftoppm produced no pages")
    return pages


@dataclass
class SummaryDocument:
    """A 510(k) summary prepared for reading."""

    k_number: str
    pdf_path: Path
    url: str
    page_count: int
    pages: list[PageImage]
    text_pages: list[str] = field(default_factory=list)

    @property
    def has_text_layer(self) -> bool:
        """Whether the pages read carry a usable text layer."""
        return has_text_layer(self.text_pages)

    @property
    def text_layer_pages(self) -> list[int]:
        """Source pages that carry a usable text layer."""
        return [i + 1 for i, t in enumerate(self.text_pages) if page_has_text(t)]


def load_summary(
    k_number: str,
    cache_dir: Path = DEFAULT_CACHE_DIR,
    *,
    max_pages: int = DEFAULT_MAX_PAGES,
    dpi: int = DEFAULT_DPI,
    transport: httpx.BaseTransport | None = None,
) -> SummaryDocument:
    """Download (or reuse the cache), rasterize and extract the text layer."""
    k = normalize_k_number(k_number)
    pdf = download_510k_pdf(k, cache_dir, transport=transport)
    return SummaryDocument(
        k_number=k,
        pdf_path=pdf,
        url=pdf_url(k),
        page_count=page_count(pdf),
        pages=rasterize(pdf, max_pages=max_pages, dpi=dpi),
        text_pages=extract_text_pages(pdf, max_pages),
    )
