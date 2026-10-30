r"""Fetch real openFDA evidence for the simulated company's product codes.

HACKATHON-BUILT — Meta Global AI Developer Hackathon (Oct 26 – Nov 4, 2026).

For each product code of the simulated company that the demo database does not hold,
this stores, in ``demo/company/evidence/<code>.json``:

* the device-type name from openFDA ``device/classification.json``;
* MAUDE reports received in the last 8 weeks (at most 100), from ``device/event.json``,
  fetched with ``OpenFDAClient`` (User-Agent set, ``OPENFDA_API_KEY`` from the environment);
* the latest 100 recalls from ``device/recall.json``;
* every query URL (never with the API key).

No model and no key other than openFDA's. Problem patterns are NOT computed here: the
page groups the stored reports with documented keyword rules
(``maudesignal.company.patterns``), so the grouping is always recomputed from the file.

    python scripts/fetch_company_evidence.py            # codes read from demo/company
    python scripts/fetch_company_evidence.py --codes IYN OTE
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections.abc import Callable, Iterable
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any, Protocol

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from maudesignal.common.exceptions import OpenFDAAPIError  # noqa: E402
from maudesignal.company.constants import (  # noqa: E402
    CLASSIFICATION_ENDPOINT,
    RECALL_ENDPOINT,
    company_dir,
    demo_db_path,
)
from maudesignal.company.evidence import demo_db_codes  # noqa: E402
from maudesignal.config import openfda_api_key_from_env  # noqa: E402
from maudesignal.ingestion.openfda_client import (  # noqa: E402
    OPENFDA_EVENT_ENDPOINT,
    USER_AGENT,
    OpenFDAClient,
    build_query,
    search_param,
)
from maudesignal.ingestion.pipeline import _extract_report_id, _normalize  # noqa: E402

WEEKS = 8
REPORT_LIMIT = 100
RECALL_LIMIT = 100
SCHEMA_VERSION = "1.0"
_PAUSE_SECONDS = 0.3


class ReportSource(Protocol):
    """The part of ``OpenFDAClient`` this script uses (a fake in tests)."""

    def iter_reports(
        self,
        product_code: str,
        start_date: str | None = ...,
        end_date: str | None = ...,
        limit: int | None = ...,
    ) -> Iterable[dict[str, Any]]:
        """Yield reports."""

    def total(
        self, product_code: str, start_date: str | None = ..., end_date: str | None = ...
    ) -> int:
        """Matching report count."""


#: ``http_get(url, params) -> parsed JSON or None`` (None = openFDA found nothing).
HttpGet = Callable[[str, dict[str, str | int]], dict[str, Any] | None]


def window(today: date, weeks: int = WEEKS) -> tuple[str, str]:
    """``(date_from, date_to)`` as YYYYMMDD for the last ``weeks`` weeks up to ``today``."""
    return (today - timedelta(weeks=weeks)).strftime("%Y%m%d"), today.strftime("%Y%m%d")


def report_record(raw: dict[str, Any], product_code: str) -> dict[str, Any] | None:
    """The fields the page uses from one openFDA event record (no patient fields)."""
    rid = _extract_report_id(raw)
    if rid is None:
        return None
    norm = _normalize(raw, product_code)
    text = " ".join(t for t in (norm["narrative"], norm["mfr_narrative"]) if t)
    return {
        "report_id": rid,
        "event_type": norm["event_type"],
        "date_received": raw.get("date_received"),
        "report_source": norm["report_source"],
        "brand_name": norm["brand_name"],
        "manufacturer": norm["manufacturer"],
        "product_problems": [str(p) for p in raw.get("product_problems") or []],
        "text": text,
    }


def recall_record(raw: dict[str, Any]) -> dict[str, Any] | None:
    """The fields the page uses from one openFDA recall row."""
    number = raw.get("product_res_number")
    if not number:
        return None
    started = raw.get("event_date_initiated")
    return {
        "recall_number": str(number),
        "event_number": raw.get("res_event_number"),
        "recalling_firm": raw.get("recalling_firm"),
        "product_description": str(raw.get("product_description") or ""),
        "reason_for_recall": str(raw.get("reason_for_recall") or ""),
        "recall_status": raw.get("recall_status"),
        "date_initiated": started.replace("-", "") if started else None,
        "cfres_id": raw.get("cfres_id"),
    }


def fetch_code(
    code: str,
    *,
    client: ReportSource,
    http_get: HttpGet,
    today: date,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Fetch classification, reports and recalls for one code (the evidence file document)."""
    start, end = window(today)
    notes: list[str] = []

    cls_params: dict[str, str | int] = {"search": f"product_code:{code}", "limit": 1}
    cls = http_get(CLASSIFICATION_ENDPOINT, cls_params)
    cls_row = ((cls or {}).get("results") or [{}])[0]
    classification = {
        "device_name": cls_row.get("device_name"),
        "device_class": cls_row.get("device_class"),
        "regulation_number": cls_row.get("regulation_number"),
        "query_url": f"{CLASSIFICATION_ENDPOINT}?search=product_code:{code}&limit=1",
    }
    if not classification["device_name"]:
        notes.append("openFDA returned no classification row for this code")

    query = build_query(code, start, end)
    matched = client.total(code, start, end)
    records = []
    for raw in client.iter_reports(code, start, end, limit=REPORT_LIMIT):
        rec = report_record(raw, code)
        if rec is not None:
            records.append(rec)
    records.sort(key=lambda r: (r["date_received"] or "", r["report_id"]), reverse=True)
    if matched > len(records):
        notes.append(f"{matched} reports matched the window; the {len(records)} newest are stored")

    recall_params: dict[str, str | int] = {
        "search": f"product_code:{code}",
        "sort": "event_date_initiated:desc",
        "limit": RECALL_LIMIT,
    }
    rc = http_get(RECALL_ENDPOINT, recall_params)
    rc_rows = [r for raw in (rc or {}).get("results", []) if (r := recall_record(raw))]
    rc_total = int(((rc or {}).get("meta", {}).get("results", {}) or {}).get("total", len(rc_rows)))

    stamp = (now or datetime.now(UTC)).strftime("%Y-%m-%dT%H:%M:%SZ")
    return {
        "schema_version": SCHEMA_VERSION,
        "product_code": code,
        "fetched_utc": stamp,
        "window": {"date_from": start, "date_to": end, "weeks": WEEKS},
        "classification": classification,
        "reports": {
            "query_url": f"{OPENFDA_EVENT_ENDPOINT}?search={query}&limit={REPORT_LIMIT}",
            "matched_total": matched,
            "stored": len(records),
            "records": records,
        },
        "recalls": {
            "query_url": (
                f"{RECALL_ENDPOINT}?search=product_code:{code}"
                f"&sort=event_date_initiated:desc&limit={RECALL_LIMIT}"
            ),
            "matched_total": rc_total,
            "stored": len(rc_rows),
            "records": rc_rows,
        },
        "notes": notes,
    }


def make_http_get(api_key: str | None, retries: int = 3) -> HttpGet:
    """GET against openFDA with the project User-Agent, the key from the environment, retries."""
    http = httpx.Client(timeout=30.0, headers={"User-Agent": USER_AGENT})

    def get(url: str, params: dict[str, str | int]) -> dict[str, Any] | None:
        q: dict[str, str | int] = {**params, "search": search_param(str(params["search"]))}
        if api_key:
            q["api_key"] = api_key
        for attempt in range(retries):
            time.sleep(_PAUSE_SECONDS)
            try:
                resp = http.get(url, params=q)
            except httpx.HTTPError as exc:
                if attempt == retries - 1:
                    raise OpenFDAAPIError(f"HTTP error contacting openFDA: {exc}") from exc
                time.sleep(2**attempt)
                continue
            if resp.status_code == 404:
                return None
            if resp.status_code in (429, 500, 503) and attempt < retries - 1:
                time.sleep(2**attempt)
                continue
            if resp.status_code != 200:
                raise OpenFDAAPIError(f"openFDA status {resp.status_code} for {url}")
            body: dict[str, Any] = resp.json()
            return body
        return None

    return get


def codes_to_fetch(folder: Path) -> list[str]:
    """Company product codes that the demo database does not hold (sorted, unique)."""
    doc = json.loads((folder / "company.json").read_text(encoding="utf-8"))
    held = demo_db_codes(demo_db_path())
    return sorted({d["product_code"] for d in doc["devices"]} - held)


def main(argv: list[str] | None = None) -> int:
    """Fetch every code; exit 1 when any code failed (the others are still written)."""
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0] if __doc__ else "")
    ap.add_argument(
        "--codes", nargs="*", help="product codes (default: the company's non-DB codes)"
    )
    ap.add_argument("--out", type=Path, default=None, help="folder (default demo/company/evidence)")
    args = ap.parse_args(argv)

    folder = company_dir()
    out = args.out or folder / "evidence"
    out.mkdir(parents=True, exist_ok=True)
    codes = args.codes or codes_to_fetch(folder)
    api_key = openfda_api_key_from_env()
    failures = 0
    with OpenFDAClient(api_key=api_key, page_size=REPORT_LIMIT) as client:
        http_get = make_http_get(api_key)
        for code in codes:
            try:
                doc = fetch_code(
                    code, client=client, http_get=http_get, today=datetime.now(UTC).date()
                )
            except OpenFDAAPIError as exc:
                failures += 1
                print(f"{code}: FAILED {exc}", file=sys.stderr)
                continue
            (out / f"{code}.json").write_text(
                json.dumps(doc, indent=1, ensure_ascii=False) + "\n", encoding="utf-8"
            )
            print(
                f"{code}: {doc['reports']['stored']} reports, "
                f"{doc['recalls']['stored']} recalls, type {doc['classification']['device_name']}"
            )
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
