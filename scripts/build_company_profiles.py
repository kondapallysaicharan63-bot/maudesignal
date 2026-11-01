"""Build web/public/data/company_profiles.json: a simulated lifecycle profile per demo device.

HACKATHON-BUILT — Meta Global AI Developer Hackathon (Oct 26 – Nov 4, 2026).

Every device of "Demo MedTech Co. (simulated)" (web/public/data/company.json) gets a full,
fictional lifecycle: design and risk management, verification and validation, the FDA
submission, launch, post-market complaints and CAPAs, and a dated activity log. All of that is
SIMULATED sample data and is labelled so on every screen.

Only three things are real, and they are read from data already stored in the repo, never typed
in: the product code, its FDA device name (company.json, from openFDA classification), and its
device class and regulation number (demo/company/evidence/<CODE>.json, or the openFDA block of
the MAUDE reports stored in data/demo/maudesignal_demo.db). When a value is not in stored data the
field is null and the page says so.

The output is deterministic (fixed seed, fixed as-of date), so re-running the script gives the same
file and a diff shows exactly what changed:

    python3.12 scripts/build_company_profiles.py            # writes the file
    python3.12 scripts/build_company_profiles.py --check    # exit 1 if the file is out of date
"""

# ruff: noqa: E501
from __future__ import annotations

import argparse
import json
import random
import sqlite3
import sys
from collections import Counter
from datetime import date, timedelta
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
COMPANY = ROOT / "web" / "public" / "data" / "company.json"
EVIDENCE_DIR = ROOT / "demo" / "company" / "evidence"
DEMO_DB = ROOT / "data" / "demo" / "maudesignal_demo.db"
OUT = ROOT / "web" / "public" / "data" / "company_profiles.json"

SEED = 20261101
AS_OF = date(2026, 11, 1)
BANNER = "SIMULATED — sample data. A fictional company and fictional devices; only the product code, its FDA name, class and regulation number are real stored FDA data."

# Decision wording by pathway: "cleared" for 510(k), "granted" for De Novo, "approved" only for PMA.
VERB = {"510(k)": "cleared", "De Novo": "granted", "PMA": "approved"}
NUMBER_PREFIX = {"510(k)": "K-SIM-", "De Novo": "DEN-SIM-", "PMA": "P-SIM-"}
# FDA review days (clock running, hold time excluded) by pathway.
FDA_DAYS = {"510(k)": (86, 96), "De Novo": (148, 160), "PMA": (176, 188)}

FUNCTIONS = (
    "Design Engineering",
    "Quality Engineering",
    "Regulatory Affairs",
    "Clinical",
    "Post-Market Surveillance",
    "Management review",
)

# Fictional people (no real person is meant). Each name carries "(simulated)" wherever it is shown.
PEOPLE: dict[str, list[str]] = {
    "Design Engineering": ["Hana Kowalczyk", "Oren Vasquez", "Siddharth Rao", "Freya Lindqvist"],
    "Quality Engineering": ["Marisol Ortega", "Tobias Achterberg", "Wen Liang", "Aoife Brennan"],
    "Regulatory Affairs": ["Priya Natarajan", "Gideon Mbeki-Hart", "Colette Duval"],
    "Clinical": ["Dr. Amara Okafor", "Dr. Lukas Brandt", "Dr. Selin Aydin"],
    "Post-Market Surveillance": ["Jonah Whitfield", "Ines Carvalho", "Kofi Asante"],
    "Management review": ["Ruth Calloway", "Matteo Ferrante"],
}

# Per device: the pathway and stage, plus the submission date the other dates are built around.
# Stages: development, under_review, decided (decision made, launch planned), on_market, post_market.
PLAN: dict[str, dict[str, Any]] = {
    "DMC-01": {
        "stage": "post_market",
        "submitted": "2022-03-14",
        "family": "imaging_software",
        "ai": False,
    },
    "DMC-02": {
        "stage": "on_market",
        "submitted": "2024-05-06",
        "family": "imaging_software",
        "ai": False,
    },
    "DMC-03": {
        "stage": "under_review",
        "submitted": "2026-07-20",
        "family": "imaging_software",
        "ai": True,
        "ai_response": True,
    },
    "DMC-04": {
        "stage": "on_market",
        "submitted": "2024-10-21",
        "family": "imaging_software",
        "ai": True,
        "fail": "usability",
    },
    "DMC-05": {
        "stage": "on_market",
        "submitted": "2023-09-11",
        "family": "imaging_software",
        "ai": True,
        "pathway": "De Novo",
    },
    "DMC-06": {
        "stage": "post_market",
        "submitted": "2021-11-08",
        "family": "imaging_hardware",
        "ai": False,
        "fail": "emc",
    },
    "DMC-07": {
        "stage": "on_market",
        "submitted": "2022-06-27",
        "family": "imaging_hardware",
        "ai": False,
    },
    "DMC-08": {
        "stage": "post_market",
        "submitted": "2022-09-19",
        "family": "physio_monitor",
        "ai": False,
        "fail": "software",
    },
    "DMC-09": {
        "stage": "decided",
        "submitted": "2026-02-09",
        "family": "physio_monitor",
        "ai": False,
    },
    "DMC-10": {
        "stage": "development",
        "submitted": "2027-04-12",
        "family": "physio_monitor",
        "ai": False,
    },
    "DMC-11": {
        "stage": "on_market",
        "submitted": "2023-02-13",
        "family": "imaging_hardware",
        "ai": False,
    },
    "DMC-12": {
        "stage": "under_review",
        "submitted": "2026-08-10",
        "family": "physio_monitor",
        "ai": False,
        "ai_response": False,
    },
}

STAGE_LABEL = {
    "development": "In development",
    "under_review": "Submitted — under FDA review",
    "on_market": "On market",
    "post_market": "Post-market",
}

INTENDED_USE = {
    "imaging_software": "Software that displays, processes and helps trained clinicians report on medical images. It does not replace the clinician's reading.",
    "imaging_hardware": "An imaging system used by trained operators to acquire images that clinicians then read.",
    "physio_monitor": "A monitoring device used by trained staff to observe patient measurements and be alerted to changes.",
}
AI_USE = " A machine-learning function marks areas for the clinician to look at; the clinician makes every finding."

DESIGN_INPUTS = {
    "imaging_software": [
        "Open and display studies from the site's image archive within 3 s at the 95th percentile",
        "Keep each report tied to the correct patient and study at every step",
        "Show measurement units and calibration on every measurement",
        "Log every user action with time and user ID",
    ],
    "imaging_hardware": [
        "Acquire images at the stated resolution across the full field of view",
        "Meet electrical safety and EMC limits for hospital use",
        "Stop acquisition within 1 s when the operator presses stop",
        "Label every image with the acquisition settings",
    ],
    "physio_monitor": [
        "Measure within the stated accuracy across the stated range",
        "Raise an audible and visible alarm within 10 s of a limit being crossed",
        "Run 4 h on battery with alarms active",
        "Meet electrical safety, EMC and skin-contact requirements",
    ],
}
DESIGN_OUTPUTS = {
    "imaging_software": [
        "Software requirements specification",
        "Architecture and detailed design",
        "User interface specification",
        "Labeling and instructions for use",
    ],
    "imaging_hardware": [
        "System and subsystem drawings",
        "Firmware and console software design",
        "Bill of materials",
        "Labeling and instructions for use",
    ],
    "physio_monitor": [
        "Sensor and electronics design",
        "Alarm system specification",
        "Firmware design",
        "Labeling and instructions for use",
    ],
}
HAZARDS = {
    "imaging_software": [
        (
            "Images or report shown for the wrong patient",
            "Delayed or wrong diagnosis",
            "Serious",
            "Patient and study ID checked at open and at sign-off; mismatch blocks sign-off",
            "Acceptable",
        ),
        (
            "Measurement shown with wrong scale",
            "Wrong size recorded",
            "Moderate",
            "Calibration shown on screen; unit test of every scale path",
            "Acceptable",
        ),
        (
            "Report cannot be finalised (server error)",
            "Delayed report",
            "Minor",
            "Local draft kept; clear error with retry; server monitoring",
            "Acceptable",
        ),
    ],
    "imaging_hardware": [
        (
            "Excess energy to the patient",
            "Burn or tissue heating",
            "Serious",
            "Hardware output limit independent of software; tested limits",
            "Acceptable",
        ),
        (
            "Image artefact hides a finding",
            "Missed or delayed diagnosis",
            "Serious",
            "Daily quality-control phantom check; artefact warning on screen",
            "Acceptable",
        ),
        (
            "Electromagnetic interference with nearby equipment",
            "Other equipment malfunctions",
            "Moderate",
            "Shielding and filtering; tested to IEC 60601-1-2",
            "Acceptable",
        ),
    ],
    "physio_monitor": [
        (
            "Alarm not raised when a limit is crossed",
            "Delayed treatment",
            "Serious",
            "Alarm self-test at start-up; independent watchdog; alarm tested at each limit",
            "Acceptable",
        ),
        (
            "Reading drifts out of accuracy",
            "Wrong clinical picture",
            "Moderate",
            "Accuracy checked in V&V; sensor-fault message",
            "Acceptable",
        ),
        (
            "Skin irritation from the sensor",
            "Skin reaction",
            "Minor",
            "Biocompatible materials; wear-time limit in labeling",
            "Acceptable",
        ),
    ],
}
COMPLAINT_CATEGORIES = {
    "imaging_software": [
        "Software error or freeze",
        "Login or connection",
        "Display or measurement",
        "Usability question",
        "Other",
    ],
    "imaging_hardware": [
        "Image quality",
        "Hardware fault",
        "Software error",
        "Usability question",
        "Other",
    ],
    "physio_monitor": [
        "Alarm behaviour",
        "Reading accuracy",
        "Sensor or cable",
        "Battery",
        "Other",
    ],
}
REGIONS = [["United States"], ["United States"], ["United States (pilot sites)"]]


def d(s: str) -> date:
    """A date from YYYY-MM-DD."""
    return date.fromisoformat(s)


def iso(x: date) -> str:
    """YYYY-MM-DD."""
    return x.isoformat()


def when(x: date) -> dict[str, Any]:
    """A date field; ``planned`` is true when it is after the as-of date."""
    return {"date": iso(x), "planned": x > AS_OF}


def person(rng: random.Random, function: str) -> str:
    """A fictional person of a function, marked simulated."""
    return f"{rng.choice(PEOPLE[function])} (simulated)"


def classification(code: str, db: sqlite3.Connection | None) -> dict[str, Any]:
    """Device class and regulation number for a code, from stored data only (null when absent)."""
    f = EVIDENCE_DIR / f"{code}.json"
    if f.exists():
        c = json.loads(f.read_text())
        cl = c.get("classification") or {}
        return {
            "device_class": cl.get("device_class") or None,
            "regulation_number": cl.get("regulation_number") or None,
            "source": f"openFDA device classification, stored in demo/company/evidence/{code}.json",
            "fetched": c.get("fetched_utc"),
        }
    if db is not None:
        votes: Counter[tuple[str | None, str | None]] = Counter()
        fetched = ""
        for raw, fa in db.execute(
            "select raw_json, fetched_at from raw_reports where product_code = ?", (code,)
        ):
            fetched = max(fetched, str(fa))
            for dev in json.loads(raw).get("device", []):
                if dev.get("device_report_product_code") != code:
                    continue
                o = dev.get("openfda") or {}
                votes[(o.get("device_class") or None, o.get("regulation_number") or None)] += 1
        if votes:
            (klass, reg), n = votes.most_common(1)[0]
            return {
                "device_class": klass,
                "regulation_number": reg,
                "source": f"openFDA fields of {n} MAUDE reports stored in data/demo/maudesignal_demo.db",
                "fetched": fetched[:19].replace(" ", "T") + "Z" if fetched else None,
            }
    return {
        "device_class": None,
        "regulation_number": None,
        "source": "not in stored data",
        "fetched": None,
    }


def pathway_for(plan: dict[str, Any], klass: str | None) -> str:
    """The pathway: PMA for class 3, else 510(k) unless the plan says De Novo."""
    if plan.get("pathway"):
        return str(plan["pathway"])
    return "PMA" if klass == "3" else "510(k)"


def build_dates(rng: random.Random, plan: dict[str, Any], pathway: str) -> dict[str, date | None]:
    """Milestone dates, built around the submission date (design, V&V, Pre-Sub, submission, ...)."""
    s = d(plan["submitted"])
    design_start = s - timedelta(days=rng.randint(700, 760))
    design_freeze = s - timedelta(days=rng.randint(380, 420))
    vv_start = s - timedelta(days=rng.randint(330, 360))
    vv_end = s - timedelta(days=rng.randint(150, 170))
    presub = s - timedelta(days=rng.randint(90, 110))
    lo, hi = FDA_DAYS[pathway]
    total_fda = rng.randint(lo, hi)
    ai_day = rng.randint(38, 55)
    ai_request = s + timedelta(days=ai_day)
    hold = rng.randint(45, 85)
    ai_response = ai_request + timedelta(days=hold)
    decided = ai_response + timedelta(days=total_fda - ai_day)
    decision: date | None = decided
    launch: date | None = decided + timedelta(days=rng.randint(35, 70))
    stage = plan["stage"]
    if stage == "under_review":
        if plan.get("ai_response"):
            # The response was sent: keep it in the past.
            ai_response = min(ai_response, AS_OF - timedelta(days=6))
        else:
            # The response is still being written: due date is planned, decision not known.
            ai_response = max(ai_response, AS_OF + timedelta(days=19))
        decision = None
        launch = None
    if stage == "decided" and launch is not None:
        launch = max(launch, d("2027-01-18"))
    return {
        "design_start": design_start,
        "design_freeze": design_freeze,
        "vv_start": vv_start,
        "vv_end": vv_end,
        "presub": presub,
        "submission": s,
        "ai_request": ai_request,
        "ai_response": ai_response,
        "decision": decision,
        "launch": launch,
    }


def fda_counts(dates: dict[str, date | None]) -> dict[str, int | None]:
    """FDA review days (clock running) and hold days (waiting on the AI response)."""
    s, a, r, dec = (
        dates["submission"],
        dates["ai_request"],
        dates["ai_response"],
        dates["decision"],
    )
    if not (s and a and r and dec):
        return {"fda_days": None, "hold_days": None}
    hold = (r - a).days
    return {"fda_days": (dec - s).days - hold, "hold_days": hold}


def protocols(
    rng: random.Random, plan: dict[str, Any], dates: dict[str, date | None], n0: int
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Test protocols with results, and the problems found and retested."""
    fam = plan["family"]
    vs, ve = dates["vv_start"], dates["vv_end"]
    assert vs and ve
    span = (ve - vs).days
    rows: list[tuple[str, str | None]] = [
        ("Software verification (unit and integration)", "IEC 62304"),
        ("Usability — summative evaluation", "IEC 62366-1"),
    ]
    if fam != "imaging_software":
        rows = [
            ("Electrical safety", "IEC 60601-1"),
            ("Electromagnetic compatibility (EMC)", "IEC 60601-1-2"),
        ] + rows
    if fam == "physio_monitor":
        rows.append(("Alarm system verification", "IEC 60601-1-8"))
        rows.append(("Biocompatibility (skin contact)", "ISO 10993-1"))
    rows.append(("Design validation — simulated use", None))
    out: list[dict[str, Any]] = []
    problems: list[dict[str, Any]] = []
    fail = plan.get("fail")
    for i, (title, std) in enumerate(rows):
        day = vs + timedelta(days=int(span * (i + 1) / (len(rows) + 2)))
        pid = f"TP-{n0 + i:03d}"
        failed = (
            (fail == "emc" and "EMC" in title)
            or (fail == "usability" and "Usability" in title)
            or (fail == "software" and "Software verification" in title)
        )
        out.append(
            {
                "id": pid,
                "title": title,
                "standard": std,
                **when(day),
                "result": "fail" if failed else "pass",
                "report": f"TR-{n0 + 100 + i}",
            }
        )
        if failed:
            retest_day = day + timedelta(days=rng.randint(28, 42))
            rid = f"TP-{n0 + i:03d}R"
            if fail == "emc":
                desc = "Radiated emissions exceeded the limit at one frequency band during EMC testing."
                change = "Added a ferrite on the display cable and a shielding gasket on the rear panel (design change DC-21)."
            elif fail == "usability":
                desc = "In the summative usability study, 3 of 15 simulated users missed the 'uncertain' marker on a result."
                change = "Made the marker larger, added a text label and a confirmation step (design change DC-14)."
            else:
                desc = "Integration test found that an alarm limit change was not saved after a restart."
                change = "Fixed limit storage and added a restart test to the regression suite (design change DC-09)."
            problems.append(
                {
                    "id": f"PR-{n0 + i:03d}",
                    "found_in": pid,
                    **when(day),
                    "description": desc,
                    "change": change,
                    "retest_id": rid,
                    "retest_date": iso(retest_day),
                    "retest_result": "pass",
                }
            )
            out.append(
                {
                    "id": rid,
                    "title": f"{title} — retest after change",
                    "standard": std,
                    **when(retest_day),
                    "result": "pass",
                    "report": f"TR-{n0 + 150 + i}",
                }
            )
    if plan["stage"] == "development":
        for p in out:
            p["result"] = "planned" if p["planned"] else p["result"]
    return out, problems


def study(
    rng: random.Random, plan: dict[str, Any], dates: dict[str, date | None]
) -> dict[str, Any] | None:
    """The simulated standalone performance study of an AI device (None otherwise)."""
    if not plan["ai"]:
        return None
    pos = rng.choice([180, 210, 240])
    neg = rng.choice([420, 480, 520])
    tp = int(pos * rng.uniform(0.88, 0.93))
    tn = int(neg * rng.uniform(0.86, 0.92))
    ve = dates["vv_end"]
    assert ve
    return {
        "label": "Standalone performance study (SIMULATED results on a simulated test set)",
        "date": iso(ve - timedelta(days=12)),
        "planned": False,
        "test_set": f"{pos + neg} cases from 3 sites not used in training ({pos} positive, {neg} negative; simulated)",
        "positives": pos,
        "negatives": neg,
        "true_positives": tp,
        "true_negatives": tn,
        "sensitivity": round(tp / pos, 3),
        "specificity": round(tn / neg, 3),
        "reference": "Consensus of two readers (simulated)",
    }


def months_between(a: date, b: date) -> list[str]:
    """Month keys YYYY-MM from a to b, inclusive."""
    out = []
    y, m = a.year, a.month
    while (y, m) <= (b.year, b.month):
        out.append(f"{y:04d}-{m:02d}")
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def build_profile(
    rng: random.Random, dev: dict[str, Any], n: int, db: sqlite3.Connection | None
) -> dict[str, Any]:
    """One device's simulated lifecycle profile."""
    plan = PLAN[dev["id"]]
    fam = plan["family"]
    cl = classification(dev["product_code"], db)
    pathway = pathway_for(plan, cl["device_class"])
    verb = VERB[pathway]
    dates = build_dates(rng, plan, pathway)
    stage = plan["stage"]
    num = f"{NUMBER_PREFIX[pathway]}{n:04d}"
    software = True
    st_label = STAGE_LABEL.get(stage) or f"{verb.capitalize()} — launch planned"

    milestones: list[dict[str, Any]] = []
    for key, label in (
        ("design_start", "Design started"),
        ("design_freeze", "Design review DR-2 (design freeze)"),
        ("vv_start", "V&V started"),
        ("vv_end", "V&V complete"),
        ("presub", "Pre-Sub meeting"),
        ("submission", f"{pathway} submitted"),
        ("ai_request", "FDA Additional Information request"),
        ("ai_response", "Response to AI request"),
        ("decision", f"{verb.capitalize()} by FDA"),
        ("launch", "Launch"),
    ):
        x = dates.get(key)
        if x is None:
            continue
        if stage == "development" and key in ("ai_request", "ai_response", "decision", "launch"):
            continue
        milestones.append({"key": key, "label": label, **when(x)})

    reviews = []
    for i, (key, name) in enumerate(
        (
            ("design_start", "DR-1 Design input review"),
            ("design_freeze", "DR-2 Design output review (design freeze)"),
            ("vv_end", "DR-3 Design transfer review"),
        )
    ):
        x = dates[key]
        assert x
        x = x + timedelta(days=14 if i == 0 else 0)
        attendees = [
            {"name": person(rng, f), "role": f}
            for f in ("Design Engineering", "Quality Engineering", "Regulatory Affairs", "Clinical")
        ]
        attendees.append(
            {
                "name": f"{rng.choice(PEOPLE['Design Engineering'][::-1])} (simulated)",
                "role": "Independent reviewer",
            }
        )
        reviews.append(
            {
                "id": f"DR-{i + 1}",
                "name": name,
                **when(x),
                "attendees": attendees,
                "outcome": "Planned" if x > AS_OF else "Approved with actions closed",
            }
        )

    prots, problems = protocols(rng, plan, dates, 100 + n * 20)
    stu = study(rng, plan, dates)

    presub = dates["presub"]
    assert presub
    regulatory: dict[str, Any] = {
        "pathway": pathway,
        "decision_verb": verb,
        "presub": {
            "number": f"Q-SIM-{n:04d}",
            **when(presub),
            "feedback": (
                []
                if presub > AS_OF
                else [
                    (
                        "FDA agreed with the proposed predicate approach in principle (simulated)."
                        if pathway == "510(k)"
                        else f"FDA discussed the {pathway} evidence plan (simulated)."
                    ),
                    (
                        "FDA asked for subgroup results by site and image vendor (simulated)."
                        if plan["ai"]
                        else (
                            "FDA asked for the full EMC and electrical safety test reports (simulated)."
                            if fam != "imaging_software"
                            else "FDA asked for cybersecurity documentation in the submission (simulated)."
                        )
                    ),
                ]
            ),
        },
        "submission": {"number": num, **when(dates["submission"])},  # type: ignore[arg-type]
        "ai_request": None,
        "ai_response": None,
        "decision": None,
        "predicate": (
            "A legally marketed device of the same product code with the same intended use (described generically; no real K-number)."
            if pathway == "510(k)"
            else None
        ),
        **(
            fda_counts(dates)
            if stage not in ("development", "under_review")
            else {"fda_days": None, "hold_days": None}
        ),
    }
    if stage != "development":
        a, r = dates["ai_request"], dates["ai_response"]
        assert a and r
        regulatory["ai_request"] = {
            **when(a),
            "summary": "FDA asked for more detail on "
            + (
                "the performance study test set"
                if plan["ai"]
                else "software anomaly assessment and labeling"
            )
            + " (simulated).",
        }
        regulatory["ai_response"] = {
            **when(r),
            "summary": (
                "Response being prepared; due by the planned date."
                if r > AS_OF
                else "Regulatory Affairs sent the added analyses and updated labeling (simulated)."
            ),
        }
        dec = dates["decision"]
        if dec:
            regulatory["decision"] = {**when(dec), "outcome": verb}

    market: dict[str, Any] = {
        "launch": None,
        "regions": [],
        "sites": None,
        "units_shipped": None,
        "udi_di": f"SIM-UDI-{dev['model']}-{n:03d}",
    }
    launch = dates["launch"]
    if launch and stage != "development":
        market["launch"] = when(launch)
        if launch <= AS_OF:
            years = max(1, (AS_OF - launch).days // 365 + 1)
            market["regions"] = rng.choice(REGIONS)
            market["sites"] = rng.choice([12, 20, 35, 50]) * years
            market["units_shipped"] = (
                {
                    "imaging_software": rng.choice([40, 80, 120]),
                    "imaging_hardware": rng.choice([20, 40, 60]),
                    "physio_monitor": rng.choice([300, 600, 1200]),
                }[fam]
                * years
                // 10
                * 10
            )
            # Sites never exceed units: one installation per software site, several units per hardware site.
            per_site = {"imaging_software": 1, "imaging_hardware": 2, "physio_monitor": 20}[fam]
            market["sites"] = max(5, market["units_shipped"] // per_site // 5 * 5)

    post: dict[str, Any] = {"complaints_by_month": [], "categories": [], "capas": []}
    if launch and launch <= AS_OF:
        months = months_between(
            max(launch, AS_OF - timedelta(days=360)), AS_OF - timedelta(days=AS_OF.day)
        )
        base = rng.randint(2, 6)
        counts = [max(0, base + rng.randint(-2, 3)) for _ in months]
        post["complaints_by_month"] = [
            {"month": m, "count": c} for m, c in zip(months, counts, strict=True)
        ]
        total = sum(counts)
        cats = COMPLAINT_CATEGORIES[fam]
        weights = [5, 3, 3, 2, 1]
        left = total
        rows = []
        for i, c in enumerate(cats):
            v = left if i == len(cats) - 1 else round(total * weights[i] / sum(weights))
            v = min(v, left)
            rows.append({"name": c, "count": v})
            left -= v
        post["categories"] = rows
        if stage == "post_market":
            o1 = AS_OF - timedelta(days=rng.randint(300, 420))
            post["capas"].append(
                {
                    "id": f"CAPA-SIM-{n:02d}1",
                    "title": f"Recurring '{cats[0].lower()}' complaints",
                    "owner": person(rng, "Quality Engineering"),
                    "opened": iso(o1),
                    "closed": iso(o1 + timedelta(days=rng.randint(90, 150))),
                    "state": "closed",
                }
            )
            o2 = AS_OF - timedelta(days=rng.randint(25, 70))
            post["capas"].append(
                {
                    "id": f"CAPA-SIM-{n:02d}2",
                    "title": f"Trend review: '{cats[1].lower()}' above monthly limit",
                    "owner": person(rng, "Quality Engineering"),
                    "opened": iso(o2),
                    "closed": None,
                    "state": "open",
                }
            )
        elif stage == "on_market" and n % 2 == 0:
            o1 = AS_OF - timedelta(days=rng.randint(150, 250))
            post["capas"].append(
                {
                    "id": f"CAPA-SIM-{n:02d}1",
                    "title": f"Labeling clarification for '{cats[3].lower()}'",
                    "owner": person(rng, "Quality Engineering"),
                    "opened": iso(o1),
                    "closed": iso(o1 + timedelta(days=rng.randint(45, 80))),
                    "state": "closed",
                }
            )

    # Activity log (past entries only, newest first).
    log: list[dict[str, Any]] = []

    def add(x: date | None, function: str, action: str, who: str | None = None) -> None:
        if x is None or x > AS_OF:
            return
        log.append(
            {
                "date": iso(x),
                "person": who or person(rng, function),
                "role": function,
                "action": action,
            }
        )

    add(
        dates["design_start"],
        "Design Engineering",
        "opened the design history file and design plan",
    )
    add(
        (dates["design_start"] + timedelta(days=14)) if dates["design_start"] else None,
        "Design Engineering",
        "held design review DR-1 (design inputs)",
    )
    add(dates["design_freeze"], "Management review", "approved design freeze at DR-2")
    add(
        dates["design_freeze"],
        "Quality Engineering",
        "approved the risk management plan (ISO 14971)",
    )
    add(dates["design_freeze"], "Clinical", "reviewed the clinical hazards in the risk analysis")
    for p in prots:
        if p["result"] == "fail":
            add(
                d(p["date"]),
                "Quality Engineering",
                f"recorded a failed test in {p['report']} ({p['id']})",
            )
        elif p["result"] == "pass":
            add(
                d(p["date"]) + timedelta(days=5),
                "Quality Engineering",
                f"approved test report {p['report']} ({p['id']})",
            )
    for pr in problems:
        add(
            d(pr["date"]) + timedelta(days=7),
            "Design Engineering",
            f"made the change for {pr['id']}: {pr['change'].split(' (')[0].lower()}",
        )
    if stu:
        add(
            d(stu["date"]),
            "Clinical",
            "signed the standalone performance study report (simulated results)",
        )
    add(dates["vv_end"], "Design Engineering", "held design review DR-3 (design transfer)")
    add(
        presub,
        "Regulatory Affairs",
        f"held the Pre-Sub meeting {regulatory['presub']['number']} with FDA",
    )
    add(dates["submission"], "Regulatory Affairs", f"submitted the {pathway} {num}")
    if stage != "development":
        add(
            dates["ai_request"],
            "Regulatory Affairs",
            "logged the FDA Additional Information request",
        )
        add(dates["ai_response"], "Regulatory Affairs", "submitted the response to the AI request")
        add(dates["decision"], "Regulatory Affairs", f"recorded the FDA decision: {verb}")
        add(launch, "Management review", "approved the launch")
    for c in post["capas"]:
        add(d(c["opened"]), "Quality Engineering", f"opened {c['id']}", c["owner"])
        if c["closed"]:
            add(
                d(c["closed"]),
                "Quality Engineering",
                f"closed {c['id']} after the effectiveness check",
                c["owner"],
            )
    if len(post["complaints_by_month"]) >= 2:
        last = post["complaints_by_month"][-2]["month"]
        add(
            d(f"{last}-01") + timedelta(days=33),
            "Post-Market Surveillance",
            f"published the monthly complaint trend for {last}",
        )
        add(
            AS_OF - timedelta(days=rng.randint(40, 80)),
            "Management review",
            "reviewed complaint trends and open CAPAs",
        )
    for h in dev.get("history", []):
        add(
            d(h["date"]),
            "Post-Market Surveillance",
            f"set 'Does this apply to us?' to {h['to_status']}",
            h["actor"],
        )
    log.sort(key=lambda e: (e["date"], e["role"], e["action"]), reverse=True)

    overview = {
        "fda_device_name": (dev.get("device_type") or {}).get("name") or None,
        "fda_name_source": (dev.get("device_type") or {}).get("source") or "not in stored data",
        "device_class": cl["device_class"],
        "regulation_number": cl["regulation_number"],
        "classification_source": cl["source"],
        "classification_fetched": cl["fetched"],
        "pathway": pathway,
        "intended_use": INTENDED_USE[fam]
        + (AI_USE if plan["ai"] else "")
        + " (Simulated intended use.)",
        "stage": stage,
        "status_label": st_label,
        "software": software,
        "ai": plan["ai"],
    }
    sw = {
        "iec62304_class": "C" if fam == "physio_monitor" else "B",
        "documentation_level": (
            "Enhanced" if fam == "physio_monitor" or plan["ai"] or pathway == "PMA" else "Basic"
        ),
    }
    return {
        "id": dev["id"],
        "name": dev["name"],
        "model": dev["model"],
        "product_code": dev["product_code"],
        "owner": dev["owner"],
        "simulated": True,
        "overview": overview,
        "milestones": milestones,
        "design": {
            "inputs": [
                {"id": f"DI-{i + 1:02d}", "text": t} for i, t in enumerate(DESIGN_INPUTS[fam])
            ],
            "outputs": [
                {"id": f"DO-{i + 1:02d}", "text": t} for i, t in enumerate(DESIGN_OUTPUTS[fam])
            ],
            "hazards": [
                {
                    "id": f"HZ-{i + 1:02d}",
                    "hazard": h,
                    "harm": hm,
                    "severity": sv,
                    "control": c,
                    "residual": r,
                }
                for i, (h, hm, sv, c, r) in enumerate(HAZARDS[fam])
            ],
            "software": sw,
            "reviews": reviews,
        },
        "vv": {"protocols": prots, "problems": problems, "study": stu},
        "regulatory": regulatory,
        "market": market,
        "postmarket": post,
        "activity": log,
    }


def build() -> dict[str, Any]:
    """The whole file."""
    company = json.loads(COMPANY.read_text())
    rng = random.Random(SEED)
    db = sqlite3.connect(f"file:{DEMO_DB}?mode=ro", uri=True) if DEMO_DB.exists() else None
    try:
        profiles = {
            dev["id"]: build_profile(rng, dev, i + 1, db)
            for i, dev in enumerate(company["devices"])
            if dev["id"] in PLAN
        }
    finally:
        if db is not None:
            db.close()
    return {
        "schema_version": "1.0",
        "simulated": True,
        "banner": BANNER,
        "company": company.get("company"),
        "as_of": iso(AS_OF),
        "seed": SEED,
        "generated_by": "scripts/build_company_profiles.py",
        "real_fields": [
            "product_code",
            "overview.fda_device_name",
            "overview.device_class",
            "overview.regulation_number",
        ],
        "profiles": profiles,
    }


def render() -> str:
    """The file text (stable JSON)."""
    return json.dumps(build(), indent=1, ensure_ascii=False) + "\n"


def main(argv: list[str] | None = None) -> int:
    """Write the file, or check it is up to date."""
    ap = argparse.ArgumentParser(description="Build the simulated device lifecycle profiles.")
    ap.add_argument(
        "--check", action="store_true", help="exit 1 when the stored file is out of date"
    )
    args = ap.parse_args(argv)
    text = render()
    if args.check:
        same = OUT.exists() and OUT.read_text() == text
        print("up to date" if same else f"{OUT} is out of date; run without --check")
        return 0 if same else 1
    OUT.write_text(text)
    print(f"wrote {OUT.relative_to(ROOT)} ({len(text)} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
