"""FDA device names for product codes, from stored sources only.

HACKATHON-BUILT — Meta Global AI Developer Hackathon (Oct 26 – Nov 4, 2026).

Two kinds of name, kept apart on purpose:

* the **FDA device type** of a product code (its openFDA classification
  ``device_name``, e.g. LLZ → "System, Image Processing, Radiological"), and
* the **brand names written on the reports** themselves.

A 510(k) catalog row names one cleared device, not the whole product code, so
it is never used as the product code's name here. Nothing is guessed: a code
with no stored classification name simply has none.
"""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Iterable

from maudesignal.storage.database import Database

MANIFEST_NAME = "SEED_MANIFEST.json"


def classification_names(db: Database) -> dict[str, str]:
    """Return product_code → FDA classification device name, where one is stored.

    Sources: catalog rows written from the openFDA classification endpoint, and
    the seed manifest next to the demo database (its per-code queries carry the
    classification name).

    Args:
        db: The database.

    Returns:
        ``product_code -> device_name``.
    """
    names = {
        d.product_code: d.device_name
        for d in db.list_catalog_devices()
        if d.source_keyword == "openfda_classification" and d.device_name
    }
    manifest = db.path.parent / MANIFEST_NAME
    if manifest.is_file():
        try:
            queries = json.loads(manifest.read_text(encoding="utf-8")).get("queries", [])
        except (OSError, ValueError):
            queries = []
        for q in queries:
            if q.get("product_code") and q.get("device_name"):
                names.setdefault(q["product_code"], q["device_name"])
    return names


def report_brands(db: Database) -> dict[str, str]:
    """Return maude_report_id → the brand name written on that report (non-empty only).

    Args:
        db: The database.

    Returns:
        ``report_id -> brand_name``.
    """
    return {
        e.maude_report_id: e.brand_name.strip()
        for e in db.list_normalized_events()
        if e.brand_name and e.brand_name.strip()
    }


def brand_counts(
    report_ids: Iterable[str], brands: dict[str, str], limit: int = 3
) -> list[tuple[str, int]]:
    """Count the brand names on a set of reports, most frequent first.

    Brand spelling varies between reporters ("IntelliSpace Cardiovascular" vs
    "INTELLISPACE CARDIOVASCULAR"), so names are grouped case-insensitively and
    shown in their most common spelling.

    Args:
        report_ids: Reports to count.
        brands: Output of :func:`report_brands`.
        limit: Maximum brands returned.

    Returns:
        ``(brand, count)`` pairs; reports with no brand are not counted.
    """
    spellings: dict[str, Counter[str]] = {}
    for rid in report_ids:
        name = brands.get(rid)
        if name:
            spellings.setdefault(name.casefold(), Counter())[name] += 1
    grouped = [(c.most_common(1)[0][0], sum(c.values())) for c in spellings.values()]
    return sorted(grouped, key=lambda x: (-x[1], x[0]))[:limit]
