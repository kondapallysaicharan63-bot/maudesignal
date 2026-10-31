# MaudeSignal connector for Meta Muse: form answers

Status: **not submitted.** This file is the single source for every answer given on the Muse
connector form. Nothing here says Meta or anyone else has reviewed or endorsed the connector.

> **Merge note.** The longer version of this file (deploy steps, API and MCP reference, draft
> form answers 2.2 to 2.5) lives on `track-c-live`. This branch (`track-b-live`) adds only the
> parts below: the icon and the **Data questionnaire**. When the two branches meet, keep both
> texts in one file (an add/add conflict on this path is expected); the questionnaire below
> replaces the short privacy statement in 2.3 of the other version, and the public page
> `web/public/privacy/index.html` must say the same thing.

## Icon

512 x 512, original (a flat line with one spike and a red dot on a paper-coloured square; no Meta
or FDA mark): `docs/hackathon/maudesignal-icon.svg` and `docs/hackathon/maudesignal-icon.png`.

## Addresses the form needs (also shown on the site's "Connect to Muse" page)

| Field | Answer |
|---|---|
| MCP address | `https://maudesignal-api.vercel.app/mcp` |
| OpenAPI file | `https://maudesignal-api.vercel.app/openapi.json` |
| Authentication | API key in the `X-API-Key` header. No OAuth (not available). |
| Privacy policy | `https://maudesignal-api.vercel.app/privacy` (the same text is served by the web project at `/privacy/`) |
| Terms | `https://maudesignal-api.vercel.app/terms` |
| Key for a reviewer | handed over by the owner through the form's secure field, never in a chat or a repository |

## Data questionnaire

These are the answers to Meta's data questions. They describe what the code does today; anything
that is not known is marked **to confirm** and is not guessed. The public `/privacy` page repeats
them word for word in plain language.

| Question | Answer |
|---|---|
| What personal data does the connector collect? | **None by design.** There are no accounts, no sign-up and no name or email field. Feedback is free text without a name. The connector asks people not to type patient details, and checks free text for emails, phone numbers, "MRN" plus digits and dates of birth before it stores anything (a guard, not a guarantee). |
| Does it handle patient or health data? | **No.** The data it serves is public openFDA device data (adverse-event reports, recalls, 510(k) records), already de-identified by FDA. It is a quality and regulatory triage aid; it is not medical advice and not clinical decision support. |
| Where is data processed and stored? | On Vercel. Serverless functions run in the **US, region iad1 (Washington, D.C.)**; no other region is set in `vercel.json`, so Vercel's default applies (**to confirm** in the Vercel project settings before submitting). The web workspace is static files served by Vercel. Feedback notes and visit counts are kept in a **private Vercel Blob store**. Stored public-data snapshots ship inside the deployment. |
| Who are the subprocessors? | **Vercel** (hosting, serverless functions, private Blob storage, and Web Analytics on the web workspace). **Meta Platforms, through the Meta Model API**, only for the `ask` tool when live answers are switched on; with no model key, or when the daily cost cap is reached, `ask` returns a recorded answer and nothing is sent to Meta. **openFDA (api.fda.gov, run by FDA)** as the public data source: it receives only a three-letter product code or a report number, never a question. For the optional "Search outside sources" button the server also asks public news and feed sources (GDELT, FDA feeds, other public RSS) for pages matching a product code and short device terms, and fetches those public pages. If the owner turns on e-mail notifications for feedback, **Resend** relays that e-mail (off unless configured). |
| What is sent to Meta? | Only the text of an `ask` question (and the conversation turns the page sends with it) plus the checked facts needed to answer, when live answers are on. Not sent: keys, IP addresses, files, photos. A label photo is read once for the camera feature and is never stored; it is not part of the connector. What Meta does with API requests is governed by Meta's own terms for the Meta Model API. |
| What is logged? | One audit entry per tool call: the **key id** (a keyed hash; never the key), the **tool name**, the **time**, the inputs that are public identifiers (a product code or a report number), a hash of the answer, counts of facts and withheld sentences, and the data source and its dates. **No question text**: for `ask` only a SHA-256 of the question and its length are kept. Feedback entries hold the rating, the free text, the page and an optional personal link code, **no name, no email, no IP address, no user agent**. Visit entries hold the page, the time and the link code. For rate limiting, a counter keyed by a salted hash of the network address lives only as long as the limit window. Vercel also keeps its own request logs (method, path, status, address, time) under its own retention. |
| How long is it kept? | **No automatic deletion period is set today** for audit, feedback or visit entries (**to confirm**: the owner may add one); rate-limit counters last only for their window (minutes to a day); in-memory data disappears when a server instance stops. Entries are deleted on request (next row). Vercel's own request logs follow Vercel's retention, which MaudeSignal does not control. |
| How can someone ask for deletion? | E-mail **kondapallysaicharan63@gmail.com** (**to confirm** this is the address to publish) with the key id or the personal link code the entries are tied to. Because no name or email is stored, entries can only be found by that code or key id. Entries tied to a code or key are deleted and the owner replies when done. |
| Is any of it sold, used for ads or shared for marketing? | **No.** It is not sold, not used for advertising or profiling, and not shared with anyone other than the subprocessors above, who handle it only to run the service. MaudeSignal does not use it to train models. |
| Is it combined with data from other sources about a person? | **No.** No person is identified, so there is nothing to combine. |
| Are minors' data collected? | No. The service is for quality and regulatory professionals at medical-device companies (B2B). |
| Can users export or see their data? | The connector holds no profile. A person who gave a link code can ask for the feedback entries tied to it by e-mail (the deletion contact above). |
| Security | Keys only in headers, never in a URL; read-only tools (nothing writes to FDA or any other system); per-key and per-address limits; browser calls allowed only from the owner's listed web origins; the secret scan in CI (`scripts/scan_secrets.py`) fails the build if a key is committed. |
| Regions covered | U.S. FDA (openFDA) data only. MHRA (UK) alerts appear only where an answer labels them "MHRA (UK)". No other regulator is covered. |

### Things the owner still has to do for this section to be final

* Confirm the Vercel region of the API project (iad1 expected) and say so in the form.
* Decide a retention period for audit, feedback and visit entries, or keep "none set"; update the
  table row and `web/public/privacy/index.html` together.
* Confirm the contact e-mail to publish.
* Put the same text on the API's own `/privacy` (the API project is on `track-c-live`, which this
  branch does not touch).
