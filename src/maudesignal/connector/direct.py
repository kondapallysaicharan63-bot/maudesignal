"""Tier 2 of the chat: direct answers from the existing deterministic tools, no model.

HACKATHON-BUILT — Meta Global AI Developer Hackathon (Oct 26 – Nov 4, 2026).

A simple question with one intent (see ``tiers.route``) is answered by filling a fixed
template with values read by the copilot's own read-only tools (``copilot.tools``) and the
stored digest and sweep. Every template sentence carries the gate claims for the facts it
states, and the claim gate (``gate.verify_sentence``) checks each sentence against the
stored records exactly as it checks a model's sentence: a number that does not recompute, a
report id, recall number or K-number that is not stored, or a number with no claim blocks the
sentence, and a blocked sentence is never shown. Every shown sentence that states FDA data has
the openFDA link behind it.

Live openFDA numbers cannot be recomputed from stored records, so a code outside the stored
snapshot is never answered with numbers here: the answer opens the "Check any device type"
page instead. Nothing here calls a model; nothing costs money.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from maudesignal.connector import links
from maudesignal.connector.data import ConnectorData
from maudesignal.connector.forbidden import is_clean
from maudesignal.connector.guidance import either, suggest_codes
from maudesignal.connector.speech import plural, speak_date, speak_range, were
from maudesignal.connector.tiers import Route
from maudesignal.copilot.tools import device_510k, my_device_types, report_sources
from maudesignal.gate import Claim, verify_sentence
from maudesignal.gate.claims import (
    CountClaim,
    DeviceClaim,
    QuoteClaim,
    RecallClaim,
    RecallCountClaim,
    RecordClaim,
    SourceCountClaim,
)
from maudesignal.monitor.digest import CHANGE_LABELS

LinkPair = tuple[str, str]  # (url, label)

MAX_FLAGGED = 3
MAX_RECALLS = 3
QUOTE_CHARS = 200
WITHHELD_REASON = "a sentence of this lookup did not pass the claim gate, so it is not shown"
FORBIDDEN_REASON = "a sentence of this lookup contains a term this service does not use"
_SOURCES = ("manufacturer", "user facility", "voluntary", "distributor")


@dataclass
class Draft:
    """One template sentence before the gate: its text, the claims it makes, its links."""

    text: str
    claims: list[Claim] = field(default_factory=list)
    links: list[LinkPair] = field(default_factory=list)


@dataclass
class Shown:
    """A sentence that passed the gate, with the links behind it."""

    text: str
    links: list[LinkPair]


@dataclass
class DirectAnswer:
    """A tier-2 answer: gated sentences, what was left out, and where to go next."""

    intent: str
    tool: str
    sentences: list[Shown]
    withheld: list[str] = field(default_factory=list)
    suggestions: list[str] = field(default_factory=list)
    did_you_mean: list[str] = field(default_factory=list)
    #: A page of the web app to open: ``{"view": "check-device", "code": "QAS"}`` and so on.
    open: dict[str, str] | None = None
    source: str = "Stored demo snapshot of openFDA data"
    gate_checked: int = 0

    @property
    def spoken_text(self) -> str:
        """All shown sentences, as one text to read aloud."""
        return " ".join(s.text for s in self.sentences)


def gate(drafts: list[Draft], data: ConnectorData) -> tuple[list[Shown], list[str], int]:
    """Run every draft sentence through the claim gate.

    Returns:
        ``(shown, withheld_reasons, checked)``: the sentences that passed (with their own
        links plus the link of each passed claim), a fixed reason per blocked sentence, and how
        many sentences were checked.
    """
    store = data.store
    shown: list[Shown] = []
    withheld: list[str] = []
    for d in drafts:
        if not is_clean(d.text):
            withheld.append(FORBIDDEN_REASON)
            continue
        verdict = verify_sentence(d.text, d.claims, store)
        if verdict.status != "pass":
            withheld.append(WITHHELD_REASON)
            continue
        found = list(d.links)
        for cv in verdict.claim_verdicts:
            lk = links.claim_link(cv.claim)
            if lk is not None:
                found.append(lk)
        by_url: dict[str, str] = {}
        for url, label in found:
            by_url.setdefault(url, label)  # one link per URL; the template's label wins
        shown.append(Shown(d.text, list(by_url.items())))
    return shown, withheld, len(drafts)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _ymd(value: str) -> str:
    return str(value).replace("-", "")


def _num(value: float) -> str:
    if float(value).is_integer():
        return str(int(value))
    return f"{value:.2f}".rstrip("0").rstrip(".")


def _window(data: ConnectorData) -> tuple[str, str, str, str]:
    w = data.digest()["window"]
    return (
        _ymd(w["current_start"]),
        _ymd(w["current_end"]),
        _ymd(w["baseline_start"]),
        _ymd(w["baseline_end"]),
    )


def _signals(data: ConnectorData) -> list[dict[str, Any]]:
    digest = data.digest()
    order = {r["product_code"]: r["rank"] for r in digest.get("ranking", [])}
    return sorted(
        digest["signals"],
        key=lambda s: (order.get(s["product_code"], 10_000), s["product_code"]),
    )


def _stored_codes(data: ConnectorData) -> list[str]:
    return [str(s["product_code"]) for s in _signals(data)]


def _signal_draft(data: ConnectorData, s: dict[str, Any]) -> Draft:
    """'In the stored snapshot for the week ..., LLZ (...) shows ...: 33 reports ...'."""
    cs, ce, bs, be = _window(data)
    code = str(s["product_code"])
    names: dict[str, str] = dict(data.digest().get("device_types") or {})
    head = f"{code} ({names[code]})" if names.get(code) else code
    n, b = int(s["current_count"]), int(s["baseline_count"])
    mean = float(s["baseline_weekly_mean"])
    label = str(s.get("label") or CHANGE_LABELS.get(str(s["classification"]), "no change"))
    text = (
        f"In the stored snapshot for the week {speak_range(cs, ce)}, {head} shows {label}: "
        f"{plural(n, 'report')} received, against a weekly average of {_num(mean)} in the four "
        f"weeks before ({plural(b, 'report')})."
    )
    claims: list[Claim] = [
        CountClaim(code, n, date_from=cs, date_to=ce),
        CountClaim(code, b, date_from=bs, date_to=be),
    ]
    if abs(b / 4.0 - mean) > 0.005:
        # The average must be the stored baseline count over four weeks; if it is not, the
        # sentence carries a claim that cannot pass, so the gate holds it back.
        claims.append(CountClaim(code, -1))
    return Draft(
        text,
        claims,
        [
            (links.counts_link(code, cs, ce), "openFDA: reports in this week"),
            (links.counts_link(code, bs, be), "openFDA: reports in the four weeks before"),
        ],
    )


def _not_stored(code: str) -> DirectAnswer:
    return DirectAnswer(
        intent="check_code",
        tool="check_device_type",
        sentences=[
            Shown(
                f"{code} is not in the stored snapshot, so I have no checked numbers for it here.",
                [],
            ),
            Shown(
                f"Open Check any device type to count {code} reports live on openFDA.",
                [(links.counts_link(code, None, None), f"openFDA: reports for {code}")],
            ),
        ],
        open={"view": "check-device", "code": code},
        suggestions=[f"Check product code {c}" for c in ("LLZ", "QIH")],
    )


def _need_code(intent: str, data: ConnectorData) -> DirectAnswer:
    codes = _stored_codes(data)
    ask = {
        "recalls": "Recalls for {}",
        "who_filed": "Who filed {} reports?",
    }.get(intent, "Check product code {}")
    return DirectAnswer(
        intent="need_code",
        tool="none",
        sentences=[
            Shown(
                f"Which product code? The stored snapshot has {either(codes)}.",
                [],
            )
        ],
        suggestions=[ask.format(c) for c in codes[:4]],
    )


# ---------------------------------------------------------------------------
# Intents
# ---------------------------------------------------------------------------


def _what_changed(data: ConnectorData, code: str | None, *, alerts: bool) -> DirectAnswer:
    cs, ce, _bs, _be = _window(data)
    signals = _signals(data)
    tool = "what_changed_this_week"
    if code is not None:
        mine = [s for s in signals if s["product_code"] == code]
        if not mine:
            return _not_stored(code)
        shown, withheld, n = gate([_signal_draft(data, mine[0])], data)
        return DirectAnswer(
            intent="alerts" if alerts else "what_changed",
            tool=tool,
            sentences=shown,
            withheld=withheld,
            gate_checked=n,
            suggestions=[f"Recalls for {code}", f"Who filed {code} reports?"],
        )
    flagged = [s for s in signals if s["classification"] != "stable"]
    stable = [s for s in signals if s["classification"] == "stable"]
    drafts = [_signal_draft(data, s) for s in flagged[:MAX_FLAGGED]]
    if not flagged:
        drafts.append(
            Draft(
                f"No stored device type is flagged for the week {speak_range(cs, ce)}.",
                links=[
                    (links.counts_link(s["product_code"], cs, ce), s["product_code"])
                    for s in stable
                ],
            )
        )
    if stable:
        codes = [str(s["product_code"]) for s in stable]
        drafts.append(
            Draft(
                f"The other stored device {'type shows' if len(codes) == 1 else 'types show'} "
                f"no change: {', '.join(codes)}.",
                links=[(links.counts_link(c, cs, ce), f"openFDA: {c} this week") for c in codes],
            )
        )
    shown, withheld, n = gate(drafts, data)
    first = str(flagged[0]["product_code"]) if flagged else "LLZ"
    return DirectAnswer(
        intent="alerts" if alerts else "what_changed",
        tool=tool,
        sentences=shown,
        withheld=withheld,
        gate_checked=n,
        open={"view": "alerts"} if alerts else None,
        suggestions=[
            f"Recalls for {first}",
            f"Who filed {first} reports?",
            "Show the AI device sweep",
        ],
    )


def _check(data: ConnectorData, code: str) -> DirectAnswer:
    if code not in _stored_codes(data):
        return _not_stored(code)
    answer = _what_changed(data, code, alerts=False)
    rows = data.store.select_recalls(product_code=code)
    extra = Draft(
        f"The stored snapshot holds {plural(len(rows), 'recall')} for {code} (one per "
        "recalled product).",
        [RecallCountClaim(code, len(rows))],
    )
    shown, withheld, n = gate([extra], data)
    answer.intent = "check_code"
    answer.tool = "check_device_type"
    answer.sentences += shown
    answer.withheld += withheld
    answer.gate_checked += n
    answer.open = {"view": "check-device", "code": code}
    return answer


def _recalls(data: ConnectorData, code: str) -> DirectAnswer:
    rows = sorted(
        data.store.select_recalls(product_code=code),
        key=lambda r: (r.date_initiated or "", r.recall_number),
        reverse=True,
    )
    all_link = (links.product_recalls_link(code), f"openFDA: recalls for {code}")
    if not rows:
        drafts = [
            Draft(f"The stored snapshot holds no recalls for product code {code}.", [], [all_link]),
            Draft("That does not mean none exist; the openFDA link checks.", [], [all_link]),
        ]
    else:
        drafts = [
            Draft(
                f"The stored snapshot holds {plural(len(rows), 'recall')} for product code "
                f"{code} (one per recalled product).",
                [RecallCountClaim(code, len(rows))],
            )
        ]
        for r in rows[:MAX_RECALLS]:
            when = speak_date(r.date_initiated) if r.date_initiated else "an unknown date"
            text = f"Recall {r.recall_number} started {when}"
            text += f" by {r.recalling_firm}" if r.recalling_firm else ""
            text += f", status {r.recall_status}." if r.recall_status else "."
            drafts.append(Draft(text, [RecallClaim(r.recall_number, code)]))
    shown, withheld, n = gate(drafts, data)
    return DirectAnswer(
        intent="recalls",
        tool="recalls",
        sentences=shown,
        withheld=withheld,
        gate_checked=n,
        suggestions=[f"Check product code {code}", f"Who filed {code} reports?"],
    )


def _report(data: ConnectorData, report_id: str) -> DirectAnswer:
    rec = data.store.record(report_id)
    if rec is None:
        return DirectAnswer(
            intent="report",
            tool="get_report",
            sentences=[
                Shown(
                    "That report is not in the stored snapshot; that does not mean it is not on "
                    "openFDA.",
                    [(links.report_link(report_id), "openFDA: search this report id")],
                )
            ],
        )
    kind = (rec.event_type or "unknown").lower()
    received = speak_date(rec.date_received) if rec.date_received else "an unknown date"
    drafts = [
        Draft(
            f"Report {rec.report_id}: product code {rec.product_code}, event type {kind}, "
            f"received {received}.",
            [RecordClaim(rec.report_id, rec.product_code)],
        )
    ]
    who = [
        p
        for p in (
            f"brand {rec.brand_name}" if rec.brand_name else "",
            f"manufacturer {rec.manufacturer}" if rec.manufacturer else "",
        )
        if p
    ]
    if who:
        drafts.append(
            Draft(
                f"Report {rec.report_id} lists {' and '.join(who)}.",
                [RecordClaim(rec.report_id, rec.product_code)],
            )
        )
    narrative = " ".join(rec.text.split())
    if narrative:
        cut = narrative[:QUOTE_CHARS]
        if len(narrative) > QUOTE_CHARS:
            cut = cut.rsplit(" ", 1)[0]
        cut = cut.rstrip(" .,;:")
        drafts.append(
            Draft(
                f'The narrative starts, word for word: "{cut}"',
                [QuoteClaim(cut, report_id=rec.report_id)],
            )
        )
    shown, withheld, n = gate(drafts, data)
    return DirectAnswer(
        intent="report",
        tool="get_report",
        sentences=shown,
        withheld=withheld,
        gate_checked=n,
        suggestions=[f"Check product code {rec.product_code}", f"Recalls for {rec.product_code}"],
    )


def _who_filed(data: ConnectorData, code: str) -> DirectAnswer:
    if code not in _stored_codes(data):
        return _not_stored(code)
    rs = report_sources(data.tool_context(), code)
    total = int(rs["report_count"])
    drafts = [
        Draft(
            f"The stored snapshot holds {plural(total, 'report')} for {code}.",
            [CountClaim(code, total)],
        )
    ]
    counts: dict[str, int] = dict(rs["source_counts"])
    parts: list[str] = []
    claims: list[Claim] = []
    for src in _SOURCES:
        if counts.get(src):
            parts.append(f"{plural(counts[src], src + ' report')}")
            claims.append(SourceCountClaim(code, src, counts[src]))
    if parts:
        drafts.append(
            Draft(
                f"By who filed them: {', '.join(parts)}.",
                claims,
                [(links.counts_link(code, None, None), f"openFDA: reports for {code}")],
            )
        )
    nm = int(rs["non_manufacturer_count"])
    drafts.append(
        Draft(
            f"{plural(nm, 'report')} {were(nm)} not filed by a manufacturer.",
            [SourceCountClaim(code, "non-manufacturer", nm)],
            [(links.counts_link(code, None, None), f"openFDA: reports for {code}")],
        )
    )
    if counts.get("unknown"):
        drafts.append(Draft("Reports with no source given are not counted by source here."))
    shown, withheld, n = gate(drafts, data)
    return DirectAnswer(
        intent="who_filed",
        tool="report_sources",
        sentences=shown,
        withheld=withheld,
        gate_checked=n,
        suggestions=[f"Check product code {code}", f"Recalls for {code}"],
    )


def _k510(data: ConnectorData, k: str) -> DirectAnswer:
    dev = device_510k(data.tool_context(), k)
    k_link = (links.k510_link(k), "openFDA: this 510(k)")
    if "error" in dev:
        return DirectAnswer(
            intent="k510",
            tool="device_510k",
            sentences=[
                Shown("That K-number is not in the stored 510(k) records.", [k_link]),
                Shown("The openFDA link searches every 510(k).", [k_link]),
            ],
        )
    pc = str(dev["product_code"])
    when = speak_date(str(dev.get("decision_date") or "")) or "an unknown date"
    text = f"{dev['k_number']} is {dev['device_name']}, product code {pc}"
    text += f", from {dev['applicant']}" if dev.get("applicant") else ""
    text += f", with a 510(k) decision dated {when}."
    drafts = [Draft(text, [DeviceClaim(str(dev["k_number"]), pc)])]
    cited = [str(r) for r in dev.get("recalls_citing_this_k_number") or []]
    if cited:
        cite: list[Claim] = [DeviceClaim(str(dev["k_number"]))]
        cite += [RecallClaim(r) for r in cited[:MAX_RECALLS]]
        drafts.append(
            Draft(
                f"Stored recalls that cite {dev['k_number']}: {', '.join(cited[:MAX_RECALLS])}.",
                cite,
            )
        )
    shown, withheld, n = gate(drafts, data)
    return DirectAnswer(
        intent="k510",
        tool="device_510k",
        sentences=shown,
        withheld=withheld,
        gate_checked=n,
        suggestions=[f"Check product code {pc}", f"Recalls for {pc}"],
    )


def _my_devices(data: ConnectorData) -> DirectAnswer:
    mem = my_device_types(data.tool_context())
    codes = [str(c) for c in mem.get("device_types") or []]
    if not codes:
        return DirectAnswer(
            intent="my_devices",
            tool="my_device_types",
            sentences=[
                Shown("You have not chosen any device types to watch here yet.", []),
                Shown("Open Our devices to choose the product codes you follow.", []),
            ],
            open={"view": "our-devices"},
            suggestions=list(SUGGESTED_CHECKS),
        )
    cs, ce, _bs, _be = _window(data)
    drafts = [
        Draft(
            f"You watch {', '.join(codes)}.",
            links=[(links.counts_link(c, cs, ce), f"openFDA: {c} this week") for c in codes],
        )
    ]
    stored = {str(s["product_code"]): s for s in _signals(data)}
    drafts += [_signal_draft(data, stored[c]) for c in codes if c in stored]
    shown, withheld, n = gate(drafts, data)
    return DirectAnswer(
        intent="my_devices",
        tool="my_device_types",
        sentences=shown,
        withheld=withheld,
        gate_checked=n,
        open={"view": "our-devices"},
    )


SUGGESTED_CHECKS = ("Check product code LLZ", "Check product code QIH")


def _sweep(data: ConnectorData) -> DirectAnswer:
    sweep = data.sweep()
    rows = [r for r in sweep.get("rows") or [] if isinstance(r, dict)]
    meta = sweep.get("meta") or {}
    if not rows:
        return DirectAnswer(
            intent="ai_sweep",
            tool="ai_sweep",
            sentences=[Shown("No AI device sweep is stored here.", [])],
            open={"view": "ai-sweep"},
        )
    window = meta.get("window") or {}
    cs, ce = _ymd(str(window.get("current_start") or "")), _ymd(
        str(window.get("current_end") or "")
    )
    flagged = [r for r in rows if r.get("classification") != "stable"]
    when = speak_date(str(meta.get("generated_utc") or "")[:10]) or "its last run"
    drafts = [
        Draft(
            f"The stored AI device sweep of {when} checked {len(rows)} product codes from FDA's "
            f"list of AI-enabled devices for the week {speak_range(cs, ce)}.",
            links=(
                [(str(meta["source"]), "FDA: AI-enabled device list")]
                if str(meta.get("source") or "").startswith("https://")
                else []
            ),
        )
    ]
    if flagged:
        named = [
            f"{r['product_code']} ({CHANGE_LABELS.get(str(r.get('classification')), 'changed')})"
            for r in flagged
        ]
        drafts.append(
            Draft(
                f"{len(flagged)} of them met the detector's rules: {', '.join(named)}.",
                links=[
                    (
                        links.counts_link(str(r["product_code"]), cs, ce),
                        f"openFDA: {r['product_code']}",
                    )
                    for r in flagged
                ],
            )
        )
    else:
        drafts.append(Draft("None of them met the detector's rules that week."))
    shown, withheld, n = gate(drafts, data)
    return DirectAnswer(
        intent="ai_sweep",
        tool="ai_sweep",
        sentences=shown,
        withheld=withheld,
        gate_checked=n,
        open={"view": "ai-sweep"},
        source="Stored AI-device sweep (live openFDA counts at the time of the sweep)",
        suggestions=[f"Check product code {str(flagged[0]['product_code'])}"] if flagged else [],
    )


def _did_you_mean(data: ConnectorData, r: Route) -> DirectAnswer:
    known = data.known_product_codes()
    close = list(dict.fromkeys(c for u in r.unclear_codes for c in suggest_codes(u, known)))
    asked = ", ".join(r.unclear_codes)
    return DirectAnswer(
        intent="did_you_mean",
        tool="none",
        sentences=[
            Shown(f"I don't know the product code {asked}. Did you mean {either(close)}?", []),
            Shown(
                f"If {asked} is right, open Check any device type to look it up live.",
                [],
            ),
        ],
        suggestions=list(r.suggestions),
        did_you_mean=close,
        open={"view": "check-device", "code": r.unclear_codes[0]},
    )


def answer(data: ConnectorData, r: Route) -> DirectAnswer:
    """The tier-2 answer for a route (``r.tier`` must be ``direct``)."""
    code = r.product_code or (r.unclear_codes[0] if len(r.unclear_codes) == 1 else None)
    handlers: dict[str, Callable[[], DirectAnswer]] = {
        "alerts": lambda: _what_changed(data, code, alerts=True),
        "what_changed": lambda: _what_changed(data, code, alerts=False),
        "ai_sweep": lambda: _sweep(data),
        "my_devices": lambda: _my_devices(data),
        "did_you_mean": lambda: _did_you_mean(data, r),
    }
    if r.intent in handlers:
        return handlers[r.intent]()
    if r.intent == "report" and r.report_id:
        return _report(data, r.report_id)
    if r.intent == "k510" and r.k_number:
        return _k510(data, r.k_number)
    if code is None:
        return _need_code(r.intent, data)
    if r.intent == "recalls":
        return _recalls(data, code)
    if r.intent == "who_filed":
        return _who_filed(data, code)
    return _check(data, code)
