"""Dashboard page for the Meta vision features: 510(k) summary reader + label camera.

HACKATHON-BUILT — Meta Global AI Developer Hackathon (Oct 26 – Nov 4, 2026).

Stored-first: with no ``META_MODEL_API_KEY`` the page shows readings recorded from
real Muse Spark / SAM 3.1 runs (``demo/vision/*.json``) and says plainly that live
reading needs a key. Every field carries its verification state; conflicts show
both reads and are never resolved for the analyst.
"""

from __future__ import annotations

import base64
import hashlib
import html
import os
from pathlib import Path
from typing import Any

import streamlit as st

from maudesignal.copilot.spend import SpendLimitError
from maudesignal.dashboard.copilot_pages import FRAMING_BANNER
from maudesignal.dashboard.spend_ui import guard as spend_guard
from maudesignal.dashboard.spend_ui import guarded_client
from maudesignal.monitor.deterioration import ProductCodeSignal, detect_from_database
from maudesignal.storage.database import Database
from maudesignal.vision import DEMO_K_NUMBERS
from maudesignal.vision.label import SESSION_ONLY_FIELDS, LabelResult
from maudesignal.vision.pipeline import (
    DEMO_VISION_DIR,
    load_recorded_labels,
    load_recorded_summaries,
)
from maudesignal.vision.verify import SOURCE_TYPE, FieldVerdict, VerifiedSummary


def vision_dir() -> Path:
    """Recorded vision runs (``MAUDESIGNAL_VISION_DIR`` overrides ``demo/vision``)."""
    return Path(os.environ.get("MAUDESIGNAL_VISION_DIR", str(DEMO_VISION_DIR)))


_PILL = {
    "VERIFIED": ("#e7f6ec", "#1e7b3a"),
    "CONFLICT": ("#fff4e5", "#a15c00"),
    "UNVERIFIABLE": ("#eef1f4", "#4b5563"),
}
_KEY_NOTE = (
    "Live reading needs a Meta Model API key (`META_MODEL_API_KEY`). Without one this page "
    "shows readings recorded from real Muse Spark and SAM 3.1 runs by "
    "`scripts/record_vision_runs.py`."
)


def _has_key() -> bool:
    return bool(os.environ.get("META_MODEL_API_KEY"))


def pill(status: str) -> str:
    """HTML pill for a field status."""
    bg, fg = _PILL.get(status, _PILL["UNVERIFIABLE"])
    return (
        f'<span style="background:{bg};color:{fg};border-radius:10px;padding:1px 8px;'
        f'font-size:12px;font-weight:600">{html.escape(status)}</span>'
    )


def _fmt(value: Any) -> str:
    if isinstance(value, list):
        return ", ".join(str(v) for v in value) or "—"
    return str(value) if value not in (None, "") else "—"


def field_rows_html(fields: list[FieldVerdict]) -> str:
    """The per-field verification table as HTML."""
    rows = []
    for f in fields:
        if f.status == "VERIFIED":
            shown = html.escape(_fmt(f.value))
        else:
            shown = (
                f"<b>Read A</b> (p.{f.read_a.page or '—'}, {f.read_a.legibility}): "
                f"{html.escape(_fmt(f.read_a.value))}<br><b>Read B</b> "
                f"(p.{f.read_b.page or '—'}, {f.read_b.legibility}): "
                f"{html.escape(_fmt(f.read_b.value))}"
            )
        checks = "<br>".join(
            f"{html.escape(c.source)}: {html.escape(c.outcome)} — {html.escape(c.detail)}"
            for c in f.checks
        )
        note = f"<br><i>{html.escape(f.note)}</i>" if f.note else ""
        rows.append(
            "<tr>"
            f"<td style='vertical-align:top'>{pill(f.status)}</td>"
            f"<td style='vertical-align:top'><code>{html.escape(f.name)}</code></td>"
            f"<td style='vertical-align:top'>{shown}{note}</td>"
            f"<td style='vertical-align:top;font-size:12px;color:#4b5563'>{checks}</td>"
            "</tr>"
        )
    return (
        "<table style='width:100%;border-collapse:collapse;font-size:14px'>"
        "<tr><th align='left'>Status</th><th align='left'>Field</th>"
        "<th align='left'>Value</th><th align='left'>Checks</th></tr>" + "".join(rows) + "</table>"
    )


def stored_summaries(db: Database) -> dict[str, VerifiedSummary]:
    """Readings saved in the database (live runs), keyed by K-number."""
    import json

    out: dict[str, VerifiedSummary] = {}
    for rec in db.list_external_sources(source_type=SOURCE_TYPE, limit=500):
        try:
            out[rec.source_id] = VerifiedSummary.from_dict(json.loads(rec.raw_json))
        except (ValueError, KeyError, TypeError):
            continue
    return out


def _data_url_bytes(url: str) -> bytes | None:
    if not url.startswith("data:") or "," not in url:
        return None
    try:
        return base64.b64decode(url.split(",", 1)[1])
    except ValueError:
        return None


def render_summary(s: VerifiedSummary) -> None:
    """Show one checked 510(k) reading."""
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Two-read agreement", f"{s.agreement_pct:.0f}%")
    c2.metric("Verified", s.count("VERIFIED"))
    c3.metric("Conflicts (human check)", s.count("CONFLICT"))
    c4.metric("Unverifiable", s.count("UNVERIFIABLE"))
    layer = "has a text layer" if s.has_text_layer else "has NO text layer (scanned image)"
    st.caption(
        f"{s.k_number}: read {s.pages_read} of {s.page_count} pages twice (A: in order, "
        f"1600 px; B: reverse order, 1100 px). The PDF {layer}. Muse Spark cost "
        f"${s.cost_usd:.4f}. Recorded {s.created_at}. Source: {s.pdf_url}"
    )
    if s.thumbnails:
        imgs = [b for b in (_data_url_bytes(t) for t in s.thumbnails) if b]
        cols = st.columns(min(8, max(1, len(imgs))))
        for i, b in enumerate(imgs):
            cols[i % len(cols)].image(b, caption=f"p.{i + 1}")
    st.html(field_rows_html(s.fields))
    if s.count("CONFLICT"):
        st.warning(
            "Conflicts are shown with both reads and are not resolved automatically: "
            "low clarity — a human must check the PDF."
        )


def _summary_tab(db: Database) -> None:
    recorded = {s.k_number: s for s in load_recorded_summaries(vision_dir())}
    stored = stored_summaries(db)
    catalog_ks = sorted({d.k_number for d in db.list_catalog_devices() if d.k_number})
    have = set(recorded) | set(stored)
    rest = ({k for k, _ in DEMO_K_NUMBERS} | set(catalog_ks)) - have
    options = sorted(have) + sorted(rest)  # recorded readings first
    if not _has_key():
        st.info(_KEY_NOTE)
    k = st.selectbox(
        "510(k) number",
        options,
        format_func=lambda x: f"{x}  ({'recorded' if x in have else 'not read yet'})",
        key="vision_k",
    )
    live = st.session_state.get("vision_live_summaries", {})
    summary = live.get(k) or stored.get(k) or recorded.get(k)
    if _has_key() and st.button(f"Read {k} live (2 Muse Spark calls)", key="vision_read_live"):
        _read_live(db, k)  # pragma: no cover - needs a live key
        summary = st.session_state.get("vision_live_summaries", {}).get(k, summary)
    if summary is None:
        st.caption("No reading for this 510(k) yet.")
        return
    render_summary(summary)


def _read_live(db: Database, k: str) -> None:  # pragma: no cover - needs a live key
    from maudesignal.vision.fda_pdf import FdaPdfError
    from maudesignal.vision.openfda510k import OpenFda510k, OpenFdaError
    from maudesignal.vision.pipeline import read_and_verify_510k
    from maudesignal.vision.spark import VisionModelError
    from maudesignal.vision.verify import store_summary

    try:
        spend_guard(db).check("vision")
        with st.spinner("Fetching the PDF, reading it twice with Muse Spark, checking…"):
            with OpenFda510k(os.environ.get("OPENFDA_API_KEY")) as ofda:
                s = read_and_verify_510k(k, client=guarded_client(db), openfda=ofda)
            store_summary(db, s)
    except SpendLimitError as exc:
        st.warning(f"{exc} No Meta call was made; the recorded reading (if any) is shown.")
        return
    except (FdaPdfError, VisionModelError, OpenFdaError) as exc:
        st.error(f"Not read: {exc}")
        return
    st.session_state.setdefault("vision_live_summaries", {})[k] = s


# ---------------------------------------------------------------------------
# Label camera
# ---------------------------------------------------------------------------


def signal_for(db: Database, product_code: str) -> ProductCodeSignal | None:
    """This week vs baseline for one product code, or None when not in the database."""
    try:
        result = detect_from_database(db)
    except ValueError:
        return None
    for sig in result.signals:
        if sig.product_code == product_code:
            return sig
    return None


def render_signal(db: Database, product_code: str) -> None:
    """The matched product's 7-day vs 4-week-baseline numbers."""
    sig = signal_for(db, product_code)
    st.subheader(f"Signals for product code {product_code}")
    if sig is None:
        st.caption(f"No stored MAUDE reports for {product_code} in this database.")
        return
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Reports, last 7 days", sig.current_count)
    c2.metric("Baseline weekly mean", f"{sig.baseline_weekly_mean:.1f}")
    c3.metric("Spike ratio", "—" if sig.spike_ratio is None else f"{sig.spike_ratio:.2f}×")
    share = sig.current_severe_share
    c4.metric("Injury/death share", "—" if share is None else f"{100 * share:.0f}%")
    st.caption(f"Classification: {sig.classification} (deterministic monitor, no model).")


def render_label(result: LabelResult, image: bytes | None, *, session: bool) -> None:
    """Show a label reading: SAM box, fields, checks, candidates."""
    if image is not None:
        from maudesignal.vision.images import draw_boxes, fit, open_image

        img = fit(open_image(image), 1600)
        boxes = [b.scaled_to(img.width, img.height).as_tuple() for b in result.sam_boxes]
        hi = None
        if result.chosen_box is not None:
            chosen = result.chosen_box.scaled_to(img.width, img.height).as_tuple()
            hi = boxes.index(chosen) if chosen in boxes else None
        st.image(draw_boxes(img, boxes, highlight=hi), caption=_sam_caption(result))
    else:
        st.caption(_sam_caption(result))
    rows = []
    for name, f in result.fields.items():
        if name in SESSION_ONLY_FIELDS and not session:
            continue
        tag = " (this session only, never stored)" if name in SESSION_ONLY_FIELDS else ""
        rows.append({"field": name + tag, "value": f.value or "—", "legibility": f.legibility})
    st.dataframe(rows, hide_index=True, width="stretch")
    st.markdown(f"**510(k):** `{result.k_number or '—'}` — {result.k_status.replace('_', ' ')}")
    outcome_status = {"pass": "VERIFIED", "fail": "CONFLICT"}
    for c in result.checks:
        status = outcome_status.get(c.outcome, "UNVERIFIABLE")
        st.markdown(
            f"- {pill(status)} `{c.source}` {html.escape(c.detail)}", unsafe_allow_html=True
        )
    st.caption(f"SAM + Muse Spark cost ${result.cost_usd:.4f}.")


def _sam_caption(result: LabelResult) -> str:
    if result.sam_prompt:
        return (
            f"SAM 3.1 prompt '{result.sam_prompt}': {len(result.sam_boxes)} match(es); the blue "
            "box was cropped and read by Muse Spark."
        )
    return result.sam_note or "Full photo read."


def _pick_product(result: LabelResult, key: str) -> str | None:
    if result.product_code and result.match_basis != "ambiguous":
        if result.match_basis != "k_number":
            st.info(
                f"Matched by name ({result.match_basis.replace('_', ' ')}), not by a printed "
                "510(k) number — confirm before relying on it."
            )
        return result.product_code
    if not result.candidates:
        st.warning("No 510(k) match. Check the photo or search the catalog by name.")
        return None
    st.warning("Several 510(k) records match this name. Pick one — nothing is auto-selected.")
    labels = [
        f"{c.k_number} · {c.product_code} · {c.device_name} · {c.applicant} · {c.decision_date}"
        for c in result.candidates
    ]
    choice = st.radio("Candidates (openFDA)", ["— choose —", *labels], key=key)
    if choice == "— choose —":
        return None
    return result.candidates[labels.index(choice)].product_code


def _label_tab(db: Database) -> None:
    if not _has_key():
        st.info(_KEY_NOTE)
        runs = load_recorded_labels(vision_dir())
        if not runs:
            st.caption(
                "No recorded label runs yet: put real label photos in `demo/vision/labels/` and "
                "run `scripts/record_vision_runs.py` with a key."
            )
        for i, run in enumerate(runs):
            with st.container(border=True):
                res = LabelResult.from_dict(run)
                img_path = vision_dir() / "labels" / str(run.get("image_file") or "")
                image = img_path.read_bytes() if img_path.is_file() else None
                st.markdown(f"**{html.escape(str(run.get('image_file') or run.get('_file')))}**")
                render_label(res, image, session=False)
                code = _pick_product(res, key=f"vision_rec_pick_{i}")
                if code:
                    render_signal(db, code)
        return
    _label_live(db)  # pragma: no cover - needs a live key


def _label_live(db: Database) -> None:  # pragma: no cover - needs a live key
    from maudesignal.vision.images import ImageInputError
    from maudesignal.vision.label import read_device_label
    from maudesignal.vision.openfda510k import OpenFda510k
    from maudesignal.vision.sam import SAM_USD_PER_IMAGE, SamClient
    from maudesignal.vision.spark import VisionModelError

    shot = st.camera_input("Photograph a device label or box")
    upload = st.file_uploader("…or upload a photo", type=["jpg", "jpeg", "png", "webp"])
    source = shot if shot is not None else upload
    if source is None:
        return
    data = source.getvalue()
    digest = hashlib.sha256(data).hexdigest()
    if st.session_state.get("vision_label_digest") != digest:
        catalog = {d.k_number for d in db.list_catalog_devices() if d.k_number}
        key = os.environ["META_MODEL_API_KEY"]
        base = os.environ.get("META_MODEL_API_BASE_URL", "https://api.meta.ai/v1")
        g = spend_guard(db)
        try:
            g.check("sam")
            with (
                st.spinner("SAM 3.1 is finding the label, Muse Spark is reading it…"),
                SamClient(key, base_url=base) as sam,
                OpenFda510k(os.environ.get("OPENFDA_API_KEY")) as ofda,
            ):
                try:
                    res = read_device_label(
                        data,
                        client=guarded_client(db),
                        sam=sam,
                        openfda=ofda,
                        catalog_k_numbers=catalog,
                    )
                except SpendLimitError:
                    # SAM already ran; count it before reporting the refusal.
                    g.record(kind="sam", model=sam.model, cost_usd=SAM_USD_PER_IMAGE)
                    raise
            g.record(kind="sam", model=sam.model, cost_usd=res.sam_cost_usd)
        except SpendLimitError as exc:
            st.warning(f"{exc} No further Meta call was made; recorded label runs are below.")
            return
        except (ImageInputError, VisionModelError) as exc:
            st.error(f"Not read: {exc}")
            return
        st.session_state["vision_label_digest"] = digest
        st.session_state["vision_label_result"] = res
    res = st.session_state["vision_label_result"]
    render_label(res, data, session=True)
    code = _pick_product(res, key="vision_live_pick")
    if code:
        render_signal(db, code)


def page_vision(db: Database) -> None:
    """Vision page: 510(k) summary reader and device-label camera."""
    st.html(FRAMING_BANNER)
    tab_doc, tab_label = st.tabs(["510(k) summary reader", "Device label camera"])
    with tab_doc:
        st.caption(
            "Muse Spark reads the summary's page images twice, independently. Each field is "
            "VERIFIED only when both reads agree and openFDA / the PDF text layer agree too; "
            "disagreements are flagged for a human, never resolved silently."
        )
        _summary_tab(db)
    with tab_label:
        st.caption(
            "SAM 3.1 finds the label, Muse Spark reads it, openFDA confirms the 510(k). "
            "Lot and serial numbers stay in this session and are never stored."
        )
        _label_tab(db)
