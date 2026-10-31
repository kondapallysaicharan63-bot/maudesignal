# MaudeSignal connector for Meta Muse (read-only REST API and MCP server)

Status: **built and tested locally; not deployed from this environment; not submitted.** Part 1
is the REST API, how to deploy it, how to make a key, and how to check it. Part 2 (at the end of
this page) is the MCP transport at `/mcp`, the draft answers for the connector submission form,
privacy and terms text, and a real local MCP client transcript. Nothing on this page says anyone
has reviewed or endorsed the connector.

## Form answers (single source for the Meta connector form)

**Submission status: Not submitted.** This section is the one place the connector form answers
live; the pages `/privacy` and `/terms` and the answers below are written from the same text
(`src/maudesignal/connector/legal_pages.py`, checked by a test). Field names on the live form may
differ: read the live form before pasting anything, and correct what differs here.

| Field | Answer |
|---|---|
| Connector name | MaudeSignal |
| Icon | `docs/hackathon/maudesignal-icon.svg` (vector) and `docs/hackathon/maudesignal-icon.png` (512 x 512). Original artwork: a pulse line across a report page. No Meta and no FDA logo. |
| Short description | Read-only triage aid for U.S. FDA device adverse-event reports (MAUDE), recalls and device-type checks. Each fact carries its openFDA link. Advisory only; not medical advice; nothing is filed with FDA. |
| Long description | Five read-only tools over public openFDA device data: what changed this week (a stored snapshot, with its dates), a live openFDA check of any three-letter product code using the weekly detector's rules, a question tool answered by Muse Spark through deterministic tools where every sentence goes through a claim gate and sentences that cannot be verified are marked and never spoken as fact, one stored report, and recalls for a product code. Every answer carries a fixed advisory line and its data source (stored snapshot with dates, or live openFDA with the query time). For quality and regulatory professionals at medical-device companies; not for patients; not clinical decision support. |
| Endpoint (MCP) | `https://maudesignal-api.vercel.app/mcp` (MCP over streamable HTTP, stateless, protocol 2025-06-18). `GET /v1/connect` (no key) returns this URL, the OpenAPI URL, the header name, the demo key and three steps. |
| Endpoint (REST) | `https://maudesignal-api.vercel.app/v1/tools/<tool>` |
| OpenAPI URL | `https://maudesignal-api.vercel.app/openapi.json` (OpenAPI 3.1; `info.termsOfService` points to `/terms`) |
| Authentication | API key in the `X-API-Key` header (`Authorization: Bearer <key>` also works). No OAuth. Several keys can be listed in `MAUDESIGNAL_API_KEYS`, each revocable by deleting its entry; an entry may be labelled `label=KEY` so logs show the label (for example `charan=...,meta-review=...`). **How a reviewer gets a key:** Charan sends the `meta-review` key to the reviewer privately, never in the form, a chat transcript or the repository. For a first try without any key request, a public **demo key** is shown by `GET /v1/connect` when the operator sets `MAUDESIGNAL_DEMO_KEYS`. |
| Tools (all read-only) | `what_changed_this_week`: this week's change for a product code, from the stored snapshot (dates shown). `check_device_type`: a live openFDA check of any three-letter product code. `ask`: a question answered by Muse Spark through read-only tools, every sentence checked by the claim gate, or the closest recorded answer, labelled. `get_report`: one stored report by id. `recalls`: recalls for a product code with their openFDA links. |
| Example prompts | 1. "What changed this week for LLZ?" 2. "Check device type QIH against live openFDA." 3. "Show recalls for LLZ." 4. "Get report 50426770." 5. "How many LLZ reports were filed in the last stored week, and what is the link?" |
| Rate limits | Keyed: 30 requests per key per minute (`MAUDESIGNAL_RATE_LIMIT_PER_MIN`) and a per-key daily cost cap on `ask` (`MAUDESIGNAL_API_DAILY_USD`, default $2.00; $0.25 per call). Demo key: 10 per minute (`MAUDESIGNAL_DEMO_RATE_PER_MIN`) and 200 per day, on every read tool, and it never starts a live model call (`ask` returns a recorded answer, labelled). Keyless public check: 10 per address per hour. Live website routes: ask 30, voice 10, label 5, mentions 10 per address per day. **Global cap:** all live model calls together, the website routes and the keyed `ask` tool, stop at **$3.00 per UTC day** (`MAUDESIGNAL_LIVE_DAILY_USD`); after that, answers come from recorded runs, labelled recorded. The shared ledger is one stored record per request, so concurrent requests cannot erase each other's entries; it was tested with a fake store only (limits and the one known assumption are in the cost section of Part 2). |
| Data handling | Public openFDA data only (de-identified by FDA); no personal or patient data collected; no accounts. Question text is not logged (hash and length only). See the Data questionnaire below and `/privacy`. |
| Privacy policy | `https://maudesignal-api.vercel.app/privacy` |
| Terms | `https://maudesignal-api.vercel.app/terms` |
| Support contact | The address in `MAUDESIGNAL_CONTACT_EMAIL` (shown at runtime on `/privacy` and `/terms`; never written in git), and GitHub issues: `https://github.com/kondapallysaicharan63-bot/maudesignal/issues` |
| Writes / side effects | None. No tool writes anywhere; nothing is filed with FDA. |
| Category / audience | Quality and regulatory professionals at medical-device companies (B2B). |
| Anything else the form asks | Not known. Leave blank or ask the owner; do not invent. |

## Data questionnaire

The same answers as `/privacy` (one text, two places).

| Question | Answer |
|---|---|
| What does this service do with data? | It gives read-only access to public FDA device data (openFDA: adverse-event reports, recalls, 510(k) records) and, where a result says so, to device alerts from the UK MHRA, always labelled as UK. It is an advisory triage aid for quality and regulatory review. |
| Is any personal or patient data collected? | No. The data served is public and already de-identified by FDA. There are no accounts and no sign-up. Do not type patient or personal details into a question: the live routes refuse text that looks like a name with a title, an age, an email address or a phone number, and nothing is kept when they do. |
| Where is data processed and stored? | The service's functions run on Vercel in region iad1 (Washington, D.C., United States), as set in the project's vercel.json. Feedback entries, page-visit entries and the daily spend records are stored in a private Vercel Blob store. The region of that store is chosen when the store is created in the Vercel dashboard; the code does not check it, so this page does not state it. The other services named below (Meta Model API, Resend, GDELT, and Upstash if the operator sets it up) process what they receive in their own locations, which this service does not control. |
| Who else handles data (subprocessors)? | Vercel (hosting, runtime logs and Blob storage). Meta Model API: only when live answers are switched on, for the live ask, voice and label routes; the question text, the voice clip or the label photo is sent once to produce the answer when live answers are on, and is not stored by this service. Resend (email): only if the operator turns on email for new feedback; the email carries the feedback fields, no name and no address. Upstash (Redis): optional, only if the operator sets it up; it then holds the audit log, the rate-limit hashes and the daily cost ledger (no question text, no address, no name). Public data sources that this service reads: openFDA, GOV.UK (MHRA alerts), GDELT and FDA public feeds (for the outside-mentions search). These send us public data; we send them a product code or a search term, never a person's details. |
| What is logged, and for how long? | Per tool call: a key id (a keyed hash of the key, never the key), the tool name, the time, the status and the cost. Never the text of a question: for ask, only a hash and a length are recorded. Feedback is stored without names (role and quote consent only). A page visit stores the referral code, the page and the time. This service never stores an IP address: before any rate limit or counter sees it, the address is replaced by a keyed hash, which is held in memory (or in the operator's Redis store, if one is set up) only to apply limits, for at most twice the limit window (two days for daily counters). Vercel's own request logs may include the address; they are kept by Vercel for Vercel's runtime-log retention for this plan. Feedback and visits are kept until the hackathon review ends, then deleted on request or by 30 November 2026. |
| Cookies, tracking, sale of data, advertising? | No tracking cookies. No sale of data. No advertising and no use of data for ads. The separate web app may use Vercel Web Analytics for page-view counts, which sets no cookies. |
| Not medical advice, nothing filed | Nothing here is medical advice or clinical decision support. Nothing is filed with FDA or any other regulator. This is not an FDA-cleared device. It is an open-source project by Saicharan Kondapally. |
| How do I ask for deletion? | Write to the contact address (shown on `/privacy`, read from `MAUDESIGNAL_CONTACT_EMAIL` at runtime; if it is not set, the GitHub issues URL is shown) and give the referral code you were sent. Feedback and visits carry no name, so the code is how an entry is found. Entries are deleted on request. |

Retention detail: logs live as long as Vercel keeps runtime logs on the plan in use; the number of
days is not stated here because it depends on the plan and was not checked. The daily spend record
is a set of small objects, one per request, under one UTC day in the private Blob store (each name
holds a dollar figure and a call count; no personal data).

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
| Production branch | the branch you want live (`track-c-muse` until it is merged) |
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
  that send `/`, `/docs-page`, `/openapi.json` and `/v1/*` to the function.
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
| `MAUDESIGNAL_API_KEYS` | the key | Made by the script in step 3; never typed into git or chat. Comma-separated for several keys; each entry is `KEY`, `sha256:<hex>`, `label=KEY` or `label=sha256:<hex>`. Delete an entry to revoke that key. |
| `MAUDESIGNAL_TRUST_FORWARDED` | `1` | Vercel's edge sets `X-Forwarded-For`; without this the limiter would see one address. |
| `MAUDESIGNAL_KEY_PEPPER` | a long random string | Server-side secret for key ids in ledger file names and audit session ids. |
| `MAUDESIGNAL_WEB_ORIGINS` | e.g. `https://<web-project>.vercel.app` | Comma-separated exact origins that may call the keyless route from a browser. No wildcard (a `*` entry is ignored). Empty means no browser origin is allowed. |
| `MAUDESIGNAL_RATE_LIMIT_PER_MIN` | default `30` | Requests per key per minute. |
| `MAUDESIGNAL_FAILED_AUTH_PER_MIN` | default `10` | Wrong or missing keys per address per minute before 429. |
| `MAUDESIGNAL_PUBLIC_CHECK_PER_HOUR` | default `10` | Keyless checks per address per hour. |
| `MAUDESIGNAL_API_DAILY_USD` / `MAUDESIGNAL_API_REQUEST_USD` | defaults `2.00` / `0.25` | Cost cap of `ask` per key per UTC day, and per call. |
| `OPENFDA_API_KEY` | optional | Used only on the server for live openFDA checks (higher quota). Never in a response. |
| `UPSTASH_REDIS_REST_URL`, `UPSTASH_REDIS_REST_TOKEN` | optional | Add an Upstash Redis database (Vercel Marketplace, or upstash.com) and copy its REST URL and token. When both are set, the rate limits, the daily cost ledger, the six-hour cache and the audit log are shared by every instance. If the integration names them differently, add these two names by hand. |
| `BLOB_READ_WRITE_TOKEN` | the private Blob store's token | Also makes the global daily cost ledger durable and shared when Upstash is not configured (see below). |
| `MAUDESIGNAL_LIVE_DAILY_USD` | default `3.00` | The one global cap for every live model call per UTC day. |
| `MAUDESIGNAL_DEMO_KEYS` | optional | Public demo keys, same format as `MAUDESIGNAL_API_KEYS`; not secret. |
| `MAUDESIGNAL_DEMO_RATE_PER_MIN` | default `10` | Demo key requests per minute (and 200 per day). |
| `MAUDESIGNAL_CONTACT_EMAIL` | an address you choose to publish | Shown on `/privacy` and `/terms` at runtime; never in git. |
| `MAUDESIGNAL_PUBLIC_URL` | optional, e.g. `https://maudesignal-api.vercel.app` | Base URL that `GET /v1/connect` reports. |
| `META_MODEL_API_KEY` | optional | Leave **unset** until you accept the cost: `ask` then answers from recorded runs. |
| `MAUDESIGNAL_ALLOW_PER_INSTANCE_CAP` | `1` only if you set the model key without Upstash | Explicit acceptance that the cap and limits are per instance. Not needed with Upstash. |

Production traffic must reach the function without a Vercel login page: in Project > Settings >
Deployment Protection, make sure Production is not behind Vercel Authentication (or use a custom
domain). The first `curl` below shows whether it is.

### 3. Create the key without ever printing it

```bash
# Option a: the script writes it straight into Vercel (encrypted, Production).
VERCEL_TOKEN=... VERCEL_PROJECT_ID=prj_... VERCEL_TEAM_ID=team_... \
  python3.12 -m maudesignal.connector.keygen
# prints only: set; copy it from Vercel > Project > Settings > Environment Variables >
#              MAUDESIGNAL_API_KEYS (click to reveal)

# Option b: no Vercel token; the key goes to a mode-600 file outside the repository.
python3.12 -m maudesignal.connector.keygen
# prints only the file path and what to do with it
```

Option a appends the new key to the existing `MAUDESIGNAL_API_KEYS` list (earlier keys keep
working); to revoke a key, delete its entry in the dashboard. If the existing variable is a Vercel
"sensitive" one, its value cannot be read back, so the script refuses and changes nothing; add the
entry by hand instead. Option b: paste the file's one line
as the value of `MAUDESIGNAL_API_KEYS` in the dashboard, then delete the file. Either way the key
is never printed to stdout or stderr, never logged, never written inside the repository, and
Vercel's reply is never printed (only an HTTP status on failure). Tests run the script as a
subprocess and scan both streams for the key. Redeploy after changing an environment variable.

### 4. Verify with harmless reads

```bash
BASE=https://<your-api-project>.vercel.app
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
* `GET /v1/health` (no key), the five tools under `/v1/tools/` (key), `GET /v1/audit/recent` (key).
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
  the per-address limits, the daily cost ledger of `ask`, the six-hour cache and the audit log live
  in Redis; otherwise in memory of one instance (reset on a cold start). `GET /v1/health` says which.
  Tested with a mocked REST client only; **not run against a real Upstash database.** If Redis
  fails: rate limits fall back to the instance's memory, the cache is skipped, the audit append is
  logged and skipped (the request still answers; `/v1/audit/recent` answers 503), and the cost
  ledger raises so `ask` falls back to a recorded answer instead of spending without a cap. If the ledger write fails after a model call has already
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

Five read-only tools (REST and MCP, same code):
`what_changed_this_week`, `check_device_type`, `ask`, `get_report`, `recalls`.
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

1. **Without a shared store, rate limits and the daily cost cap are per server instance.** The
   per-minute limiter is in memory and the spend ledger is a file in the instance's temporary
   folder; on Vercel each instance has its own and both reset on a cold start. `/v1/health` reports
   `limits_scope: per_instance`. Live Muse Spark calls are therefore **off in code** unless
   either (a) `UPSTASH_REDIS_REST_URL` and `UPSTASH_REDIS_REST_TOKEN` are both set (cap and limits
   are then shared; tested with a mocked client only), or (b) the operator sets
   `MAUDESIGNAL_ALLOW_PER_INSTANCE_CAP=1`. A model key alone returns recorded answers
   (`provenance.kind = recorded_answer`). When the key is set but live mode is not allowed, the
   recorded answer says live calls are switched off on this server (`live_off`); with no key it says
   none is configured (`no_model`). Before enabling live mode, also put a hard spending limit on the
   Meta key itself.
   `MAUDESIGNAL_TRUST_FORWARDED=1`: use the first `X-Forwarded-For` entry as the client address
   for rate limiting. **Set it on Vercel** (its edge sets the header); leave it unset anywhere
   else, where the header is caller-controlled and the socket address is used instead.
   Outside Vercel, also run uvicorn with `--no-proxy-headers` (or `--forwarded-allow-ips` set to
   the real proxy only): by default uvicorn rewrites the client address from `X-Forwarded-For`
   when the peer is `127.0.0.1`, which lets a caller behind a local reverse proxy rotate it.
   With Upstash the per-key limit uses fixed one-minute windows (up to twice the limit can pass
   across a window edge); the in-memory limiter is sliding. The daily cost cap reserves the per-call
   cap in Redis before each model call and releases it afterwards, so concurrent instances cannot
   all pass a read-only check.
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

# Part 2. MCP server, submission answers, privacy, terms

**Submission status: Not submitted.** The owner changes this line only after he submits the form
himself. Nothing here says Meta, Muse or anyone else has reviewed, accepted or endorsed this
connector, and no such review has happened.

## Feedback and visits (private)

Added for outreach. Nothing here is in the public OpenAPI document, and no public route serves a
record. The tool is an advisory triage aid, not medical advice; do not type patient details.

| Route | Auth | What it does |
|---|---|---|
| `POST /v1/feedback` | none; browser origin must be in `MAUDESIGNAL_WEB_ORIGINS` | rating 1-5 ("Does this match real PMS/RA work?"), comment, blocker, one_thing, optional role, consent (`quote_name_role`, `quote_anonymous`, `no_quote`), optional `ref` (see code rule below), page, client_ts. An optional `name` from an old client is accepted and dropped before storage. 201 on success. 5 per hour per address (`MAUDESIGNAL_FEEDBACK_PER_HOUR`), 16 KB body cap (413). Free text that looks like an email, phone, SSN, "MRN" + digits or a date of birth gets 422 and is not stored (a guard, not a guarantee). |
| `POST /v1/visit` | same | `{ref?, page, client_ts}`, 204. 60 per hour per address. |
| `GET /admin` | page holds no data | asks for the admin key (password field, kept in `sessionStorage` only), loads the summary, shows a "By code" section (one block per code: code, label, visits, pages opened, first and last seen, and a feedback table with time, page, rating, comment, blocker, one thing, role and quote consent in plain words), a "Hide TEST codes" checkbox, a "Delete TEST entries" button (asks to confirm), and two CSV downloads. States "No names, emails or IP addresses are stored." |
| `GET /v1/admin/summary` | `X-Admin-Key` | visits and feedback per ref code and per page, average rating per ref, and `codes`: one entry per code, newest activity first, with `code`, `label`, `visits`, `pages_opened`, `first_seen_utc`, `last_seen_utc` and its `feedback` rows (no names). |
| `GET /v1/admin/export?kind=feedback\|visits&format=csv\|json` | `X-Admin-Key` | every record (no name column). CSV cells starting with `=`, `+`, `-` or `@` are prefixed with `'`. |
| `POST /v1/admin/delete-test` | `X-Admin-Key` | deletes every stored visit and feedback entry whose code is `TEST` followed only by numbers or `. _ ~ -` (any case, for example `TEST1`, `test-2`) and returns `{"deleted": {"visits": n, "feedback": n}, "failed": n}`. Nothing else is deleted; `tester7` or `Testa.M` are ordinary codes. An object that fails to delete is counted in `failed` and the rest carry on. Both record stores (memory and Vercel Blob) can delete; Blob uses `POST /delete` with the object url. |

**Code rule.** Personal links look like `https://<web>/?r=CODE`. A code is 1 to 64 characters from
`A-Z a-z 0-9 . _ ~ -` (`^[A-Za-z0-9._~-]{1,64}$`). A code that does not match is not lost: the visit or
feedback is stored with the code `invalid-code` (the bad value itself is never stored). Codes
that are `TEST` plus only numbers or `. _ ~ -` (any case; not `tester7`) are labelled "test" in `/admin`; `email-batch-1` is labelled "email batch 1".

**No names.** No names, emails or IP addresses are stored. Charan keeps the names-to-codes list
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
- *Cost:* one global cap for every live call, **$3.00 per UTC day** (`MAUDESIGNAL_LIVE_DAILY_USD`),
  shared by the website routes (ask, voice, label, mentions) and the keyed `ask` tool. Per-request
  caps: ask 0.25, voice 0.30, label 0.30 (`MAUDESIGNAL_LIVE_ASK_USD`, `_VOICE_USD`, `_LABEL_USD`);
  mentions costs nothing (no model) and
  only checks that the cap is not yet reached. The ledger is, in this order: (1) Upstash
  Redis when configured (atomic, the whole value is enforced); (2) otherwise **one small object
  per request under each UTC day in the private Blob store** (`BLOB_READ_WRITE_TOKEN`), shared by
  every instance and kept across cold starts; (3) only without either, a per-instance memory
  ledger with the cap divided by `MAUDESIGNAL_LIVE_INSTANCE_DIVISOR` (default 2), which resets on a
  cold start and is not a hard cap. **Blob ledger design:** nothing is read, changed and written
  back, so no writer can overwrite another's entry. Each hold, each release and each real cost is
  its own new object (`ledger/live-global/<day>/<kind>-<micro-USD>-<calls>-<uuid>.json`, kind h,
  r or a); today's spend is the sum of the listing (holds + real costs - releases). A request
  reserves before any model call: if the listed total plus its hold is already over the cap it is
  refused without writing; otherwise it writes its hold, lists again, and removes its own hold and
  is refused if the sum is over the cap. Two requests that reserve at the same moment each write
  before they list, so the later listing sees both and at least one is refused (at worst both).
  Settling adds a real-cost object and a release object; the hold is never edited. **It fails
  closed:** if the listing cannot be read, a write fails or an object name cannot be parsed, the
  answer is a recorded one and no model call starts (the keyed `ask` tool reports reason `cap`).
  **Known limit:** this relies on a completed write showing up in the next listing of the store.
  That was tested with a fake store only, not against a real Blob store. If the store ever lagged,
  overlapping requests could pass by at most one request cap; the cap enforced is therefore the
  daily total minus the largest per-request cap (default 3.00 - 0.30 = 2.70), which leaves room
  for one such overlap, so total live spend is still meant to stay at or under $3.00. More than
  one such overlap is not covered and is not measured. A model call that has been paid for but
  whose cost object could not be written is logged as `connector_spend_not_recorded` (USD amount
  and day only) for the operator to reconcile. No call starts once a cap is reached.
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
for the code and terms in free public sources only (GDELT DOC 2.0 for news, FDA press-release,
recall and warning-letter feeds, two public medical-device news feeds), labelled **news and public
web**. The feed URLs were not reachable from the build sandbox, so `sources_tried` reports each
source's real status (`ok`, `failed: ...`) instead of assuming it. Each candidate page is
fetched; a mention is kept only if its quoted sentence is found word for word in the fetched page
text. Dropped, with counts in `dropped`: `quote_not_found` (the source offered a sentence that is
not on the page), `personal_details` (an email, phone, age, a title with a name, "patient
<Name>"), `off_topic` (the page does not mention the terms, or the sentence has a term this
service never uses). Every mention has `badge` "Unverified — not checked against FDA records" and
is never mixed with claim-gated FDA facts; `source_kind` is the fixed value for FDA-hosted pages (listed in
`mentions.py`), otherwise `news` or `web`. At most 10 mentions; the whole search ends in under 50 s. Limits: 10 per address
per UTC day, inside the global cost cap (a read-only check, no hold; refused when the cap is reached or
the ledger cannot be read). When the cap, the limit or the network stops a live search, the stored
file `demo/mentions/<CODE>.json` answers with `mode: "recorded"` and a `recorded_note`; with no
file the lists are empty and the note says so. `.github/workflows/mentions-record.yml` writes
`LLZ.json` (and any codes in the request) when `demo/mentions/REQUEST` changes on `track-c-live`;
the file holds `0`, so nothing runs yet and **no stored mentions file exists yet**.

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

Same five tools as the REST routes, same process, same code path. Each REST route and each
`tools/call` goes through one `dispatch` function in `connector/app.py`, so the answer, the audit
entry and the cost cap are shared.

| Item | Value |
|---|---|
| Endpoint | `https://<your-api-project>.vercel.app/mcp` (HTTPS on Vercel; the host is whatever the API project gets) |
| Transport | Streamable HTTP, **stateless**: one JSON-RPC message per `POST`, a JSON reply, no session id, no event stream. `GET`, `DELETE`, `PUT`, `PATCH` on `/mcp` return 405. |
| Protocol version | `2025-06-18` (header `MCP-Protocol-Version` may be `2025-06-18` or `2025-03-26`; anything else is 400) |
| Methods | `initialize`, `ping`, `tools/list`, `tools/call`; notifications and client replies get 202 with no body. Batches are refused (protocol 2025-06-18 removed them). |
| Auth | `X-API-Key: <key>` **or** `Authorization: Bearer <key>` (the Bearer form also works on the REST routes). A key in the URL is refused (400). Wrong or missing key: 401; repeated wrong keys from one address: 429. |
| Limits | The same per-key rate limit as REST (every HTTP request to `/mcp` counts once, also `tools/list`), the same per-key daily cost cap for `ask`, the same audit log (`GET /v1/audit/recent`). |
| Browsers | A request that carries an `Origin` header is refused (403) unless the origin is listed in `MAUDESIGNAL_WEB_ORIGINS` (the MCP DNS-rebinding guard). Server-side clients send no `Origin`. |
| Tool annotations | `readOnlyHint: true`, `destructiveHint: false`, `idempotentHint: true` on all five; `openWorldHint: true` on `what_changed_this_week`, `check_device_type` and `ask` (they can reach live openFDA or the live model), `false` on `get_report` and `recalls`. |
| Result | `content`: one text item, the speakable summary. `structuredContent`: the full answer (`tool`, `speakable`, `facts` with links, `advisory`, `provenance`, `withheld`), identical to the REST body of the same call (a test compares them for all five). `outputSchema` is the answer model. |
| Errors | Unknown tool or malformed call: JSON-RPC error `-32602`; unknown method `-32601`; bad JSON `-32700` (HTTP 400). A tool that cannot answer (invalid input, report not stored, openFDA unreachable) returns `isError: true` with a fixed, key-free message. |
| Manifest | `api/mcp-manifest.json`, also served at `GET /mcp-manifest.json` without a key. Generated by `python3.12 -m maudesignal.connector.manifest` from the same tool registry (`connector/registry.py`) that builds `tools/list` and supplies the REST descriptions; a test fails if the file drifts or if REST and MCP descriptions differ. |

Why not the `mcp` Python SDK: this server only needs request/response, and a serverless
function cannot hold the sessions and streams the SDK's default server keeps. The hand-written
version is about 130 lines (`connector/mcp_server.py`), has no extra dependency, and is covered by
`tests/unit/test_connector_mcp.py` (19 tests). It was also checked with the `mcp` Python SDK client
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
  recalls: readOnlyHint=True destructiveHint=False openWorldHint=False inputs=['product_code']

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

## 2.2 to 2.4 Form answers, privacy and terms

Moved to the top of this page ("Form answers" and "Data questionnaire") so there is one source.
The pages are served at `/privacy` and `/terms`.

## 2.5 What the owner must still do (nothing below has been done)

* Deploy the API project and note its URL; create a read-only reviewer key with the key script.
* Set `MAUDESIGNAL_CONTACT_EMAIL` (the pages show it at runtime) and, optionally,
  `MAUDESIGNAL_DEMO_KEYS` and `MAUDESIGNAL_PUBLIC_URL`.
* Read the live submission form, correct every field marked "confirm against the live form", and
  submit it himself.
* Only then change the status line at the top of part 2 from "Not submitted".
