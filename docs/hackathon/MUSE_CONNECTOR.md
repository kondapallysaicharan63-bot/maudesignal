# MaudeSignal connector for Meta Muse (read-only REST API; MCP server next)

Status: **built and tested locally; not deployed from this environment; not submitted.** This is
part 1 of the connector doc: the REST API, how to deploy it, how to make a key, and how to check
it. The MCP transport, the submission form answers and any "submitted" line come in later parts,
and only after the owner submits. Nothing on this page says anyone has reviewed or endorsed the
connector.

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
| `MAUDESIGNAL_API_KEYS` | the key | Made by the script in step 3; never typed into git or chat. Comma-separated for several keys. |
| `MAUDESIGNAL_TRUST_FORWARDED` | `1` | Vercel's edge sets `X-Forwarded-For`; without this the limiter would see one address. |
| `MAUDESIGNAL_KEY_PEPPER` | a long random string | Server-side secret for key ids in ledger file names and audit session ids. |
| `MAUDESIGNAL_WEB_ORIGINS` | e.g. `https://<web-project>.vercel.app` | Comma-separated exact origins that may call the keyless route from a browser. No wildcard (a `*` entry is ignored). Empty means no browser origin is allowed. |
| `MAUDESIGNAL_RATE_LIMIT_PER_MIN` | default `30` | Requests per key per minute. |
| `MAUDESIGNAL_FAILED_AUTH_PER_MIN` | default `10` | Wrong or missing keys per address per minute before 429. |
| `MAUDESIGNAL_PUBLIC_CHECK_PER_HOUR` | default `10` | Keyless checks per address per hour. |
| `MAUDESIGNAL_API_DAILY_USD` / `MAUDESIGNAL_API_REQUEST_USD` | defaults `2.00` / `0.25` | Cost cap of `ask` per key per UTC day, and per call. |
| `OPENFDA_API_KEY` | optional | Used only on the server for live openFDA checks (higher quota). Never in a response. |
| `UPSTASH_REDIS_REST_URL`, `UPSTASH_REDIS_REST_TOKEN` | optional | Add an Upstash Redis database (Vercel Marketplace, or upstash.com) and copy its REST URL and token. When both are set, the rate limits, the daily cost ledger, the six-hour cache and the audit log are shared by every instance. If the integration names them differently, add these two names by hand. |
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

Option a replaces the previous value of `MAUDESIGNAL_API_KEYS` (older keys stop working); to keep
several keys, edit the comma-separated list in the dashboard. Option b: paste the file's one line
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
  User-Agent. Per-address limit (default 10 per hour, `MAUDESIGNAL_PUBLIC_CHECK_PER_HOUR`), a
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

Five read-only tools (REST now, MCP in a later milestone, same code):
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
5. **MCP is not built yet.** Only the REST transport exists; do not describe the connector as
   an MCP server until `tools/list` and `tools/call` are implemented and tested.
6. Live openFDA calls (`check_device_type`, unstored codes, the keyless route) and the live Muse
   Spark call have not been run from this environment (no network); tests use fakes.
