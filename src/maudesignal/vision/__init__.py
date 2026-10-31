"""Meta vision features: 510(k) summary reader (F6) and device-label camera (F7).

HACKATHON-BUILT — Meta Global AI Developer Hackathon (Oct 26 – Nov 4, 2026).

* :mod:`maudesignal.vision.fda_pdf` — download / rasterize / text-layer of 510(k) PDFs
* :mod:`maudesignal.vision.reader` — Muse Spark reads page images (strict JSON)
* :mod:`maudesignal.vision.verify` — two-read agreement + openFDA + text-layer checks
* :mod:`maudesignal.vision.sam` — SAM 3.1 segmentation client and output parser
* :mod:`maudesignal.vision.label` — label photo → SAM crop → Spark read → openFDA
* :mod:`maudesignal.vision.label_match` — label reading → up to 3 possible openFDA matches →
  device-type view (a person confirms; every fact gated)
"""

from __future__ import annotations

# Real 510(k) summaries used for the recorded demo (one or more per demo product code).
# The 2003-2004 LLZ summaries are expected to be scanned paper; the recording script
# measures and records whether each PDF actually has a text layer.
DEMO_K_NUMBERS: tuple[tuple[str, str], ...] = (
    ("K031779", "LLZ"),  # CADSTREAM, Confirma, Inc. (2003)
    ("K043333", "LLZ"),  # VITREA2 3.7, Vital Images, Inc. (2004)
    ("K261677", "QIH"),  # AIRA v1, Aramis Global AI Consultancies (2026) — in the demo catalog
    ("K210666", "MYN"),  # Chest-CAD, Imagen Technologies (2021)
    ("K190442", "POK"),  # Koios DS for Breast, Koios Medical (2019)
)

__all__ = ["DEMO_K_NUMBERS", "LABEL_MATCH_SCHEMA_VERSION"]

#: Schema of ``demo/vision/label-match-*.json`` (see ``vision/label_match.py``).
LABEL_MATCH_SCHEMA_VERSION = "1.0"
