"""The ``/privacy`` and ``/terms`` pages (plain HTML, inline CSS, no external assets).

HACKATHON-BUILT — Meta Global AI Developer Hackathon (Oct 26 – Nov 4, 2026).

Every statement here describes what this code does. The contact address is never written in git:
it is read from ``MAUDESIGNAL_CONTACT_EMAIL`` when the page is served and HTML-escaped; when the
variable is unset the GitHub issues URL is shown. Whether live ``ask`` is on is computed from the
running configuration, and nothing else about it is revealed.
"""

from __future__ import annotations

import html
import os

from maudesignal.connector.ask import (
    MAX_QUESTION_CHARS,
    MIN_QUESTION_CHARS,
    live_mode_allowed,
)
from maudesignal.connector.callcap import MAX_CALL_HOLD_USD, enforced_cap
from maudesignal.connector.globalcap import global_daily_usd
from maudesignal.connector.models import ADVISORY
from maudesignal.connector.security import DEFAULT_DEMO_RATE_PER_MIN, DEMO_PER_DAY

CONTACT_ENV = "MAUDESIGNAL_CONTACT_EMAIL"
ISSUES_URL = "https://github.com/kondapallysaicharan63-bot/maudesignal/issues"
LAST_UPDATED = "2026-10-31"
RETENTION_DATE = "2026-12-31"

_CSS = """
:root{--paper:#f6f3ec;--ink:#16130f;--ink-2:#4a443b;--rule:#d8d1c3;--card:#fffdf8}
@media (prefers-color-scheme:dark){:root{--paper:#14120f;--ink:#f1ece2;--ink-2:#c4bcae;
--rule:#3a352d;--card:#1c1a16}}
*{box-sizing:border-box}
body{margin:0;background:var(--paper);color:var(--ink);line-height:1.6;
font-family:Georgia,'Times New Roman',serif}
main{max-width:46rem;margin:0 auto;padding:2rem 16px 3rem}
h1{font-size:1.8rem;line-height:1.2;margin:0 0 .25rem}
h2{font-size:1.15rem;margin:1.8rem 0 .4rem;padding-top:.8rem;border-top:1px solid var(--rule)}
p,li{font-size:1rem}
a{color:inherit}
.meta{color:var(--ink-2);font-size:.9rem}
.box{background:var(--card);border:1px solid var(--rule);border-radius:8px;padding:.6rem 1rem}
nav a{margin-right:1rem}
code{font-family:ui-monospace,Menlo,Consolas,monospace;font-size:.9em}
"""


def contact_html() -> str:
    """The contact line: the address from the environment (escaped) or the issues URL."""
    email = os.environ.get(CONTACT_ENV, "").strip()
    issues = f'<a href="{ISSUES_URL}">{ISSUES_URL}</a>'
    if email:
        safe = html.escape(email, quote=True)
        return f"Email {safe} or open an issue at {issues}."
    return f"Open an issue at {issues}."


def _live_limits() -> tuple[int, int, int, int, int]:
    """``(ask, voice, label, mentions, burst)`` per-address limits of the live website routes."""
    from maudesignal.connector.live import LiveConfig  # lazy: live imports this package

    cfg = LiveConfig.from_env()
    return (
        cfg.ask_per_day,
        cfg.voice_per_day,
        cfg.label_per_day,
        cfg.mentions_per_day,
        cfg.burst_per_min,
    )


def live_routes_line(live_on: bool | None = None) -> str:
    """What the live website routes send to Meta, stated for the running configuration."""
    if live_mode_allowed() if live_on is None else live_on:
        return (
            "<strong>Live routes are ON in this deployment.</strong> The website's live ask, "
            "voice and label routes send what you give them to Meta (Meta Model API: Muse "
            "Spark for questions and label reading, Muse Voice for transcription, SAM 3.1 for "
            "the label crop): the question text, the audio clip or the label image. It is sent "
            "once to produce the answer; this service does not store the text, the audio or "
            "the image."
        )
    return (
        "<strong>Live routes are OFF in this deployment</strong> (no model key or no private "
        "spend ledger is configured). The website's ask, voice and label routes return "
        "recorded answers and nothing is sent to Meta."
    )


def live_ask_line(live_on: bool | None = None) -> str:
    """One sentence saying whether this deployment sends ``ask`` questions to Meta."""
    if live_mode_allowed() if live_on is None else live_on:
        return (
            "<strong>Live ask is ON in this deployment.</strong> The text of an <code>ask</code> "
            "question is sent to Meta (Meta Model API, Muse Spark) with the server-side model key."
        )
    return (
        "<strong>Live ask is OFF in this deployment.</strong> <code>ask</code> returns recorded "
        "answers and nothing is sent to Meta."
    )


def _shell(title: str, body: str) -> str:
    return (
        "<!doctype html><html lang='en'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        f"<title>{html.escape(title)} | MaudeSignal API</title><style>{_CSS}</style></head><body>"
        "<main><nav><a href='/'>API docs</a><a href='/privacy'>Privacy</a>"
        f"<a href='/terms'>Terms</a></nav>{body}</main></body></html>"
    )


def render_privacy(
    *,
    rate_per_min: int,
    public_per_hour: int,
    shared_store: bool,
    live_on: bool | None = None,
    clients_on: bool = True,
) -> str:
    """The privacy page (it answers a connector data questionnaire).

    Args:
        rate_per_min: Requests per key per minute in force.
        public_per_hour: Keyless checks per address per hour in force.
        shared_store: True when an Upstash Redis store is configured.
        live_on: Whether live Meta calls are on here; ``None`` reads the environment.
        clients_on: Whether per-client call counts are kept (``MAUDESIGNAL_CLIENTS_PANEL``).
    """
    redis = (
        "Upstash Redis is configured here: rate-limit counters, the per-key daily totals, a "
        "six-hour cache of keyless check answers and the audit log are held there."
        if shared_store
        else "No Upstash Redis store is configured here: rate-limit counters and the audit log "
        "live in the memory of one server instance and are lost on a cold start."
    )
    resend = (
        "If the operator has set an email notifier (Resend), a new feedback entry is also "
        "emailed to the operator; this is off unless that is configured."
    )
    clients = (
        "<li>Per-client call counts (for the operator's private admin page): for each tool call "
        "with a key, a short one-way id of the key (never the key or any part of it), the key's "
        "label if it has one, whether it came over REST, MCP or the public demo key, and the "
        "time. No question, tool input, answer, address or user agent is kept with it.</li>"
        if clients_on
        else "<li>Per-client call counts are switched off here: none are kept.</li>"
    )
    clients_kept = " and per-client call counts" if clients_on else ""
    body = f"""
<h1>Privacy</h1>
<p class="meta">MaudeSignal connector API. Last updated {LAST_UPDATED}.</p>
<p class="box">{html.escape(ADVISORY)}</p>

<h2>What this service is</h2>
<p>A read-only connector to public adverse-event data from FDA (openFDA). Where an answer says so,
it also shows UK MHRA device alerts, labelled "MHRA (UK)", as regulator context only. No tool
writes anything. It is an open-source project by Saicharan Kondapally. It is not an FDA-cleared
device, not medical advice, and nothing is filed with FDA.</p>

<h2>Personal and patient data</h2>
<p>None is collected or wanted. The service has no accounts and no sign-up, and asks for no name,
email address or patient information. Do not put patient details in a question or in feedback;
the feedback form refuses text that looks like an email address, phone number, ID number or date
of birth, which is a guard and not a guarantee.</p>

<h2>Where data is processed and stored</h2>
<p>On Vercel in the United States (function region iad1, Washington DC). Vercel Blob (private)
holds website feedback and visit records{clients_kept} and the live-call spend ledger: one
small object per Meta call with its dollar amounts (its worst-case hold and, once the call
succeeded, its real cost) and no text, no address and no key. {html.escape(redis)}</p>

<h2>Subprocessors</h2>
<ul>
<li>Vercel Inc.: hosting, runtime logs and Blob storage.</li>
<li>Meta Platforms: Meta Model API, only when a model key is set on the server: for the
<code>ask</code> tool (full keys only) and for the website's live ask, voice and label routes.
{live_ask_line(live_on)} {live_routes_line(live_on)}</li>
<li>Upstash: only if a Redis store is configured (see above).</li>
<li>Resend: only if an email notifier is configured. {html.escape(resend)}</li>
</ul>

<h2>Public data sources</h2>
<p>openFDA (api.fda.gov) is queried live with a product code and, to match a device (the
website's label reader or the lookup_device tool), with the device name, model, manufacturer,
K-number or GTIN you give or that is read from the label (a UDI's lot and serial are never
sent). MHRA (UK) alerts come from a
stored copy previously fetched from the GOV.UK search API; this service does not call GOV.UK when
you use it.
The website's outside-mentions search sends a product code and device search terms (no personal
details; the route refuses text that looks like patient data) to public sources: GDELT, FDA
press-release, recall, MedWatch and medical-device feeds, and MedTech Dive. No model is called
for it.</p>

<h2>What is logged</h2>
<ul>
<li>For each tool call: a key id (a peppered one-way hash, never the key), the tool name, the time,
and the status. Spend on <code>ask</code> is kept as a daily total per key id (not per call),
and the spend ledger keeps one small object per Meta call with its dollar amounts only (see Where
data is processed and stored).
If the key has a label (for example a reviewer's name) the label is logged next to the key id.
Calls made with the public demo key are logged the same way, with the label <code>demo</code>.</li>
<li>The text of a question is <strong>not</strong> logged: only its SHA-256 and its length.
During a live <code>ask</code> the question is held briefly in the server instance's temporary
working database and replaced by its SHA-256 when the answer is done.</li>
<li>New feedback stores rating, comments, role, quote consent, referral code, page and time -
no names and no email addresses. Feedback sent before 31 October 2026 could include a name the
person typed; names are removed from those entries except where the person chose to be quoted by
name and role.</li>
<li>Visits store: referral code, page and time.</li>
{clients}
<li>IP addresses are never stored by this code. Before any rate limit sees an address it is turned
into a salted one-way hash (HMAC-SHA256); only that hash is used as the limit key, in memory or, if
a Redis store is configured, in that store, for at most twice the limit window. Vercel, as host,
keeps its own request logs (method, path, status, time and address) under its own retention rules;
this code does not copy them.</li>
</ul>

<h2>Retention</h2>
<p>Request logs follow Vercel's runtime-log retention for this plan. Feedback and visit
records{clients_kept} are kept until {RETENTION_DATE} and then deleted, earlier on request.</p>

<h2>Sale, advertising, cookies</h2>
<p>No sale of data, no advertising and no tracking cookies. This site sets no cookies.</p>

<h2>Limits that apply</h2>
<p>{rate_per_min} requests per key per minute; {public_per_hour} keyless checks per address per
hour; the live website routes are limited per address per day. Full numbers are on the
<a href="/terms">terms</a> page.</p>

<h2>Deletion and questions</h2>
<p>{contact_html()}</p>
"""
    return _shell("Privacy", body)


def render_terms(
    *,
    rate_per_min: int,
    public_per_hour: int,
    daily_usd: float,
    request_usd: float,
    failed_auth_per_min: int,
    total_daily_usd: float | None = None,
    demo_per_min: int = DEFAULT_DEMO_RATE_PER_MIN,
    demo_per_day: int = DEMO_PER_DAY,
) -> str:
    """The terms page, with the limits in force.

    Args:
        rate_per_min: Requests per key per minute.
        public_per_hour: Keyless checks per address per hour.
        daily_usd: Daily cost cap of ``ask`` per key.
        request_usd: Cost cap of one ``ask`` call.
        failed_auth_per_min: Wrong keys per address per minute before a 429.
        total_daily_usd: The one daily cost cap of the live website routes and ``ask`` together
            (``MAUDESIGNAL_LIVE_DAILY_USD``).
        demo_per_min: Requests per minute allowed to the public demo key.
        demo_per_day: Requests per UTC day allowed to the public demo key.
    """
    if total_daily_usd is None:
        total_daily_usd = global_daily_usd()
    live_ask, live_voice, live_label, live_mentions, live_burst = _live_limits()
    hold = MAX_CALL_HOLD_USD
    cap = enforced_cap(total_daily_usd)
    per_instance_item = ""
    if os.environ.get("MAUDESIGNAL_ALLOW_PER_INSTANCE_CAP", "").strip() == "1":
        per_instance_item = (
            "<li><strong>This deployment runs with the local-only override on.</strong> With no "
            "private ledger store, the spend ledger below is kept in the memory of one server "
            "process and starts again on a cold start, so the total over several instances can "
            f"pass ${total_daily_usd:.2f} per UTC day.</li>"
        )
    body = f"""
<h1>Terms</h1>
<p class="meta">MaudeSignal connector API. Last updated {LAST_UPDATED}.</p>
<p class="box">{html.escape(ADVISORY)}</p>

<h2>As is</h2>
<p>The service is provided as is, without warranty of any kind, for research and demonstration.
It can be changed, limited or stopped at any time. Stored data can be out of date; every answer
says its source and date.</p>

<h2>Not medical advice</h2>
<p>It is not medical advice and must not be used for clinical decisions. Outputs are signals for a
person to review. Nothing is filed with FDA, and the project is not an FDA-cleared device.</p>

<h2>Read-only</h2>
<p>Every tool is read-only. No endpoint writes data on your behalf.</p>

<h2>Keys and limits</h2>
<ul>
<li>API keys are personal and can be revoked at any time. Do not share a key.</li>
<li>{rate_per_min} requests per key per minute.</li>
<li>The public demo key (shown by <code>GET /v1/connect</code> when the operator sets one) is
shared by design: it works on every read tool except the audit list, is limited to
{demo_per_min} requests per minute and {demo_per_day} per UTC day, and never starts a live model
call (<code>ask</code> returns a recorded answer, labelled recorded). The per-minute and
per-day limits are counted per server instance unless a shared Upstash store is configured, so
without one the effective limit is the number shown times the instances.</li>
<li>{failed_auth_per_min} wrong or missing keys per address per minute, then HTTP 429.</li>
<li>{public_per_hour} keyless device-type checks per address per hour.</li>
<li>For <code>ask</code>: a question of {MIN_QUESTION_CHARS} to {MAX_QUESTION_CHARS} characters,
at most ${request_usd:.2f} per call and ${daily_usd:.2f} per key per UTC day. When a cap is
reached, <code>ask</code> returns a recorded answer instead of a live one.</li>
</ul>

<h2>Live website routes and the daily cost cap</h2>
<ul>
<li>The website's live routes (<code>/v1/live/ask</code>, <code>/v1/live/voice</code>,
<code>/v1/live/label</code>) and the keyed <code>ask</code> tool share ONE cost rule with a hard
ceiling of ${total_daily_usd:.2f} per UTC day.</li>
<li>Before every single model call (each Muse Spark reply, including each tool round and each
repair round, each voice transcription and each SAM image) the service works out the most that
one call could cost: the size of the prompt times the input price plus the reply limit times the
output price. It writes that worst-case amount as its own entry in a private ledger, adds up
every entry of the day, and makes the call only if the total, its own entry included, stays at
or under the limit. Otherwise it removes its entry and shows a recorded answer.</li>
<li>Only after a successful reply that reports its usage is the entry lowered to the real cost.
A call that fails, times out, or returns no usage stays counted at its worst case for the rest of
the day, even if it was never billed. The count can therefore be too high, never too low.</li>
<li>Calls that start at the same moment can each pass the check, so the limit enforced is
${total_daily_usd:.2f} minus the largest worst case one call may have (${hold:.2f}; a call whose
worst case is higher is not made): ${cap:.2f}. Live calls normally stop at about ${cap:.2f}, and
the total is designed to stay at or under ${total_daily_usd:.2f}; this relies on the ledger
store showing each completed write in the next listing.</li>
<li>If the ledger cannot be read, listed or written, no call is made and a recorded answer is
shown. With no private ledger store, live calls are off.</li>
{per_instance_item}
<li>Per address per UTC day: {live_ask} live questions, {live_voice} voice questions,
{live_label} label reads and {live_mentions} outside-mentions searches; at most {live_burst}
live requests per minute. Each is counted with the address stored only as a salted hash.</li>
<li>Voice clips are limited to 60 seconds and 4 MB, label images to 4 MB. The label and voice
routes refuse text that looks like patient data.</li>
</ul>

<h2>Acceptable use</h2>
<ul>
<li>Do not try to bypass rate limits, cost caps or authentication.</li>
<li>Do not put patient or personal data in questions or feedback.</li>
<li>Do not present an output as advice or as a finding by a regulator.</li>
</ul>

<h2>Privacy and contact</h2>
<p>See the <a href="/privacy">privacy</a> page. {contact_html()}</p>
"""
    return _shell("Terms", body)
