"""Signal Evaluation & CAPA dossier (PDF) and its independent AI reviewer.

HACKATHON-BUILT — Meta Global AI Developer Hackathon (Oct 26 – Nov 4, 2026).

* :mod:`~maudesignal.dossier.builder` — deterministic assembly from stored records.
* :mod:`~maudesignal.dossier.render` — Jinja2 → HTML → WeasyPrint PDF.
* :mod:`~maudesignal.dossier.figures` — every printed number tagged with a re-verifiable claim.
* :mod:`~maudesignal.dossier.narrative` — Muse Spark narrative behind the claim-level gate.
* :mod:`~maudesignal.dossier.review` — Muse Wonder independent reviewer (findings only).
* :mod:`~maudesignal.dossier.illustration` — optional Muse Image cover (off by default).
"""

from maudesignal.dossier.builder import DossierBuild, DossierError, build_dossier
from maudesignal.dossier.figures import verify_html
from maudesignal.dossier.render import pdf_page_png, render_html, render_pdf

__all__ = [
    "DossierBuild",
    "DossierError",
    "build_dossier",
    "pdf_page_png",
    "render_html",
    "render_pdf",
    "verify_html",
]
