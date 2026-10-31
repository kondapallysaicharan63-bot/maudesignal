"""The ``/privacy`` and ``/terms`` pages (plain HTML, inline CSS, no external assets).

HACKATHON-BUILT — Meta Global AI Developer Hackathon (Oct 26 – Nov 4, 2026).

The privacy page answers a data questionnaire honestly: where data is processed and stored, who
else handles it, what is logged and for how long, how to ask for deletion. The same answers sit
in ``docs/hackathon/MUSE_CONNECTOR.md`` under "Data questionnaire"; change both together. The
contact address is read at runtime from ``MAUDESIGNAL_CONTACT_EMAIL`` and is never written in the
repository; without it the page names the GitHub issues URL.
"""

from __future__ import annotations

import html
import os
import re

from maudesignal.connector.docs_page import SUPPORT_URL

CONTACT_ENV = "MAUDESIGNAL_CONTACT_EMAIL"
_EMAIL = re.compile(r"^[A-Za-z0-9._%+-]{1,64}@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+$")

STYLE = """
:root{--paper:#f6f3ec;--ink:#16130f;--muted:#5e574c;--rule:#d9d2c2;--accent:#1d3fbf;
--card:#fffdf8}
@media (prefers-color-scheme:dark){:root{--paper:#14120f;--ink:#f1ece2;--muted:#a39b8d;
--rule:#3a352d;--accent:#9db0ff;--card:#1b1915}}
*{box-sizing:border-box}
body{margin:0;background:var(--paper);color:var(--ink);
font:17px/1.6 Newsreader,Georgia,serif}
main{max-width:46rem;margin:0 auto;padding:2rem 16px 4rem}
h1{font-size:2rem;line-height:1.2;margin:0 0 .5rem}
h2{font-size:1.25rem;margin:2rem 0 .5rem;border-top:1px solid var(--rule);padding-top:1rem}
p,li{max-width:42rem}
a{color:var(--accent)}
.lede{color:var(--muted)}
table{border-collapse:collapse;width:100%;background:var(--card)}
th,td{border:1px solid var(--rule);padding:.5rem .7rem;text-align:left;vertical-align:top}
.scroll{overflow-x:auto}
nav{margin-bottom:1.5rem;font:15px/1.4 "Geist",system-ui,sans-serif}
nav a{margin-right:1rem}
"""

#: (question, answer) pairs, shown on the page and copied into MUSE_CONNECTOR.md.
STATIC_ANSWERS: tuple[tuple[str, str], ...] = (
    (
        "What does this service do with data?",
        "It gives read-only access to public FDA device data (openFDA: adverse-event reports, "
        "recalls, 510(k) records) and, where a result says so, to device alerts from the UK "
        "MHRA, always labelled as UK. It is an advisory triage aid for quality and regulatory "
        "review.",
    ),
    (
        "Is any personal or patient data collected?",
        "No. The data served is public and already de-identified by FDA. There are no accounts "
        "and no sign-up. Do not type patient or personal details into a question: the live "
        "routes refuse text that looks like a name with a title, an age, an email address or a "
        "phone number, and nothing is kept when they do.",
    ),
    (
        "Where is data processed and stored?",
        "The service's functions run on Vercel in region iad1 (Washington, D.C., United "
        "States), as set in the project's vercel.json. Feedback entries, page-visit entries "
        "and the daily spend records are stored in a private Vercel Blob store. The region of"
        " that store is chosen when the store is created in the Vercel dashboard; the code "
        "does not check it, so this page does not state it. The other services named below "
        "(Meta Model API, Resend, GDELT, and Upstash if the operator sets it up) process what"
        " they receive in their own locations, which this service does not control.",
    ),
    (
        "Who else handles data (subprocessors)?",
        "Vercel (hosting, runtime logs and Blob storage). Meta Model API: only when live "
        "answers are switched on, for the live ask, voice and label routes; the question text, "
        "the audio clip or the image is sent once to produce the answer and is not stored by "
        "this service. Resend (email): only if the operator turns on email for new feedback; "
        "the email carries the feedback fields, no name and no address. Public data sources "
        "that this service reads: openFDA, GOV.UK (MHRA alerts), GDELT and FDA public feeds "
        "(for the outside-mentions search). These send us public data; we send them a product "
        "code or a search term, never a person's details.",
    ),
    (
        "What is logged, and for how long?",
        "Per tool call: a key id (a keyed hash of the key, never the key), the tool name, the"
        " time, the status and the cost. Never the text of a question: for ask, only a hash "
        "and a length are recorded. Feedback is stored without names (role and quote consent "
        "only). A page visit stores the referral code, the page and the time. This service "
        "never stores an IP address: before any rate limit or counter sees it, the address is"
        " replaced by a keyed hash, which is held in memory (or in the operator's Redis "
        "store, if one is set up) only to apply limits, for at most twice the limit window "
        "(two days for daily counters). Vercel's own request logs may include the address; "
        "they are kept by Vercel for Vercel's runtime-log retention for this plan. Feedback "
        "and visits are kept until the hackathon review ends, then deleted on request or by "
        "30 November 2026.",
    ),
    (
        "Cookies, tracking, sale of data, advertising?",
        "No tracking cookies. No sale of data. No advertising and no use of data for ads. The "
        "separate web app may use Vercel Web Analytics for page-view counts, which sets no "
        "cookies.",
    ),
    (
        "Not medical advice, nothing filed",
        "Nothing here is medical advice or clinical decision support. Nothing is filed with "
        "FDA or any other regulator. This is not an FDA-cleared device. It is an open-source "
        "project by Saicharan Kondapally.",
    ),
)


def contact_line(env: dict[str, str] | None = None) -> tuple[str, str]:
    """``(text, href)`` for the deletion and support contact.

    The email comes from ``MAUDESIGNAL_CONTACT_EMAIL`` when it looks like an address;
    otherwise the GitHub issues URL is used.
    """
    raw = (os.environ if env is None else env).get(CONTACT_ENV, "").strip()
    if _EMAIL.match(raw):
        return raw, f"mailto:{raw}"
    return SUPPORT_URL, SUPPORT_URL


def _page(title: str, body: str) -> str:
    return (
        "<!doctype html><html lang='en'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width, initial-scale=1'>"
        f"<title>{html.escape(title)}</title><style>{STYLE}</style></head><body><main>"
        "<nav><a href='/'>API docs</a><a href='/privacy'>Privacy</a>"
        "<a href='/terms'>Terms</a></nav>"
        f"{body}</main></body></html>"
    )


def render_privacy(env: dict[str, str] | None = None) -> str:
    """The privacy page as HTML."""
    text, href = contact_line(env)
    rows = "".join(
        f"<tr><th scope='row'>{html.escape(q)}</th><td>{html.escape(a)}</td></tr>"
        for q, a in STATIC_ANSWERS
    )
    deletion = (
        "<tr><th scope='row'>How do I ask for deletion?</th><td>Write to "
        f"<a href='{html.escape(href)}'>{html.escape(text)}</a> and give the referral code "
        "you were sent (feedback and visits carry no name, so the code is how an entry is "
        "found). Entries are deleted on request.</td></tr>"
    )
    body = (
        "<h1>Privacy</h1>"
        "<p class='lede'>MaudeSignal is an open-source project. This page answers, in plain "
        "words, what happens to data when you use the API, the connector or the website.</p>"
        f"<div class='scroll'><table><tbody>{rows}{deletion}</tbody></table></div>"
        "<h2>Contact</h2>"
        f"<p>Questions, corrections or deletion: <a href='{html.escape(href)}'>"
        f"{html.escape(text)}</a>.</p>"
        "<p><a href='/terms'>Terms</a></p>"
    )
    return _page("MaudeSignal privacy", body)


TERMS_ITEMS: tuple[str, ...] = (
    "Research and demonstration use. The service is provided as is, without warranty of any "
    "kind, including accuracy, completeness, availability or fitness for a purpose.",
    "Not medical advice. Nothing returned is clinical guidance, and no clinical decision "
    "should be made from it. A qualified person must review any signal before acting on it.",
    "Nothing is filed with FDA or any other regulator. This is not an FDA-cleared device.",
    "Sources and dates. Every answer says where it came from: a stored snapshot with its "
    "dates, live openFDA with the query time, a recorded answer or a live model answer. "
    "Stored data can be out of date. Sentences marked as left out could not be verified and "
    "must not be stated as fact. Outside mentions from news and public web pages are "
    "unverified and are never mixed with checked FDA facts.",
    "Rate limits apply to every key and every address, and a global daily cost cap applies "
    "to live model calls; when a limit is reached the service answers from recorded runs, "
    "labelled as recorded. Do not try to get around a limit.",
    "Keys are read-only and the operator can revoke any key at any time. Do not share a key "
    "that was given to you. The public demo key is shared by design and has lower limits.",
    "Do not send personal or patient information.",
    "U.S. FDA (openFDA) data only, plus labelled MHRA (UK) context where a result says so. "
    "No other regulator is covered.",
    "To the extent the law allows, the operator is not liable for decisions made from the "
    "output. The operator may change, limit or stop the service at any time.",
)


def render_terms(env: dict[str, str] | None = None) -> str:
    """The terms page as HTML."""
    text, href = contact_line(env)
    items = "".join(f"<li>{html.escape(t)}</li>" for t in TERMS_ITEMS)
    body = (
        "<h1>Terms</h1>"
        "<p class='lede'>Short terms for the MaudeSignal API, connector and website, an "
        "open-source project by Saicharan Kondapally.</p>"
        f"<ol>{items}</ol>"
        f"<p>Contact: <a href='{html.escape(href)}'>{html.escape(text)}</a>. "
        "<a href='/privacy'>Privacy</a></p>"
    )
    return _page("MaudeSignal terms", body)
