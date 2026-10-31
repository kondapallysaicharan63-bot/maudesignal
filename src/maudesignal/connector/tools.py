"""The connector's read-only tools (everything except ``ask``, which is in ``ask.py``).

HACKATHON-BUILT — Meta Global AI Developer Hackathon (Oct 26 – Nov 4, 2026).

Every tool returns one :class:`~maudesignal.connector.models.ToolAnswer`:
a short speakable summary, a facts list where each fact has its openFDA or
record link, the fixed advisory line, and provenance (stored demo snapshot
with its dates, or live openFDA with the query time). Numbers are copied from
the stored digest, the stored records or the live check; nothing is estimated
here and no model is called.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, TypeVar

from maudesignal.common.exceptions import OpenFDAAPIError
from maudesignal.connector import links
from maudesignal.connector.data import ConnectorData
from maudesignal.connector.errors import InvalidInputError, NotFoundError, SourceUnavailableError
from maudesignal.connector.forbidden import is_clean
from maudesignal.connector.guidance import either, suggest_codes, unknown_code_error
from maudesignal.connector.models import Fact, Provenance, RecallsAnswer, ToolAnswer
from maudesignal.connector.speech import compose, plain, plural, speak_date, speak_range, were
from maudesignal.monitor.digest import CHANGE_LABELS
from maudesignal.monitor.live_check import LiveCheck, LiveCheckError, normalize_code

LiveChecker = Callable[[str], LiveCheck]
#: True: the code is in the openFDA classification list; False: it is not; None: could not tell.
CodeChecker = Callable[[str], bool | None]
Clock = Callable[[], datetime]

TOOL_NAMES = (
    "what_changed_this_week",
    "check_device_type",
    "ask",
    "get_report",
    "recalls",
    "lookup_device",
)

_REPORT_ID = re.compile(r"^[A-Za-z0-9-]{1,24}$")
NARRATIVE_CHARS = 240
MAX_RECALL_FACTS = 5


LIVE_FAILED_LEAD = "Live openFDA could not be reached, so this is the stored demo snapshot."
OMITTED_TEXT = (
    "Text left out because it contains a term this service does not repeat; "
    "open the link to read the source."
)
OMITTED_SPEAKABLE = (
    "Part of this answer was left out because it contains a term this service does not "
    "repeat. The facts list has the rest, each with its link."
)


_A = TypeVar("_A", bound=ToolAnswer)


def screen(answer: _A) -> _A:
    """Final guard on every outgoing answer: no forbidden term in speakable or facts.

    Stored source text (a narrative, a recall reason, a firm name) is passed on word for
    word, so it can carry a word this service never uses itself. A fact that does is kept
    with its link but its text is replaced; a speakable that does is replaced too.
    """
    for fact in answer.facts:
        if not is_clean(fact.text):
            fact.text = OMITTED_TEXT
    if not is_clean(answer.speakable):
        answer.speakable = OMITTED_SPEAKABLE
    return answer


def utc_now() -> datetime:
    """Current UTC time."""
    return datetime.now(UTC)


def _stamp(now: datetime) -> str:
    return now.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _num(value: float) -> str:
    """4.0 -> '4', 8.75 -> '8.75' (never scientific notation)."""
    if float(value).is_integer():
        return str(int(value))
    return f"{value:.2f}".rstrip("0").rstrip(".")


def _severe_phrase(n: int) -> str:
    return (
        "One of them was an injury or death report."
        if n == 1
        else (f"{n} of them were injury or death reports.")
    )


def _ymd(iso_or_ymd: str) -> str:
    return iso_or_ymd.replace("-", "")


def _code(product_code: str) -> str:
    try:
        return normalize_code(product_code)
    except LiveCheckError as exc:
        raise InvalidInputError(str(exc)) from exc


def snapshot_provenance(
    data: ConnectorData, window_text: str | None, *, recalls: bool = False
) -> Provenance:
    """Provenance for an answer read from the stored demo snapshot."""
    manifest = data.manifest()
    fetched = str(manifest.get("fetched_at_utc") or "")[:10]
    source = "Stored demo snapshot of openFDA device adverse-event reports"
    if recalls:
        ext = manifest.get("external_sources")
        fetched = str((ext or {}).get("fetched_at_utc") or fetched)[:10]
        source = "Stored demo snapshot of openFDA device recalls"
    parts = [window_text] if window_text else []
    if fetched:
        parts.append(f"snapshot fetched {fetched}")
    latest = str(manifest.get("max_date_received") or "")
    if latest and not recalls:
        parts.append(f"latest stored report received {speak_date(latest)}")
    return Provenance(
        kind="stored_demo_snapshot",
        source=source,
        data_dates="; ".join(parts) or None,
        note="Not live data. The links open the live openFDA record or query for comparison.",
    )


def live_provenance(check: LiveCheck, now: datetime) -> Provenance:
    """Provenance for an answer computed from live openFDA counts."""
    w = check.window
    dates = (
        f"week {speak_range(w.current_start, w.current_end)}; "
        f"baseline {speak_range(w.baseline_start, w.baseline_end)}"
        if w
        else "no report in the last two years"
    )
    return Provenance(
        kind="live_openfda",
        source="openFDA device/event.json (counts only; no report text downloaded)",
        data_dates=dates,
        queried_at_utc=_stamp(now),
        note="Same four rules, windows and thresholds as the weekly detector.",
    )


# ---------------------------------------------------------------------------
# what_changed_this_week
# ---------------------------------------------------------------------------


def _signal_fact(s: dict[str, Any], names: dict[str, str], window: dict[str, str]) -> Fact:
    code = str(s["product_code"])
    start, end = _ymd(window["current_start"]), _ymd(window["current_end"])
    name = names.get(code)
    head = f"{code} ({name})" if name else code
    text = (
        f"{head}: {s['label']}. {plural(int(s['current_count']), 'report')} received "
        f"{speak_range(start, end)}, against a weekly average of "
        f"{_num(float(s['baseline_weekly_mean']))} in the four weeks before."
    )
    if s.get("current_severe_count"):
        text += " " + _severe_phrase(int(s["current_severe_count"]))
    return Fact(
        text=text,
        link=links.counts_link(code, start, end),
        link_label="openFDA: reports in this week",
    )


def _stored_what_changed(data: ConnectorData, product_code: str | None) -> ToolAnswer:
    digest = data.digest()
    window = digest["window"]
    names: dict[str, str] = dict(digest.get("device_types") or {})
    order = {r["product_code"]: r["rank"] for r in digest.get("ranking", [])}
    signals = sorted(
        digest["signals"],
        key=lambda s: (order.get(s["product_code"], 10_000), s["product_code"]),
    )
    rng = speak_range(
        window["current_start"].replace("-", ""), window["current_end"].replace("-", "")
    )
    if product_code is not None:
        signals = [s for s in signals if s["product_code"] == product_code]
    flagged = [s for s in signals if s["classification"] != "stable"]
    stable = [s for s in signals if s["classification"] == "stable"]

    parts: list[str] = []
    if flagged:
        top = flagged[0]
        parts.append(
            f"In the stored demo snapshot for {rng}, {top['product_code']} shows "
            f"{top['label']}: {plural(int(top['current_count']), 'report')} against a weekly "
            f"average of "
            f"{_num(float(top['baseline_weekly_mean']))} in the four weeks before."
        )
        if len(flagged) > 1:
            others = ", ".join(str(s["product_code"]) for s in flagged[1:])
            parts.append(f"Also changed: {others}.")
    else:
        which = product_code or "any device type"
        parts.append(f"In the stored demo snapshot for {rng}, {which} shows no change.")
    if stable and product_code is None:
        n = len(stable)
        parts.append(f"The other {n} device {'type shows' if n == 1 else 'types show'} no change.")
    return ToolAnswer(
        tool="what_changed_this_week",
        speakable=compose(parts),
        facts=[_signal_fact(s, names, window) for s in flagged + stable],
        provenance=snapshot_provenance(data, f"week {rng}"),
    )


def _live_answer(tool: str, check: LiveCheck, now: datetime) -> ToolAnswer:
    code = check.product_code
    prior_link = dict(check.queries).get("Everything before this week") or links.counts_link(
        code, None, None
    )
    if check.window is None or check.as_of is None:
        total = check.prior_report_count
        said = (
            f"{code} has no reports on openFDA in the last two years; "
            f"{plural(total, 'report')} in total."
            if total
            else f"openFDA returned no reports for {code}."
        )
        return ToolAnswer(
            tool=tool,
            speakable=compose([said]),
            facts=[
                Fact(
                    text=f"{plural(total, 'report')} on openFDA for {code}, all dates.",
                    link=links.counts_link(code, None, None),
                    link_label="openFDA: reports, all dates",
                )
            ],
            provenance=live_provenance(check, now),
        )
    w = check.window
    cs, ce = w.current_start.strftime("%Y%m%d"), w.current_end.strftime("%Y%m%d")
    bs, be = w.baseline_start.strftime("%Y%m%d"), w.baseline_end.strftime("%Y%m%d")
    changes = " and ".join(CHANGE_LABELS[t] for t in check.triggers) or check.change
    parts = [
        f"Live from openFDA as of {speak_date(check.as_of)}, {code} shows {changes}.",
        f"There {were(check.current_count)} {plural(check.current_count, 'report')} in the 7 "
        "days ending that day, against a "
        f"weekly average of {_num(check.baseline_weekly_mean)} in the four weeks before.",
    ]
    if check.new_event_types:
        parts.append(f"New kinds of event this week: {', '.join(check.new_event_types)}.")
    elif check.current_severe_count:
        parts.append(_severe_phrase(check.current_severe_count))
    facts = [
        Fact(
            text=f"{plural(check.current_count, 'report')} received {speak_range(cs, ce)}.",
            link=links.counts_link(code, cs, ce),
            link_label="openFDA: reports in this week",
        ),
        Fact(
            text=(
                f"{plural(check.baseline_count, 'report')} received {speak_range(bs, be)}, "
                f"a weekly average of {_num(check.baseline_weekly_mean)}."
            ),
            link=links.counts_link(code, bs, be),
            link_label="openFDA: reports in the baseline",
        ),
        Fact(
            text=f"{plural(check.prior_report_count, 'report')} received before {speak_date(cs)}.",
            link=prior_link,
            link_label="openFDA: reports before this week",
        ),
    ]
    if check.current_count:
        facts.append(
            Fact(
                text=(
                    f"{check.current_severe_count} of this week's "
                    f"{plural(check.current_count, 'report')} "
                    f"{were(check.current_count)} injury or death."
                ),
                link=dict(check.queries).get("This week, by event type")
                or links.counts_link(code, cs, ce),
                link_label="openFDA: this week by event type",
            )
        )
    return ToolAnswer(
        tool=tool,
        speakable=compose(parts),
        facts=facts,
        provenance=live_provenance(check, now),
    )


def what_changed_this_week(
    data: ConnectorData,
    product_code: str | None = None,
    *,
    live_checker: LiveChecker,
    now: Clock = utc_now,
    code_exists: CodeChecker | None = None,
) -> ToolAnswer:
    """What changed in the latest stored week; a code outside the stored set is checked live.

    Args:
        data: Stored data.
        product_code: Optional three-letter FDA product code.
        live_checker: Live openFDA check (used only for a code not in the stored set).
        now: Clock (tests).
        code_exists: Looks the code up in the openFDA classification list (only asked when the
            live check finds no reports and the code is not otherwise known).

    Raises:
        InvalidInputError: The code is not three letters.
        SourceUnavailableError: A live check was needed and openFDA could not be reached.
    """
    if product_code is None:
        return screen(_stored_what_changed(data, None))
    code = _code(product_code)
    stored = {str(s["product_code"]) for s in data.digest()["signals"]}
    if code in stored:
        return screen(_stored_what_changed(data, code))
    return _live(data, code, "what_changed_this_week", live_checker, now, code_exists)


def _live(
    data: ConnectorData,
    code: str,
    tool: str,
    live_checker: LiveChecker,
    now: Clock,
    code_exists: CodeChecker | None = None,
) -> ToolAnswer:
    try:
        check = live_checker(code)
    except OpenFDAAPIError as exc:
        raise SourceUnavailableError(
            "openFDA could not be reached just now; try again shortly."
        ) from exc
    known = data.known_product_codes()
    if (
        code not in known
        and check.window is None
        and check.prior_report_count == 0
        and check.current_count == 0
        and code_exists is not None
        and code_exists(code) is False
    ):
        # No stored data and no report on openFDA ever: a typo, unless FDA lists the code in its
        # device classification (many real codes have no reports). Suggestions are only shown,
        # never applied. If the classification list cannot be read, the code is not called
        # unknown.
        raise unknown_code_error(code, known)
    return screen(_live_answer(tool, check, now()))


# ---------------------------------------------------------------------------
# check_device_type
# ---------------------------------------------------------------------------


def check_device_type(
    data: ConnectorData,
    product_code: str,
    *,
    live_checker: LiveChecker,
    now: Clock = utc_now,
    code_exists: CodeChecker | None = None,
) -> ToolAnswer:
    """Live openFDA counts for any product code, with the detector's rules.

    If openFDA cannot be reached and the code is in the stored set, the stored answer
    is returned and says so; otherwise the call fails with ``SourceUnavailableError``.
    """
    code = _code(product_code)
    try:
        return _live(data, code, "check_device_type", live_checker, now, code_exists)
    except SourceUnavailableError:
        if code not in {str(s["product_code"]) for s in data.digest()["signals"]}:
            raise
        stored = _stored_what_changed(data, code)
        stored.tool = "check_device_type"
        rest = re.split(r"(?<=[.!?])\s+", stored.speakable)
        stored.speakable = compose([LIVE_FAILED_LEAD, *rest[:2]])  # at most three sentences
        stored.provenance.note = (
            "Live openFDA could not be reached, so this is the stored demo snapshot instead."
        )
        return screen(stored)


# ---------------------------------------------------------------------------
# get_report
# ---------------------------------------------------------------------------


def get_report(data: ConnectorData, report_id: str) -> ToolAnswer:
    """One stored MAUDE report: key fields and the start of its narrative.

    Raises:
        InvalidInputError: The id is not a plausible report id.
        NotFoundError: The report is not in the stored demo snapshot.
    """
    rid = report_id.strip()
    if not _REPORT_ID.match(rid):
        raise InvalidInputError("A report id is letters, digits and dashes, up to 24 characters.")
    record = data.store.record(rid)
    if record is None:
        raise NotFoundError(
            f"Report {rid} is not in the stored demo snapshot. "
            "That does not mean it is not on openFDA."
        )
    link = links.report_link(rid)
    kind = (record.event_type or "unknown").lower()
    received = speak_date(record.date_received) if record.date_received else "an unknown date"
    facts = [
        Fact(
            text=(
                f"Report {rid}: product code {record.product_code}, event type {kind}, "
                f"received {received}."
            ),
            link=link,
            link_label="openFDA report",
        )
    ]
    who = ", ".join(
        p
        for p in (
            f"brand {record.brand_name}" if record.brand_name else "",
            f"manufacturer {record.manufacturer}" if record.manufacturer else "",
        )
        if p
    )
    if who:
        facts.append(
            Fact(text=f"Report {rid} lists {who}.", link=link, link_label="openFDA report")
        )
    narrative = " ".join(record.text.split())
    if narrative:
        cut = narrative[:NARRATIVE_CHARS] + ("..." if len(narrative) > NARRATIVE_CHARS else "")
        facts.append(
            Fact(
                text=f'Start of the narrative, word for word: "{cut}"',
                link=link,
                link_label="openFDA report",
            )
        )
    return screen(
        ToolAnswer(
            tool="get_report",
            speakable=compose(
                [
                    f"Report {rid} is a {kind} report for product code {record.product_code}, "
                    f"received {received}.",
                    "The start of its narrative is in the facts.",
                ]
            ),
            facts=facts,
            provenance=snapshot_provenance(data, f"report received {received}"),
        )
    )


# ---------------------------------------------------------------------------
# recalls
# ---------------------------------------------------------------------------


def _first_sentence(text: str, limit: int = 160) -> str:
    one = plain(" ".join(text.split()))
    cut = re.split(r"(?<=[.!?])\s", one, maxsplit=1)[0]
    return cut if len(cut) <= limit else cut[:limit].rsplit(" ", 1)[0] + "..."


def recalls(
    data: ConnectorData, product_code: str, *, code_exists: CodeChecker | None = None
) -> RecallsAnswer:
    """Stored FDA recalls for a product code, newest first (top five as facts).

    Suggestions ("did you mean", distance 1 only; also the structured ``suggestions`` list)
    appear only when the code is not stored and the openFDA classification check says it does
    not exist (``False``). A real code, or a check that
    could not run (``None``), gets no suggestion and is never called unknown.

    Raises:
        InvalidInputError: The code is not three letters.
    """
    code = _code(product_code)
    rows = sorted(
        data.store.select_recalls(product_code=code),
        key=lambda r: (r.date_initiated or "", r.recall_number),
        reverse=True,
    )
    prov = snapshot_provenance(data, None, recalls=True)
    all_link = links.product_recalls_link(code)
    if not rows:
        # recalls is stored-only, so a typo is not an error here: the answer still opens the
        # openFDA link, and close known codes are offered as a question, never applied.
        known = data.known_product_codes()
        close: list[str] = []
        if code not in known and code_exists is not None and code_exists(code) is False:
            close = suggest_codes(code, known)
        said = [
            f"The stored demo snapshot holds no recalls for product code {code}.",
            "That does not mean none exist; open the openFDA link to check.",
        ]
        if close:
            said.append(f"{code} isn't a product code we know - did you mean {either(close)}?")
            prov.note = (
                f"{prov.note or ''} Possible codes, not applied: {', '.join(close)}. "
                "Confirm the code with the person."
            )
        return screen(
            RecallsAnswer(
                tool="recalls",
                speakable=compose(said),
                facts=[
                    Fact(
                        text=f"openFDA recall query for product code {code}.",
                        link=all_link,
                        link_label="openFDA: recalls for this code",
                    )
                ],
                provenance=prov,
                suggestions=close,
            )
        )
    latest = rows[0]
    started = speak_date(latest.date_initiated) if latest.date_initiated else "an unknown date"
    events = {r.event_number for r in rows if r.event_number}
    if events and all(r.event_number for r in rows):
        # openFDA lists one row per recalled product; several rows can share one recall event
        counted = (
            f"{plural(len(rows), 'recall product record')} "
            f"({plural(len(events), 'recall event')})"
        )
    else:
        counted = plural(len(rows), "recall product record")
    parts = [
        f"The stored demo snapshot holds {counted} for product code {code}.",
        f"The most recent started {started}"
        + (f" by {latest.recalling_firm}." if latest.recalling_firm else "."),
    ]
    facts = [
        Fact(
            text=f"{counted} for product code {code} in the stored snapshot.",
            link=all_link,
            link_label="openFDA: recalls for this code",
        )
    ]
    for r in rows[:MAX_RECALL_FACTS]:
        when = speak_date(r.date_initiated) if r.date_initiated else "unknown date"
        facts.append(
            Fact(
                text=(
                    f"Recall {r.recall_number}, started {when}"
                    + (f" by {r.recalling_firm}" if r.recalling_firm else "")
                    + (f", status {r.recall_status}" if r.recall_status else "")
                    + f". Reason: {_first_sentence(r.reason_for_recall)}"
                ),
                link=links.recall_link(r.recall_number),
                link_label="openFDA recall",
            )
        )
    return screen(
        RecallsAnswer(tool="recalls", speakable=compose(parts), facts=facts, provenance=prov)
    )
