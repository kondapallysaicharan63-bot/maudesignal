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
from maudesignal.connector.models import ADVISORY

CONTACT_ENV = "MAUDESIGNAL_CONTACT_EMAIL"
ISSUES_URL = "https://github.com/kondapallysaicharan63-bot/maudesignal/issues"
LAST_UPDATED = "2026-10-31"
RETENTION_DATE = "2026-11-30"

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


def live_ask_line() -> str:
    """One sentence saying whether this deployment sends ``ask`` questions to Meta."""
    if live_mode_allowed():
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
) -> str:
    """The privacy page (it answers a connector data questionnaire).

    Args:
        rate_per_min: Requests per key per minute in force.
        public_per_hour: Keyless checks per address per hour in force.
        shared_store: True when an Upstash Redis store is configured.
    """
    redis = (
        "Upstash Redis is configured here: rate-limit counters, the daily cost ledger, a "
        "six-hour cache of keyless check answers and the audit log are held there."
        if shared_store
        else "No Upstash Redis store is configured here: rate-limit counters and the audit log "
        "live in the memory of one server instance and are lost on a cold start."
    )
    resend = (
        "If the operator has set an email notifier (Resend), a new feedback entry is also "
        "emailed to the operator; this is off unless that is configured."
    )
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
holds only website feedback and visit records. {html.escape(redis)}</p>

<h2>Subprocessors</h2>
<ul>
<li>Vercel Inc.: hosting, runtime logs and Blob storage.</li>
<li>Meta Platforms: Meta Model API, only when the <code>ask</code> tool runs live with a
server-side model key. {live_ask_line()}</li>
<li>Upstash: only if a Redis store is configured (see above).</li>
<li>Resend: only if an email notifier is configured. {html.escape(resend)}</li>
</ul>

<h2>Public data sources</h2>
<p>openFDA (api.fda.gov) is queried live with a product code only. MHRA (UK) alerts come from a
stored copy previously fetched from the GOV.UK search API; this service does not call GOV.UK when
you use it.</p>

<h2>What is logged</h2>
<ul>
<li>For each tool call: a key id (a peppered one-way hash, never the key), the tool name, the time,
and the status. Spend on <code>ask</code> is kept as a daily total per key id (not per call).</li>
<li>The text of a question is <strong>not</strong> logged: only its SHA-256 and its length.
During a live <code>ask</code> the question is held briefly in the server instance's temporary
working database and replaced by its SHA-256 when the answer is done.</li>
<li>New feedback stores rating, comments, role, quote consent, referral code, page and time -
no names and no email addresses. Feedback sent before 31 October 2026 could include a name the
person typed; names are removed from those entries except where the person chose to be quoted by
name and role.</li>
<li>Visits store: referral code, page and time.</li>
<li>IP addresses are never stored by this code. Before any rate limit sees an address it is turned
into a salted one-way hash (HMAC-SHA256); only that hash is used as the limit key, in memory or, if
a Redis store is configured, in that store, for at most twice the limit window. Vercel, as host,
keeps its own request logs (method, path, status, time and address) under its own retention rules;
this code does not copy them.</li>
</ul>

<h2>Retention</h2>
<p>Request logs follow Vercel's runtime-log retention for this plan. Feedback and visit records are
kept until {RETENTION_DATE} and then deleted, earlier on request.</p>

<h2>Sale, advertising, cookies</h2>
<p>No sale of data, no advertising and no tracking cookies. This site sets no cookies.</p>

<h2>Limits that apply</h2>
<p>{rate_per_min} requests per key per minute; {public_per_hour} keyless checks per address per
hour. Full numbers are on the <a href="/terms">terms</a> page.</p>

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
    total_daily_usd: float,
) -> str:
    """The terms page, with the limits in force.

    Args:
        rate_per_min: Requests per key per minute.
        public_per_hour: Keyless checks per address per hour.
        daily_usd: Daily cost cap of ``ask`` per key.
        request_usd: Cost cap of one ``ask`` call.
        failed_auth_per_min: Wrong keys per address per minute before a 429.
        total_daily_usd: Daily cost cap of ``ask`` over all keys together.
    """
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
<li>{failed_auth_per_min} wrong or missing keys per address per minute, then HTTP 429.</li>
<li>{public_per_hour} keyless device-type checks per address per hour.</li>
<li>For <code>ask</code>: a question of {MIN_QUESTION_CHARS} to {MAX_QUESTION_CHARS} characters,
at most ${request_usd:.2f} per call, ${daily_usd:.2f} per key per UTC day and
${total_daily_usd:.2f} over all keys together per UTC day. When a cap is reached, <code>ask</code>
returns a recorded answer instead of a live one.</li>
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
