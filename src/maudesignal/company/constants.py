"""Constants for the simulated-company workflow ("Does this apply to us?").

Everything about the company is SAMPLE data kept in ``demo/company/``. The problem
evidence next to it (MAUDE reports, recalls) is real FDA data. The two are never mixed:
the company files hold no report, recall or count; the evidence files hold no company.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]

#: Printed on every screen and every PDF section that shows the simulated company.
BANNER = "Simulated company — sample data. Problem evidence is real FDA data."

COMPANY_NAME = "Demo MedTech Co. (simulated)"

#: Suffix every simulated person's name carries, so a log line can never be mistaken
#: for a real person.
SIMULATED_SUFFIX = "(simulated)"

# Statuses, in the only order a device may move through them (forward-only).
S_NEEDS_REVIEW = "Needs review"
S_TESTING = "Testing in progress"
S_COVERED = "Already covered"
S_NOT_APPLICABLE = "Not applicable to our device"
S_MONITORING = "Monitoring — nothing open"

#: Rank of each status. A change must move to a strictly higher rank, so a status never
#: moves backwards and never moves sideways (covered <-> not applicable is rejected).
STATUS_RANK: dict[str, int] = {
    S_NEEDS_REVIEW: 1,
    S_TESTING: 2,
    S_COVERED: 3,
    S_NOT_APPLICABLE: 3,
    S_MONITORING: 4,
}
STATUSES: tuple[str, ...] = tuple(STATUS_RANK)

#: Detail fields each status needs (a status without them is rejected).
STATUS_REQUIRED: dict[str, tuple[str, ...]] = {
    S_NEEDS_REVIEW: ("owner",),
    S_TESTING: ("owner", "due_date"),
    S_COVERED: ("reference",),
    S_NOT_APPLICABLE: ("reason",),
    S_MONITORING: (),
}

ACTION_REGISTER = "company.status.register"
ACTION_CHANGE = "company.status.change"

#: Names that are the tool, a model or a system, never a named simulated person.
TOOL_ACTORS = frozenset(
    {"tool", "system", "maudesignal", "claude", "muse", "spark", "model", "ai", "bot", "auto"}
)

#: Words and phrases no company surface may print (also checked in verbatim quotes).
FORBIDDEN = re.compile(
    r"\b(safe|unsafe|compliant|validated|overnight)\b"
    r"|fda[- ]approved|part 11 compliant|worsening signals?|citation-checked|complaint data",
    re.IGNORECASE,
)

MAUDE_DETAIL_URL = (
    "https://www.accessdata.fda.gov/scripts/cdrh/cfdocs/cfmaude/detail.cfm?mdrfoi__id={}"
)
CLASSIFICATION_ENDPOINT = "https://api.fda.gov/device/classification.json"
EVENT_ENDPOINT = "https://api.fda.gov/device/event.json"
RECALL_ENDPOINT = "https://api.fda.gov/device/recall.json"

#: A fetched or stored group needs at least this many reports to be called a pattern.
MIN_PATTERN_REPORTS = 2
#: Verbatim quotes per pattern, and their length window (characters).
MAX_QUOTES = 2
QUOTE_MIN_CHARS = 40
QUOTE_MAX_CHARS = 220


def company_dir() -> Path:
    """Folder of the simulated-company files (``MAUDESIGNAL_COMPANY_DIR`` overrides)."""
    return Path(os.environ.get("MAUDESIGNAL_COMPANY_DIR", str(PROJECT_ROOT / "demo" / "company")))


def demo_db_path() -> Path:
    """The committed demo database the evidence is read from, read-only."""
    return Path(
        os.environ.get(
            "MAUDESIGNAL_COMPANY_DB", str(PROJECT_ROOT / "data" / "demo" / "maudesignal_demo.db")
        )
    )


def investigations_dir() -> Path:
    """Recorded weekly-investigator runs whose groups the company page reuses."""
    return PROJECT_ROOT / "demo" / "investigations"


def sweep_path() -> Path:
    """The recorded AI-device sweep the flagged / stable codes are taken from."""
    return PROJECT_ROOT / "demo" / "sweep" / "ai-device-sweep.json"


def contains_forbidden(text: str) -> bool:
    """True when ``text`` holds a word the company surfaces never print."""
    return FORBIDDEN.search(text) is not None
