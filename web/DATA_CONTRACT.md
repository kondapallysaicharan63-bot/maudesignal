# Web data contract (v1.0)

Owner: coordinator. Track A makes sure the **inputs** are complete and valid;
Track B owns `scripts/export_web_data.py`, which reads them and writes the
**outputs** to `web/public/data/`. The web app reads only these outputs (stored
first, no key). Change this file only through the coordinator.

## Rules for every output

- `schema_version: "1.0"` at the top of every JSON file.
- Copy numbers from the inputs; never recompute them differently or invent one.
  Where the exporter derives a number (counts below), the rule is written here.
- Never include an API key, a lot or serial number (`session_fields_omitted` stays
  omitted), or anything that looks like PHI.
- Paths in outputs are relative to `web/public/data/`.
- Missing input → the field is `null` and the file's `notes[]` says why. Never fake.

## Inputs (repo paths)

| Input | Path |
|---|---|
| Demo database | `data/demo/maudesignal_demo.db` |
| What-changed digests | `digests/YYYY-MM-DD.json` (+ `.md`) |
| Copilot transcripts | `demo/transcripts/<ts>-<label>.json` |
| Audit exports | `demo/transcripts/audit-<run_label>.json` |
| Evidence pack | `demo/dossier/<doc_id>-{draft,approved}.pdf`, `-narrative.json`, `-review.json` |
| Vision runs | `demo/vision/510k-*.json`, `demo/vision/label-*.json`, `demo/vision/label-match-*.json`, images `demo/vision/labels/*.jpg` |
| AI device sweep | `demo/sweep/ai-device-sweep.json` |
| Report-source counts | `docs/hackathon/SOURCE_COUNTS.md` |

## Outputs (`web/public/data/`)

### `manifest.json`
```json
{"schema_version": "1.0", "generated_utc": "...", "source_commit": "<git sha>",
 "files": ["threads.json", "investigations.json", "protocol.json", "..."],
 "header": {"claims_verified": 0, "sentences_verified": 0, "sentences_withheld": 0,
            "answers": 0, "audit_chain_ok": true},
 "notes": []}
```
Header counts are over the **final** sentences of every transcript in `threads.json`:
`claims_verified` = claims with `status == "pass"`; `sentences_verified` /
`sentences_withheld` = sentences with `status == "pass"` / `"block"`.
`audit_chain_ok` = every run in `audit.json` has `chain_ok == true`. The UI strip
reads: "Every sentence checked against FDA data · {claims_verified} claims verified ·
{sentences_withheld} withheld".

### `threads.json`
```json
{"schema_version": "1.0",
 "workflows": [{"id": "overnight-signals", "title": "What changed this week", "thread_ids": ["01-what-changed"]}],
 "threads": [{
   "id": "06-trap", "workflow": "ask-copilot", "question": "...",
   "voice": {"transcript_text": "...", "language": "English", "audio_seconds": 5.36} ,
   "recorded_at_utc": "...", "model": "muse-spark-1.3",
   "tool_steps": [{"name": "weekly_signals", "arguments": {}, "summary": "searched 137 reports"}],
   "sentences": [{"text": "...", "status": "pass|block", "reasons": [],
                  "claims": [{"kind": "count", "status": "pass", "reason": "recomputed 33", "evidence_ids": ["50426770"]}]}],
   "first_pass": {"passed": 3, "blocked": 1, "sentences": [...]},
   "repaired": true,
   "usage": {"input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0}
 }]}
```
- `id` = transcript `label`; `voice` is `null` for typed questions.
- `name` uses the display names in `dashboard/copilot_pages.py` `_TOOL_LABELS`
  (e.g. `overnight_signals` → `weekly_signals`).
- `summary` is built only from numbers present in `result_preview`; if none, it is
  the tool name in words ("checked recalls"). Never an invented count.
- Workflow ids: `overnight-signals` (labels 01, 02, 13, 15, 20, 22), `ask-copilot`
  (all other typed labels and every `00-voice-*`), `capa-need-evidence` (05).
  Voice clips 00-voice-a and 00-voice-b (greetings, not product questions) are listed
  under `ask-copilot` after the product questions.

### `evidence.json`
Every report id referenced by any claim in `threads.json`:
```json
{"schema_version": "1.0", "reports": {"50426770": {"product_code": "LLZ",
  "date_received": "20260825", "event_type": "Malfunction", "report_source": "manufacturer",
  "brand": "...", "excerpt": "first 400 chars of the stored narrative",
  "maude_url": "<same URL the Streamlit app builds>"}}}
```
Ids that are not report keys (510(k), recall, PMID, CFR) go under
`"other": {"<id>": {"kind": "...", "label": "...", "url": "..."}}` from the stored rows.

### `briefs.json`
One entry per `digests/*.json`, newest first: `{"date", "headline", "counts",
"window", "signals", "device_types", "ranking", "window_sources", "footer"}`, copied as is.

### `audit.json`
`{"runs": [{"run_label", "chain_ok", "first_bad_seq", "entries": [{"seq", "ts",
"actor", "action", "entity_id", "payload", "prev_hash", "entry_hash"}]}]}`;
`payload` is `payload_json` parsed. `chain_ok` is **re-verified by the exporter**
with `maudesignal.copilot.audit_export.verify_entries`, not copied.

### `dossier.json`
`{"doc_id", "pdf": {"draft": "dossier/<doc_id>-draft.pdf", "approved": "dossier/<doc_id>-approved.pdf"},
"narrative": <narrative json>, "review": {"model", "findings", "parse_error"}}`;
PDFs are copied to `web/public/data/dossier/`.

### `vision.json`
`{"k510": [<510k-*.json as stored>], "labels": [<label-*.json as stored, image copied
to vision/<file>.jpg, "image": "vision/<file>.jpg">]}`. SAM boxes come from each
label's `sam` field. Each label also carries `"matches": <label-match-<stem>.json as stored,
"confirmed" forced to null> | null` (null when no matching run was stored). Steps that ran several
queries store `count: null` and a `queries[]` list (`count` or `groups_sum` per query).
Current `vision.json` was built from the label-match files of `origin/hackathon-day2` commit
3205dd7 (the 02:52Z rerun); those files are not on `track-b-next2` itself.

### `sweep.json`
`demo/sweep/ai-device-sweep.json` as stored (meta, rows, errors).

### `investigations.json`
Agentic workflow runs recorded by Track A (`demo/investigations/*.json`): weekly
investigator and recall-triggered sweep. Each entry: `{"id", "kind":
"weekly-investigator"|"recall-sweep", "product_code", "trigger", "recorded_at_utc",
"model", "tool_steps"[], "sentences"[] (same shape as threads), "groups"[{"label",
"report_ids"[], "count"}], "protocol" (see below)}`. Empty list with a note until the
first recorded run exists. Never synthesized by the exporter.

### `protocol.json`
The search protocol behind each recorded answer or investigation (workflow 3 of the
plan): `{"<thread or investigation id>": [{"tool", "dataset", "filters", "date_from",
"date_to", "count", "run_at"}]}`, built from stored tool calls only.

### `sources.json`
`[{"id": "maude", "label": "openFDA MAUDE", "records": <count in demo DB>, "last_refresh": "<max date_received>"},
  {"id": "recalls"...}, {"id": "510k"...}, {"id": "pubmed"...}, {"id": "mhra", "label": "MHRA (UK)", ...}]`
counted from the demo database tables. MHRA is labelled "MHRA (UK)", context only.

### `schedules.json`
`[{"id": "daily-monitor", "label": "Daily monitor", "cron": "17 11 * * *",
"workflow": ".github/workflows/monitor.yml", "last_result": {"date": "<newest digest date>", "headline": "..."}},
{"id": "ai-sweep", "label": "AI device sweep", "cron": "23 12 * * 1", "last_result": {"date": "<sweep generated_utc>", "flagged": 6, "checked": 181}}]`
Read from the workflow files and the newest outputs; no GitHub API call.

### `alerts.json`

Built by `scripts/export_alerts.py` (also run by `export_web_data.py`) from stored files only: `demo/sweep/ai-device-sweep.json`,
`digests/*.json`, `data/demo/maudesignal_demo.db`, `demo/company/` (devices, owners, fetched evidence). `{schema_version, generated_utc,
banner, alerts: [Alert], notes}`. One `Alert` per flagged sweep row (`sweep:<CODE>`), per flagged digest signal (`brief:<DATE>:<CODE>`) and
per simulated device marked Needs review (`company:<DEVICE-ID>`); these ids are the bell / dashboard / Signals list / Our devices ids.

```json
{"id": "sweep:IYN", "product_code": "IYN", "device_type": "name or null",
 "rule": "reports suddenly increased | more serious than usual | new kind of problem | null (a Needs review device with no weekly rule)",
 "rule_words": "the rule in plain words (thresholds read from the detector's constants)",
 "source": {"kind": "sweep|brief|company", "label": "...", "as_of": "YYYY-MM-DD"},
 "window": {"this_week": {"from","to","count"}, "baseline_4wk": {"from","to","count","weekly_mean"}},
 "numbers": [{"label", "value", "openfda_url"}],
 "reports": [{"report_id","date_received","event_type","quote","quote_note","openfda_url","maude_url"}],
 "reports_total": 21, "reports_stored": 21,
 "recalls": [{"id","date","reason","reason_truncated","url"}], "recalls_total": 100,
 "k510": [{"k_number","applicant","decision_date","url"}], "k510_total": 1,
 "who_filed": {"manufacturer": 21, "user_facility": 0, "other": 0},
 "next_steps": ["plain-language suggestions; the last always says a person decides"],
 "owner": {"name": "... (simulated)", "status": "Needs review", "device_id", "device_name"},
 "gate": {"checked": 9, "passed": 9, "withheld": 0}, "notes": []}
```
- Counts come from the stored sweep / digest file and are checked against the stored rows by the claim gate (`CountClaim`) whenever the
  stored rows hold the whole window (the digest's own database; a complete fetched evidence file). A count the rows do not support is held
  back (`gate.withheld`) and named in `notes`; `reports_total` is the file's count and `reports_stored` the rows kept here ("showing N of M").
- Reports: this week's stored rows (injury and death first for "more serious than usual", then newest), at most 10, each with one sentence
  of 40 to 220 characters copied word for word from the narrative and passed by the gate (`QuoteClaim`). A sentence with a person's details
  (title + name, "patient <Name>", age, email, phone) is skipped, and so is the fragment after "Dr."; a report with no usable sentence has
  `quote: null` and a `quote_note`. Recalls and 510(k) records are the latest 5 stored for the code; a recall excerpt and each 510(k)
  record pass the gate or are held back. `gate` counts exactly the claims put to the gate. A code with nothing stored has empty lists
  and a note; nothing is estimated.
- `owner` is set only when the code is one of the simulated company's devices; the page then prints the banner "Simulated company — sample
  data. Problem evidence is real FDA data." over it.

### `mentions.json`

`{schema_version, codes: {<CODE>: MentionsResult}, notes}`: the stored outside-source searches, copied from `demo/mentions/<CODE>.json`
(same shape as the live answer below, `mode: "recorded"`). When that folder is absent (it is not on this branch) `codes` is `{}` and the
page says "No stored search yet"; nothing is invented.

## Feedback and visit pings

`/v1/visit` fires once per view per session whenever an API base is configured. The body is
`{ref?, page, client_ts}`. `?r=CODE` (`^[A-Za-z0-9._~-]{1,64}$`, same as the API) is read once and kept
in sessionStorage for the session: a later view without `?r=` keeps it, and a new `?r=` replaces it. A
`?r=` value that fails the pattern (or is empty) is sent as `ref: "invalid-code"` and kept the same
way. With no `?r=` at all, `ref` is left out and the server labels the visit "email-batch-1".

`/v1/feedback` sends `{rating, comment, blocker, one_thing, role, consent, ref, page, client_ts}`.
There is no name field. `consent` is `quote_name_role` ("Quote me by name and role (we'll confirm with
you first)"), `quote_anonymous` or `no_quote`. No name, email, IP, user agent or other visitor data
is sent (fetch keepalive, credentials omit). The ref code is removed from the URL before it is sent to
Web Analytics (`beforeSend` in `main.tsx`, `stripRef` in `analytics.ts`).

## Live API (chat, voice, camera)

Used only when the site is built with `VITE_MAUDESIGNAL_API_BASE` set. Without it nothing below is called and
every screen shows the stored runs, labelled "Recorded run". The page never stores a question, an answer, audio
or a photo (memory only; a reload starts clean) and sends no cookies or credentials (`credentials: "omit"`).
CORS on the server: only the origins in `MAUDESIGNAL_WEB_ORIGINS`, no credentials. Code: `src/live/`.

| Call | Body |
|---|---|
| `POST /v1/live/ask` | JSON `{question: str 3..500, history?: [{question, answer}] (last 4; the page cuts each answer to 600 chars, the server does too), product_code?, ref?}` |
| `POST /v1/live/voice` | multipart: part `audio` = WAV PCM16 mono 16000 Hz, at most 60 s and 4 MB (made in the browser: `MediaRecorder` -> `AudioContext.decodeAudioData` -> mono -> 16 kHz -> WAV, `src/live/audio.ts`); optional part `meta` = JSON `{history?, product_code?}` |
| `POST /v1/live/label` | multipart: part `image` = JPEG or PNG, at most 4 MB (Vercel refuses larger bodies before the app runs, with no CORS headers). The page draws every photo, camera or upload, on a canvas with the long side at most 1600 px and sends a fresh JPEG at quality 0.85 (no EXIF), retrying at 0.7 then 0.55 if the result is over 4 MB and showing a message if it is still too big; the original file bytes are never sent. The server re-encodes it again and never stores it |

All three answer with:
```json
{"mode": "live|recorded", "recorded_note": "why + which recorded run (shown when mode is recorded)",
 "not_medical_advice": true,
 "trace": [{"step": "...", "model": "muse-spark-1.3|muse-voice-transcribe-1.0|sam-3.1|null", "ms": 812, "status": "ok|skipped|failed", "note": "..."}],
 "cost_usd": null, "limits": {"remaining_today": 9, "resets_utc": "2026-11-01T00:00:00Z"}}
```
- ask / voice add `heard` (voice only; always shown before the answer) and
  `answer: {speakable: [{text, links: [{label, url}]}], withheld: [{reason}], spoken_text}`. Only `speakable`
  sentences are shown, with their links under them. `withheld` is shown only as "N sentences held back: <reasons>"
  (the held text is never sent or shown). `spoken_text` is the only text read aloud (`speechSynthesis`).
- label adds `reading: {legibility, fields: {device_name, manufacturer, model, k_number, udi, gtin} (each {value, legibility}, value "" when not read),
  values_withheld?: ["lot", "serial"] (those two are never returned; the page says so)}` and `matches: {status: needs_person_to_confirm|no_match_found, candidates: [up to 3 {k_number,
  device_name, applicant, product_code, why_matched[], why_not_matched[], links[]}], search_failed?: true, note?}` and `confirmed: null`.
  When `search_failed` is true (or a `note` is present) and there are no candidates, openFDA could not be searched: the
  page shows the note and a retry hint instead of "No match found" and no candidate list. `no_match_found` without it
  means a search ran and found nothing.
  A value the server lists in `values_withheld` is shown as "value withheld"; an unreadable or empty field (illegible, `""`, null) is shown as "not read". Neither is ever filled in. An empty `legibility` is shown as "unknown". No candidate is chosen for the person;
  "Confirm this match" and "None of these" act only in the page.
- Errors: `422 {code: "patient_data"|"invalid_input", message}` (the message is shown as is, cut to 400 chars),
  `429 {code: "rate_limited", message, retry_after_s}`, `413` too large, anything else is a generic "service error".

What the page does on each outcome:

| Outcome | Page |
|---|---|
| 200 `mode: "live"` | "Live answer" badge, trace steps with model and ms, sentences word by word (instant with `prefers-reduced-motion`), links, held-back line, "Not medical advice" under every answer, live questions left today |
| 200 `mode: "recorded"` | "Recorded run" badge + `recorded_note` |
| 429 | "Daily live limit reached - showing recorded runs"; the answer is the closest stored run (same shape, labelled, its note names the run); later questions make no request. A spoken question or photo shows the message and the recorded voice / label runs |
| 422 `patient_data` / `invalid_input` | the server's message, no answer |
| network error, timeout (70 s; 60 s for a photo), 5xx, unreadable answer | the closest stored run, labelled "Recorded run", note says why |
| microphone / camera permission denied or none present | a plain message, and the recorded voice / label runs |

The stub used by the browser tests is `qa/live_stub.py`; it implements this contract, checks the WAV header and the
JPEG (no EXIF) and logs request bodies at `GET /__log`. Run `python3 qa/e2e_live.py` from `web/`.

### Outside mentions: `POST /v1/live/mentions`

JSON `{product_code: 3 letters, device_terms?: [str] (at most 5, each at most 60 characters)}`. No key, no cookies. Per-IP 10 a day, inside the
global live cost cap even when no model is used; 429 shows the stored search. Answer:
```json
{"product_code": "LLZ", "searched_utc": "...",
 "sources_tried": [{"name", "url", "status", "n"}],
 "mentions": [{"source_name", "source_kind": "official|news|web", "date", "url", "quote": "exact sentence found on the fetched page",
               "why_matched": "one deterministic line: which terms matched", "badge": "Unverified — not checked against FDA records"}],
 "dropped": {"quote_not_found": 0, "personal_details": 0, "off_topic": 0},
 "trace": [], "limits": {}, "mode": "live|recorded", "recorded_note": "..."}
```
Free sources only (GDELT DOC 2.0, FDA press-release and recall feeds, other public RSS; nothing behind a login). The server keeps a mention
only when its quoted sentence is found verbatim in the fetched page text and drops any sentence with a person's details; at most 10. The
page does not trust that further than it can see: it prints its own fixed badge text (the server's `badge` is ignored), shows "Official
source" only for an `https` fda.gov address (whatever `source_kind` says), drops and counts a quote that holds a person's details
(`dropped.personal_details`), ignores a non-`https` link, and keeps the box apart from the checked FDA facts ("News and public web
(unverified)", dashed border). Line under the title: "N found, N dropped because the quote was not on the page, N dropped for
personal details". Stored search first; on 429, an error or no API address the stored search is shown, or "No stored search yet".

### Connect: `GET /v1/connect`

The real API body: `{mcp_url, openapi_url, docs_url, auth_header: "X-API-Key", demo_key: str|null, demo_limits: {per_minute, per_day, live_model, note}, steps}`.
The page reads `demo_limits` (and says "No live Spark answers" unless `live_model` is true, with the per-minute and per-day numbers as sent). The
older names (`key_header`, `privacy_url`, `terms_url`, `limits: {read_only, live_spark, note}`) are still accepted as a fallback; without
`privacy_url` and `terms_url` the page uses `/privacy` and `/terms` on the MCP address's origin. The
"Connect to Muse" page shows these with a one-click Copy for the key. Any failure, or no API address, shows the fixed text: MCP URL
`https://maudesignal-api.vercel.app/mcp`, OpenAPI URL `https://maudesignal-api.vercel.app/openapi.json`, "Ask Charan for a key", and links
to `/privacy` and `/terms` on the API. Three steps: open Muse connectors, add the MCP URL, paste the key in the `X-API-Key` header. No OAuth.

## Tests

- Alerts, mentions, connect (`web/`): `src/alertsMentions.test.ts` (helpers, validation, the POST, fallback), `src/alertPanel.test.tsx` (DOM: panel, mentions box,
  Connect page), `python3 qa/shoot_p.py` (Playwright against `vite preview` and the stub: every way into the panel, Esc, focus trap and return,
  Open in chat live and recorded, mentions, Connect, header at 390 and 1440, light and dark, screenshots `qa/screenshots/P-*.png`).
  `tests/unit/test_export_alerts.py` runs the exporter on a fixture repository and on the real stored data.

- Live (`web/`): `npm test` (WAV encoder, resampler, payload builders, error mapping, history trimming, label rows,
  recorded fallback; DOM tests with a mocked fetch for live / recorded / 429 / 422 / voice / keyboard) and
  `python3 qa/e2e_live.py` (Playwright, Chromium with fake camera and microphone, against `vite preview` and the stub).
- Track B: `tests/unit/test_export_web_data.py` runs the exporter into a temp dir and
  checks every file exists, has `schema_version`, and that the header counts equal a
  direct count over the transcripts.
- Track A: `tests/unit/test_data_contract.py` checks the inputs: every transcript
  parses, every claim's evidence id exists in the demo DB, every audit export
  re-verifies, every vision label has no `lot`/`serial` value.
