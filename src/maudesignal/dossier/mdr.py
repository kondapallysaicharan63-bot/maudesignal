"""MDR assessment worksheet mapped to FDA Form 3500A.

HACKATHON-BUILT — Meta Global AI Developer Hackathon (Oct 26 – Nov 4, 2026).

Section letters and item numbers follow the 3500A mandatory-reporting
instructions; the 21 CFR 803.52 paragraph each item answers is listed beside
it (sources: ``docs/dossier_sources.md``). MaudeSignal pre-fills only what
openFDA already published for the cited reports (brand, model, manufacturer,
product code, event type, date received, 510(k) number). Everything else is
left blank for the manufacturer. Reportability is never decided here.

The due dates reuse ``maudesignal.copilot.tools.deadline_check`` so the
worksheet and the copilot can never disagree.
"""

from __future__ import annotations

from datetime import date

from maudesignal.copilot.tools import deadline_check
from maudesignal.dossier.model import DeviceInfo, MdrRow, MdrWorksheet

BLANK = ""
NOT_PREFILLED_PHI = "Not pre-filled — MaudeSignal handles no patient-identifying information"


def _join(values: tuple[str, ...], limit: int = 6) -> str:
    if not values:
        return BLANK
    shown = list(values[:limit])
    more = len(values) - len(shown)
    return "; ".join(shown) + (f"; +{more} more" if more > 0 else "")


def worksheet_rows(
    device: DeviceInfo,
    *,
    event_types: tuple[str, ...],
    date_received_range: tuple[str, str] | None,
) -> tuple[MdrRow, ...]:
    """Build the 3500A-mapped rows with openFDA pre-fills where available.

    Args:
        device: Device identification from the cited reports.
        event_types: Distinct openFDA event types among the cited reports.
        date_received_range: ``(earliest, latest)`` FDA date_received (ISO dates).

    Returns:
        Worksheet rows in 3500A order.
    """
    rng = f"{date_received_range[0]} to {date_received_range[1]}" if date_received_range else ""
    of = "openFDA device event"
    r = MdrRow
    # fmt: off
    return (
        r("A", "A1–A5", "Patient identifier, age, sex, weight, race/ethnicity", "803.52(a)",
          NOT_PREFILLED_PHI, "—"),
        r("B", "B1", "Type of report (adverse event / product problem …)", "803.52(b)", BLANK, "—"),
        r("B", "B2", "Outcomes attributed to adverse event", "803.52(b)", BLANK, "—"),
        r("B", "B3", "Date of event", "803.52(b)",
          "Per report — not in the evidence table; open each FDA record (date received is shown)",
          "—"),
        r("B", "B5", "Describe event or problem", "803.52(b)",
          "Per report — MAUDE narrative excerpts in Evidence table", "mdr_text"),
        r("B", "B6–B7", "Relevant tests/laboratory data; other relevant history", "803.52(b)",
          BLANK, "—"),
        r("D", "D1", "Brand name", "803.52(c)", _join(device.brand_names),
          f"{of}: device.brand_name"),
        r("D", "D2a", "Product code (procode)", "803.52(c)", device.product_code,
          f"{of}: device.device_report_product_code"),
        r("D", "D2b", "Common device name", "803.52(c)",
          _join(device.generic_names) or (device.classification_name or BLANK),
          f"{of}: device.generic_name"),
        r("D", "D3", "Manufacturer name, city, state, country", "803.52(c)",
          _join(device.manufacturers), f"{of}: device.manufacturer_d_*"),
        r("D", "D4", "Model #, lot #, catalog #, serial #, UDI", "803.52(c)",
          ("Model: " + _join(device.model_numbers)) if device.model_numbers else BLANK,
          f"{of}: device.model_number"),
        r("D", "D5–D10", "Operator, implant/explant dates, reprocessing, 3rd-party service, "
          "availability for evaluation, concomitant products", "803.52(c)", BLANK, "—"),
        r("E", "E1–E4", "Initial reporter (name, address, health professional, occupation)",
          "803.52(d)", BLANK, "—"),
        r("F", "F1–F13", "User facility / importer block", "803.52(f)(11)",
          "Not applicable to a manufacturer report unless correcting UF/importer data", "—"),
        r("G", "G1", "Contact office and manufacturing site", "803.52(e)", BLANK, "—"),
        r("G", "G2", "Report source", "803.52(e)", BLANK, "—"),
        r("G", "G3", "Date received by manufacturer (awareness)", "803.52(e)",
          "See awareness date above (human entry)", "user input"),
        r("G", "G4", "PMA / 510(k) number", "803.52(e)", _join(device.k_numbers),
          f"{of}: pma_pmn_number"),
        r("G", "G6", "Type of report (initial / follow-up / 5-day …)", "803.52(e)", BLANK, "—"),
        r("G", "G7", "Adverse event term(s)", "803.52(e)", BLANK, "—"),
        r("G", "G8", "Manufacturer report number", "803.52(e)", BLANK, "—"),
        r("H", "H1", "Type of reportable event (death / serious injury / malfunction)",
          "803.52(f)", ("openFDA event_type observed: " + ", ".join(event_types))
          if event_types else BLANK, f"{of}: event_type (reference only)"),
        r("H", "H3", "Device evaluated by manufacturer? (summary or reason not)", "803.52(f)",
          BLANK, "—"),
        r("H", "H6", "Adverse event problem codes (device, patient, evaluation)", "803.52(f)",
          BLANK, "—"),
        r("H", "H7", "Remedial action initiated (type)", "803.52(f)", BLANK, "—"),
        r("H", "H9", "Correction/removal report number (21 USC 360i(g))", "803.52(f)", BLANK,
          "—"),
        r("H", "H10", "Additional manufacturer narrative", "803.52(f)", BLANK, "—"),
        r("—", "FDA", "Date received by FDA (MAUDE)", "—", rng, f"{of}: date_received"),
    )
    # fmt: on


def build_worksheet(
    device: DeviceInfo,
    *,
    awareness_date: date | None,
    awareness_basis: str,
    event_types: tuple[str, ...],
    date_received_range: tuple[str, str] | None,
) -> MdrWorksheet:
    """Assemble the worksheet; due dates only when a human-entered awareness date exists."""
    due_30 = due_5 = None
    if awareness_date is not None:
        ymd = awareness_date.strftime("%Y%m%d")
        # deadline_check ignores its context argument; it is a pure date calculation.
        due_30 = {k: str(v) for k, v in deadline_check(None, ymd).items()}  # type: ignore[arg-type]
        due_5 = {
            k: str(v)
            for k, v in deadline_check(None, ymd, five_day_trigger=True).items()  # type: ignore[arg-type]
        }
    return MdrWorksheet(
        awareness_date=awareness_date,
        awareness_basis=awareness_basis,
        due_30=due_30,
        due_5=due_5,
        rows=worksheet_rows(
            device, event_types=event_types, date_received_range=date_received_range
        ),
    )
