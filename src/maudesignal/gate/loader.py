"""Build an ``EvidenceStore`` from MaudeSignal's database.

HACKATHON-BUILT — Meta Global AI Developer Hackathon (Oct 26 – Nov 4, 2026).
"""

from __future__ import annotations

from maudesignal.gate.evidence import DeviceRef, EvidenceRecord, EvidenceStore
from maudesignal.storage.database import Database


def store_from_database(db: Database, *, product_code: str | None = None) -> EvidenceStore:
    """Load stored MAUDE events and the 510(k) catalog as gate evidence.

    Args:
        db: Open MaudeSignal database.
        product_code: Optional filter to keep the store small.
    """
    dates = db.date_received_lookup()
    records = [
        EvidenceRecord(
            report_id=ev.maude_report_id,
            product_code=ev.product_code,
            event_type=ev.event_type,
            date_received=dates.get(ev.maude_report_id),
            text=" ".join(t for t in (ev.narrative, ev.mfr_narrative) if t),
            manufacturer=ev.manufacturer,
            brand_name=ev.brand_name,
        )
        for ev in db.list_normalized_events(product_code=product_code)
    ]
    devices = [
        DeviceRef(
            k_number=d.k_number,
            product_code=d.product_code,
            device_name=d.device_name,
            company_name=d.company_name,
        )
        for d in db.list_catalog_devices()
        if d.k_number
    ]
    return EvidenceStore(records=records, devices=devices)
