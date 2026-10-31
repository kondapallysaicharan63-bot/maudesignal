# MaudeSignal connector for Meta Muse (read-only REST API and MCP server)

This page is the single source for every answer on the Meta connector form (the first part,
"Form answers"), followed by how the API is deployed and what it does. Nothing on this page says
Meta, Muse or anyone else has reviewed or endorsed the connector.

# Form answers

**Status: Submitted to Meta's Muse Connector Program — pending review.** Submitted Oct 31, 2026; business verification, data questionnaire and technical details complete; Meta shows "In review".

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

## Example prompts

1. What changed this week for LLZ?
2. Check product code QAS on openFDA.
3. Show recalls for LLZ.
4. Get report 50426770.
5. Ask: what changed this week for LLZ? (with live ask off this returns the closest recorded answer)
6. I photographed this label: Welch Allyn 802 LTR, which FDA records match? (Muse reads the photo itself, then calls `lookup_device`; the answer lists possible matches and says a person confirms.)

## Rate limits and cost caps

Defaults in the code (each can be changed by the operator with an environment variable):

* 30 requests per key per minute (`MAUDESIGNAL_RATE_LIMIT_PER_MIN`); every HTTP request to `/mcp`
  counts once.
* 10 wrong or missing keys per address per minute, then 429 (`MAUDESIGNAL_FAILED_AUTH_PER_MIN`).
* 10 keyless device-type checks per address per hour (`MAUDESIGNAL_PUBLIC_CHECK_PER_HOUR`).
* `ask`: at most $0.25 per call, $2.00 per key per UTC day and $3.00 over all keys together per
  UTC day (`MAUDESIGNAL_API_REQUEST_USD`, `MAUDESIGNAL_API_DAILY_USD`,
  `MAUDESIGNAL_API_TOTAL_DAILY_USD`); past a cap the closest recorded answer is returned. With two
  keys, set `MAUDESIGNAL_API_DAILY_USD=1.50` (or less) as well, and keep `MAUDESIGNAL_KEY_PEPPER`
  set (see "Two keys").
* Feedback form: 5 per hour per address; visits 60 per hour per address.

The live pages `/terms` and `/privacy` show the numbers actually in force.

## Data handling summary

Public openFDA data only (and MHRA (UK) alerts, labelled). No personal or patient data is collected
or wanted. Hosted on Vercel, United States (function region iad1). Question text is not logged
(only its SHA-256 and length). IP addresses are never stored by this code: before any rate limit
sees one it is turned into a salted one-way hash, and only that hash is the limit key (in memory,
or in the operator's Redis store for at most twice the limit window). Feedback records (no email addresses; no names except where the person chose to be quoted by name and role, see the Data questionnaire) and visit records are kept until 2026-12-31.
Meta receives an `ask` question only when live ask is on. Details: `/privacy`.

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
| Where is data processed and stored? | Vercel, United States (function region iad1, Washington DC). Vercel Blob (private) holds only website feedback and visit records. |
| Subprocessors? | Vercel Inc. (hosting, logs, Blob). Meta Platforms (Meta Model API) only when `ask` runs live with a server-side model key. Upstash (Redis) and Resend (email) only if the operator configures them. |
| Does Meta receive user input? | Only the text of an `ask` question, only when live ask is on. When off, `ask` returns recorded answers and nothing is sent to Meta. `/privacy` states which applies at request time. |
| Which public sources are queried? | openFDA (api.fda.gov) is queried live with a product code only. MHRA (UK) alerts come from a stored copy previously fetched from the GOV.UK search API; this service does not call GOV.UK when you use it. |
| What is logged? | Key id (a peppered one-way hash, never the key), tool name, time, status. If the key has a label (for example a reviewer's name) the label is logged next to the key id. Calls made with the public demo key are logged the same way, with the label `demo`. Spend on `ask` is kept as a daily total per key id (not per call). Question text is not logged; during a live `ask` it is held briefly in the server instance's temporary working database and replaced by its SHA-256 when the answer is done. |
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
3. A cap over all keys together applies on top: `MAUDESIGNAL_API_TOTAL_DAILY_USD`, default `3.00`
   per UTC day, however many keys exist. `/terms` shows it. When either cap is reached, `ask`
   returns a recorded answer. Live `ask` is also still off unless `META_MODEL_API_KEY` is set and a
   shared store (or the per-instance override) is configured.

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
| `MAUDESIGNAL_API_TOTAL_DAILY_USD` | default `3.00` | Cost cap of `ask` over all keys together per UTC day (a ledger shared by every key). |
| `OPENFDA_API_KEY` | optional | Used only on the server for live openFDA checks (higher quota). Never in a response. |
| `UPSTASH_REDIS_REST_URL`, `UPSTASH_REDIS_REST_TOKEN` | optional | Add an Upstash Redis database (Vercel Marketplace, or upstash.com) and copy its REST URL and token. When both are set, the rate limits, the daily cost ledger, the six-hour cache and the audit log are shared by every instance. If the integration names them differently, add these two names by hand. |
| `META_MODEL_API_KEY` | optional | Leave **unset** until you accept the cost: `ask` then answers from recorded runs. |
| `MAUDESIGNAL_ALLOW_PER_INSTANCE_CAP` | `1` only if you set the model key without Upstash | Explicit acceptance that the cap and limits are per instance. Not needed with Upstash. |

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

## 2.1 The MCP server (`POST /mcp`)

Same six tools as the REST routes, same process, same code path. Each REST route and each
`tools/call` goes through one `dispatch` function in `connector/app.py`, so the answer, the audit
entry and the cost cap are shared.

| Item | Value |
|---|---|
| Endpoint | `https://maudesignal-api.vercel.app/mcp` |
| Transport | Streamable HTTP, **stateless**: one JSON-RPC message per `POST`, a JSON reply, no session id, no event stream. `GET`, `DELETE`, `PUT`, `PATCH` on `/mcp` return 405. |
| Protocol version | `2025-06-18` (header `MCP-Protocol-Version` may be `2025-06-18` or `2025-03-26`; anything else is 400) |
| Methods | `initialize`, `ping`, `tools/list`, `tools/call`; notifications and client replies get 202 with no body. Batches are refused (protocol 2025-06-18 removed them). |
| Auth | `X-API-Key: <key>` **or** `Authorization: Bearer <key>` (the Bearer form also works on the REST routes). A key in the URL is refused (400). Wrong or missing key: 401; repeated wrong keys from one address: 429. |
| Limits | The same per-key rate limit as REST (every HTTP request to `/mcp` counts once, also `tools/list`), the same per-key daily cost cap for `ask`, the same audit log (`GET /v1/audit/recent`). |
| Browsers | A request that carries an `Origin` header is refused (403) unless the origin is listed in `MAUDESIGNAL_WEB_ORIGINS` (the MCP DNS-rebinding guard). Server-side clients send no `Origin`. |
| Tool annotations | `readOnlyHint: true`, `destructiveHint: false`, `idempotentHint: true` on all six; `openWorldHint: true` on `what_changed_this_week`, `check_device_type`, `ask` and `lookup_device` (they can reach live openFDA or the live model), `false` on `get_report` and `recalls`. |
| Result | `content`: one text item, the speakable summary. `structuredContent`: the full answer (`tool`, `speakable`, `facts` with links, `advisory`, `provenance`, `withheld`), identical to the REST body of the same call (a test compares them for all six). `outputSchema` is the answer model; `lookup_device` has its own, which adds `status`, `confirmed`, `note`, `searched_with`, `matches` and `device_types`. |
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

## 2.2 Privacy, terms and what is still open

The privacy and terms texts are served by the API itself at `/privacy` and `/terms`
(`connector/legal_pages.py`); the form answers above repeat them. Still open, and done by Charan:
set `MAUDESIGNAL_CONTACT_EMAIL` in Vercel, add the two keys, redeploy, read the live form and
correct any field that differs, submit it himself, then change the status line at the top.
