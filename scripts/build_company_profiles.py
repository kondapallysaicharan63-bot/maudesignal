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


# --- PMS decision paths (F22/F23, simulated) ---------------------------------------------------
# People decide, the tool supplies evidence. Each path is: triage -> PMS review board -> outcome -> risk.
# The plan below is hand-written (dates, outcomes, rationale) so a reviewer can read it; only the names of
# simulated people are drawn from the seeded generator.

CLAUSES: dict[str, dict[str, str]] = {
    "qmsr": {
        "tag": "21 CFR 820 (QMSR)",
        "why": "The quality system rule requires documented complaint handling and corrective action; it incorporates ISO 13485.",
    },
    "i821": {
        "tag": "ISO 13485 §8.2.1",
        "why": "Feedback: post-market information, here the FDA problem pattern, is collected as an input to the quality system.",
    },
    "i822": {
        "tag": "ISO 13485 §8.2.2",
        "why": "Complaint handling: each complaint is assessed, and a decision not to investigate is recorded with its reason.",
    },
    "i823": {
        "tag": "ISO 13485 §8.2.3",
        "why": "Reporting to regulatory authorities: the company sets and applies criteria for what must be reported.",
    },
    "i852": {
        "tag": "ISO 13485 §8.5.2",
        "why": "Corrective action: the cause is addressed, the action has an owner and a due date, and its effect is checked.",
    },
    "r803": {
        "tag": "21 CFR 803",
        "why": "Medical device reporting: the manufacturer assesses reportability and reports within 30 calendar days of becoming aware.",
    },
    "r806": {
        "tag": "21 CFR 806",
        "why": "Corrections and removals: a correction or removal made to reduce a health risk is assessed for a report.",
    },
    "r7": {
        "tag": "21 CFR 7",
        "why": "Recall policy: the firm considers whether the situation calls for a recall and documents why or why not.",
    },
    "i14971": {
        "tag": "ISO 14971",
        "why": "Risk management: production and post-production information is fed back and the risk file is reviewed and updated.",
    },
}

STEP_CLAUSES: dict[str, list[str]] = {
    "triage": ["i821", "i822", "qmsr"],
    "board": ["i822", "i823"],
    "ntf": ["i822", "qmsr"],
    "capa": ["i852", "qmsr"],
    "escalation": ["r803", "r806", "r7", "i823"],
    "risk": ["i14971"],
}

SEVERITY = ["Negligible", "Minor", "Serious", "Critical", "Catastrophic"]
PROBABILITY = ["Improbable", "Remote", "Occasional", "Probable", "Frequent"]
ATTENDEE_ROLES = [
    "Quality Engineering",
    "Regulatory Affairs",
    "Clinical",
    "Design Engineering",
    "Post-Market Surveillance",
]

# kind: ntf (note to file), capa, recall (escalation assessment, recall not warranted),
# mdr (escalation assessment, reportable), open (no outcome yet). risk: (S, P) before and after.
PATH_PLAN: dict[str, list[dict[str, Any]]] = {
    "DMC-01": [
        {
            "signal": "LLZ-inv-2",
            "kind": "ntf",
            "triage": "2026-10-12",
            "board": "2026-10-19",
            "outcome": "2026-10-19",
            "risk": (2, 2, 2, 2),
            "summary": "No complaint on our device matches this pattern; the report-finalising path in our software differs from the one described.",
            "rationale": "No matching complaint on our device in the last 12 months (simulated search). The failure described depends on a third-party server setup we do not ship.",
        },
        {
            "signal": "LLZ-inv-3",
            "kind": "recall",
            "triage": "2026-10-12",
            "board": "2026-10-26",
            "outcome": "2026-10-26",
            "risk": (2, 3, 2, 3),
            "summary": "Sign-in errors are described. Our complaint file has two server-error complaints (simulated) with a documented workaround and no effect on the images shown.",
            "assess": {
                "mdr": "not reportable",
                "corr": "not reportable",
                "recall": "recall not warranted",
            },
            "mdr_why": "No death or serious injury, and the malfunction would not be likely to cause or contribute to one if it recurred: the user can sign in again and the images are unchanged.",
            "corr_why": "No correction or removal is being made to reduce a risk to health; the workaround is a user instruction already in the manual.",
            "recall_why": "The board found no reasonable probability of serious adverse health consequences; the issue is an availability inconvenience with a workaround. Considered and ruled out; revisit if complaints rise.",
        },
        {
            "signal": "LLZ-inv-1",
            "kind": "capa",
            "triage": "2026-10-12",
            "board": "2026-10-23",
            "outcome": "2026-10-30",
            "risk": (3, 4, 3, 2),
            "summary": "Two complaints on our device (simulated) match this pattern and both involve a study shown without its prior images.",
            "capa_title": "Prior images missing after a server error",
            "capa_due": "2026-12-18",
            "capa_state": "open",
            "capa_status": "Testing in progress: fix built, regression test running",
        },
    ],
    "DMC-02": [
        {
            "signal": "LLZ-inv-2",
            "kind": "ntf",
            "triage": "2026-10-12",
            "board": "2026-10-21",
            "outcome": "2026-10-21",
            "risk": (2, 2, 2, 2),
            "summary": "ReportDesk shares no code with the finalise step described.",
            "rationale": "Already covered: our report workflow saves a local draft, so a failed finalise does not lose work (software verification, simulated).",
        },
        {
            "signal": "LLZ-inv-3",
            "kind": "ntf",
            "triage": "2026-10-12",
            "board": "2026-10-21",
            "outcome": "2026-10-21",
            "risk": (2, 2, 2, 2),
            "summary": "Connection errors are handled by the same retry path reviewed for the sister product.",
            "rationale": "Already covered by the retry and error-message design and by the CAPA opened for the sister product.",
        },
        {
            "signal": "LLZ-inv-1",
            "kind": "ntf",
            "triage": "2026-10-12",
            "board": "2026-10-28",
            "outcome": "2026-10-30",
            "risk": (3, 2, 3, 2),
            "summary": "Same pattern as the sister product's corrective action; the shared component is fixed there.",
            "rationale": "Already covered: the shared component is corrected under the sister product's open CAPA, and this device takes the same release.",
        },
    ],
    "DMC-03": [
        {
            "signal": "QIH-patient-data",
            "kind": "open",
            "triage": "2026-10-20",
            "board": "2026-11-06",
            "summary": "Agenda: does a pattern about patient data attached to the wrong study apply to the design under review?",
        }
    ],
    "DMC-04": [
        {
            "signal": "MYN-wrong-result",
            "kind": "capa",
            "triage": "2026-09-16",
            "board": "2026-09-23",
            "outcome": "2026-09-25",
            "risk": (4, 3, 4, 2),
            "summary": "One complaint on our device (simulated) reported a result that disagreed with the reader's own finding. The board asked for a corrective action.",
            "capa_title": "Corrective action: result disagreement on low-contrast slides",
            "capa_due": "2026-10-30",
            "capa_state": "closed",
            "capa_status": "Closed 2026-10-27 after the effectiveness check",
        }
    ],
    "DMC-06": [
        {
            "signal": "IYN-freeze-crash",
            "kind": "mdr",
            "triage": "2026-09-03",
            "board": "2026-09-10",
            "outcome": "2026-09-10",
            "risk": (4, 3, 4, 2),
            "summary": "Complaint COMP-SIM-0309 (simulated): the system froze during a time-critical guided procedure; the procedure was finished on another system after a delay. No injury was reported.",
            "receipt": "2026-09-02",
            "submitted": "2026-09-24",
            "assess": {
                "mdr": "reportable",
                "corr": "not reportable",
                "recall": "recall not warranted",
            },
            "mdr_why": "No injury occurred, but the board assessed that a freeze in a time-critical procedure would be likely to cause or contribute to serious injury if it recurred, so it assessed the event as reportable.",
            "corr_why": "A software update is planned in the normal release cycle; it is not a removal or correction made to reduce a risk to health.",
            "recall_why": "One event, the system recovers on restart, and the update is already scheduled. Considered and ruled out as not warranted.",
        },
        {
            "signal": "IYN-display-quality",
            "kind": "ntf",
            "triage": "2026-09-03",
            "board": "2026-09-10",
            "outcome": "2026-09-10",
            "risk": (2, 2, 2, 2),
            "summary": "Display artefact reports concern a transducer type we do not ship with this system.",
            "rationale": "Not our configuration: the artefact described occurs with a transducer outside our labeled configuration. Daily phantom check remains the control.",
        },
        {
            "signal": "IYN-load-transfer",
            "kind": "open",
            "triage": "2026-10-30",
            "board": "2026-11-10",
            "summary": "Agenda: images or data failing to load or transfer; two complaints on our device since the MDR assessment (simulated).",
        },
    ],
    "DMC-07": [
        {
            "signal": None,
            "kind": "open",
            "triage": "2026-10-30",
            "board": "2026-11-05",
            "summary": "Agenda: the weekly count for this product code is above its recent baseline; are any reports about a function our device has?",
        }
    ],
    "DMC-08": [
        {
            "signal": None,
            "kind": "open",
            "triage": "2026-10-30",
            "board": "2026-11-04",
            "summary": "Agenda: the share of serious reports for this product code rose; is the failure described one our alarm design can show?",
        }
    ],
    "DMC-09": [
        {
            "signal": "MUD-wrong-result",
            "kind": "open",
            "triage": "2026-10-30",
            "board": "2026-11-12",
            "summary": "Agenda: wrong-reading reports for this product code; pre-market, so the question is whether the design inputs and risk file already cover them.",
        }
    ],
    "DMC-12": [
        {
            "signal": "MWI-wrong-result",
            "kind": "open",
            "triage": "2026-10-30",
            "board": "2026-10-31",
            "held": True,
            "summary": "Fifteen reports of wrong readings were reviewed against the accuracy verification. The board asked Clinical for a sensor-site comparison before deciding.",
            "decision": "Hold: reconvene on 2026-11-14 with the Clinical comparison.",
        }
    ],
}

NO_PATH_REASON = {
    "Not applicable to our device": "No decision path: the owner recorded this product code as not applicable to our device.",
}


def clause_tags(*keys: str) -> list[dict[str, str]]:
    """The compliance chips of a step, each with its one-line reason."""
    return [dict(CLAUSES[k]) for k in keys]


def risk_cell(s: int, p: int) -> dict[str, Any]:
    """A cell of the 5x5 risk matrix (severity x probability) with its zone."""
    score = s * p
    zone = (
        "acceptable"
        if score <= 4
        else "reduce as far as possible" if score <= 9 else "not acceptable"
    )
    return {
        "severity": s,
        "severity_label": SEVERITY[s - 1],
        "probability": p,
        "probability_label": PROBABILITY[p - 1],
        "score": score,
        "zone": zone,
    }


def build_decision(
    rng: random.Random, dev: dict[str, Any], n: int, profile_stage: str, post: dict[str, Any]
) -> dict[str, Any]:
    """The decision paths of one device; adds the CAPA of a CAPA outcome to ``post['capas']``."""
    label = (dev.get("status") or {}).get("label") or ""
    plan = PATH_PLAN.get(dev["id"], [])
    if not plan:
        reason = NO_PATH_REASON.get(label)
        if reason is None:
            reason = "No decision path: no problem pattern or sweep signal is stored for this product code."
        return {"none_reason": reason, "paths": []}
    owner = dev["owner"]
    pre_market = profile_stage in ("development", "under_review", "decided")
    paths: list[dict[str, Any]] = []
    for k, e in enumerate(plan, start=1):
        kind = e["kind"]
        board_day = d(e["board"])
        held = board_day <= AS_OF
        attendees = [{"name": person(rng, r), "role": r} for r in ATTENDEE_ROLES]
        decision_text: str | None
        if kind == "open":
            decision_text = e.get("decision")
        elif kind == "ntf":
            decision_text = "Note to file: no further action, rationale documented."
        elif kind == "capa":
            decision_text = "Open a CAPA."
        else:
            decision_text = (
                "Escalation assessment recorded (reportability, correction or removal, recall)."
            )
        triage_day = d(e["triage"])
        path: dict[str, Any] = {
            "id": f"DP-{dev['id']}-{k}",
            "signal": {
                "kind": "sweep" if e["signal"] is None else "pattern",
                "pattern_id": e["signal"],
            },
            "state": "open" if kind == "open" else "decided",
            "pre_market": pre_market,
            "triage": {
                **when(triage_day),
                "owner": owner,
                "role": "Post-Market Surveillance",
                "note": "Owner assigned; the signal was logged for the board agenda.",
                "tags": clause_tags(*STEP_CLAUSES["triage"]),
            },
            "board": {
                **when(board_day),
                "held": held,
                "attendees": attendees,
                "summary": e["summary"],
                "decision": decision_text if held else None,
                "tags": clause_tags(*STEP_CLAUSES["board"]),
            },
            "outcome": None,
            "risk": None,
        }
        if kind == "open":
            paths.append(path)
            continue
        out_day = d(e["outcome"])
        signer = person(rng, "Quality Engineering")
        if kind == "ntf":
            path["outcome"] = {
                "kind": "ntf",
                **when(out_day),
                "rationale": e["rationale"],
                "signed_by": signer,
                "signed_role": "Quality Engineering",
                "tags": clause_tags(*STEP_CLAUSES["ntf"]),
            }
        elif kind == "capa":
            if e["capa_state"] == "open":  # replaces the generic trend-review CAPA of the device
                post["capas"] = [c for c in post["capas"] if c["state"] != "open"]
            capa_id = f"CAPA-SIM-{n:02d}{len(post['capas']) + 1:02d}"
            due = d(e["capa_due"])
            capa = {
                "id": capa_id,
                "title": e["capa_title"],
                "owner": person(rng, "Quality Engineering"),
                "opened": iso(out_day),
                "closed": None if e["capa_state"] == "open" else iso(due - timedelta(days=3)),
                "state": e["capa_state"],
            }
            post["capas"].append(capa)
            path["outcome"] = {
                "kind": "capa",
                **when(out_day),
                "capa_id": capa_id,
                "owner": capa["owner"],
                "due": iso(due),
                "due_planned": due > AS_OF,
                "status": e["capa_status"],
                "tags": clause_tags(*STEP_CLAUSES["capa"]),
            }
        else:
            a = e["assess"]
            mdr: dict[str, Any] = {"result": a["mdr"], "rationale": e["mdr_why"]}
            if a["mdr"] == "reportable":
                receipt, sub = d(e["receipt"]), d(e["submitted"])
                mdr.update(
                    receipt_date=iso(receipt),
                    due_date=iso(receipt + timedelta(days=30)),
                    submitted_date=iso(sub),
                    day_of_30=(sub - receipt).days,
                    clock_note=(
                        "The 30 calendar days of 21 CFR 803 run from the day the company became aware of the event, "
                        f"here its receipt of complaint COMP-SIM-0309 (simulated) on {niceish(receipt)}. They do not "
                        "run from the date any report appears in FDA's database. Regulatory Affairs recorded the "
                        "submission as made on a simulated date inside the 30 days; MaudeSignal files nothing."
                    ),
                )
            path["outcome"] = {
                "kind": "escalation",
                **when(out_day),
                "assessed_by": "the board",
                "mdr": mdr,
                "correction_removal": {"result": a["corr"], "rationale": e["corr_why"]},
                "recall": {"result": a["recall"], "rationale": e["recall_why"]},
                "signed_by": signer,
                "signed_role": "Regulatory Affairs",
                "tags": clause_tags(*STEP_CLAUSES["escalation"]),
            }
        sb, pb, sa, pa = e["risk"]
        hhe = {
            "ntf": "Health hazard evaluation not needed: no new hazard or harm was identified; the risk file was reviewed and left unchanged.",
            "capa": "Health hazard evaluation (simulated): the worst credible harm is a delayed or repeated study; the corrective action is expected to lower the probability.",
            "recall": "Health hazard evaluation (simulated): an unavailable sign-in is a delay, not a harm to the patient; no change to the risk estimate.",
            "mdr": "Health hazard evaluation (simulated): a freeze during a time-critical procedure can delay care; the planned update lowers the probability of recurrence.",
        }[kind]
        changed = (sb, pb) != (sa, pa)
        path["risk"] = {
            "hhe_summary": hhe,
            "before": risk_cell(sb, pb),
            "after": risk_cell(sa, pa),
            "after_is_expected": changed
            and ((kind == "capa" and e["capa_state"] == "open") or kind == "mdr"),
            "risk_file": {
                "ref": f"RMF-{dev['model']}-rev{2 + (k % 3)}",
                **when(
                    out_day + timedelta(days=2) if out_day + timedelta(days=2) <= AS_OF else out_day
                ),
                "change": "Risk estimate updated" if changed else "Reviewed, no change",
            },
            "tags": clause_tags(*STEP_CLAUSES["risk"]),
        }
        paths.append(path)
    order = {"open": 0, "decided": 1}
    paths.sort(key=lambda x: (order[x["state"]], x["triage"]["date"]))
    return {"none_reason": None, "paths": paths}


def niceish(x: date) -> str:
    """A date as '2 Sep 2026' for sentences in the data."""
    return f"{x.day} {x.strftime('%b %Y')}"


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
                    "id": f"CAPA-SIM-{n:02d}01",
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
                    "id": f"CAPA-SIM-{n:02d}02",
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
                    "id": f"CAPA-SIM-{n:02d}01",
                    "title": f"Labeling clarification for '{cats[3].lower()}'",
                    "owner": person(rng, "Quality Engineering"),
                    "opened": iso(o1),
                    "closed": iso(o1 + timedelta(days=rng.randint(45, 80))),
                    "state": "closed",
                }
            )

    decision = build_decision(rng, dev, n, stage, post)

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
    for dp in decision["paths"]:
        add(
            d(dp["triage"]["date"]),
            "Post-Market Surveillance",
            f"triaged the signal for {dp['id']}",
            dp["triage"]["owner"],
        )
        if dp["board"]["held"]:
            add(
                d(dp["board"]["date"]),
                "Quality Engineering",
                f"took part in the PMS review board for {dp['id']}",
            )
        oc = dp["outcome"]
        if oc and oc["kind"] == "ntf":
            add(
                d(oc["date"]),
                "Quality Engineering",
                f"signed the note to file for {dp['id']}",
                oc["signed_by"],
            )
        elif oc and oc["kind"] == "escalation":
            add(
                d(oc["date"]),
                "Regulatory Affairs",
                f"recorded the board's assessments (reportability, correction or removal, recall) for {dp['id']}",
                oc["signed_by"],
            )
        if dp["risk"]:
            add(
                d(dp["risk"]["risk_file"]["date"]),
                "Design Engineering",
                f"updated the risk file {dp['risk']['risk_file']['ref']} after {dp['id']}",
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
        "decision": decision,
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
