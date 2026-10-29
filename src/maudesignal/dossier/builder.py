"""Assemble a Signal Evaluation & CAPA dossier from stored records.

HACKATHON-BUILT — Meta Global AI Developer Hackathon (Oct 26 – Nov 4, 2026).

Every number comes from :mod:`maudesignal.monitor` (the deterioration
detector) or is counted from the evidence store, and is wrapped in a
:class:`~maudesignal.dossier.figures.Figure` whose claim re-derives it. The
builder re-verifies all figures through the gate before rendering and prints
the result on the cover page. No model is called here.
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

from maudesignal.dossier.chart import weekly_chart_svg
from maudesignal.dossier.figures import (
    Figure,
    const_figure,
    count_figure,
    derived_figure,
    records_figure,
    verify_figures,
)
from maudesignal.dossier.mdr import build_worksheet
from maudesignal.dossier.model import (
    AuditRow,
    CapaInfo,
    DeviceInfo,
    DossierData,
    EvidenceRow,
    Illustration,
    NarrativeSection,
    SignalSection,
    WeeklyBar,
)
from maudesignal.dossier.narrative import gate_narrative, load_recording, omitted_section
from maudesignal.gate import EvidenceStore, verify_sentence
from maudesignal.gate.loader import store_from_database
from maudesignal.monitor.deterioration import (
    BASELINE_WEEKS,
    CLASSIFICATION_PRECEDENCE,
    SPIKE_MULTIPLIER,
    ProductCodeSignal,
    build_window,
    detect_from_database,
)
from maudesignal.storage.database import Database
from maudesignal.storage.models import CapaDraftRecord

MAUDE_URL = "https://www.accessdata.fda.gov/scripts/cdrh/cfdocs/cfmaude/detail.cfm?mdrfoi__id={}"
EXCERPT_CHARS = 300
PROMPT_EXCERPT_CHARS = 600
DETERMINISTIC_ACTOR = "maudesignal:monitor (deterministic)"
NO_TEXT = "(no narrative text in the openFDA record)"


class DossierError(ValueError):
    """Raised when a dossier cannot be built (unknown CAPA, no signal, empty data)."""


@dataclass
class DossierBuild:
    """A built dossier plus the evidence store its figures were verified against."""

    data: DossierData
    store: EvidenceStore
    excerpts: dict[str, str]


def _ymd(d: date) -> str:
    return d.strftime("%Y%m%d")


def _iso(yyyymmdd: str | None) -> str | None:
    if not yyyymmdd or len(yyyymmdd) != 8:
        return yyyymmdd
    return f"{yyyymmdd[:4]}-{yyyymmdd[4:6]}-{yyyymmdd[6:]}"


def _excerpt(text: str, n: int = EXCERPT_CHARS) -> str:
    t = " ".join(text.split())
    return t if len(t) <= n else t[: n - 1].rstrip() + "…"


def _distinct(values: list[str]) -> tuple[str, ...]:
    """Distinct non-empty values (case-insensitive), most frequent first, ties alphabetical.

    The most frequent spelling of each case-folded value is kept.
    """
    spellings: dict[str, Counter[str]] = {}
    for v in values:
        s = " ".join((v or "").split())
        if s:
            spellings.setdefault(s.casefold(), Counter())[s] += 1
    ranked = sorted(
        spellings.values(), key=lambda c: (-sum(c.values()), c.most_common(1)[0][0].casefold())
    )
    return tuple(c.most_common(1)[0][0] for c in ranked)


def top_flagged_signal(db: Database, as_of: date | None = None) -> ProductCodeSignal | None:
    """The highest-priority non-stable signal (precedence, then current count)."""
    result = detect_from_database(db, as_of)
    ranked = sorted(
        result.non_stable(),
        key=lambda s: (CLASSIFICATION_PRECEDENCE.index(s.classification), -s.current_count),
    )
    return ranked[0] if ranked else None


def device_info(db: Database, product_code: str, report_ids: list[str]) -> DeviceInfo:
    """Device identification from the raw openFDA rows of the cited reports.

    Only ``device[]`` and ``pma_pmn_number`` are read — never patient fields.
    """
    brands: list[str] = []
    generics: list[str] = []
    mfrs: list[str] = []
    models: list[str] = []
    ks: list[str] = []
    cls_names: list[str] = []
    regs: list[str] = []
    classes: list[str] = []
    for raw in db.list_raw_reports(report_ids):
        try:
            payload: dict[str, Any] = json.loads(raw.raw_json)
        except ValueError:
            continue
        ks.append(str(payload.get("pma_pmn_number") or ""))
        for dev in payload.get("device") or []:
            if not isinstance(dev, dict):
                continue
            brands.append(str(dev.get("brand_name") or ""))
            generics.append(str(dev.get("generic_name") or ""))
            models.append(str(dev.get("model_number") or ""))
            place = ", ".join(
                p
                for p in (
                    str(dev.get("manufacturer_d_name") or "").strip(),
                    str(dev.get("manufacturer_d_city") or "").strip(),
                    str(dev.get("manufacturer_d_state") or "").strip(),
                    str(dev.get("manufacturer_d_country") or "").strip(),
                )
                if p
            )
            mfrs.append(place)
            ofda = dev.get("openfda") or {}
            if isinstance(ofda, dict):
                cls_names.append(str(ofda.get("device_name") or ""))
                regs.append(str(ofda.get("regulation_number") or ""))
                classes.append(str(ofda.get("device_class") or ""))
    catalog = next((d for d in db.list_catalog_devices() if d.product_code == product_code), None)

    def first(xs: list[str]) -> str | None:
        d = _distinct(xs)
        return d[0] if d else None

    return DeviceInfo(
        product_code=product_code,
        classification_name=first(cls_names),
        regulation_number=first(regs),
        device_class=first(classes),
        catalog_label=catalog.device_name if catalog else None,
        brand_names=_distinct(brands),
        generic_names=_distinct(generics),
        manufacturers=_distinct(mfrs),
        model_numbers=_distinct(models),
        k_numbers=_distinct(ks),
    )


def signal_section(sig: ProductCodeSignal, as_of: date, store: EvidenceStore) -> SignalSection:
    """Wrap every monitor number in a re-verifiable figure."""
    w = build_window(as_of)
    pc = sig.product_code
    cs, ce = _ymd(w.current_start), _ymd(w.current_end)
    bs, be = _ymd(w.baseline_start), _ymd(w.baseline_end)
    cur = count_figure(pc, sig.current_count, date_from=cs, date_to=ce)
    base = count_figure(pc, sig.baseline_count, date_from=bs, date_to=be)
    weeks = const_figure(BASELINE_WEEKS)
    mean = derived_figure("div", [base, weeks], sig.baseline_count / BASELINE_WEEKS, digits=2)
    threshold = derived_figure(
        "mul", [const_figure(SPIKE_MULTIPLIER), mean], SPIKE_MULTIPLIER * mean.value, digits=2
    )
    ratio = (
        derived_figure("div", [cur, mean], sig.current_count / mean.value, digits=2, suffix="×")
        if sig.baseline_count
        else None
    )

    def severe(df: str, dt: str) -> Figure:
        parts: list[Figure] = []
        for et in ("injury", "death"):
            n = len(store.select(product_code=pc, event_type=et, date_from=df, date_to=dt))
            parts.append(count_figure(pc, n, event_type=et, date_from=df, date_to=dt))
        return derived_figure("sum", parts, sum(p.value for p in parts), digits=0)

    cur_sev = severe(cs, ce)
    base_sev = severe(bs, be)

    def share(num: Figure, den: Figure) -> Figure | None:
        if not den.value:
            return None
        return derived_figure("pct", [num, den], 100 * num.value / den.value, digits=1, suffix="%")

    weekly: list[WeeklyBar] = []
    for i in range(BASELINE_WEEKS):
        start = w.baseline_start + timedelta(days=7 * i)
        end = start + timedelta(days=6)
        n = len(store.select(product_code=pc, date_from=_ymd(start), date_to=_ymd(end)))
        fig = count_figure(pc, n, date_from=_ymd(start), date_to=_ymd(end))
        weekly.append(WeeklyBar(f"B{i + 1}", start, end, fig, False))
    weekly.append(WeeklyBar("Current", w.current_start, w.current_end, cur, True))
    bars = tuple(weekly)
    return SignalSection(
        product_code=pc,
        classification=sig.classification,
        triggers=sig.triggers,
        as_of=as_of,
        current_start=w.current_start,
        current_end=w.current_end,
        baseline_start=w.baseline_start,
        baseline_end=w.baseline_end,
        current_count=cur,
        baseline_count=base,
        baseline_weekly_mean=mean,
        spike_ratio=ratio,
        spike_threshold=threshold,
        current_severe=cur_sev,
        baseline_severe=base_sev,
        current_severe_share=share(cur_sev, cur),
        baseline_severe_share=share(base_sev, base),
        event_type_counts=tuple(
            (et, count_figure(pc, n, event_type=et, date_from=cs, date_to=ce))
            for et, n in sig.current_event_type_counts
        ),
        weekly=bars,
        chart_svg=weekly_chart_svg(bars, mean, threshold),
    )


def _doc_seq(db: Database, product_code: str, capa_id: str | None) -> int:
    capas = sorted(
        (c for c in db.list_capa_drafts() if c.product_code == product_code),
        key=lambda c: (c.created_at, c.capa_id),
    )
    for i, c in enumerate(capas, start=1):
        if c.capa_id == capa_id:
            return i
    return 1


def _capa_info(db: Database, row: CapaDraftRecord, store: EvidenceStore) -> CapaInfo:
    decision = next(
        (a for a in db.list_audit(entity_id=row.capa_id) if a.action == f"capa.{row.status}"),
        None,
    )
    flags = verify_sentence(row.problem_statement, [], store).ungrounded
    return CapaInfo(
        capa_id=row.capa_id,
        title=row.title,
        problem_statement=row.problem_statement,
        problem_statement_flags=tuple(flags),
        status=row.status,
        created_by=row.created_by,
        created_at=row.created_at,
        decided_by=row.decided_by,
        decided_at=row.decided_at,
        decision_note=row.decision_note,
        decision_audit_seq=decision.seq if decision and row.status != "draft" else None,
        decision_audit_hash=decision.entry_hash if decision and row.status != "draft" else None,
        report_ids=tuple(json.loads(row.report_ids_json)),
    )


def _audit_rows(db: Database, entity_ids: set[str], capa_id: str | None) -> tuple[AuditRow, ...]:
    out: list[AuditRow] = []
    for a in db.list_audit():
        related = a.entity_id in entity_ids
        if not related and capa_id and a.action == "copilot.answer":
            try:
                related = capa_id in (json.loads(a.payload_json).get("capa_ids") or [])
            except (ValueError, AttributeError):
                related = False
        if related:
            out.append(AuditRow(a.seq, a.ts, a.actor, a.action, a.entity_id, a.entry_hash[:12]))
    return tuple(out)


def build_dossier(
    db: Database,
    *,
    capa_id: str | None = None,
    product_code: str | None = None,
    as_of: date | None = None,
    awareness_date: date | None = None,
    awareness_basis: str = "entered by the reviewer",
    narrative: NarrativeSection | None = None,
    recorded_dir: Path | None = None,
    illustration: Illustration | None = None,
    generated_at: datetime | None = None,
) -> DossierBuild:
    """Build the dossier for one CAPA-need evidence pack, or for a signal when no CAPA is given.

    Args:
        db: Open MaudeSignal database.
        capa_id: CAPA-need evidence pack to document. Its product code selects the signal.
        product_code: Signal to document when no CAPA is given (default: the top flagged change).
        as_of: Detection as-of date (default: latest stored ``date_received``).
        awareness_date: Manufacturer awareness date for the MDR clock (human input).
        awareness_basis: How the awareness date was obtained (printed on the worksheet).
        narrative: Pre-gated narrative (live run). If None, a recording in
            ``recorded_dir`` is gated and used; otherwise the section is omitted.
        recorded_dir: Folder holding ``<doc_id>-narrative.json`` recordings.
        illustration: Optional AI cover illustration (default: none).
        generated_at: Timestamp to print (default: now, UTC).

    Raises:
        DossierError: unknown CAPA id, no signal for the product code, or no data.
    """
    capa_row = db.get_capa_draft(capa_id) if capa_id else None
    if capa_id and capa_row is None:
        raise DossierError(f"unknown CAPA-need evidence pack {capa_id}")
    try:
        detection = detect_from_database(db, as_of)
    except ValueError as exc:
        raise DossierError(str(exc)) from exc
    pc = capa_row.product_code if capa_row else product_code
    if pc is None:
        top = top_flagged_signal(db, as_of)
        if top is None:
            raise DossierError("no flagged change and no CAPA-need evidence pack to document")
        pc = top.product_code
    sig = next((s for s in detection.signals if s.product_code == pc), None)
    if sig is None:
        raise DossierError(f"no stored reports for product code {pc}")

    store = store_from_database(db)
    signal = signal_section(sig, detection.window.as_of, store)
    capa = _capa_info(db, capa_row, store) if capa_row else None
    report_ids = list(capa.report_ids) if capa else list(sig.current_report_ids)

    excerpts: dict[str, str] = {}
    raw_numbers: dict[str, str] = {}
    for raw in db.list_raw_reports(report_ids):
        try:
            raw_numbers[raw.maude_report_id] = str(json.loads(raw.raw_json).get("report_number"))
        except ValueError:
            continue
    rows: list[EvidenceRow] = []
    for rid in report_ids:
        rec = store.record(rid)
        if rec is None:
            continue
        excerpts[rid] = _excerpt(rec.text, PROMPT_EXCERPT_CHARS)
        rows.append(
            EvidenceRow(
                report_id=rid,
                url=MAUDE_URL.format(rid.split("-")[0]),
                mfr_report_number=raw_numbers.get(rid) or None,
                date_received=_iso(rec.date_received),
                event_type=(rec.event_type or "unknown").capitalize(),
                brand_name=rec.brand_name,
                excerpt=_excerpt(rec.text) or NO_TEXT,
            )
        )
    rows.sort(key=lambda r: (r.date_received or "", r.report_id))
    device = device_info(db, pc, report_ids)

    dates = sorted(r.date_received for r in rows if r.date_received)
    mdr = build_worksheet(
        device,
        awareness_date=awareness_date,
        awareness_basis=awareness_basis,
        event_types=tuple(sorted({r.event_type for r in rows if r.event_type})),
        date_received_range=(dates[0], dates[-1]) if dates else None,
    )

    seq = _doc_seq(db, pc, capa.capa_id if capa else None)
    doc_id = f"SER-{pc}-{signal.as_of:%Y%m%d}-{seq:03d}"
    status = capa.status if capa else "no-capa"
    revision = {"no-capa": "0.1", "draft": "0.2"}.get(status, "1.0")

    if narrative is None:
        rec_path = recorded_dir / f"{doc_id}-narrative.json" if recorded_dir else None
        recording = load_recording(rec_path) if rec_path else None
        narrative = (
            gate_narrative(recording, store, source="recorded") if recording else omitted_section()
        )

    entity_ids = {doc_id} | ({capa.capa_id} if capa else set())
    audit = _audit_rows(db, entity_ids, capa.capa_id if capa else None)
    chain_ok, first_bad = db.verify_audit_chain()

    evidence_count = records_figure([r.report_id for r in rows])
    data = DossierData(
        doc_id=doc_id,
        revision=revision,
        status=status,
        generated_at=generated_at or datetime.now(UTC).replace(tzinfo=None, microsecond=0),
        prepared_by=capa.created_by if capa else DETERMINISTIC_ACTOR,
        prepared_at=capa.created_at if capa else None,
        device=device,
        signal=signal,
        evidence=tuple(rows),
        evidence_count=evidence_count,
        capa=capa,
        mdr=mdr,
        narrative=narrative,
        audit=audit,
        audit_chain_ok=chain_ok,
        audit_chain_first_bad=first_bad,
        audit_chain_total=len(db.list_audit()),
        db_label=f"{db.path.name} (latest openFDA date_received {db.max_date_received()})",
        illustration=illustration,
    )
    report = verify_figures(all_figures(data), store)
    data.figures_checked = report.total
    data.figures_failed = len(report.failed)
    if sig.current_severe_count != int(signal.current_severe.value):
        data.extra_notes.append("Severe count differs between monitor and evidence store.")
    return DossierBuild(data=data, store=store, excerpts=excerpts)


def all_figures(data: DossierData) -> list[Figure]:
    """Every figure the template prints (for pre-render verification)."""
    s = data.signal
    figs: list[Figure] = [
        s.current_count,
        s.baseline_count,
        s.baseline_weekly_mean,
        s.spike_threshold,
        s.current_severe,
        s.baseline_severe,
        data.evidence_count,
    ]
    figs += [f for f in (s.spike_ratio, s.current_severe_share, s.baseline_severe_share) if f]
    figs += [f for _, f in s.event_type_counts]
    figs += [b.count for b in s.weekly]
    return figs
