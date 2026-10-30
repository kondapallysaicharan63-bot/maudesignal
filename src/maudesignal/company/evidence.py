"""Real FDA evidence for one product code, from the demo database or a fetched file.

Two sources, both real openFDA data, neither holding any company data:

* ``demo_db``: the committed demo database (``data/demo/maudesignal_demo.db``) for the
  codes it holds (LLZ, QIH, MYN, POK). It is opened read-only (SQLite ``mode=ro``).
* ``fetched``: ``demo/company/evidence/<code>.json`` written by
  ``scripts/fetch_company_evidence.py`` (last 8 weeks of reports and the latest recalls).

A code with neither is ``missing``: the page says "evidence not fetched yet" and shows
no count, pattern or quote for it.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from maudesignal.company.constants import (
    CLASSIFICATION_ENDPOINT,
    RECALL_ENDPOINT,
    company_dir,
    demo_db_path,
)
from maudesignal.gate import EvidenceRecord, EvidenceStore, RecallRef

ORIGIN_DEMO_DB = "demo_db"
ORIGIN_FETCHED = "fetched"
ORIGIN_MISSING = "missing"

SEED_MANIFEST = Path("data") / "demo" / "SEED_MANIFEST.json"


@dataclass(frozen=True)
class EvidenceReport:
    """One stored MAUDE report with the fields the pattern rules read."""

    report_id: str
    product_code: str
    event_type: str | None
    date_received: str | None  # YYYYMMDD
    report_source: str | None
    brand_name: str | None
    manufacturer: str | None
    product_problems: tuple[str, ...]
    text: str  # narrative + manufacturer narrative, as openFDA returned them


@dataclass(frozen=True)
class EvidenceRecall:
    """One stored openFDA device recall row."""

    recall_number: str
    product_code: str
    recalling_firm: str | None
    product_description: str
    reason_for_recall: str
    recall_status: str | None
    date_initiated: str | None  # YYYYMMDD
    event_number: str | None = None
    cfres_id: str | None = None

    @property
    def url(self) -> str | None:
        """Public FDA recall page."""
        if not self.cfres_id:
            return None
        return (
            f"https://www.accessdata.fda.gov/scripts/cdrh/cfdocs/cfRES/res.cfm?id={self.cfres_id}"
        )


@dataclass(frozen=True)
class CodeEvidence:
    """Everything stored about one product code."""

    product_code: str
    origin: str
    reports: tuple[EvidenceReport, ...] = ()
    recalls: tuple[EvidenceRecall, ...] = ()
    recalls_matched_total: int | None = None
    window_from: str | None = None
    window_to: str | None = None
    queries: tuple[tuple[str, str], ...] = ()
    classification_name: str | None = None
    classification_query_url: str | None = None
    classification_source: str | None = None
    fetched_utc: str | None = None
    notes: tuple[str, ...] = field(default_factory=tuple)

    @property
    def available(self) -> bool:
        """True when stored evidence exists for this code."""
        return self.origin != ORIGIN_MISSING

    def store(self) -> EvidenceStore:
        """Gate evidence store over these reports and recalls."""
        records = [
            EvidenceRecord(
                report_id=r.report_id,
                product_code=r.product_code,
                event_type=r.event_type,
                date_received=r.date_received,
                text=r.text,
                manufacturer=r.manufacturer,
                brand_name=r.brand_name,
                report_source=r.report_source,
            )
            for r in self.reports
        ]
        recalls = [
            RecallRef(
                recall_number=c.recall_number,
                product_code=c.product_code,
                event_number=c.event_number,
                recalling_firm=c.recalling_firm,
                product_description=c.product_description,
                reason_for_recall=c.reason_for_recall,
                recall_status=c.recall_status,
                date_initiated=c.date_initiated,
            )
            for c in self.recalls
        ]
        return EvidenceStore.from_iterables(records, recalls=recalls)


def classification_url(product_code: str) -> str:
    """The openFDA classification query that names a product code's device type."""
    return f"{CLASSIFICATION_ENDPOINT}?search=product_code:{product_code}"


def recall_query_url(product_code: str) -> str:
    """The openFDA recall query behind a code's stored recalls."""
    return f"{RECALL_ENDPOINT}?search=product_code:{product_code}"


def _ymd(iso: str | None) -> str | None:
    return iso.replace("-", "") if iso else None


def missing(product_code: str, note: str = "evidence not fetched yet") -> CodeEvidence:
    """Placeholder for a code with no stored evidence."""
    return CodeEvidence(product_code=product_code, origin=ORIGIN_MISSING, notes=(note,))


# ── demo database (read-only) ────────────────────────────────────────────────


def _connect_readonly(path: Path) -> sqlite3.Connection:
    return sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)


def demo_db_codes(db_path: Path | None = None) -> set[str]:
    """Product codes that have MAUDE reports in the demo database."""
    path = db_path or demo_db_path()
    if not path.is_file():
        return set()
    con = _connect_readonly(path)
    try:
        return {r[0] for r in con.execute("SELECT DISTINCT product_code FROM raw_reports")}
    finally:
        con.close()


def _manifest_queries(product_code: str, root: Path) -> tuple[tuple[str, str], ...]:
    manifest = root / SEED_MANIFEST
    if not manifest.is_file():
        return ()
    doc = json.loads(manifest.read_text(encoding="utf-8"))
    for q in doc.get("queries", []):
        if q.get("product_code") == product_code and q.get("example_url"):
            return (("openFDA MAUDE query that filled the demo database", str(q["example_url"])),)
    return ()


def load_demo_db_evidence(
    product_code: str, db_path: Path | None = None, root: Path | None = None
) -> CodeEvidence:
    """Read one code's stored reports and recalls from the demo database, read-only."""
    from maudesignal.company.constants import PROJECT_ROOT

    path = db_path or demo_db_path()
    if not path.is_file():
        return missing(product_code, "demo database not found")
    con = _connect_readonly(path)
    try:
        rows = con.execute(
            "SELECT e.maude_report_id, e.event_type, r.date_received, e.report_source, "
            "e.brand_name, e.manufacturer, e.narrative, e.mfr_narrative, r.raw_json "
            "FROM normalized_events e JOIN raw_reports r "
            "ON r.maude_report_id = e.maude_report_id "
            "WHERE e.product_code = ? ORDER BY e.maude_report_id",
            (product_code,),
        ).fetchall()
        if not rows:
            return missing(product_code, "no stored reports for this product code")
        reports = []
        name_from_report: str | None = None
        for rid, etype, drec, src, brand, mfr, narr, mnarr, raw in rows:
            doc = json.loads(raw)
            problems = tuple(str(p) for p in doc.get("product_problems") or [])
            if name_from_report is None:
                dev = (doc.get("device") or [{}])[0]
                name_from_report = (dev.get("openfda") or {}).get("device_name")
            reports.append(
                EvidenceReport(
                    report_id=str(rid),
                    product_code=product_code,
                    event_type=etype,
                    date_received=drec,
                    report_source=src,
                    brand_name=brand,
                    manufacturer=mfr,
                    product_problems=problems,
                    text=" ".join(t for t in (narr, mnarr) if t),
                )
            )
        recalls = []
        for sid, raw in con.execute(
            "SELECT source_id, raw_json FROM external_sources "
            "WHERE source_type = 'fda_recall' AND product_code = ? ORDER BY source_id",
            (product_code,),
        ):
            d: dict[str, Any] = json.loads(raw)
            recalls.append(
                EvidenceRecall(
                    recall_number=str(d.get("product_res_number") or sid),
                    product_code=product_code,
                    recalling_firm=d.get("recalling_firm"),
                    product_description=str(d.get("product_description") or ""),
                    reason_for_recall=str(d.get("reason_for_recall") or ""),
                    recall_status=d.get("recall_status"),
                    date_initiated=_ymd(d.get("event_date_initiated")),
                    event_number=d.get("res_event_number"),
                    cfres_id=d.get("cfres_id"),
                )
            )
        cat = con.execute(
            "SELECT device_name FROM device_catalog "
            "WHERE product_code = ? AND source_keyword = 'openfda_classification'",
            (product_code,),
        ).fetchone()
    finally:
        con.close()
    if cat and cat[0]:
        cname, csource = str(cat[0]), "openFDA device classification (stored in the demo database)"
    elif name_from_report:
        cname = str(name_from_report)
        csource = "device.openfda.device_name of a stored MAUDE report"
    else:
        cname, csource = None, None
    dates = sorted(r.date_received for r in reports if r.date_received)
    queries = _manifest_queries(product_code, root or PROJECT_ROOT)
    if recalls:
        queries = (*queries, ("openFDA recall query", recall_query_url(product_code)))
    return CodeEvidence(
        product_code=product_code,
        origin=ORIGIN_DEMO_DB,
        reports=tuple(reports),
        recalls=tuple(sorted(recalls, key=lambda c: c.date_initiated or "", reverse=True)),
        recalls_matched_total=None,  # demo DB holds a stored subset; no openFDA match total
        window_from=dates[0] if dates else None,
        window_to=dates[-1] if dates else None,
        queries=queries,
        classification_name=cname,
        classification_query_url=classification_url(product_code),
        classification_source=csource,
    )


# ── fetched file ─────────────────────────────────────────────────────────────


def evidence_path(product_code: str, folder: Path | None = None) -> Path:
    """Where ``scripts/fetch_company_evidence.py`` stores one code."""
    return (folder or company_dir() / "evidence") / f"{product_code}.json"


def load_fetched_evidence(product_code: str, folder: Path | None = None) -> CodeEvidence:
    """Read ``demo/company/evidence/<code>.json`` (or report that it is not there yet)."""
    path = evidence_path(product_code, folder)
    if not path.is_file():
        return missing(product_code)
    doc = json.loads(path.read_text(encoding="utf-8"))
    rep = doc.get("reports", {})
    rec = doc.get("recalls", {})
    cls = doc.get("classification") or {}
    reports = tuple(
        EvidenceReport(
            report_id=str(r["report_id"]),
            product_code=product_code,
            event_type=r.get("event_type"),
            date_received=r.get("date_received"),
            report_source=r.get("report_source"),
            brand_name=r.get("brand_name"),
            manufacturer=r.get("manufacturer"),
            product_problems=tuple(str(p) for p in r.get("product_problems") or []),
            text=str(r.get("text") or ""),
        )
        for r in rep.get("records", [])
    )
    recalls = tuple(
        EvidenceRecall(
            recall_number=str(c["recall_number"]),
            product_code=product_code,
            recalling_firm=c.get("recalling_firm"),
            product_description=str(c.get("product_description") or ""),
            reason_for_recall=str(c.get("reason_for_recall") or ""),
            recall_status=c.get("recall_status"),
            date_initiated=c.get("date_initiated"),
            event_number=c.get("event_number"),
            cfres_id=c.get("cfres_id"),
        )
        for c in rec.get("records", [])
    )
    window = doc.get("window") or {}
    queries = []
    if rep.get("query_url"):
        queries.append(("openFDA MAUDE query (last 8 weeks, limit 100)", str(rep["query_url"])))
    if rec.get("query_url"):
        queries.append(("openFDA recall query (latest 100)", str(rec["query_url"])))
    return CodeEvidence(
        product_code=product_code,
        origin=ORIGIN_FETCHED,
        reports=reports,
        recalls=recalls,
        recalls_matched_total=rec.get("matched_total"),
        window_from=window.get("date_from"),
        window_to=window.get("date_to"),
        queries=tuple(queries),
        classification_name=cls.get("device_name"),
        classification_query_url=cls.get("query_url"),
        classification_source="openFDA device classification" if cls.get("device_name") else None,
        fetched_utc=doc.get("fetched_utc"),
        notes=tuple(doc.get("notes") or ()),
    )


def load_evidence(
    product_code: str,
    *,
    db_path: Path | None = None,
    evidence_folder: Path | None = None,
    db_codes: set[str] | None = None,
) -> CodeEvidence:
    """Evidence for a code: the demo database if it holds the code, else the fetched file."""
    codes = demo_db_codes(db_path) if db_codes is None else db_codes
    if product_code in codes:
        return load_demo_db_evidence(product_code, db_path)
    return load_fetched_evidence(product_code, evidence_folder)
