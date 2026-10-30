"""The "Simulated company checklist" section of the CAPA-need evidence pack PDF.

For the pack's product code: the simulated company's devices on that code, each device's
status (named simulated person, date) and the real problem patterns on the code. No pack
number is changed or recomputed here.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from maudesignal.company.build import NOT_FETCHED, load_company, status_detail
from maudesignal.company.constants import BANNER, COMPANY_NAME


@dataclass(frozen=True)
class ChecklistPattern:
    """One pattern line."""

    label: str
    count: int
    basis: str


@dataclass(frozen=True)
class ChecklistDevice:
    """One device row of the checklist."""

    device_id: str
    name: str
    model: str
    owner: str
    status: str
    status_detail: str
    set_by: str
    status_date: str
    patterns: tuple[ChecklistPattern, ...]
    evidence_note: str | None


@dataclass(frozen=True)
class CompanyChecklist:
    """Checklist section data."""

    banner: str
    company: str
    product_code: str
    devices: tuple[ChecklistDevice, ...]
    chain_ok: bool
    note: str


def checklist_for(product_code: str, folder: Path | None = None) -> CompanyChecklist | None:
    """The checklist for one product code, or None when the company has no device on it."""
    try:
        view = load_company(folder)
    except FileNotFoundError:
        return None
    on_code = view.on_code(product_code)
    if not on_code:
        return None
    rows = []
    for d in on_code:
        s = d.status
        rows.append(
            ChecklistDevice(
                device_id=d.device_id,
                name=d.name,
                model=d.model,
                owner=d.owner,
                status=s.to_status if s else "no status yet",
                status_detail=status_detail(s) if s else "",
                set_by=s.actor if s else "",
                status_date=s.date_label if s else "",
                patterns=tuple(ChecklistPattern(p.label, p.count, p.basis) for p in d.patterns),
                evidence_note=d.evidence_note
                or ("no pattern found by the stored rules" if not d.patterns else None),
            )
        )
    return CompanyChecklist(
        banner=BANNER,
        company=COMPANY_NAME,
        product_code=product_code,
        devices=tuple(rows),
        chain_ok=view.chain_ok,
        note=(
            "Statuses are set by the named simulated people shown, never by this tool. "
            f"A device with “{NOT_FETCHED}” has no stored real reports yet, so no "
            "pattern is shown for it."
        ),
    )
