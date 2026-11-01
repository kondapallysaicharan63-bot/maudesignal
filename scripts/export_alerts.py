"""Export the alert detail file for the web workspace (``web/public/data/alerts.json``).

HACKATHON-BUILT — Meta Global AI Developer Hackathon (Oct 26 – Nov 4, 2026).

One entry per alert the workspace can open: every flagged row of the AI-device sweep, every flagged
signal of a stored daily digest, and every simulated company device that is marked "Needs review".
Everything is built from stored files only (no network, no key, no model call):

* ``demo/sweep/ai-device-sweep.json``     counts per week and the openFDA query behind each
* ``digests/*.json``                      the daily digests (counts, windows)
* ``data/demo/maudesignal_demo.db``       stored reports, recalls and 510(k) records
* ``demo/company/``                       simulated devices and owners; fetched evidence per code
* ``demo/mentions/<CODE>.json``           stored outside-source searches (copied when present)

Every report quote, recall excerpt, 510(k) record and count that is shown is first checked by the
claim gate (``maudesignal.gate``) against the stored rows; what does not pass is held back and
counted in the entry's ``gate`` block. Nothing here decides anything: the next steps say that a
person decides.

    python3 scripts/export_alerts.py
    python3 scripts/export_alerts.py --out /tmp/web-data
"""

# ruff: noqa: E402, E501
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

import export_web_data as ewd  # noqa: E402

from maudesignal.gate import (  # noqa: E402
    CountClaim,
    DeviceClaim,
    EvidenceStore,
    QuoteClaim,
    verify_claim,
)
from maudesignal.gate.evidence import (
    DeviceRef,
    EvidenceRecord,
    RecallRef,
    normalize_source,
)  # noqa: E402
from maudesignal.monitor.deterioration import (  # noqa: E402
    BASELINE_WEEKS,
    SEVERITY_ESCALATION_PP,
    SPIKE_MIN_REPORTS,
    SPIKE_MULTIPLIER,
)

SCHEMA_VERSION = "1.0"
MAX_REPORTS = 10
MAX_RECALLS = 5
MAX_K510 = 5
RULE_BY_CLASS = {
    "spike": "reports suddenly increased",
    "severity_escalation": "more serious than usual",
    "new_signal": "new kind of problem",
}
RULE_WORDS = {
    "reports suddenly increased": (
        f"Reports suddenly increased: at least {SPIKE_MIN_REPORTS} reports this week and at least "
        f"{SPIKE_MULTIPLIER} times the weekly average of the {BASELINE_WEEKS} weeks before."
    ),
    "more serious than usual": (
        f"More serious than usual: the share of injury or death reports rose by "
        f"{SEVERITY_ESCALATION_PP} points or more compared with the {BASELINE_WEEKS} weeks before."
    ),
    "new kind of problem": (
        "New kind of problem: reports in a device type that had none before, or a kind of event "
        "never seen before for that device type."
    ),
}
NO_RULE_WORDS = (
    "No weekly rule fired for this device type. It is shown because the simulated owner marked "
    "the device Needs review."
)
SEVERE_TYPES = ("death", "injury")
EVENT_API = "https://api.fda.gov/device/event.json"
CLASSIFICATION_API = "https://api.fda.gov/device/classification.json"

# What the pages must never print (same list as the web exporter) plus personal details.
FORBIDDEN = ewd.COMPANY_FORBIDDEN
_NOT_A_NAME = (
    "was|is|has|had|did|who|with|and|in|on|the|a|an|experienced|reported|stated|states|developed|"
    "presented|underwent|were|information|identifier|identification|outcome|problem|age|weight|sex|"
    "gender|date|code|condition|death|safety|care|harm|injury|impact"
)
# A name starts with a capital letter, so the two name patterns are case-sensitive; the rest ignore case.
_PERSONAL = re.compile(
    r"\b(?:Dr|Mr|Mrs|Ms|Miss|Prof)\.?\s+[A-Z][a-z]+"  # title + name
    rf"|\b[Pp]atient\s+(?!(?:{_NOT_A_NAME})\b)[A-Z][a-z]+"  # "patient Smith"
    r"|(?i:\b\d{1,3}[- ]?(?:year|yr)s?[- ]?old\b|\bage[d]?\s*:?\s*\d{1,3}\b)"  # age
    r"|[\w.+-]+@[\w-]+\.[\w.-]+"  # email
    r"|(?<!\d)(?:\+?1[ -.]?)?\(?\d{3}\)?[ -.]\d{3}[ -.]\d{4}(?!\d)"  # phone
)


_ENDS_WITH_TITLE = re.compile(r"\b(?:Dr|Mr|Mrs|Ms|Miss|Prof)\.$")


def has_personal_details(text: str) -> bool:
    """True when the text holds a title + name, ``patient <Name>``, an age, an email or a phone number."""
    return bool(_PERSONAL.search(text))


def iso(ymd: str | None) -> str | None:
    """``20260825`` -> ``2026-08-25``; anything else unchanged; None stays None."""
    if ymd and re.fullmatch(r"\d{8}", ymd):
        return f"{ymd[:4]}-{ymd[4:6]}-{ymd[6:]}"
    return ymd


def ymd(day: str) -> str:
    """``2026-08-25`` -> ``20260825``."""
    return day.replace("-", "")


def event_url(code: str, start: str, end: str, count_by: str = "event_type.exact") -> str:
    """The openFDA event query for one product code and a date range (YYYYMMDD), counted by a field."""
    return (
        f"{EVENT_API}?search=device.device_report_product_code%3A{code}"
        f"+AND+date_received%3A%5B{start}+TO+{end}%5D&count={count_by}"
    )


def report_url(report_id: str) -> str:
    """The openFDA record of one MAUDE report."""
    return f"{EVENT_API}?search=mdr_report_key%3A{report_id}"


# ── stored inputs ────────────────────────────────────────────────────────────
def _k510_rows(root: Path, code: str) -> list[dict[str, Any]]:
    path = root / ewd.DEMO_DB
    if not path.is_file():
        return []
    con = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)
    try:
        rows = con.execute(
            "SELECT raw_json, url FROM external_sources "
            "WHERE source_type = 'fda_510k' AND product_code = ?",
            (code,),
        ).fetchall()
    finally:
        con.close()
    out = []
    for raw, url in rows:
        d = json.loads(raw)
        out.append(
            {
                "k_number": str(d.get("k_number") or ""),
                "applicant": str(d.get("applicant") or ""),
                "device_name": str(d.get("device_name") or ""),
                "decision_date": str(d.get("decision_date") or ""),
                "url": url,
            }
        )
    out.sort(key=lambda r: (r["decision_date"], r["k_number"]), reverse=True)
    return out


def _store(code: str, ev: dict[str, Any], k510: list[dict[str, Any]]) -> EvidenceStore:
    return EvidenceStore.from_iterables(
        [
            EvidenceRecord(
                report_id=str(r["report_id"]),
                product_code=code,
                event_type=r.get("event_type"),
                date_received=r.get("date_received"),
                text=str(r.get("text") or ""),
                manufacturer=r.get("manufacturer"),
                brand_name=r.get("brand_name"),
                report_source=r.get("report_source"),
            )
            for r in ev["reports"]
        ],
        [
            DeviceRef(
                k_number=k["k_number"],
                product_code=code,
                device_name=k["device_name"],
                company_name=k["applicant"],
                decision_date=k["decision_date"],
            )
            for k in k510
        ],
        recalls=[
            RecallRef(
                recall_number=str(c["recall_number"]),
                product_code=code,
                event_number=c.get("event_number"),
                recalling_firm=c.get("recalling_firm"),
                product_description=str(c.get("product_description") or ""),
                reason_for_recall=str(c.get("reason_for_recall") or ""),
                recall_status=c.get("recall_status"),
                date_initiated=c.get("date_initiated"),
            )
            for c in ev["recalls"]
        ],
    )


# ── one alert ────────────────────────────────────────────────────────────────
class Gate:
    """Counts the facts the claim gate checked, passed and held back for one alert."""

    def __init__(self) -> None:
        """Start at zero."""
        self.checked = 0
        self.passed = 0

    def add(self, ok: bool) -> bool:
        """Record one verdict and return it."""
        self.checked += 1
        self.passed += int(ok)
        return ok

    def block(self) -> dict[str, int]:
        """The ``gate`` object of the contract."""
        return {
            "checked": self.checked,
            "passed": self.passed,
            "withheld": self.checked - self.passed,
        }


def _pick_quote(text: str, report_id: str, store: EvidenceStore, gate: Gate) -> str | None:
    """First sentence of 40-220 characters the gate finds word for word in the report; None when there is none.

    Only a sentence that was actually put to the gate is counted. A report with no narrative text, or with
    no sentence of a usable length, adds nothing to the gate counts.
    """
    prev = ""
    for s in ewd._sentences(text):
        after_title = bool(
            _ENDS_WITH_TITLE.search(prev)
        )  # "Dr." + "Jones said ..." was split at the full stop
        prev = s
        if after_title or not ewd.QUOTE_MIN_CHARS <= len(s) <= ewd.QUOTE_MAX_CHARS:
            continue
        if FORBIDDEN.search(s) or has_personal_details(s):
            continue
        if gate.add(verify_claim(QuoteClaim(quote=s, report_id=report_id), store).status == "pass"):
            return s
    return None


def _reports(
    code: str,
    ev: dict[str, Any] | None,
    store: EvidenceStore | None,
    window: dict[str, Any],
    rule: str | None,
    gate: Gate,
) -> tuple[list[dict[str, Any]], dict[str, int] | None, int | None]:
    """``(reports, who_filed, stored_in_window)`` for the alert's current window."""
    if ev is None or store is None:
        return [], None, None
    start, end = ymd(window["this_week"]["from"]), ymd(window["this_week"]["to"])
    rows = [r for r in ev["reports"] if start <= str(r.get("date_received") or "") <= end]
    who = {"manufacturer": 0, "user_facility": 0, "other": 0}
    for r in rows:
        src = normalize_source(r.get("report_source"))
        who[
            (
                "manufacturer"
                if src == "manufacturer"
                else "user_facility" if src == "user facility" else "other"
            )
        ] += 1

    def priority(r: dict[str, Any]) -> int:
        et = str(r.get("event_type") or "").lower()
        return 0 if rule == "more serious than usual" and et in SEVERE_TYPES else 1

    rows.sort(key=lambda r: (priority(r), -int(r.get("date_received") or 0), str(r["report_id"])))
    out = []
    for r in rows[:MAX_REPORTS]:
        rid = str(r["report_id"])
        quote = _pick_quote(str(r.get("text") or ""), rid, store, gate)
        out.append(
            {
                "report_id": rid,
                "date_received": iso(r.get("date_received")),
                "event_type": (str(r.get("event_type") or "").capitalize() or None),
                "quote": quote,
                "quote_note": (
                    None
                    if quote
                    else "No sentence of this report could be quoted (no narrative text, or no usable sentence)."
                ),
                "openfda_url": report_url(rid),
                "maude_url": ewd.MAUDE_DETAIL_URL.format(rid),
            }
        )
    return out, who, len(rows)


def _recalls(
    store: EvidenceStore | None, ev: dict[str, Any] | None, gate: Gate
) -> tuple[list[dict[str, Any]], int]:
    if ev is None or store is None:
        return [], 0
    recalls = sorted(ev["recalls"], key=lambda c: c.get("date_initiated") or "", reverse=True)
    out = []
    for rc in recalls[:MAX_RECALLS]:
        item = ewd._recall_item(rc, store)
        gate.add(item["excerpt"] is not None)
        out.append(
            {
                "id": item["recall_number"],
                "date": iso(item["date_initiated"]),
                "reason": item["excerpt"],
                "reason_truncated": item["excerpt_truncated"],
                "url": item["url"],
            }
        )
    return out, len(recalls)


def _k510(
    store: EvidenceStore | None, rows: list[dict[str, Any]], code: str, gate: Gate
) -> list[dict[str, Any]]:
    out = []
    for k in rows[:MAX_K510]:
        ok = store is not None and gate.add(
            verify_claim(DeviceClaim(k_number=k["k_number"], product_code=code), store).status
            == "pass"
        )
        if ok:
            out.append(
                {
                    "k_number": k["k_number"],
                    "applicant": k["applicant"],
                    "decision_date": k["decision_date"],
                    "url": k["url"],
                }
            )
    return out


def _next_steps(rule: str | None, has_reports: bool) -> list[str]:
    steps = []
    if has_reports:
        steps.append(
            "Read the reports listed above and check whether they describe the same kind of problem."
        )
    else:
        steps.append(
            "Open the openFDA links above to read the reports of that week; none are stored in this workspace."
        )
    if rule == "more serious than usual":
        steps.append("Read the injury and death reports first, then the others.")
    elif rule == "new kind of problem":
        steps.append(
            "Check whether the new kind of event or the first reports match anything already known for this device type."
        )
    elif rule == "reports suddenly increased":
        steps.append(
            "Check whether the extra reports share one cause, one software version or one site."
        )
    else:
        steps.append(
            "Compare the device type's recent reports and recalls with what the owner already knows."
        )
    steps.append("Look at the recalls and 510(k) records listed for this device type.")
    steps.append(
        "Ask the device owner to decide whether a review should be opened. A person decides; nothing is filed with FDA."
    )
    return steps


def _owner(
    devices: list[dict[str, Any]], code: str, device_id: str | None
) -> dict[str, Any] | None:
    mine = [d for d in devices if d["product_code"] == code]
    pick = (
        next((d for d in mine if d["id"] == device_id), None)
        or next((d for d in mine if (d.get("status") or {}).get("label") == "Needs review"), None)
        or (mine[0] if mine else None)
    )
    if pick is None:
        return None
    return {
        "name": pick["owner"],
        "status": (pick.get("status") or {}).get("label"),
        "device_id": pick["id"],
        "device_name": pick["name"],
    }


def _count_gate(
    code: str,
    ev: dict[str, Any] | None,
    store: EvidenceStore | None,
    start: str,
    end: str,
    value: int,
    gate: Gate,
    notes: list[str],
) -> None:
    """Check a count against the stored rows when those rows hold the whole window; else say so."""
    if ev is None or store is None or not _complete(ev, start, end):
        return
    v = verify_claim(
        CountClaim(product_code=code, value=value, date_from=start, date_to=end), store
    )
    if not gate.add(v.status == "pass"):
        notes.append(
            f"{code}: stored rows give a different count than the file for {start} to {end} ({v.reason})."
        )


def _complete(ev: dict[str, Any], start: str, end: str) -> bool:
    """The stored reports hold every report of the window (complete fetch, or the digest's own database)."""
    lo, hi = ev["window"]
    if not lo or not hi or not (lo <= start and end <= hi):
        return False
    if ev["origin"] == "fetched":
        return bool(ev.get("complete"))
    return True


def build_one(
    root: Path,
    spec: dict[str, Any],
    devices: list[dict[str, Any]],
    cache: dict[str, Any],
) -> dict[str, Any]:
    """One alert entry."""
    code = spec["product_code"]
    if code not in cache:
        ev = ewd._load_demo_db(root, code) or ewd._load_fetched(root / ewd.COMPANY_DIR, code)
        if ev is not None and ev["origin"] == "fetched":
            doc = ewd.read_json(root / ewd.COMPANY_DIR / "evidence" / f"{code}.json")
            rep = doc["reports"]
            ev["complete"] = rep.get("matched_total") == rep.get("stored")
        k = _k510_rows(root, code)
        cache[code] = (ev, k, _store(code, ev, k) if ev else None)
    ev, k510_rows, store = cache[code]
    gate = Gate()
    notes: list[str] = list(spec.get("notes", []))
    rule: str | None = spec["rule"]
    win = spec["window"]
    c = spec["counts"]
    # openFDA lags real time, so the window is never "this week": the sweep's window is "the
    # latest sweep week", any other stored window "the stored week".
    wk = "the latest sweep week" if spec["source"].get("kind") == "sweep" else "the stored week"
    numbers: list[dict[str, Any]] = []
    if c is not None:
        this_s, this_e = ymd(win["this_week"]["from"]), ymd(win["this_week"]["to"])
        base_s, base_e = ymd(win["baseline_4wk"]["from"]), ymd(win["baseline_4wk"]["to"])
        win["this_week"]["count"] = c["this"]
        win["baseline_4wk"]["count"] = c["base"]
        win["baseline_4wk"]["weekly_mean"] = round(c["base"] / BASELINE_WEEKS, 2)
        if c.get("mean") is not None and abs(c["mean"] - c["base"] / BASELINE_WEEKS) > 0.01:
            notes.append(
                f"{code}: the stored weekly mean {c['mean']} differs from {c['base']} / {BASELINE_WEEKS}."
            )
        _count_gate(code, ev, store, this_s, this_e, c["this"], gate, notes)
        _count_gate(code, ev, store, base_s, base_e, c["base"], gate, notes)
        url_now = spec["urls"]["this"] or event_url(code, this_s, this_e)
        url_before = spec["urls"]["base"] or event_url(code, base_s, base_e)
        numbers = [
            {"label": f"Reports in {wk}", "value": c["this"], "openfda_url": url_now},
            {
                "label": f"Reports in the {BASELINE_WEEKS} weeks before",
                "value": c["base"],
                "openfda_url": url_before,
            },
            {
                "label": f"Weekly average of those {BASELINE_WEEKS} weeks",
                "value": win["baseline_4wk"]["weekly_mean"],
                "openfda_url": url_before,
            },
        ]
        if rule == "reports suddenly increased" and c["base"] > 0:
            numbers.append(
                {
                    "label": f"{wk.capitalize()} compared with the weekly average (times)",
                    "value": round(c["this"] / (c["base"] / BASELINE_WEEKS), 2),
                    "openfda_url": url_now,
                }
            )
        if rule == "more serious than usual" and c.get("severe") is not None:
            numbers.append(
                {
                    "label": f"Injury or death reports in {wk}",
                    "value": c["severe"][0],
                    "openfda_url": url_now,
                }
            )
            numbers.append(
                {
                    "label": f"Injury or death reports in the {BASELINE_WEEKS} weeks before",
                    "value": c["severe"][1],
                    "openfda_url": url_before,
                }
            )
        if rule == "new kind of problem" and c.get("prior") is not None:
            numbers.append(
                {
                    "label": "Reports for this device type before the 4 weeks",
                    "value": c["prior"],
                    "openfda_url": url_before,
                }
            )
    reports, who, stored_n = (
        _reports(code, ev, store, win, rule, gate) if c is not None else ([], None, None)
    )
    total = c["this"] if c is not None else None
    if c is not None and stored_n is not None and stored_n != c["this"]:
        notes.append(
            f"{stored_n} of the {c['this']} reports of that week are stored in this workspace; the rest are on openFDA."
        )
    if c is not None and ev is None:
        notes.append(
            "No reports are stored for this device type in this workspace; use the openFDA links."
        )
    recalls, recalls_total = _recalls(store, ev, gate)
    k510 = _k510(store, k510_rows, code, gate)
    if recalls_total == 0:
        notes.append("No recalls are stored for this device type.")
    return {
        "id": spec["id"],
        "product_code": code,
        "device_type": spec["device_type"],
        "rule": rule,
        "rule_words": RULE_WORDS.get(rule or "", NO_RULE_WORDS),
        "source": spec["source"],
        "window": win if c is not None else None,
        "numbers": numbers,
        "reports": reports,
        "reports_total": total,
        "reports_stored": stored_n,
        "recalls": recalls,
        "recalls_total": recalls_total,
        "k510": k510,
        "k510_total": len(k510_rows),
        "who_filed": who,
        "next_steps": _next_steps(rule, bool(reports)),
        "owner": _owner(devices, code, spec.get("device_id")),
        "gate": gate.block(),
        "notes": notes,
    }


# ── the list of alerts ───────────────────────────────────────────────────────
def _window(a: str, b: str, c: str, d: str) -> dict[str, Any]:
    return {
        "this_week": {"from": iso(a), "to": iso(b), "count": None},
        "baseline_4wk": {"from": iso(c), "to": iso(d), "count": None, "weekly_mean": None},
    }


def _names(root: Path) -> dict[str, str]:
    names: dict[str, str] = {}
    path = root / ewd.DEMO_DB
    if path.is_file():
        con = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)
        try:
            for code, name in con.execute(
                "SELECT product_code, device_name FROM device_catalog WHERE source_keyword = 'openfda_classification'"
            ):
                names[code] = name
        finally:
            con.close()
    for f in sorted((root / ewd.COMPANY_DIR / "evidence").glob("*.json")):
        d = ewd.read_json(f)
        n = (d.get("classification") or {}).get("device_name")
        if n:
            names.setdefault(d["product_code"], n)
    return names


def specs(root: Path, company: dict[str, Any]) -> list[dict[str, Any]]:
    """The alerts to build, from the stored sweep, digests and simulated company."""
    names = _names(root)
    out: list[dict[str, Any]] = []
    sweep_path = root / "demo" / "sweep" / "ai-device-sweep.json"
    sweep_rows: dict[str, dict[str, Any]] = {}
    if sweep_path.is_file():
        sweep_rows = {r["product_code"]: r for r in ewd.read_json(sweep_path)["rows"]}

    def from_sweep(r: dict[str, Any]) -> dict[str, Any]:
        w = r["window"]
        q = dict(r.get("queries", []))
        sev = None
        if r.get("current_severe_count") is not None and r.get("baseline_severe_count") is not None:
            sev = (r["current_severe_count"], r["baseline_severe_count"])
        return {
            "window": _window(
                w["current_start"], w["current_end"], w["baseline_start"], w["baseline_end"]
            ),
            "counts": {
                "this": r["current_count"],
                "base": r["baseline_count"],
                "mean": r.get("baseline_weekly_mean"),
                "severe": sev,
                "prior": r.get("prior_report_count"),
            },
            "urls": {
                "this": q.get("This week, by event type"),
                "base": q.get("4 weeks before, by event type"),
            },
        }

    for code, r in sorted(sweep_rows.items()):
        rule = RULE_BY_CLASS.get(r["classification"])
        if rule:
            out.append(
                {
                    "id": f"sweep:{code}",
                    "product_code": code,
                    "device_type": names.get(code),
                    "rule": rule,
                    "source": {
                        "kind": "sweep",
                        "label": "AI device sweep",
                        "as_of": iso(r["as_of"]),
                    },
                    **from_sweep(r),
                }
            )
    for p in sorted((root / "digests").glob("*.json")):
        d = ewd.read_json(p)
        w = d["window"]
        for s in d.get("signals", []):
            rule = RULE_BY_CLASS.get(s["classification"])
            if not rule:
                continue
            code = s["product_code"]
            sev = (s["current_severe_count"], s["baseline_severe_count"])
            out.append(
                {
                    "id": f"brief:{d['as_of']}:{code}",
                    "product_code": code,
                    "device_type": names.get(code),
                    "rule": rule,
                    "source": {
                        "kind": "brief",
                        "label": "Demo snapshot brief",
                        "as_of": d["as_of"],
                    },
                    "window": _window(
                        ymd(w["current_start"]),
                        ymd(w["current_end"]),
                        ymd(w["baseline_start"]),
                        ymd(w["baseline_end"]),
                    ),
                    "counts": {
                        "this": s["current_count"],
                        "base": s["baseline_count"],
                        "mean": s.get("baseline_weekly_mean"),
                        "severe": sev,
                        "prior": s.get("prior_report_count"),
                    },
                    "urls": {"this": None, "base": None},
                }
            )
    for dev in company.get("devices", []):
        if (dev.get("status") or {}).get("label") != "Needs review":
            continue
        code = dev["product_code"]
        row = sweep_rows.get(code)
        base: dict[str, Any] = (
            from_sweep(row)
            if row is not None
            else {
                "window": None,
                "counts": None,
                "urls": {"this": None, "base": None},
                "notes": ["This code is not in the stored sweep."],
            }
        )
        out.append(
            {
                "id": f"company:{dev['id']}",
                "product_code": code,
                "device_type": (dev.get("device_type") or {}).get("name") or names.get(code),
                "rule": RULE_BY_CLASS.get(row["classification"]) if row is not None else None,
                "source": {
                    "kind": "company",
                    "label": "Our devices (simulated)",
                    "as_of": (dev["status"] or {}).get("date"),
                },
                "device_id": dev["id"],
                **base,
            }
        )
    return out


def build_alerts(
    root: Path, generated_utc: str | None = None, company: dict[str, Any] | None = None
) -> dict[str, Any]:
    """The whole ``alerts.json`` document."""
    stamp = generated_utc or datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    company = company if company is not None else ewd.build_company(root, generated_utc)
    devices = company.get("devices", [])
    cache: dict[str, Any] = {}
    alerts = [build_one(root, s, devices, cache) for s in specs(root, company)]
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_utc": stamp,
        "banner": ewd.COMPANY_BANNER,
        "alerts": alerts,
        "notes": (
            []
            if alerts
            else ["No flagged sweep rows, digest signals or Needs review devices are stored."]
        ),
    }


MENTION_BADGE = "Unverified — not checked against FDA records"


def _clean_mentions(doc: dict[str, Any]) -> dict[str, Any] | None:
    """A stored search, hardened for the web copy; None when it is not a recorded search.

    Kept: only a ``recorded`` file, and only mentions with an ``https`` url, a non-empty quote and no
    personal details in the quote or the reason. The badge text is forced. A mention dropped for personal
    details is counted in ``dropped.personal_details`` so the line on the page stays true.
    """
    if doc.get("mode") != "recorded" or not isinstance(doc.get("mentions"), list):
        return None
    kept: list[dict[str, Any]] = []
    personal = 0
    for m in doc["mentions"]:
        if not isinstance(m, dict) or m.get("mode", "recorded") != "recorded":
            continue
        url, quote = m.get("url"), m.get("quote")
        if not (isinstance(url, str) and url.startswith("https://")):
            continue
        if not (isinstance(quote, str) and quote.strip()):
            continue
        if any(
            has_personal_details(str(m.get(k) or ""))
            for k in ("quote", "why_matched", "source_name")
        ):
            personal += 1
            continue
        kept.append({**m, "badge": MENTION_BADGE})
    dropped = dict(doc["dropped"]) if isinstance(doc.get("dropped"), dict) else {}
    dropped["personal_details"] = int(dropped.get("personal_details") or 0) + personal
    return {**doc, "mentions": kept, "dropped": dropped}


def build_mentions(root: Path) -> dict[str, Any]:
    """``mentions.json``: the stored outside-source searches (``demo/mentions/<CODE>.json``), checked before they are copied."""
    folder = root / "demo" / "mentions"
    codes: dict[str, Any] = {}
    for p in sorted(folder.glob("*.json")) if folder.is_dir() else []:
        doc = ewd.read_json(p)
        clean = _clean_mentions(doc) if isinstance(doc, dict) else None
        if clean is not None:
            codes[str(clean.get("product_code") or p.stem).upper()] = clean
    return {
        "schema_version": SCHEMA_VERSION,
        "codes": codes,
        "notes": (
            []
            if codes
            else ["No stored outside-source search exists yet (demo/mentions is empty)."]
        ),
    }


def main() -> int:
    """CLI entry point."""
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", type=Path, default=ROOT / "web" / "public" / "data")
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    doc = build_alerts(ROOT)
    ewd.write_json(args.out / "alerts.json", doc)
    ewd.write_json(args.out / "mentions.json", build_mentions(ROOT))
    print(f"wrote {len(doc['alerts'])} alerts to {args.out / 'alerts.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
