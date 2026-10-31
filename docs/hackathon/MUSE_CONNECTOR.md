# MaudeSignal connector for Meta Muse (read-only REST API and MCP server)

This page is the single source for every answer on the Meta connector form (the first part,
"Form answers"), followed by how the API is deployed and what it does. Nothing on this page says
Meta, Muse or anyone else has reviewed or endorsed the connector.

# Form answers

**Status: Submitted to Meta's Muse Connector Program — pending review.**

Detail: submitted Oct 31, 2026; business verification, data questionnaire and technical details
complete; Meta shows "In review".

Field names and limits on the live form may differ from the headings below; read the form first
and paste from here.

## Name

MaudeSignal

## Short description

Read-only triage of public FDA device adverse-event data, with links. (66 characters; limit 80.)

## Long description

MaudeSignal is a read-only connector to public FDA adverse-event data (MAUDE, recalls and 510(k)
records from openFDA). It answers questions for quality and regulatory professionals at
medical-device companies: what changed this week for a device type, a live count check for any
three-letter product code, one stored report, recalls, and a free-text question answered through
deterministic tools. Every sentence of an `ask` answer passes a claim check, and a sentence that
cannot be linked to an openFDA or stored record is listed as withheld and is never spoken as fact.
Every answer carries its source and date, and a fixed line: advisory triage aid; not medical
advice; nothing is filed with FDA. MHRA (UK) alerts appear only as labelled regulator context.

## Category suggestion

Regulatory and quality (B2B) or Research. Audience: quality, regulatory and post-market
surveillance staff. Not for patients; not clinical decision support.

## Endpoints

| What | URL |
|---|---|
| MCP (streamable HTTP, stateless, protocol 2025-06-18) | `https://maudesignal-api.vercel.app/mcp` |
| REST base | `https://maudesignal-api.vercel.app` |
| OpenAPI 3.1 | `https://maudesignal-api.vercel.app/openapi.json` |
| Docs page | `https://maudesignal-api.vercel.app/` |
| Health (no key) | `https://maudesignal-api.vercel.app/v1/health` |
| Connect info (no key) | `https://maudesignal-api.vercel.app/v1/connect` |
| Privacy / Terms | `https://maudesignal-api.vercel.app/privacy`, `https://maudesignal-api.vercel.app/terms` |

`GET /v1/connect` needs no key (CORS only for the origins in `MAUDESIGNAL_WEB_ORIGINS`). It returns
`mcp_url`, `openapi_url`, `docs_url`, `privacy_url`, `terms_url`, `auth_header` (`X-API-Key`),
`demo_key` (the first demo key, or `null` when none is set), `demo_limits` and three short steps.
Set `MAUDESIGNAL_PUBLIC_URL` if the public address differs from the one the request arrives on.

## Authentication

Header `X-API-Key: <key>` (the form `Authorization: Bearer <key>` also works). Keys are read-only
and can be revoked at any time. A key in a URL is refused. No OAuth.

`MAUDESIGNAL_API_KEYS` holds the keys, comma-separated. Each entry may carry a label, written
`label=KEY` (label: 1 to 32 letters, digits, `-` or `_`). For this submission the value is exactly:

```
charan=<your key>,meta-review=<reviewer key>
```

The label is never part of the key: send only `<key>`, never `charan=<key>` (that is refused).
Logs and the audit list show the label next to the key id. Other accepted entry forms: a plain
`KEY` (at least 32 characters), `sha256:<64 hex>` and `label=sha256:<64 hex>`. Spaces around commas
are fine. A bad label stops the server at startup with a message that names the entry number and
never shows a key.

**How the reviewer key is sent:** privately, outside this repository and outside the submission
form (for example in the form's private reviewer-notes field or a direct message to the reviewer),
as the bare key. It is never written in the repository, in a pull request or in a public post.

**Revoking:** delete that entry from `MAUDESIGNAL_API_KEYS` in Vercel and redeploy; only that key
stops working. Set `MAUDESIGNAL_KEY_PEPPER` first so the other key keeps its key id.

## Demo key

A public key anyone can use for a first try, set with `MAUDESIGNAL_DEMO_KEYS` (same entry formats;
leave it unset to switch the demo key off). It is public by design and must never be committed.
`GET /v1/connect` shows the first demo key when it was entered as a plain key.

* Can: call every read tool (`what_changed_this_week`, `check_device_type`, `ask`, `get_report`,
  `recalls`, `lookup_device`) over REST and MCP.
* Cannot: read the audit list (HTTP 403), start a live model call (`ask` returns a recorded answer,
  labelled recorded, whatever the server's model settings), or reach any admin route.
* Limits, per demo key: `MAUDESIGNAL_DEMO_RATE_PER_MIN` requests per minute (default 10) and 200
  per UTC day. Over a limit the answer is HTTP 429 with `Retry-After`. Without a shared Upstash
  store these counts are kept per server instance (and reset on a cold start), so the effective
  limit is the number times the instances.
* Audit: its calls are logged with the label `demo`.

To enable it: in Vercel > Project > Settings > Environment Variables (Production) set
`MAUDESIGNAL_DEMO_KEYS` to a new random key (for example `demo=<key>`), then redeploy.

## Tools (all read-only; none writes anything)

| Tool | What it does | Source |
|---|---|---|
| `what_changed_this_week` | Latest stored week for a product code, labelled with its dates; a code outside the stored set is checked live on openFDA. | stored snapshot, or live openFDA |
| `check_device_type` | Live openFDA report counts for any product code, using the weekly detector's four rules, windows and thresholds. | live openFDA |
| `ask` | A free-text question (3 to 500 characters) answered through deterministic tools; every sentence passes the claim gate; withheld sentences are listed apart. | **Live Muse Spark only when live ask is on; with it off, a recorded answer, labelled `recorded_answer`.** |
| `get_report` | Key fields and the start of the narrative of one stored report. | stored snapshot |
| `recalls` | Stored openFDA recalls for a product code, newest first. | stored snapshot |
| `lookup_device` | For what a model read from a device photo (any of `device_name`, `model`, `manufacturer`, `k_number`, `udi`, `gtin`, `product_code`; at least one): up to 3 possible FDA records from openFDA 510(k), registration & listing and UDI, each with `why_matched`, `why_not_matched` and links; plus, for the top product code(s), this week's change (same check as `check_device_type`), recalls started in the last two years (count and link) and the report count (count and link). `status` is `needs_person_to_confirm`, `no_match_found` or `search_failed` (with a `note`). `confirmed` is always `null`: the tool never picks a record, a person confirms one or none. No model call; read-only; the demo key may use it. | live openFDA |

`check_device_type` has a keyless twin, `GET /v1/public/check_device_type`, limited per address and
never calling a model.

### Tool descriptions

Each tool description (the same text in `tools/list`, the OpenAPI document and the manifest)
starts with "Use this ..." to say when to pick the tool, says it is read-only, and ends with
example questions: `what_changed_this_week` ("What changed for LLZ this week?"),
`check_device_type` ("Is anything unusual with QIH right now?"), `lookup_device` ("I photographed
a label: Welch Allyn 802 LTR - which FDA records match?"), `recalls` ("Show recalls for LLZ."),
`get_report` ("Show me report 50426770.") and `ask` ("What changed this week for LLZ?"). The input
schemas were not changed.

### MCP prompts

`prompts/list` and `prompts/get` (also listed by `GET /v1/connect` under `prompts`). A prompt only
returns one user message that asks the model to call the connector's own read-only tools; it reads
no data. Every message tells the model to cite the FDA links, that this is not medical advice, and
to say "recorded" for recorded answers.

| Prompt | Arguments | Message asks the model to |
|---|---|---|
| `morning_brief` | `product_codes` (comma-separated, up to 10, upper-cased, duplicates dropped) | call `what_changed_this_week` for each code and summarise with links |
| `check_this_device` | `text` (name, model, maker, K-number or UDI, up to 500 characters) | call `lookup_device`, list up to 3 possible matches with why, and ask the person to confirm one record, or none, before going further |
| `does_this_apply_to_us` | `product_code`; `our_device_description` (optional) | call `check_device_type`, `what_changed_this_week` and `recalls`, and present the problem patterns as questions for the person's own records, never as a verdict |

A bad prompt call is a JSON-RPC error `-32602` whose message names the argument (for example
"product_codes is required for this prompt.").

### Server instructions

Sent in the MCP `initialize` reply (`instructions`), used as the manifest `description`, and put
at the start of the OpenAPI `info.description` (one text, `GUIDANCE` in `connector/registry.py`):
always cite the FDA links given in each answer; not medical advice and nothing is filed with FDA;
confirm the product code with the person before guessing one (use `lookup_device` or ask); when an
answer is labelled recorded, say "recorded" and its date; never present withheld sentences as
fact; a person confirms every device match.

### Error format

Same JSON on every route: `{"error": {"code": "...", "message": "..."}}`, with
`"suggestions": ["..."]` added only when there is something to offer. Over MCP the message is the
text of an `isError: true` tool result. Messages are fixed text. The one value a message repeats is a three-letter product code that already passed the letters-only check (the unknown-code message). An empty body, a body that cannot be parsed as JSON or one sent without a JSON content type gets `The request body is not valid JSON.`; valid JSON that is not an object (such as `[1, 2]`) gets `The request body must be a JSON object.`; a wrong field is named, never an index.

| Case | Message |
|---|---|
| Product code not three letters | A product code is three letters, for example LLZ or QIH. |
| Three-letter code with no stored data, no openFDA reports and no openFDA classification entry (`unknown_product_code`) | QAH isn't a product code we know - did you mean QAQ, QAS or QIH? ... (up to 3 known codes one edit away, also in `suggestions`; with none one edit away, e.g. ZZZ: `ZZZ isn't a product code we know.` and no suggestions). Both are probed against the shipped data in `tests/unit/test_connector_m2c.py`. |
| Malformed K-number | K-numbers look like K123456 (the letter K and six digits). |
| UDI / GTIN fails the GS1 check digit | The GTIN ... does not pass the GS1 check digit test ... Re-read the digits from the label. |
| Report id not letters, digits, dashes | A report id is letters, digits and dashes, up to 24 characters. |
| Missing input | `<name> is required.` plus what it should be |
| Question too short or long | `question is too long: the limit is 500 characters.` (or at least 3) |
| Input longer than its limit | `<name> is too long: the limit is N characters.` |

"Known" codes are those in the stored reports, the device catalog, the stored digest and the stored
AI-device sweep (`ConnectorData.known_product_codes`; `demo/sweep` is in the Vercel
`includeFiles`, so the deployed set matches the tests); this repository holds no offline copy of the
full openFDA classification list. A suggestion is only shown, never applied. When a live check finds
no report for a code that is not known, the connector makes one more openFDA query on
`device/classification.json` (`product_code:XXX`). If FDA lists the code, the answer is the normal
200 "openFDA returned no reports for XXX" with its link and no suggestions. Only a code that is
also absent from the classification list gets `unknown_product_code` (422). If the classification
query fails, the 200 answer stands and the code is not called unknown. `recalls` (stored data only)
never fails on such a code: it keeps its "no recalls on file" answer and, when known codes one edit away exist, adds the "did you mean"
sentence, a provenance note and the same codes in the answer's `suggestions` list. Because it may query `device/classification.json` to confirm the code, `recalls` is marked `openWorldHint: true`.

## Example prompts

1. What changed this week for LLZ?
2. Check product code QAS on openFDA.
3. Show recalls for LLZ.
4. Get report 50426770.
5. Ask: what changed this week for LLZ? (with live ask off this returns the closest recorded answer)
6. I photographed this label: Welch Allyn 802 LTR, which FDA records match? (Muse reads the photo itself, then calls `lookup_device`; the answer lists possible matches, or says none were found, and says a person confirms. Not yet run against live openFDA: a bare name such as `Welch Allyn 802 LTR` with no maker may return `no_match_found`; adding `manufacturer` helps.)

## Rate limits and cost caps

Defaults in the code (each can be changed by the operator with an environment variable):

* 30 requests per key per minute (`MAUDESIGNAL_RATE_LIMIT_PER_MIN`); every HTTP request to `/mcp`
  counts once.
* 10 wrong or missing keys per address per minute, then 429 (`MAUDESIGNAL_FAILED_AUTH_PER_MIN`).
* 10 keyless device-type checks per address per hour (`MAUDESIGNAL_PUBLIC_CHECK_PER_HOUR`).
* `ask`: at most $0.25 per call and $2.00 per key per UTC day (`MAUDESIGNAL_API_REQUEST_USD`,
  `MAUDESIGNAL_API_DAILY_USD`; a per-key total that only counts real cost after a call). Every
  Meta call, from the keyed `ask` tool and from the website's live routes alike, also goes through
  ONE daily rule with a hard ceiling of $3.00 per UTC day (`MAUDESIGNAL_LIVE_DAILY_USD`): each model
  call reserves its worst case first and is released to its real cost only after a successful
  reply (see "Cost" under "Live Muse for the public website"). Live calls normally stop at about
  $2.90, which is $3.00 minus one call's largest hold ($0.10). Past a cap the closest recorded
  answer is returned. With two keys, set `MAUDESIGNAL_API_DAILY_USD=1.50` (or less) as well, and
  keep `MAUDESIGNAL_KEY_PEPPER` set (see "Two keys").
* Feedback form: 5 per hour per address; visits 60 per hour per address.

The live pages `/terms` and `/privacy` show the numbers actually in force.

## Data handling summary

Public openFDA data only (and MHRA (UK) alerts, labelled). No personal or patient data is collected
or wanted. Hosted on Vercel, United States (function region iad1). Question text is not logged
(only its SHA-256 and length). IP addresses are never stored by this code: before any rate limit
sees one it is turned into a salted one-way hash, and only that hash is the limit key (in memory,
or in the operator's Redis store for at most twice the limit window). Feedback records (no email addresses; no names except where the person chose to be quoted by name and role, see the Data questionnaire) and visit records are kept until 2026-12-31.
Meta receives the question text for live ask, the audio for live voice and the photo for live
label, only when `META_MODEL_API_KEY` is set. Details: `/privacy`.

## Privacy URL

`https://maudesignal-api.vercel.app/privacy`

## Terms URL

`https://maudesignal-api.vercel.app/terms`

## Support / work email

`<Charan's SJSU email - Charan fills in>` (the same address goes in the Vercel variable
`MAUDESIGNAL_CONTACT_EMAIL`, so `/privacy` and `/terms` show it; it is never written in git).
GitHub issues: `https://github.com/kondapallysaicharan63-bot/maudesignal/issues`

## Icon

`docs/hackathon/maudesignal-icon.png` (512x512 PNG, Charan's design: "MAUDE / SIGNAL" with a pulse line on green). Earlier draft kept as `docs/hackathon/maudesignal-icon-alt.png` / `.svg`.
An original mark (the words MAUDE and SIGNAL above a pulse line); no Meta or FDA logo.

## Data questionnaire

| Question | Answer |
|---|---|
| What is the service? | A read-only connector to public FDA adverse-event data (openFDA). MHRA (UK) alerts are shown only as labelled regulator context. |
| Does it collect personal or patient data? | No, none is collected or wanted. No accounts, names or emails. |
| Where is data processed and stored? | Vercel, United States (function region iad1, Washington DC). Vercel Blob (private) holds website feedback and visit records and also the spend ledger: one small object per Meta call with its dollar amounts (its worst-case hold and, once the call succeeded, its real cost). Amounts only: no text, no address, no key and no user data. |
| Subprocessors? | Vercel Inc. (hosting, logs, Blob). Meta Platforms (Meta Model API) only when a model key is set on the server: for the `ask` tool (full keys only; the demo key never calls it) and for the website's live ask, voice and label routes. Upstash (Redis) and Resend (email) only if the operator configures them. |
| Does Meta receive user input? | Only when `META_MODEL_API_KEY` is set on the server: the question text for live ask (and for the `ask` tool with a full key), the audio clip for live voice (Muse Voice Transcribe, then the transcript text goes to Muse Spark), and the photo for live label (the re-encoded image goes to SAM 3.1 and Muse Spark). Each is sent once to produce the answer and is not stored by this service. With no key, nothing is sent to Meta and recorded answers are shown. `/privacy` states which applies at request time. |
| Which public sources are queried? | openFDA (api.fda.gov) is queried live with a product code and, for label matching, with the device name, model and manufacturer read from the label. MHRA (UK) alerts come from a stored copy previously fetched from the GOV.UK search API; this service does not call GOV.UK when you use it. The website's outside-mentions search fetches public news and FDA feeds (GDELT, FDA press-release, recall, MedWatch and medical-device feeds, and MedTech Dive) with a product code and device search terms (no personal details); no model is called for it. |
| What is logged? | Key id (a peppered one-way hash, never the key), tool name, time, status. If the key has a label (for example a reviewer's name) the label is logged next to the key id. Calls made with the public demo key are logged the same way, with the label `demo`. Spend on `ask` is kept as a daily total per key id (not per call); the spend ledger keeps one small object per Meta call (its worst-case hold and real cost in dollars; no text, no address, no key). Question text is not logged; during a live `ask` it is held briefly in the server instance's temporary working database and replaced by its SHA-256 when the answer is done. |
| What do feedback and visits store? | New feedback stores rating, comments, role, quote consent, referral code, page and time - no names and no email addresses. Feedback sent before 31 October 2026 could include a name the person typed; names are removed from those entries except where the person chose to be quoted by name and role. Visits: referral code, page, time. |
| Are IP addresses stored? | No. Before any rate limit sees an address it is turned into a salted one-way hash (HMAC-SHA256); only that hash is the limit key, in memory or, if a Redis store is configured, in that store for at most twice the limit window. (Vercel, as host, keeps its own request logs.) |
| Retention? | Request logs follow Vercel's runtime-log retention for this plan. Feedback and visit records are kept until 2026-12-31 and then deleted, earlier on request. |
| Sale, advertising, cookies? | No sale of data, no advertising, no tracking cookies. |
| Deletion or questions? | The support email above or the GitHub issues URL. |
| Medical advice? | No. Not medical advice; nothing is filed with FDA; not an FDA-cleared device. Open-source project by Saicharan Kondapally. |

## Two keys (reviewer key plus your own)

`MAUDESIGNAL_API_KEYS` takes several entries in one value, separated by commas, and the value for
this submission is `charan=<key>,meta-review=<key>` (see Authentication above). Run
`python3.12 -m maudesignal.connector.keygen --label charan` (and again with `--label meta-review`)
**without** `VERCEL_TOKEN` to get each entry in a mode-600 file outside the repository (the file's
single line is `LABEL=KEY`; the key is never printed). With `VERCEL_TOKEN` and `VERCEL_PROJECT_ID`
set, the script instead **appends** `LABEL=KEY` to the existing value (earlier keys keep working);
if the existing value cannot be read back through the API it changes nothing and tells you to use
the file mode. Paste the entries as the value in Vercel > Settings > Environment Variables >
Production and redeploy. To revoke one key, delete its entry and redeploy; the other keeps working
(a unit test checks this). Audit and spend records are kept per key id, so the two keys are
counted apart.

**Before the second key goes in (cost and key ids):**

1. Set `MAUDESIGNAL_KEY_PEPPER` (any long random value) **before** adding or removing a key. Without
   it the key ids are derived from all key digests, so adding or removing a key changes every key
   id and starts a fresh per-key ledger and audit trail for each key (a test checks that with a
   pepper the remaining key keeps its id).
2. Set `MAUDESIGNAL_API_DAILY_USD=1.50` (or less). The per-key cap is `2.00` by default.
3. The one global live cap applies on top: `MAUDESIGNAL_LIVE_DAILY_USD`, default `3.00` per UTC
   day, however many keys exist, shared with the website's live routes. `/terms` shows it. When either cap is reached, `ask`
   returns a recorded answer. Live `ask` is also still off unless `META_MODEL_API_KEY` is set and the private
   Vercel Blob store (`BLOB_READ_WRITE_TOKEN`) that holds the spend ledger is configured (or the
   local-only per-instance override).

---

# Deploy and behaviour

## Part 1. Deploy the REST API (a second Vercel project)

The web workspace stays its own Vercel project, rooted at `web/`. The API is a **second** project
rooted at the repository root. A Muse custom connector calls a plain REST API with an API key, so
this is deployed first; MCP comes after it.

### 1. Create the project

Vercel > Add New > Project > import the GitHub repository
`kondapallysaicharan63-bot/maudesignal`, then:

| Setting | Value |
|---|---|
| Project name | anything, e.g. `maudesignal-api` |
| Production branch | the branch now in production (`track-c-next`; this change is `track-c-submit`) |
| Root Directory | `./` (the repository root; **not** `web/`) |
| Framework Preset | Other |
| Build Command | leave empty |
| Output Directory | leave empty |
| Install Command | leave empty (Vercel installs the Python function's requirements) |
| Python | the Vercel default for new Python projects |

What the repository gives Vercel (all in git, nothing to paste):

* `vercel.json`: one function `api/index.py` (`maxDuration` 60 s), `includeFiles` for the demo
  database and the files it reads (`src`, `skills`, `demo/transcripts`, `digests`, `data/demo`,
  `design-system`, `api`), `excludeFiles` for `web`, `docs`, `tests`, `screenshots`, and rewrites
  that send `/`, `/docs-page`, `/privacy`, `/terms`, `/openapi.json` and `/v1/*` to the
  function, and `regions: ["iad1"]`.
* `api/requirements.txt`: fastapi, pydantic, sqlalchemy, httpx, tenacity, structlog, jsonschema,
  jinja2, python-dotenv, rich, openai. No streamlit, weasyprint, playwright, pandas or scipy.
  (A test fails if a heavy package is added.)

**Not verified here (no Vercel deploy was possible from this environment):** which dependency
manifest the Python runtime installs from. The repository root also has the full `pyproject.toml`
and `requirements.txt`. After the first deploy open the build log and check the "Installing
dependencies" step names `api/requirements.txt` and the function is under the size limit. If it
installed the root manifest, tell the owner before going on: the fix is a project-level change
(for example a separate branch that holds only the API files), not something to guess.

### 2. Environment variables (Project > Settings > Environment Variables, Production)

| Name | Value | Notes |
|---|---|---|
| `MAUDESIGNAL_API_KEYS` | `charan=<key>,meta-review=<key>` | Made by the script in step 3; never typed into chat or the repository. Labelled entries, see Authentication. |
| `MAUDESIGNAL_DEMO_KEYS` | optional, e.g. `demo=<key>` | The public demo key (see "Demo key"). Unset means no demo key. |
| `MAUDESIGNAL_DEMO_RATE_PER_MIN` | default `10` | Requests per demo key per minute (plus 200 per UTC day). |
| `MAUDESIGNAL_PUBLIC_URL` | optional | Base URL shown by `GET /v1/connect` when it differs from the request address. |
| `MAUDESIGNAL_CONTACT_EMAIL` | the support email | Shown (HTML-escaped) on `/privacy` and `/terms`; unset shows the GitHub issues URL. Never in git. |
| `MAUDESIGNAL_TRUST_FORWARDED` | `1` | Vercel's edge sets `X-Forwarded-For`; without this the limiter would see one address. |
| `MAUDESIGNAL_KEY_PEPPER` | a long random string | Server-side secret for key ids in ledger file names and audit session ids. |
| `MAUDESIGNAL_WEB_ORIGINS` | e.g. `https://<web-project>.vercel.app` | Comma-separated exact origins that may call the keyless route from a browser. No wildcard (a `*` entry is ignored). Empty means no browser origin is allowed. |
| `MAUDESIGNAL_RATE_LIMIT_PER_MIN` | default `30` | Requests per key per minute. |
| `MAUDESIGNAL_FAILED_AUTH_PER_MIN` | default `10` | Wrong or missing keys per address per minute before 429. |
| `MAUDESIGNAL_PUBLIC_CHECK_PER_HOUR` | default `10` | Keyless checks per address per hour. |
| `MAUDESIGNAL_API_DAILY_USD` / `MAUDESIGNAL_API_REQUEST_USD` | defaults `2.00` / `0.25` | Cost cap of `ask` per key per UTC day, and per call. |
| `OPENFDA_API_KEY` | optional (set it in production) | Used only on the server for live openFDA checks (higher quota). Never in a response. One `lookup_device` call makes about 20 openFDA requests (up to 7 searches, plus classification, the live check, recall and event queries for up to 2 product codes); without a key openFDA allows 240 requests a minute and 1,000 a day per IP. |
| `UPSTASH_REDIS_REST_URL`, `UPSTASH_REDIS_REST_TOKEN` | optional | Add an Upstash Redis database (Vercel Marketplace, or upstash.com) and copy its REST URL and token. When both are set, the rate limits, the per-key daily totals, the six-hour cache and the audit log are shared by every instance. Redis holds no part of the global spend ledger. If the integration names them differently, add these two names by hand. |
| `BLOB_READ_WRITE_TOKEN` | the private Blob store's token | Also holds the spend ledger (one object per Meta call). Without it live Meta calls are off. |
| `MAUDESIGNAL_LIVE_DAILY_USD` | default `3.00` | The hard ceiling for every Meta call per UTC day. Calls stop at this minus $0.10 (one call's largest hold). |
| `MAUDESIGNAL_DEMO_KEYS` | optional | Public demo keys, same format as `MAUDESIGNAL_API_KEYS`; not secret. |
| `MAUDESIGNAL_DEMO_RATE_PER_MIN` | default `10` | Demo key requests per minute (and 200 per day). |
| `MAUDESIGNAL_CONTACT_EMAIL` | an address you choose to publish | Shown on `/privacy` and `/terms` at runtime; never in git. |
| `MAUDESIGNAL_PUBLIC_URL` | optional, e.g. `https://maudesignal-api.vercel.app` | Base URL that `GET /v1/connect` reports. |
| `META_MODEL_API_KEY` | optional | Leave **unset** until you accept the cost: `ask` then answers from recorded runs. |
| `MAUDESIGNAL_ALLOW_PER_INSTANCE_CAP` | `1` only for local runs without a Blob store | Keeps the same ledger in this one process's memory (resets on restart; several instances do not share it). Never set it on Vercel. |

Production traffic must reach the function without a Vercel login page: in Project > Settings >
Deployment Protection, make sure Production is not behind Vercel Authentication (or use a custom
domain). The first `curl` below shows whether it is.

### 3. Create the key without ever printing it

```bash
# Option a: the script appends LABEL=KEY to the encrypted Production variable in Vercel.
VERCEL_TOKEN=... VERCEL_PROJECT_ID=prj_... VERCEL_TEAM_ID=team_... \
  python3.12 -m maudesignal.connector.keygen --label meta-review
# prints only: set; copy it from Vercel > Project > Settings > Environment Variables >
#              MAUDESIGNAL_API_KEYS (click to reveal)

# Option b: no Vercel token; the entry goes to a mode-600 file outside the repository.
python3.12 -m maudesignal.connector.keygen --label charan
# prints only the file path and what to do with it
```

Option a appends: earlier keys keep working. If the existing value cannot be read back (a variable
marked sensitive), the script changes nothing and says so; use option b and add the line by hand.
Option b: paste the file's one line (`LABEL=KEY`) into `MAUDESIGNAL_API_KEYS` in the dashboard
(after a comma if a value exists), then delete the file. Either way the key is never printed to
stdout or stderr, never logged, never written inside the repository, and Vercel's reply is never
printed (only an HTTP status on failure). Tests run the script as a subprocess and scan both
streams for the key. Redeploy after changing an environment variable.

### After the first deploy: remove old names (once)

Open `/admin`, enter the admin key, and press **Remove names** once. It removes names from feedback
sent before 31 October 2026, except where the person chose to be quoted by name and role (this is
what the privacy page states). Feedback and visit records are deleted by 2026-12-31, or earlier on
request.

### 4. Verify with harmless reads

```bash
BASE=https://maudesignal-api.vercel.app
KEY=$(cat /path/printed/by/the/script)   # option b; for option a, reveal it in the dashboard

curl -i "$BASE/v1/health"                                   # no key: 200 JSON, read_only true
curl -i -H "X-API-Key: $KEY" \
  "$BASE/v1/tools/what_changed_this_week?product_code=LLZ"  # 200, speakable + facts + advisory
curl -i "$BASE/v1/tools/what_changed_this_week?product_code=LLZ"   # no key: 401
```

Then open `$BASE/` (the docs page) and `$BASE/openapi.json`. `GET /v1/health` reports
`state_store` (`upstash_redis` or `in_memory_per_instance`) and `limits_scope`.

For the Muse connector form: base URL = `$BASE`, auth = API key in the header `X-API-Key`, spec =
`$BASE/openapi.json`. The form's exact field names are "to confirm against the live form".

### 5. What the pack contains

* `GET /` and `GET /docs-page`: the human-readable docs page (no key), in the design-system look,
  with the example requests and responses from the real runs below (`api/examples.json`).
* `GET /openapi.json` (no key): the OpenAPI 3.1 spec; `api/openapi.json` is the committed copy and a
  test fails if the two differ (regenerate: `python3.12 -m maudesignal.connector.openapi`).
* `GET /v1/health` (no key), the six tools under `/v1/tools/` (key), `GET /v1/audit/recent` (key).
* `GET /v1/public/check_device_type?product_code=` (**no key**), for the web workspace, where a
  browser gets 403 from openFDA directly. Same live check and the same four rules as the keyed
  tool (`monitor/live_check.py`), same query links, plus a `check` field equal to
  `LiveCheck.to_dict()` (classification, change, counts, shares, window, `queries` as
  `[label, url]`). openFDA is called from the server with `OPENFDA_API_KEY` and the MaudeSignal
  User-Agent. Per-address limit (default 10 per hour, `MAUDESIGNAL_PUBLIC_CHECK_PER_HOUR`; **per
  server instance without Upstash, so the effective limit is that number times the instances**), a
  six-hour cache per code, CORS only for origins in `MAUDESIGNAL_WEB_ORIGINS`. It never reaches
  `ask` or the model, so it cannot spend Meta credit. A stored-snapshot fallback (openFDA
  unreachable, code is stored) has `check: null` and is not cached.
* Shared state (optional, `store.py`): with the two Upstash variables set, the per-key rate limit,
  the per-address limits, the per-key daily total of `ask`, the six-hour cache and the audit log live
  in Redis; otherwise in memory of one instance (reset on a cold start). `GET /v1/health` says which.
  Tested with a mocked REST client only; **not run against a real Upstash database.** If Redis
  fails: rate limits fall back to the instance's memory, the cache is skipped, the audit append is
  logged and skipped (the request still answers; `/v1/audit/recent` answers 503), and the per-key
  total raises so `ask` falls back to a recorded answer instead of spending without a cap. If the per-key write fails after a model call has already
  been paid for, it is retried once, then a CRITICAL log line `connector_spend_not_recorded` carries the
  uncounted USD amount and day (no key, no token) so the operator can reconcile it. A cached public
  answer that no longer parses is treated as a miss; the cache key is versioned (`public-check:v1:`).
* Audit log: every tool call (and a failed one) appends an entry in the chain format of
  `copilot/audit_export` (`prev_hash`, `entry_hash = sha256(prev_hash + json)`, first entry after
  `GENESIS`): tool, inputs (an `ask` question is stored as the SHA-256 and length of its
  whitespace-normalised, lower-cased text, never as text: every key holder can read this log, and a
  question may contain anything), SHA-256 of the answer, gate
  counts (`facts_with_links`, `withheld`), provenance kind and dates, and the caller as
  `connector:key:<id>` or `public`, where `<id>` is the server's peppered HMAC of the key (the id
  the limiter and ledger use; nothing derived from the key without the pepper). Never the key, never the text of
  a withheld sentence. `GET /v1/audit/recent?limit=20` (key, at most 200) re-computes the chain on
  every call and reports `chain.verified`.

### 6. Real local transcripts

Captured from `uvicorn api.index:app --no-access-log --no-proxy-headers` on 127.0.0.1 with a key
made by `maudesignal.connector.keygen` (option b, read into the environment of the server and of
`curl`; it appears below as `$MAUDESIGNAL_KEY`, never as a value), no `META_MODEL_API_KEY`, no
`OPENFDA_API_KEY`, no Upstash. For this run: `MAUDESIGNAL_RATE_LIMIT_PER_MIN=9`,
`MAUDESIGNAL_PUBLIC_CHECK_PER_HOUR=2`, `MAUDESIGNAL_WEB_ORIGINS=https://app.example.com`. This
environment cannot reach openFDA, so `check_device_type` shows the documented stored fallback, and
`ask` shows the recorded answer. The 429 is the call past the per-key limit: seven calls above
plus two unlisted `recalls` calls made nine, so the next one was refused. Real output, unedited:

```text
### health (no key)
$ curl -i http://127.0.0.1:8765/v1/health
HTTP/1.1 200 OK
date: Thu, 29 Oct 2026 23:11:09 GMT
server: uvicorn
content-length: 237
content-type: application/json

{"status":"ok","service":"maudesignal-connector","version":"0.1.0","read_only":true,"tools":["what_changed_this_week","check_device_type","ask","get_report","recalls"],"limits_scope":"per_instance","state_store":"in_memory_per_instance"}

### what_changed_this_week for LLZ
$ curl -i -H "X-API-Key: $MAUDESIGNAL_KEY" "http://127.0.0.1:8765/v1/tools/what_changed_this_week?product_code=LLZ"
HTTP/1.1 200 OK
date: Thu, 29 Oct 2026 23:11:09 GMT
server: uvicorn
content-length: 1114
content-type: application/json
x-ratelimit-limit: 9
x-ratelimit-remaining: 8

{"tool":"what_changed_this_week","speakable":"In the stored demo snapshot for August 25, 2026 to August 31, 2026, LLZ shows reports suddenly increased: 33 reports against a weekly average of 8.75 in the four weeks before.","facts":[{"text":"LLZ (System, Image Processing, Radiological): reports suddenly increased. 33 reports received August 25, 2026 to August 31, 2026, against a weekly average of 8.75 in the four weeks before.","link":"https://api.fda.gov/device/event.json?search=device.device_report_product_code%3ALLZ+AND+date_received%3A%5B20260825+TO+20260831%5D&limit=1","link_label":"openFDA: reports in this week"}],"advisory":"Advisory triage aid for quality and regulatory review; not medical advice; nothing is filed with FDA.","provenance":{"kind":"stored_demo_snapshot","source":"Stored demo snapshot of openFDA device adverse-event reports","data_dates":"week August 25, 2026 to August 31, 2026; snapshot fetched 2026-10-27; latest stored report received August 31, 2026","queried_at_utc":null,"note":"Not live data. The links open the live openFDA record or query for comparison."},"withheld":[]}

### what_changed_this_week, no code
$ curl -i -H "X-API-Key: $MAUDESIGNAL_KEY" "http://127.0.0.1:8765/v1/tools/what_changed_this_week"
HTTP/1.1 200 OK
date: Thu, 29 Oct 2026 23:11:09 GMT
server: uvicorn
content-length: 2251
content-type: application/json
x-ratelimit-limit: 9
x-ratelimit-remaining: 7

{"tool":"what_changed_this_week","speakable":"In the stored demo snapshot for August 25, 2026 to August 31, 2026, LLZ shows reports suddenly increased: 33 reports against a weekly average of 8.75 in the four weeks before. The other 3 device types show no change.","facts":[{"text":"LLZ (System, Image Processing, Radiological): reports suddenly increased. 33 reports received August 25, 2026 to August 31, 2026, against a weekly average of 8.75 in the four weeks before.","link":"https://api.fda.gov/device/event.json?search=device.device_report_product_code%3ALLZ+AND+date_received%3A%5B20260825+TO+20260831%5D&limit=1","link_label":"openFDA: reports in this week"},{"text":"MYN (Analyzer, Medical Image): no change. 0 reports received August 25, 2026 to August 31, 2026, against a weekly average of 0 in the four weeks before.","link":"https://api.fda.gov/device/event.json?search=device.device_report_product_code%3AMYN+AND+date_received%3A%5B20260825+TO+20260831%5D&limit=1","link_label":"openFDA: reports in this week"},{"text":"POK (Computer-Assisted Diagnostic Software For Lesions Suspicious For Cancer): no change. 0 reports received August 25, 2026 to August 31, 2026, against a weekly average of 0 in the four weeks before.","link":"https://api.fda.gov/device/event.json?search=device.device_report_product_code%3APOK+AND+date_received%3A%5B20260825+TO+20260831%5D&limit=1","link_label":"openFDA: reports in this week"},{"text":"QIH: no change. 0 reports received August 25, 2026 to August 31, 2026, against a weekly average of 0 in the four weeks before.","link":"https://api.fda.gov/device/event.json?search=device.device_report_product_code%3AQIH+AND+date_received%3A%5B20260825+TO+20260831%5D&limit=1","link_label":"openFDA: reports in this week"}],"advisory":"Advisory triage aid for quality and regulatory review; not medical advice; nothing is filed with FDA.","provenance":{"kind":"stored_demo_snapshot","source":"Stored demo snapshot of openFDA device adverse-event reports","data_dates":"week August 25, 2026 to August 31, 2026; snapshot fetched 2026-10-27; latest stored report received August 31, 2026","queried_at_utc":null,"note":"Not live data. The links open the live openFDA record or query for comparison."},"withheld":[]}

### check_device_type LLZ (openFDA unreachable here, stored fallback)
$ curl -i -H "X-API-Key: $MAUDESIGNAL_KEY" "http://127.0.0.1:8765/v1/tools/check_device_type?product_code=LLZ"
HTTP/1.1 200 OK
date: Thu, 29 Oct 2026 23:11:09 GMT
server: uvicorn
content-length: 1182
content-type: application/json
x-ratelimit-limit: 9
x-ratelimit-remaining: 6

{"tool":"check_device_type","speakable":"Live openFDA could not be reached, so this is the stored demo snapshot. In the stored demo snapshot for August 25, 2026 to August 31, 2026, LLZ shows reports suddenly increased: 33 reports against a weekly average of 8.75 in the four weeks before.","facts":[{"text":"LLZ (System, Image Processing, Radiological): reports suddenly increased. 33 reports received August 25, 2026 to August 31, 2026, against a weekly average of 8.75 in the four weeks before.","link":"https://api.fda.gov/device/event.json?search=device.device_report_product_code%3ALLZ+AND+date_received%3A%5B20260825+TO+20260831%5D&limit=1","link_label":"openFDA: reports in this week"}],"advisory":"Advisory triage aid for quality and regulatory review; not medical advice; nothing is filed with FDA.","provenance":{"kind":"stored_demo_snapshot","source":"Stored demo snapshot of openFDA device adverse-event reports","data_dates":"week August 25, 2026 to August 31, 2026; snapshot fetched 2026-10-27; latest stored report received August 31, 2026","queried_at_utc":null,"note":"Live openFDA could not be reached, so this is the stored demo snapshot instead."},"withheld":[]}

### ask (no model key here, recorded answer)
$ curl -i -H "X-API-Key: $MAUDESIGNAL_KEY" -H 'Content-Type: application/json' -d '{"question": "What changed this week for LLZ?"}' http://127.0.0.1:8765/v1/tools/ask
HTTP/1.1 200 OK
date: Thu, 29 Oct 2026 23:11:09 GMT
server: uvicorn
content-length: 2225
content-type: application/json
x-ratelimit-limit: 9
x-ratelimit-remaining: 5

{"tool":"ask","speakable":"Live answers are not switched on here, so this is a recorded answer to a different, similar question: \"What changed this week, Did reports suddenly increase for any device\", using stored reports through August 31, 2026. Yes, LLZ reports suddenly increased this week with 33 reports from August 25 to August 31, 2026. One sentence was left out because it could not be verified or tied to a source.","facts":[{"text":"Yes, LLZ reports suddenly increased this week with 33 reports from August 25 to August 31, 2026.","link":"https://api.fda.gov/device/event.json?search=device.device_report_product_code%3ALLZ+AND+date_received%3A%5B20260825+TO+20260831%5D&limit=1","link_label":"openFDA count for LLZ"},{"text":"MYN, POK and QIH showed no change this week, each with 0 reports in the same window.","link":"https://api.fda.gov/device/event.json?search=device.device_report_product_code%3AMYN+AND+date_received%3A%5B20260825+TO+20260831%5D&limit=1","link_label":"openFDA count for MYN"},{"text":"MYN, POK and QIH showed no change this week, each with 0 reports in the same window.","link":"https://api.fda.gov/device/event.json?search=device.device_report_product_code%3APOK+AND+date_received%3A%5B20260825+TO+20260831%5D&limit=1","link_label":"openFDA count for POK"},{"text":"MYN, POK and QIH showed no change this week, each with 0 reports in the same window.","link":"https://api.fda.gov/device/event.json?search=device.device_report_product_code%3AQIH+AND+date_received%3A%5B20260825+TO+20260831%5D&limit=1","link_label":"openFDA count for QIH"}],"advisory":"Advisory triage aid for quality and regulatory review; not medical advice; nothing is filed with FDA.","provenance":{"kind":"recorded_answer","source":"Recorded run of the Muse Spark copilot; every sentence was checked by the claim gate when it was recorded","data_dates":"recorded 2026-10-28","queried_at_utc":null,"note":"No live model key is configured on this server, so no live model call was made."},"withheld":[{"text":"A named human must review the supporting reports before any regulatory decision.","reason":"passed the claim gate but has no openFDA or record link, so it is not spoken","claim_kinds":[],"status":"withheld"}]}

### get_report 50426770
$ curl -i -H "X-API-Key: $MAUDESIGNAL_KEY" "http://127.0.0.1:8765/v1/tools/get_report?report_id=50426770"
HTTP/1.1 200 OK
date: Thu, 29 Oct 2026 23:11:09 GMT
server: uvicorn
content-length: 1532
content-type: application/json
x-ratelimit-limit: 9
x-ratelimit-remaining: 4

{"tool":"get_report","speakable":"Report 5 0 4 2 6 7 7 0 is a malfunction report for product code LLZ, received August 25, 2026. The start of its narrative is in the facts.","facts":[{"text":"Report 50426770: product code LLZ, event type malfunction, received August 25, 2026.","link":"https://api.fda.gov/device/event.json?search=mdr_report_key%3A50426770&limit=1","link_label":"openFDA report"},{"text":"Report 50426770 lists brand IntelliSpace Cardiovascular, manufacturer Philips Medical Systems Nederland B.V..","link":"https://api.fda.gov/device/event.json?search=mdr_report_key%3A50426770&limit=1","link_label":"openFDA report"},{"text":"Start of the narrative, word for word: \"Philips received a complaint regarding IntelliSpace Cardiovascular (ISCV), indicating that they have a case that needs to be corrected. The device was in clinical use at the time of the event, and no adverse event or patient harm was report...\"","link":"https://api.fda.gov/device/event.json?search=mdr_report_key%3A50426770&limit=1","link_label":"openFDA report"}],"advisory":"Advisory triage aid for quality and regulatory review; not medical advice; nothing is filed with FDA.","provenance":{"kind":"stored_demo_snapshot","source":"Stored demo snapshot of openFDA device adverse-event reports","data_dates":"report received August 25, 2026; snapshot fetched 2026-10-27; latest stored report received August 31, 2026","queried_at_utc":null,"note":"Not live data. The links open the live openFDA record or query for comparison."},"withheld":[]}

### recalls LLZ
$ curl -i -H "X-API-Key: $MAUDESIGNAL_KEY" "http://127.0.0.1:8765/v1/tools/recalls?product_code=LLZ"
HTTP/1.1 200 OK
date: Thu, 29 Oct 2026 23:11:09 GMT
server: uvicorn
content-length: 2691
content-type: application/json
x-ratelimit-limit: 9
x-ratelimit-remaining: 3

{"tool":"recalls","speakable":"The stored demo snapshot holds 561 recall product records (433 recall events) for product code LLZ. The most recent started September 5, 2026 by INTELERAD MEDICAL SYSTEMS INCORPORATED.","facts":[{"text":"561 recall product records (433 recall events) for product code LLZ in the stored snapshot.","link":"https://api.fda.gov/device/recall.json?search=product_code%3ALLZ&limit=1","link_label":"openFDA: recalls for this code"},{"text":"Recall Z-0186-2027, started September 5, 2026 by INTELERAD MEDICAL SYSTEMS INCORPORATED, status Open, Classified. Reason: Following a Chromium-based web-browser, report and displayed images may not match.","link":"https://api.fda.gov/device/recall.json?search=product_res_number%3A%22Z-0186-2027%22&limit=1","link_label":"openFDA recall"},{"text":"Recall Z-3171-2026, started July 31, 2026 by GE Healthcare, status Open, Classified. Reason: Under certain conditions historical imaging data migrated from a legacy system may become incorrectly associated with a different patient.","link":"https://api.fda.gov/device/recall.json?search=product_res_number%3A%22Z-3171-2026%22&limit=1","link_label":"openFDA recall"},{"text":"Recall Z-3170-2026, started July 31, 2026 by GE Healthcare, status Open, Classified. Reason: Under certain conditions historical imaging data migrated from a legacy system may become incorrectly associated with a different patient.","link":"https://api.fda.gov/device/recall.json?search=product_res_number%3A%22Z-3170-2026%22&limit=1","link_label":"openFDA recall"},{"text":"Recall Z-3169-2026, started July 31, 2026 by GE Healthcare, status Open, Classified. Reason: Under certain conditions historical imaging data migrated from a legacy system may become incorrectly associated with a different patient.","link":"https://api.fda.gov/device/recall.json?search=product_res_number%3A%22Z-3169-2026%22&limit=1","link_label":"openFDA recall"},{"text":"Recall Z-3168-2026, started July 31, 2026 by GE Healthcare, status Open, Classified. Reason: Under certain conditions historical imaging data migrated from a legacy system may become incorrectly associated with a different patient.","link":"https://api.fda.gov/device/recall.json?search=product_res_number%3A%22Z-3168-2026%22&limit=1","link_label":"openFDA recall"}],"advisory":"Advisory triage aid for quality and regulatory review; not medical advice; nothing is filed with FDA.","provenance":{"kind":"stored_demo_snapshot","source":"Stored demo snapshot of openFDA device recalls","data_dates":"snapshot fetched 2026-10-27","queried_at_utc":null,"note":"Not live data. The links open the live openFDA record or query for comparison."},"withheld":[]}

### audit/recent (last 3, chain re-checked)
$ curl -i -H "X-API-Key: $MAUDESIGNAL_KEY" "http://127.0.0.1:8765/v1/audit/recent?limit=3"
HTTP/1.1 200 OK
date: Thu, 29 Oct 2026 23:11:09 GMT
server: uvicorn
content-length: 2243
content-type: application/json
x-ratelimit-limit: 9
x-ratelimit-remaining: 2

{"store":"in_memory_per_instance","chain":{"verified":true,"first_bad_seq":null,"entries_checked":3},"entries":[{"seq":4,"ts":"2026-10-29T23:11:10.584305","actor":"connector:key:467c81373bc6","action":"tool:ask","entity_id":"ask","payload_json":"{\"answer_sha256\": \"91228daade42a16671c4dd787b24fbafb35c88a69e6f6319a6f3cc8887eef326\", \"error\": null, \"gate\": {\"facts_with_links\": 4, \"withheld\": 1}, \"inputs\": {\"question_length\": \"31\", \"question_sha256\": \"c53ce3de663ab29e79eae627848b9ec856dbcdb56aae2701e34c6e908128648d\"}, \"provenance\": {\"data_dates\": \"recorded 2026-10-28\", \"kind\": \"recorded_answer\", \"queried_at_utc\": null}, \"tool\": \"ask\"}","prev_hash":"3ad052110650bed287f4bfb4e96ae631900747647dd889028c2e08f65ee82c49","entry_hash":"c82ffbd8e51c354d89ec5bc4395407a1c324e37e8494a33f6ff0e7e5cdec60c4"},{"seq":5,"ts":"2026-10-29T23:11:10.597068","actor":"connector:key:467c81373bc6","action":"tool:get_report","entity_id":"get_report","payload_json":"{\"answer_sha256\": \"b91010d76ab3ee9c3bdbe92a1f2a74b357e86bad33b08edafdc91429b72b77c4\", \"error\": null, \"gate\": {\"facts_with_links\": 3, \"withheld\": 0}, \"inputs\": {\"report_id\": \"50426770\"}, \"provenance\": {\"data_dates\": \"report received August 25, 2026; snapshot fetched 2026-10-27; latest stored report received August 31, 2026\", \"kind\": \"stored_demo_snapshot\", \"queried_at_utc\": null}, \"tool\": \"get_report\"}","prev_hash":"c82ffbd8e51c354d89ec5bc4395407a1c324e37e8494a33f6ff0e7e5cdec60c4","entry_hash":"e2aad6990846a504fd150bd93cf35b08da69a7de625f5283b6e0765d43654e1a"},{"seq":6,"ts":"2026-10-29T23:11:10.621589","actor":"connector:key:467c81373bc6","action":"tool:recalls","entity_id":"recalls","payload_json":"{\"answer_sha256\": \"f98c33dd4d72dd70c493c2902de8b2f0bb31e47a379b328053df852ebe44a2f3\", \"error\": null, \"gate\": {\"facts_with_links\": 6, \"withheld\": 0}, \"inputs\": {\"product_code\": \"LLZ\"}, \"provenance\": {\"data_dates\": \"snapshot fetched 2026-10-27\", \"kind\": \"stored_demo_snapshot\", \"queried_at_utc\": null}, \"tool\": \"recalls\"}","prev_hash":"e2aad6990846a504fd150bd93cf35b08da69a7de625f5283b6e0765d43654e1a","entry_hash":"833f9b3096586e346e803c7dd4fde6fd1e080785f68a8988bc3d9752c8edda5b"}]}

### 401 without a key
$ curl -i "http://127.0.0.1:8765/v1/tools/recalls?product_code=LLZ"
HTTP/1.1 401 Unauthorized
date: Thu, 29 Oct 2026 23:11:09 GMT
server: uvicorn
www-authenticate: ApiKey
content-length: 83
content-type: application/json

{"error":{"code":"unauthorized","message":"A valid X-API-Key header is required."}}

### 429 past the per-key limit (9 per minute in this run)
$ curl -i -H "X-API-Key: $MAUDESIGNAL_KEY" "http://127.0.0.1:8765/v1/tools/recalls?product_code=LLZ"
HTTP/1.1 429 Too Many Requests
date: Thu, 29 Oct 2026 23:11:09 GMT
server: uvicorn
retry-after: 60
content-length: 111
content-type: application/json

{"error":{"code":"rate_limited","message":"Rate limit of 9 requests per minute reached. Retry in 60 seconds."}}

### public check, allowed origin (no key)
$ curl -i -H "Origin: https://app.example.com" "http://127.0.0.1:8765/v1/public/check_device_type?product_code=LLZ"
HTTP/1.1 200 OK
date: Thu, 29 Oct 2026 23:11:09 GMT
server: uvicorn
content-length: 1195
content-type: application/json
x-ratelimit-limit: 2
x-ratelimit-remaining: 1
vary: Origin
access-control-allow-origin: https://app.example.com
access-control-expose-headers: Retry-After, X-RateLimit-Limit, X-RateLimit-Remaining

{"tool":"check_device_type","speakable":"Live openFDA could not be reached, so this is the stored demo snapshot. In the stored demo snapshot for August 25, 2026 to August 31, 2026, LLZ shows reports suddenly increased: 33 reports against a weekly average of 8.75 in the four weeks before.","facts":[{"text":"LLZ (System, Image Processing, Radiological): reports suddenly increased. 33 reports received August 25, 2026 to August 31, 2026, against a weekly average of 8.75 in the four weeks before.","link":"https://api.fda.gov/device/event.json?search=device.device_report_product_code%3ALLZ+AND+date_received%3A%5B20260825+TO+20260831%5D&limit=1","link_label":"openFDA: reports in this week"}],"advisory":"Advisory triage aid for quality and regulatory review; not medical advice; nothing is filed with FDA.","provenance":{"kind":"stored_demo_snapshot","source":"Stored demo snapshot of openFDA device adverse-event reports","data_dates":"week August 25, 2026 to August 31, 2026; snapshot fetched 2026-10-27; latest stored report received August 31, 2026","queried_at_utc":null,"note":"Live openFDA could not be reached, so this is the stored demo snapshot instead."},"withheld":[],"check":null}

### public check, origin not listed (no CORS header)
$ curl -i -H "Origin: https://evil.example.com" "http://127.0.0.1:8765/v1/public/check_device_type?product_code=LLZ"
HTTP/1.1 200 OK
date: Thu, 29 Oct 2026 23:11:10 GMT
server: uvicorn
content-length: 1195
content-type: application/json
x-ratelimit-limit: 2
x-ratelimit-remaining: 0
vary: Origin

{"tool":"check_device_type","speakable":"Live openFDA could not be reached, so this is the stored demo snapshot. In the stored demo snapshot for August 25, 2026 to August 31, 2026, LLZ shows reports suddenly increased: 33 reports against a weekly average of 8.75 in the four weeks before.","facts":[{"text":"LLZ (System, Image Processing, Radiological): reports suddenly increased. 33 reports received August 25, 2026 to August 31, 2026, against a weekly average of 8.75 in the four weeks before.","link":"https://api.fda.gov/device/event.json?search=device.device_report_product_code%3ALLZ+AND+date_received%3A%5B20260825+TO+20260831%5D&limit=1","link_label":"openFDA: reports in this week"}],"advisory":"Advisory triage aid for quality and regulatory review; not medical advice; nothing is filed with FDA.","provenance":{"kind":"stored_demo_snapshot","source":"Stored demo snapshot of openFDA device adverse-event reports","data_dates":"week August 25, 2026 to August 31, 2026; snapshot fetched 2026-10-27; latest stored report received August 31, 2026","queried_at_utc":null,"note":"Live openFDA could not be reached, so this is the stored demo snapshot instead."},"withheld":[],"check":null}

### 429 on the public check past 2 per hour (this run)
$ curl -i -H "Origin: https://app.example.com" "http://127.0.0.1:8765/v1/public/check_device_type?product_code=LLZ"
HTTP/1.1 429 Too Many Requests
date: Thu, 29 Oct 2026 23:11:10 GMT
server: uvicorn
retry-after: 3600
content-length: 104
content-type: application/json
vary: Origin
access-control-allow-origin: https://app.example.com
access-control-expose-headers: Retry-After, X-RateLimit-Limit, X-RateLimit-Remaining

{"error":{"code":"rate_limited","message":"Limit of 2 checks per hour reached. Retry in 3600 seconds."}}
```

Other checks in the same run: `GET /` and `GET /docs-page` returned `200 text/html; charset=utf-8`
(56608 bytes each, no key); `GET /openapi.json` returned `200 application/json` and equals
`api/openapi.json` (compared as JSON).

### Not done from this environment (stated so nothing is assumed)

* No deploy to Vercel, no `vercel build`: the vercel.json is checked by a test (parses, function
  file exists, every `includeFiles` pattern matches files, the files the app reads are covered),
  not by Vercel.
* No call to the real Vercel REST API (the script is tested with a fake HTTP function), no real
  Upstash database, no live openFDA call, no Meta API call.
* Muse itself was never asked to call this API.

## What it is

Six read-only tools (REST and MCP, same code):
`what_changed_this_week`, `check_device_type`, `ask`, `get_report`, `recalls`, `lookup_device`.
Every answer has: a short speakable summary, facts that each carry an openFDA or record link,
the fixed advisory line ("Advisory triage aid for quality and regulatory review; not medical
advice; nothing is filed with FDA."), and provenance (stored demo snapshot with its dates, or
live openFDA with the query time, or a recorded answer, or a live model answer).

## Read-only, enforced

* No endpoint writes. `ask` runs the Muse Spark copilot, whose toolbox also holds
  `draft_capa` (it inserts a draft row). The connector never offers that tool to the model and
  turns any call to it into an error (`connector/readonly.py`); a test makes a scripted model
  call it and checks the `capa_drafts` table stays empty. A test also fails if the copilot
  gains a tool that is not listed as read-only or write.
* An answer is only spoken if the claim gate passed it **and** it has an openFDA or record
  link. A sentence that passed but has no link is listed under `withheld` ("not spoken").
* Words this service never uses (`connector/forbidden.py`) are screened out of recorded and
  live text, including the left-out (`withheld`) sentences and their reasons: a left-out
  sentence that contains one is replaced by "Sentence left out: it contains a term this
  service does not use." Tests scan the whole response (speakable, facts, withheld, provenance)
  for every banned term on every stored question and on a scripted live answer.
* In live mode the text of a left-out sentence is never returned, whatever the reason (gate
  block, banned term, no link). `withheld` holds a neutral placeholder, a fixed reason text per
  claim kind (never the gate's own reason string, which can carry text the model wrote into a
  claim field such as a section or report id), and the claim kinds. Tests check that no 20-character piece of
  such a sentence, and no free text put in a claim field, is anywhere in the response or the raw REST body. (Recorded answers still
  list the recorded text of gate-blocked sentences, labelled not verified.)

## Recorded answers (no model key, or cost cap reached)

`ask` returns a real, gated recording from `demo/transcripts`, labelled
`recorded_answer`, with the recorded question and the stored-data date in the spoken lead. A
recording is used only if every meaningful word of the question appears in the recorded
question or the first sentence of its answer, and a product code in the question appears
there too. Voice-mode and greeting recordings are never used. Otherwise the answer is "no
verified answer, try the what changed / recalls tools". Count links on recorded answers are
recovered from the sentence text and kept only if the stored reports for that product code
and window number exactly what the gate recomputed.

## Known limits (read before turning the live key on)

1. **Without a shared store, rate limits are per server instance.** The per-minute limiter is in
   memory; on Vercel each instance has its own and it resets on a cold start. `/v1/health` reports
   `limits_scope: per_instance`. The daily Meta spend is different: it is kept in the private Blob
   store, one object per model call (see "Cost"), and live Muse Spark calls are **off in code**
   unless `BLOB_READ_WRITE_TOKEN` is set (or, for a local run only, the operator sets
   `MAUDESIGNAL_ALLOW_PER_INSTANCE_CAP=1`, which keeps that ledger in one process's memory). A
   model key alone returns recorded answers (`provenance.kind = recorded_answer`). When the key is
   set but live mode is not allowed, the recorded answer says live calls are switched off on this
   server (`live_off`); with no key it says none is configured (`no_model`). Before enabling live
   mode, also put a hard spending limit on the Meta key itself.
   `MAUDESIGNAL_TRUST_FORWARDED=1`: use the first `X-Forwarded-For` entry as the client address
   for rate limiting. **Set it on Vercel** (its edge sets the header); leave it unset anywhere
   else, where the header is caller-controlled and the socket address is used instead.
   Outside Vercel, also run uvicorn with `--no-proxy-headers` (or `--forwarded-allow-ips` set to
   the real proxy only): by default uvicorn rewrites the client address from `X-Forwarded-For`
   when the peer is `127.0.0.1`, which lets a caller behind a local reverse proxy rotate it.
   With Upstash the per-key limit uses fixed one-minute windows (up to twice the limit can pass
   across a window edge); the in-memory limiter is sliding.
   Other settings: `MAUDESIGNAL_KEY_PEPPER` (server-side secret for the key ids that appear in
   ledger file names and audit session ids; set it), `MAUDESIGNAL_FAILED_AUTH_PER_MIN` (wrong or
   missing keys per client address per minute before 429, default 10). Plain keys shorter than 32
   characters are refused at start-up (a warning with a count is logged, never the key).
   **The copilot's own audit rows of a live `ask`** (written inside the model run) go to a
   temporary copy of the demo database on the instance and are lost on a cold start. What a caller
   or the laptop can read is the connector's audit entry of that call (`GET /v1/audit/recent`:
   tool, question hash and length, answer hash, gate counts, provenance), which lives in Redis when Upstash is set
   and in instance memory otherwise. Do not script a "laptop shows the copilot's internal audit
   rows" beat.
2. **A key in a URL is refused (400) and the query is blanked** before uvicorn's access log
   can print it. Vercel's own request log is outside this code, so send the key only in the
   `X-API-Key` header. Run uvicorn with `--no-access-log` (or a log config that drops the
   query string) anywhere else.
3. **The audit key id is the peppered HMAC id** (`MAUDESIGNAL_KEY_PEPPER`; derived from the
   configured key digests when unset), the same id the limiter and ledger use. It is not a prefix
   of any stored credential form. Set the pepper so ids stay stable when the key list changes.
   An `ask` question is audited as a SHA-256 and a length only.
4. **Deploy check still open** (see part 1, step 1): which dependency manifest Vercel installs,
   and the bundle size. Confirm with Track B that this root `vercel.json` is only used by the API
   project (the web project is rooted at `web/` and does not read it).
5. **MCP is a minimal stateless implementation** (see part 2): `initialize`, `ping`,
   `tools/list`, `tools/call`. It was tested with a local client and with JSON-RPC over the ASGI
   test client, not with Muse or any other third-party MCP client.
6. Live openFDA calls (`check_device_type`, unstored codes, the keyless route) and the live Muse
   Spark call have not been run from this environment (no network); tests use fakes.

---

# Part 2. MCP server

Submission status: Submitted to Meta's Muse Connector Program — pending review.

## Feedback and visits (private)

Added for outreach. Nothing here is in the public OpenAPI document, and no public route serves a
record. The tool is an advisory triage aid, not medical advice; do not type patient details.

| Route | Auth | What it does |
|---|---|---|
| `POST /v1/feedback` | none; browser origin must be in `MAUDESIGNAL_WEB_ORIGINS` | rating 1-5 ("Does this match real PMS/RA work?"), comment, blocker, one_thing, optional role, consent (`quote_name_role`, `quote_anonymous`, `no_quote`), optional `ref` (see code rule below), page, client_ts. An optional `name` from an old client is accepted and dropped before storage. 201 on success. 5 per hour per address (`MAUDESIGNAL_FEEDBACK_PER_HOUR`), 16 KB body cap (413). Free text that looks like an email, phone, SSN, "MRN" + digits or a date of birth gets 422 and is not stored (a guard, not a guarantee). |
| `POST /v1/visit` | same | `{ref?, page, client_ts}`, 204. 60 per hour per address. |
| `GET /admin` | page holds no data | asks for the admin key (password field, kept in `sessionStorage` only), loads the summary, shows a "By code" section (one block per code: code, label, visits, pages opened, first and last seen, and a feedback table with time, page, rating, comment, blocker, one thing, role and quote consent in plain words), a "Hide TEST codes" checkbox, a "Delete TEST entries" button (asks to confirm), and two CSV downloads. States "No names are shown here; no emails or IP addresses are stored." |
| `GET /v1/admin/summary` | `X-Admin-Key` | visits and feedback per ref code and per page, average rating per ref, and `codes`: one entry per code, newest activity first, with `code`, `label`, `visits`, `pages_opened`, `first_seen_utc`, `last_seen_utc` and its `feedback` rows (no names). |
| `GET /v1/admin/export?kind=feedback\|visits&format=csv\|json` | `X-Admin-Key` | every record (no name column). CSV cells starting with `=`, `+`, `-` or `@` are prefixed with `'`. |
| `POST /v1/admin/delete-test` | `X-Admin-Key` | deletes every stored visit and feedback entry whose code is `TEST` followed only by numbers or `. _ ~ -` (any case, for example `TEST1`, `test-2`) and returns `{"deleted": {"visits": n, "feedback": n}, "failed": n}`. Nothing else is deleted; `tester7` or `Testa.M` are ordinary codes. An object that fails to delete is counted in `failed` and the rest carry on. Both record stores (memory and Vercel Blob) can delete; Blob uses `POST /delete` with the object url. |
| `POST /v1/admin/redact-names` | `X-Admin-Key` | body `{"dry_run": true\|false}`. Lists every stored feedback record; where a non-empty `name` is present and consent is not `quote_name_role`, the `name` key is removed and only that record is rewritten at the same blob path (Blob put with `x-allow-overwrite`). Visits and all other fields are untouched. Returns `{"checked": n, "names_removed": n, "names_kept_quote_by_name": n, "failed": n}`; `dry_run` changes nothing and returns the same counts. A store error on one record counts in `failed` and the rest carry on; a listing failure answers 503. The `/admin` button "Remove names (keep only 'quote me by name')" runs the dry run, asks to confirm, then runs it. |

**Admin step after deploy.** Open `/admin`, enter the key, and press "Remove names (keep only 'quote me by name')" once; confirm the counts in the dialog, then read the result line. Blank (whitespace-only) names are ignored. Blob storage can serve a cached copy for a short time, so wait about a minute before checking again. Records sent before 31 October 2026 may hold a typed name until this is done.

**Code rule.** Personal links look like `https://<web>/?r=CODE`. A code is 1 to 64 characters from
`A-Z a-z 0-9 . _ ~ -` (`^[A-Za-z0-9._~-]{1,64}$`). A code that does not match is not lost: the visit or
feedback is stored with the code `invalid-code` (the bad value itself is never stored). Codes
that are `TEST` plus only numbers or `. _ ~ -` (any case; not `tester7`) are labelled "test" in `/admin`; `email-batch-1` is labelled "email batch 1".

**No names.** New feedback stores no names; older entries keep a typed name only where the person chose to be quoted by name and role (see /v1/admin/redact-names). No emails or IP addresses are stored. Charan keeps the names-to-codes list
privately; the connector keeps no people list. Free text is still checked for patient details,
including the optional `role`.

Records sent without a `ref` are labelled `email-batch-1` (Charan's first email batch had no codes); override with `MAUDESIGNAL_DEFAULT_REF` (an invalid value falls back to `email-batch-1`).

Never stored: IP address, user agent. The limiter holds only a salted HMAC of the address for the
length of its window (in memory, or Upstash when configured). Records are JSON objects in a
private Vercel Blob store at `feedback/<YYYY-MM-DD>/<id>.json` and `visits/<YYYY-MM-DD>/<id>.json`.
Without `BLOB_READ_WRITE_TOKEN` an in-memory store is used and `GET /v1/health` shows
`"feedback_store": "memory"` (`"blob_private"` when the Blob store is in use).
If `MAUDESIGNAL_ADMIN_KEY` is unset the admin routes answer 503; they are never open. Failed
admin keys count against the same per-address failed-key limiter as API keys.

Environment: `BLOB_READ_WRITE_TOKEN`, `MAUDESIGNAL_ADMIN_KEY`, `MAUDESIGNAL_WEB_ORIGINS`,
`MAUDESIGNAL_TRUST_FORWARDED=1`; optional `MAUDESIGNAL_FEEDBACK_PER_HOUR`,
`MAUDESIGNAL_VISIT_PER_HOUR`, `RESEND_API_KEY` + `FEEDBACK_NOTIFY_TO` (comma-separated) +
`FEEDBACK_NOTIFY_FROM`. Email failures are logged by status or error class only and never fail the
request. The Blob REST headers (`x-vercel-blob-access: private`, `x-add-random-suffix: 0`,
`x-api-version`) follow the documented API from memory and were not exercised against the live
service from this environment; check the first real write.

## Live Muse for the public website (`/v1/live/*`)

Added so the website can talk to Muse without a connector key: a typed chat with earlier turns,
a spoken question, and a device-label photo. It is the same copilot, claim gate and label reader
as everywhere else; this layer adds limits, cost caps, upload checks and recorded fallbacks. Not
medical advice. Nothing is filed with FDA. Not in the public OpenAPI document.

| Route | Body | Muse models | What comes back |
|---|---|---|---|
| `POST /v1/live/ask` | JSON `{question (3-500 chars), history? (max 4 of {question, answer}), product_code? (3 letters), ref?}`. Each history answer is cut to 600 characters on the server. | Muse Spark 1.3 (read-only tools) | the answer sentences with their links, left-out reasons, spoken text |
| `POST /v1/live/voice` | multipart: `audio` (WAV, PCM16, mono, 16000 Hz, at most 60 s and 4 MB) and an optional `meta` JSON part `{history?, product_code?}` | Muse Voice Transcribe 1.0, then Muse Spark 1.3 | `heard` (the transcript, shown before the answer) plus the same answer block |
| `POST /v1/live/label` | multipart: `image` (JPEG or PNG, at most 4 MB; the website shrinks photos to 1600 px on the long side, JPEG quality 0.85, before sending) | SAM 3.1, then Muse Spark 1.3, then openFDA searches | `reading` and up to 3 possible matches; `confirmed` is always `null` (a person confirms) |

Every response has `mode` (`live` or `recorded`), `recorded_note` (when recorded: why, and which
recorded run), `not_medical_advice: true`, `trace` (one entry per step: `step`, `model`
(`muse-spark-1.3`, `muse-voice-transcribe-1.0`, `sam-3.1` or `null`), measured `ms`, `status`
`ok` / `skipped` / `failed`, `note`), `cost_usd` (a number, or `null` when nothing was spent) and
`limits` (`remaining_today`, `resets_utc`). `ask` and `voice` add `answer`
(`speakable: [{text, links: [{label, url}]}]`, `withheld: [{reason}]`, `spoken_text`); `voice` adds
`heard`; `label` adds `reading` (`legibility`, `fields` for device name, manufacturer, model,
K-number, UDI and GTIN, `values_withheld`) and `matches` (`status`
`needs_person_to_confirm` or `no_match_found`, `candidates` with `k_number`, `device_name`,
`applicant`, `product_code`, `why_matched`, `why_not_matched`, `links`).

Errors are `{code, message}` (also repeated under `error` for older clients): 422 `patient_data`
or `invalid_input`, 429 `rate_limited` with `retry_after_s` and a `Retry-After` header, 413
`too_large`, 403 `origin_not_allowed`, 503 `unavailable` (no recorded answer exists either).

**Rules**

- *Limits per address per UTC day:* ask 30, voice 10, label 5 (`MAUDESIGNAL_LIVE_ASK_PER_DAY`,
  `MAUDESIGNAL_LIVE_VOICE_PER_DAY`, `MAUDESIGNAL_LIVE_LABEL_PER_DAY`), plus a per-minute burst limit
  (`MAUDESIGNAL_LIVE_PER_MIN`, default 10). The address is only ever a peppered HMAC
  (`MAUDESIGNAL_KEY_PEPPER`), held in memory or in Upstash; it is never in a record and never
  logged. A request that fails validation does not use the daily count.
- *Cost:* ONE rule for every Meta call, with a hard ceiling of **$3.00 per UTC day**
  (`MAUDESIGNAL_LIVE_DAILY_USD`), shared by the website routes (ask, voice, label) and the keyed
  `ask` tool. In plain words: before each single model call the service reserves that call's
  worst-case cost; after a successful reply it lowers the reservation to the real cost; a call
  that fails, times out or returns no usage stays counted at its worst case for the rest of the
  day. Live calls normally stop at about $2.90, which is $3.00 minus one call's largest hold.
  Outside mentions makes no Meta call and does not use the ledger. Per-request caps (ask 0.25,
  voice 0.30, label 0.30; `MAUDESIGNAL_LIVE_ASK_USD`, `_VOICE_USD`, `_LABEL_USD`) only bound one
  visitor's request and write nothing to the ledger.
  **How it works** (`src/maudesignal/connector/callcap.py`; the only code that enforces the daily total):
  1. *What a call is.* Every Muse Spark chat completion (each tool round, the final answer and the
     repair round), every Voice Transcribe call and every SAM call. The keyed `ask` tool, live ask,
     live voice (transcription, then the answer) and live label (SAM, then the Spark read) all go
     through the same function.
  2. *Worst case of one call.* Spark: the prompt's size (UTF-8 bytes divided by 3, plus a flat
     8,000 tokens per image) times the input price, plus `max_tokens` times the output price
     (`max_tokens` is always set on the call, 8,000 by default). SAM: the per-image price
     ($0.0025). Transcription: the audio seconds, rounded up plus one, times the per-second price.
     A call whose worst case is above **$0.10** is not made (the largest real holds are about
     $0.04 for an ask turn and $0.07 for a label read).
  3. *Reserve.* Write `ledger/<UTC-day>/<uuid>.json` = `{"hold_usd": worst_case}` to the private Blob
     store, list the day's prefix, and add up each object's counted value: `actual_usd` when the
     object has `settled_ok` true, else `hold_usd`. If the sum, this call's object included, is
     above the cap, delete this call's own object and make no call (a recorded answer is shown).
     If the write, the list, a read or the corrupt-entry check fails, no call is made either.
  4. *Settle.* Only if the provider returned a successful reply with usage, overwrite this call's own
     object with `{"hold_usd", "actual_usd", "settled_ok": true}`. On any exception, timeout, missing
     usage or failed overwrite the object stays as it is and counts its worst case forever. The real
     cost never exceeds the worst case, so the day's total can only be over-counted. If usage ever
     did exceed the hold, the real cost is stored and a warning `call_cost_above_hold` is logged.
  5. *Enforced cap.* Two calls that reserve at the same moment can each pass, so the cap the ledger
     enforces is **$3.00 minus the largest possible single hold ($0.10) = $2.90**. Two such calls
     together end at or under $3.00. Three or more instances whose listings lag can overshoot, by up
     to (k-1) x $0.10 for k lagging instances (a probe with three lagging instances reached $3.10).
  6. *Per-key totals.* The per-key daily total of the keyed `ask` tool (`MAUDESIGNAL_API_DAILY_USD`)
     is a separate, smaller limit that counts real cost after a call. It holds nothing and
     releases nothing in the global ledger.
  Tested (`tests/unit/test_call_ledger.py`, fake store, no network): hold arithmetic; the hold is on
  the ledger before the call; hold 0.08 settles to 0.03 and is counted 0.03; an exception after the
  send, a timeout, a failed settle write and a reply without usage all keep the hold; a failed
  list, write or read, and a reached cap, give a recorded answer with no call; a deterministic
  two-instance interleave with a lagging listing (no process lock) ends at $3.00 exactly and never
  above; a randomized run of 1,000 calls with random failures never counts above $3.00 and never
  counts less than what was really billed. All with a fake store, **not a real Blob store**.
  **Known limit, not yet measured:** the rule relies on a completed write showing up in the next
  listing of the store. Before turning live on, measure put-then-list consistency against the real
  private store once and record the result here. A listing longer than 20 pages (20,000 objects)
  fails closed. A listed object that cannot be read (for example a 404) is never counted as 0: it
  counts at the largest hold, $0.10, so a store that cannot be read refuses calls rather than
  letting them through; a refused call's own deleted object can therefore over-count briefly.
  **Blob operations.** Each Meta call costs one put, one list, one read per object not yet settled,
  one overwrite to settle and (if refused) one list and one delete. These count as "advanced
  operations" on Vercel; the monthly allowance depends on the plan and was not checked here: look it
  up in the Vercel dashboard (Usage, Blob) before the review. If it runs out the ledger cannot be
  read or written, so live answers become recorded answers and feedback writes fail; nothing is
  spent.
- *Fallback:* with no `META_MODEL_API_KEY`, a cap reached, or any model error, the answer is a
  recorded run and says so (`mode: "recorded"`, with the recorded question or sample photo
  named). A recorded answer is never shown as live. Voice: if the clip cannot be transcribed, a
  recorded spoken-question run is returned and `heard` is absent. Label: the closest stored
  `demo/vision/label-match-*.json` (first one with candidates), marked as not your photo.
- *Claim gate:* every sentence goes through the gate exactly as in `ask`; a left-out sentence's
  text is never returned live, only a fixed reason. Tools are read-only (`readonly.py`);
  temperature 0; the prompts live in `skills/`.
- *Patient data:* a question, a history entry or a voice transcript that looks like patient
  details (email, phone, SSN, MRN, date of birth, a title with a name such as "Mrs. Jane Smith",
  an age such as "age 67" or "67-year-old") is refused with 422 `patient_data` and not answered.
  A guard, not a guarantee: other free-text names are not caught, so the website input keeps the
  "not a guarantee" wording.
- *Uploads:* size, type, duration and pixel count are checked before any model call. Multipart is
  parsed in memory (the standard form parsers spool large parts to temporary files, which uploads
  here must not be). The photo is decoded and re-encoded as a plain JPEG from its pixels, so EXIF,
  GPS, ICC and comment blocks are dropped; orientation is applied first. Audio and image bytes are
  never written to disk or Blob and never logged. Lot and serial numbers are never returned (the
  UDI keeps only the 01, 11 and 17 identifiers).
- *Time:* the label request is designed to end in under 55 s when upstream services behave: SAM
  calls time out at 10 s and start no new prompt after 12 s; each Spark call gets the time left of
  a 50 s budget; openFDA calls time out at 6 s, are cut at 8 s of wall-clock time (an httpx
  timeout counts each phase, not the whole call) and start no new query after 45 s. SAM's 10 s is
  a per-phase timeout, so a slowly dripping SAM response can run longer; no figure here is
  measured against the real services. The voice request has one deadline of 52 s from the start
  (transcription gets at most 15 s, Spark gets the time left, and with under 3 s left the
  recorded run answers with a timeout note). On a timeout the stored run answers, with a note.
  `vercel.json` keeps `maxDuration` 60.
- *Request size on Vercel:* Vercel rejects request bodies over 4.5 MB before the app runs, with a
  413 that has no CORS headers, so a browser sees a network error. The server limit is therefore
  4 MB for photos and audio, and the web client must downscale or re-encode a photo (1600 px long
  side, JPEG quality 0.85) before upload.
- *Label with no search:* if openFDA could not be searched (every query failed, or the 45 s window
  ended), `matches` has `search_failed: true` and a `note`; the web side shows that note instead of
  "no match found". `no_match_found` without the flag means a search ran and found nothing.
- *Shared limits need a pepper:* set `MAUDESIGNAL_KEY_PEPPER` (required when Upstash is configured).
  Without it each instance makes its own random pepper, one address gets a different id on every
  instance, and the per-address daily limits are multiplied by the number of warm instances; a
  warning (`live_pepper_missing`) is logged at start-up when this happens.
- *CORS:* only the exact origins in `MAUDESIGNAL_WEB_ORIGINS`, `POST` and `OPTIONS`, header
  `Content-Type`, no credentials; another origin gets 403.

**Deploy:** `vercel.json` `includeFiles` now covers `src`, `skills`, `demo/transcripts`,
`demo/vision` (the stored label runs), `digests`, `data/demo`, `design-system` and `api`. `api/requirements.txt`
gains `pillow`. Set `META_MODEL_API_KEY` for live answers; `OPENFDA_API_KEY` is optional. These
steps are the owner's; nothing was deployed from this branch.

**Live smoke test:** `.github/workflows/live-smoke.yml` runs `scripts/live_smoke.py` (two chat
turns, the second with history; one spoken question from `demo/voice/question.wav`, else
`question-c.wav`, resampled to 16 kHz mono if needed; one photo,
`demo/vision/labels/label-caresens-n.jpg`) in process through the real app, with a hard cap of
$0.60 in total, and commits `demo/live-smoke/result.json` to `track-c-live`. It runs only when
`demo/LIVE_SMOKE_REQUEST` is pushed to `track-c-live` with a value other than empty or `0`
(it holds `0`, so the first push spends nothing), or by hand. No live run has been made from this
branch, so no live result or cost figure is claimed here.

## Outside mentions (`POST /v1/live/mentions`, no key, no model)

Body `{product_code (3 letters), device_terms? (max 5 strings of 2 to 60 characters)}`. It looks
for the code and terms in free public sources only: GDELT DOC 2.0 for news (20 s timeout per
try, up to 2 retries after a timeout, a network error, HTTP 429 or a 5xx, with waits of 2 s and 4 s,
all inside a 32 s feed phase), FDA press-release, recall, MedWatch safety-alert and
medical-device feeds, and the MedTech Dive feed, labelled **news and public web**. MassDevice was
dropped (it answered HTTP 403 in the recorded run). FDA warning letters were dropped too: the
feed address used before answered HTTP 404 in the recorded run of 2026-10-31 and no stable feed
for them could be confirmed (the list on fda.gov is a script-driven table); nothing is claimed
about them. The MedWatch and medical-device feed addresses follow the pattern of the working FDA
press-release and recall feeds and were **not reachable from the build sandbox**, so
`sources_tried` reports each source's real status (`ok`, `failed: ...`) and result count
instead of assuming it, and the body has `searched_utc` and a `summary` line such as "0 found in
these sources (2026-10-31 UTC): <each source and its status>." for the page to show when nothing
matches. Each candidate page is
fetched; a mention is kept only if its quoted sentence is found word for word in the fetched page
text. Dropped, with counts in `dropped`: `quote_not_found` (the source offered a sentence that is
not on the page), `personal_details` (an email, phone, age, a title with a name, "patient
<Name>"), `off_topic` (the page does not mention the terms, or the sentence has a term this
service never uses). Every mention has `badge` "Unverified — not checked against FDA records" and
is never mixed with claim-gated FDA facts; `source_kind` is the fixed value for FDA-hosted pages (listed in
`mentions.py`), otherwise `news` or `web`. At most 10 mentions; the whole search ends in under 50 s. Limits: 10 per address
per UTC day. It makes no Meta call, so it costs nothing and does not use the spend ledger. When the
limit or the network stops a live search, the stored
file `demo/mentions/<CODE>.json` answers with `mode: "recorded"` and a `recorded_note`; with no
file the lists are empty and the note says so. `.github/workflows/mentions-record.yml` writes
`LLZ.json` (and any codes in the request) when `demo/mentions/REQUEST` changes on `track-c-live`;
the file holds `0`, so nothing runs yet and **no stored mentions file exists yet**.
**Unconfirmed feed addresses.** The `medwatch` and `medical-devices` FDA RSS addresses in
`mentions.py` were not reachable from the build sandbox and are **not confirmed**. During the free
recording, check that each returns HTTP 200 with RSS; any that does not is removed from `SOURCES`
and from this page and the privacy page before the live route is turned on. Until then a wrong
address shows as "failed: http 404" in the per-source status, never as a mention.

## Demo key, labelled keys and `GET /v1/connect`

`MAUDESIGNAL_DEMO_KEYS` (same format as `MAUDESIGNAL_API_KEYS`) holds public demo keys. A demo key
works on every read tool, has its own limits (`MAUDESIGNAL_DEMO_RATE_PER_MIN`, default 10 per
minute, plus 200 per day per key) and **never starts a live model call**: `ask` returns a recorded
answer, labelled. It is public by design and must never be committed. `GET /v1/connect` (no key,
CORS for the web origins) returns `mcp_url`, `openapi_url`, `docs_url`, `auth_header`
(`X-API-Key`), `demo_key` (the first entry of `MAUDESIGNAL_DEMO_KEYS` when it is a plain key,
otherwise `null`), `demo_limits` and three `steps`. Key labels (`label=KEY`) appear in the audit
actor (`connector:key:<label>:<key id>`) and in the request log; the key itself never does.
`python3.12 -m maudesignal.connector.keygen --label meta-review` appends the new key to
`MAUDESIGNAL_API_KEYS` through the Vercel API (earlier keys keep working) and prints the line to
paste, without the key.

## Remove stored names (`POST /v1/admin/redact-names`)

Admin key required. Body `{"dry_run": true|false}` (default true). For every stored feedback
record with a non-empty `name`, the name is removed unless the record's consent is
`quote_name_role`; nothing else in any record is changed and visits are never touched. The reply is
`{checked, names_removed, names_kept_for_quote_by_name, dry_run, failed}`. The `/admin` page has
the button "Remove names (keep only 'quote me by name')": it previews the counts with a dry run,
asks for confirmation, then runs.

## 2.1 The MCP server (`POST /mcp`)

Same six tools as the REST routes, same process, same code path. Each REST route and each
`tools/call` goes through one `dispatch` function in `connector/app.py`, so the answer, the audit
entry and the cost cap are shared.

| Item | Value |
|---|---|
| Endpoint | `https://maudesignal-api.vercel.app/mcp` |
| Transport | Streamable HTTP, **stateless**: one JSON-RPC message per `POST`, a JSON reply, no session id, no event stream. `GET`, `DELETE`, `PUT`, `PATCH` on `/mcp` return 405. |
| Protocol version | `2025-06-18` (header `MCP-Protocol-Version` may be `2025-06-18` or `2025-03-26`; anything else is 400) |
| Methods | `initialize`, `ping`, `tools/list`, `tools/call`, `prompts/list`, `prompts/get`; notifications and client replies get 202 with no body. Batches are refused (protocol 2025-06-18 removed them). |
| Auth | `X-API-Key: <key>` **or** `Authorization: Bearer <key>` (the Bearer form also works on the REST routes). A key in the URL is refused (400). Wrong or missing key: 401; repeated wrong keys from one address: 429. |
| Limits | The same per-key rate limit as REST (every HTTP request to `/mcp` counts once, also `tools/list`), the same per-key daily cost cap for `ask`, the same audit log (`GET /v1/audit/recent`). |
| Browsers | A request that carries an `Origin` header is refused (403) unless the origin is listed in `MAUDESIGNAL_WEB_ORIGINS` (the MCP DNS-rebinding guard). Server-side clients send no `Origin`. |
| Tool annotations | `readOnlyHint: true`, `destructiveHint: false`, `idempotentHint: true` on all six; `openWorldHint: true` on `what_changed_this_week`, `check_device_type`, `ask`, `lookup_device` and `recalls` (they can reach live openFDA or the live model), `false` on `get_report`. |
| Result | `content`: one text item, the speakable summary. `structuredContent`: the full answer (`tool`, `speakable`, `facts` with links, `advisory`, `provenance`, `withheld`), identical to the REST body of the same call (a test compares them for all six). `outputSchema` is the common answer model, except that `lookup_device` has its own (adds `status`, `confirmed`, `note`, `searched_with`, `matches` and `device_types`) and `recalls` has its own (`RecallsAnswer`, which adds `suggestions`, a list of strings that is empty when there are none; the same in REST and OpenAPI). `tests/unit/test_connector_schema_contract.py` validates every tool's `structuredContent` against its advertised `outputSchema` and every REST body against its OpenAPI response schema. |
| Errors | Unknown tool or malformed call: JSON-RPC error `-32602`; unknown method `-32601`; bad JSON `-32700` (HTTP 400). A tool that cannot answer (invalid input, report not stored, openFDA unreachable) returns `isError: true` with a fixed, key-free message; `lookup_device` instead returns `status` `search_failed` with a `note` (`isError` false). |
| Manifest | `api/mcp-manifest.json`, also served at `GET /mcp-manifest.json` without a key. Generated by `python3.12 -m maudesignal.connector.manifest` from the same tool registry (`connector/registry.py`) that builds `tools/list` and supplies the REST descriptions; a test fails if the file drifts or if REST and MCP descriptions differ. |

Why not the `mcp` Python SDK: this server only needs request/response, and a serverless
function cannot hold the sessions and streams the SDK's default server keeps. The hand-written
version is about 150 lines (`connector/mcp_server.py`), has no extra dependency, and is covered by
`tests/unit/test_connector_mcp.py` (20 tests). It was also checked with the `mcp` Python SDK client
(modelcontextprotocol, version 2.3.0, `streamable_http_client` and `ClientSession`) against the server running
under uvicorn on local HTTP: `initialize` negotiated protocol 2025-06-18, `tools/list` returned the
five tools all with `readOnlyHint` true, and `tools/call` succeeded for `recalls`, `get_report`,
`what_changed_this_week` and `ask` (recorded answer); `check_device_type` for QAS returned
`isError` because openFDA cannot be reached from this environment. The key was absent from every
response and the server log showed no error. It was **not** checked against Muse.

`vercel.json` routes `/mcp` and `/mcp-manifest.json` to the same function as the REST routes.

### Withheld sentences over MCP

`ask` in live mode never returns the text of a sentence the gate left out: `withheld` holds a
placeholder, a fixed reason and the claim kinds. `tests/unit/test_connector_mcp.py::
test_mcp_live_body_never_holds_a_withheld_sentence` runs a scripted live `ask` over `/mcp`, with
sentences the gate blocks, and scans the whole raw response body (text content and
`structuredContent`), the JSON-escaped form, and the spoken text for the blocked sentences and
any 20-character piece of them. The REST twin of that test is in `test_connector_safety.py`.

### Real local transcript (MCP client over HTTP)

> This transcript was recorded before MCP prompts and the new server instructions were added: its
> `initialize` reply shows the older instructions string and no `prompts` capability, and its
> tool list has five tools. The current `initialize` reply is described in the sections above.

Captured with a short Python client using `httpx` against `uvicorn api.index:app --no-access-log
--no-proxy-headers` on 127.0.0.1:8766, with a throw-away key made in the client process and passed
to the server's environment (never printed, and the client asserts it is absent from every
response), `MAUDESIGNAL_RATE_LIMIT_PER_MIN=10`, no `META_MODEL_API_KEY`, no `OPENFDA_API_KEY`,
no Upstash. This environment cannot reach openFDA, so `check_device_type` for a code that is not
stored returns the tool error shown, and `ask` returns the recorded answer. Long bodies are cut by
the client at the byte count it prints; the rest is as received.

```text
### initialize
HTTP 200
{"jsonrpc":"2.0","id":0,"result":{"protocolVersion":"2025-06-18","capabilities":{"tools":{"listChanged":false}},"serverInfo":{"name":"maudesignal-connector","title":"MaudeSignal (read-only)","version":"0.1.0"},"instructions":"Read-only MaudeSignal tools over openFDA device data. Speak the text content; every fact in structuredContent has an openFDA or record link. Sentences listed under withheld were not verified: never state them as fact. Advisory triage aid for quality and regulatory review; not medical advice; nothing is filed with FDA."}}

### notifications/initialized
HTTP 202 (no body)

### tools/list (Authorization: Bearer)
HTTP 200
  what_changed_this_week: readOnlyHint=True destructiveHint=False openWorldHint=True inputs=['product_code']
  check_device_type: readOnlyHint=True destructiveHint=False openWorldHint=True inputs=['product_code']
  ask: readOnlyHint=True destructiveHint=False openWorldHint=True inputs=['question']
  get_report: readOnlyHint=True destructiveHint=False openWorldHint=False inputs=['report_id']
  recalls: readOnlyHint=True destructiveHint=False openWorldHint=True inputs=['product_code']

### tools/call recalls LLZ
HTTP 200
{"jsonrpc":"2.0","id":2,"result":{"content":[{"type":"text","text":"The stored demo snapshot holds 561 recall product records (433 recall events) for product code LLZ. The most recent started September 5, 2026 by INTELERAD MEDICAL SYSTEMS INCORPORATED."}],"structuredContent":{"tool":"recalls","speakable":"The stored demo snapshot holds 561 recall product records (433 recall events) for product code LLZ. The most recent started September 5, 2026 by INTELERAD MEDICAL SYSTEMS INCORPORATED.","facts":[{"text":"561 recall product records (433 recall events) for product code LLZ in the stored snapshot.","link":"https://api.fda.gov/device/recall.json?search=product_code%3ALLZ&limit=1","link_label":"openFDA: recalls for this code"},{"text":"Recall Z-0186-2027, started September 5, 2026 by INTELERAD MEDICAL SYSTEMS INCORPORATED, status Open, Classified. Reason: Following a Chromium-based web-browser, report and displayed images may not match.","link":"https://api.fda.gov/device/recall.json?search=product_res_number%3A%22Z-0186-2027%22&limit=1","link_label":"openFDA recall"},{"text":"Recall Z-3... [2985 bytes total]

### tools/call get_report 50426770
HTTP 200
{"jsonrpc":"2.0","id":3,"result":{"content":[{"type":"text","text":"Report 5 0 4 2 6 7 7 0 is a malfunction report for product code LLZ, received August 25, 2026. The start of its narrative is in the facts."}],"structuredContent":{"tool":"get_report","speakable":"Report 5 0 4 2 6 7 7 0 is a malfunction report for product code LLZ, received August 25, 2026. The start of its narrative is in the facts.","facts":[{"text":"Report 50426770: product code LLZ, event type malfunction, received August 25, 2026.","link":"https://api.fda.gov/device/event.json?search=mdr_report_key%3A50426770&limit=1","link_label":"openFDA report"},{"text":"Report 50426770 lists brand IntelliSpace Cardiovascular, manufacturer Philips Medical Systems Nederland B.V..","link":"https://api.fda.gov/device/event.json?search=mdr_report_key%3A50426770&limit=1","link_label":"openFDA report"},{"text":"Start of the narrative, word for word: \"Philips received a complaint regarding IntelliSpace Cardiovascular (ISCV), indicating that they have a case that needs to be corrected. The device was in clinical use at the time of th... [1780 bytes total]

### tools/call what_changed_this_week LLZ
HTTP 200
{"jsonrpc":"2.0","id":4,"result":{"content":[{"type":"text","text":"In the stored demo snapshot for August 25, 2026 to August 31, 2026, LLZ shows reports suddenly increased: 33 reports against a weekly average of 8.75 in the four weeks before."}],"structuredContent":{"tool":"what_changed_this_week","speakable":"In the stored demo snapshot for August 25, 2026 to August 31, 2026, LLZ shows reports suddenly increased: 33 reports against a weekly average of 8.75 in the four weeks before.","facts":[{"text":"LLZ (System, Image Processing, Radiological): reports suddenly increased. 33 reports received August 25, 2026 to August 31, 2026, against a weekly average of 8.75 in the four weeks before.","link":"https://api.fda.gov/device/event.json?search=device.device_report_product_code%3ALLZ+AND+date_received%3A%5B20260825+TO+20260831%5D&limit=1","link_label":"openFDA: reports in this week"}],"advisory":"Advisory triage aid for quality and regulatory review; not medical advice; nothing is filed with FDA.","provenance":{"kind":"stored_demo_snapshot","source":"Stored demo snapshot of openFDA devic... [1399 bytes total]

### tools/call ask (no model key: recorded answer)
HTTP 200
{"jsonrpc":"2.0","id":5,"result":{"content":[{"type":"text","text":"Live answers are not switched on here, so this is a recorded answer to a different, similar question: \"What changed this week, Did reports suddenly increase for any device\", using stored reports through August 31, 2026. Yes, LLZ reports suddenly increased this week with 33 reports from August 25 to August 31, 2026. One sentence was left out because it could not be verified or tied to a source."}],"structuredContent":{"tool":"ask","speakable":"Live answers are not switched on here, so this is a recorded answer to a different, similar question: \"What changed this week, Did reports suddenly increase for any device\", using stored reports through August 31, 2026. Yes, LLZ reports suddenly increased this week with 33 reports from August 25 to August 31, 2026. One sentence was left out because it could not be verified or tied to a source.","facts":[{"text":"Yes, LLZ reports suddenly increased this week with 33 reports from August 25 to August 31, 2026.","link":"https://api.fda.gov/device/event.json?search=device.device_... [2733 bytes total]

### tools/call check_device_type QAS (openFDA unreachable here)
HTTP 200
{"jsonrpc":"2.0","id":9,"result":{"content":[{"type":"text","text":"openFDA could not be reached just now; try again shortly."}],"isError":true}}

### 401 without a key
HTTP 401
{"error":{"code":"unauthorized","message":"A valid X-API-Key header is required."}}

### 429 past the per-key limit (10 per minute in this run)
ping number 11: HTTP 429
{"error":{"code":"rate_limited","message":"Rate limit of 10 requests per minute reached. Retry in 60 seconds."}} | Retry-After: 60
```

Not done: no call from Muse or from any third-party MCP client, no deploy to Vercel, no live
openFDA call, no live Muse Spark call.

## 2.2 Privacy, terms and what is still open

The privacy and terms texts are served by the API itself at `/privacy` and `/terms`
(`connector/legal_pages.py`); the form answers above repeat them. Still open, and done by Charan:
set `MAUDESIGNAL_CONTACT_EMAIL` in Vercel, add the two keys, redeploy, read the live form and
correct any field that differs, submit it himself, then change the status line at the top.
