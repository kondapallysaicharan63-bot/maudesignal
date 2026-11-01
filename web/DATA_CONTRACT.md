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

Answer ratings (`?layout=v2` only) use the same `/v1/feedback` route with
`{kind: "answer_rating", answer_id (random, made in the browser, ^[A-Za-z0-9_-]{8,64}$), rating: 1|5,
comment (optional reason, ≤300 chars), consent: "no_quote", ref, page: "live-answer", client_ts}`. No question
or answer text is sent; unknown fields are refused (422). One rating per answer_id per hashed IP per 24 h
(a second gets 409 `already_rated`); ratings have their own limit (`MAUDESIGNAL_ANSWER_RATING_PER_HOUR`,
default 60/hour) separate from the survey's 5/hour. Ratings are not emailed and are kept out of the survey
average; admin shows them as up/down counts (latest per answer). Chat ids are removed from Web Analytics URLs.

## Live API (chat, voice, camera)

Used only when the site is built with `VITE_MAUDESIGNAL_API_BASE` set. Without it nothing below is called and
every screen shows the stored runs, labelled "Recorded run". The server never stores a question, an answer,
audio or a photo. Classic keeps them in memory only (a reload starts clean); `?layout=v2` saves chats in this
browser's localStorage only ("Saved on this device only"; photos are not kept), never on our server and sends no cookies or credentials (`credentials: "omit"`).
CORS on the server: only the origins in `MAUDESIGNAL_WEB_ORIGINS`, no credentials. Code: `src/live/`.

| Call | Body |
|---|---|
| `POST /v1/live/ask` | JSON `{question: str 2..500, history?: [{question, answer}] (last 4; the page cuts each answer to 600 chars, the server does too), product_code?, ref?}` |
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

**Chat tiers (Oct 31, `track-chat-tiers`; docs/hackathon/CHAT_TIERS.md).** `POST /v1/live/ask` also returns
`tier: "canned"|"direct"|"cache"|"live"` and, for tiers 1 to 3, `badge` (shown in place of the mode badge),
`cost_usd: 0`, `suggestions: [str]` (up to 4 chips; a chip is sent only when clicked), and optionally
`did_you_mean: ["LLZ"]` (never applied), `open: {view: "check-device"|"our-devices"|"ai-sweep"|"alerts", code?}`
(a button that opens that page; `alerts` has no button) and `answered_at` (cache: when Muse Spark first answered).
`mode` is `"canned"` or `"direct"` for tiers 1 and 2 and the stored `"live"` for a cache hit. Tiers 1 to 3 do not
use a daily live question (`limits.remaining_today` is unchanged). A response without `tier` (an older server) is
drawn as before. The cost line reads "Cost of this answer: $0.0000 (no model call)" for tiers 1 to 3.

**Message box with the "+" menu (Oct 31, `track-a-composer`).** Switch: build-time `VITE_FEATURE_COMPOSER_MENU`
(default on; `0`/`false`/`off`/`no` turns it off) and run-time `?composer=classic`; off, the earlier composer
renders unchanged. Code: `src/components/MessageBox.tsx`, `PlusMenu.tsx`, `VoiceBar.tsx`, `CameraSheet.tsx`.

- `GET /v1/health` now has `features: {name: true}` and answers the web origins with CORS. The page reads it once;
  a name that is absent (or not exactly `true`) means the feature is not offered. Known names:
  `voice_transcribe_only` (this track) and `research` (built by another track).
- `POST /v1/live/voice` with `meta = {"transcribe_only": true}` returns only the words:
  `{mode: "live", transcribe_only: true, heard, did_you_mean: ["LLZ"], trace: [1 Voice Transcribe step], cost_usd,
  limits, not_medical_advice}`. No question is asked and no answer is written; the page puts `heard` in the box and
  sends nothing until the person presses Send (the edited text goes to `/v1/live/ask`). It uses one of the 10 daily
  voice questions and goes through the per-call cost ledger exactly like a full voice question (reserved before,
  settled after). `did_you_mean` lists known codes one letter from an unknown capitalised three-letter word that was
  heard; a real code is never offered for correction; the page swaps the word only when the person clicks
  "Use LLZ". Errors: `503 {code: "unavailable", message}` (no model key, live calls off, cost cap, transcription
  failed; the message is shown and ends "Type your question instead"), `422` no speech / patient data, `429` the
  daily voice limit (the server's message is shown). Server switch: `MAUDESIGNAL_VOICE_TRANSCRIBE_ONLY` (default on;
  off, the option is refused with 422 and health says `voice_transcribe_only: false`). Until health confirms it
  (pending, failed or an older API), "Ask by voice" says "Voice needs the live service" and opens the recorded voice
  run; the message box never sends a recording as a question by itself. At 1:00 a recording pauses ("Limit reached
  — press Stop to use it or ✕ to discard"); nothing is sent and no voice question is used until Stop.
- "Research the web" (shown only with `features.research === true`) adds `research: true` to the ask body. An answer
  may then carry `research: {status, items: [{title, url, date, source}], label}`, shown under the answer headed
  exactly "Web research — not FDA records, not verified by the gate"; each title is a link (`target=_blank`,
  `rel=noopener noreferrer`) with its date and source. "Save to audit" posts `{url, title, date}` to
  `POST /v1/live/research/save` and shows "Saved"; a 404 hides the button. Both routes belong to another track.
- A photo (camera, phone camera or file) is attached as a thumbnail with a remove button; Send posts it to
  `/v1/live/label` as one conversation turn. Words typed with it are asked after the reading returns (the turn says
  "Your question is sent after the photo reading"), with `product_code` set to the top match's code when it has one,
  otherwise as typed. Nothing is confirmed for the person.

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

### Investigate a complaint: `POST /v1/investigate` (F25)

The page `/investigate` (v2 layout only) and its API. No model, no key, nothing stored. Entry points: the Home card
"Investigate a complaint" (its one button) and the "+" menu item of the same name (between "Try a sample label" and "Ask by
voice"; present only in the v2 layout).

**URL contract for other pages** (for example a simulated device profile that wants an "Investigate a complaint on this
device" link): `/investigate?code=XXX&device=<simulated device id>`. `code` is three letters and fills the product code box;
`device` is `[A-Za-z0-9._-]{1,40}`, is shown as "From the simulated device <id>" and is never sent anywhere. Both are
optional; anything else is ignored. The app folder, `?layout=v2` and `?r=` are kept. In code: `hrefFor({ page: 'investigate',
code, device })` (`src/v2/router.ts`, `src/investigate/api.ts`).

Request (JSON, no cookies, `credentials: "omit"`): `{product_code: 3 letters, description: 5..500 characters}`. The description
is the device problem in a few words; the page shows the banner "Do not enter patient data. Describe the device problem only."
above the form. The server runs the `/v1/live/ask` patient-data guard first and refuses with `422 {code: "patient_data",
message}` (nothing is searched). The description is used once to pick keywords and is never stored or logged: the audit entry
holds only a keyed hash (HMAC) of it and its length, the response is `Cache-Control: no-store` and does not repeat it. Keywords are the
lowercased content words of the description (at least 3 letters or digits, not a number, not in a fixed stop-word list, not the
generic words device, problem, issue, report, event), the first 6 in order; no model, no synonyms, no stemming.

Answer (`InvestigateAnswer`, see `api/openapi.json`):
```json
{"mode": "live", "product_code": "LLZ", "device_type_name": "string|null",
 "retrieved_utc": "2026-11-01T14:05:00Z", "retrieved_date": "2026-11-01", "window_start": "20251101", "window_end": "20261101",
 "keywords": ["viewer", "froze"], "keyword_rule": "...",
 "months": [{"month": "2026-07", "code_wide": 72, "code_wide_url": "https://api.fda.gov/...", "keyword_matched": 17, "keyword_url": "https://api.fda.gov/...", "partial": false}],
 "total_code_wide": {"value": 121, "url": "..."}, "total_keyword_matched": {"value": 24, "url": "..."},
 "quotes": [{"report_number": "...", "mdr_report_key": "...", "date_received": "20260701", "source": "manufacturer", "maker": "as written", "quote": "verbatim sentence", "truncated": false, "keywords_in_quote": [], "url": "...", "gate": "verbatim match"}],
 "sources": {"buckets": [{"source": "Manufacturer report", "normalized": "manufacturer", "count": 121}], "buckets_url": "...", "manufacturer_count": 121,
             "non_manufacturer": {"value": 0, "url": "..."}, "no_source_count": 0, "reports": [{"report_number", "mdr_report_key", "date_received", "source", "maker", "url"}], "note": null},
 "recalls": {"total": {"value": 561, "url": "..."}, "items": [{"recall_number", "firm", "status", "date_initiated", "reason", "url"}], "note": null},
 "clearances": {"total": {"value": 209, "url": "..."}, "items": [{"k_number", "device_name", "applicant", "decision_date", "url"}], "note": null},
 "dropped": {"quote_not_verbatim": 0, "quote_personal_details": 0, "quote_wording": 0, "record_not_confirmed": 0},
 "own_maker_note": "...cannot be separated...", "lag_note": "...", "notice": "fixed text", "not_medical_advice": true,
 "source_note": null, "notes": []}
```
- The two counts are different questions and are never added: `code_wide` is every report for the product code in the month;
  `keyword_matched` is the part of it whose narrative mentions at least one keyword (null when the description had no content
  words). The window is the 12 calendar months ending on the retrieval date (the first and last month can be partial; openFDA
  runs weeks behind). Every figure has the openFDA query that shows it; the page links only addresses that start with
  `https://api.fda.gov/` and drops any other.
- Quotes: at most 5, one per report, each a sentence of the report narrative (cut at a word at 300 characters, `truncated`),
  checked by the claim gate's verbatim-quote rule against the very record it came from before it is returned. A sentence with
  personal details or a word from `connector/forbidden.py` is left out and counted in `dropped`.
- `sources` is the F12 filter live: counts by `report_source_code` over the window (normalised with
  `gate/evidence.normalize_source`), the number not filed by a manufacturer, and the newest five of those reports.
- Reports filed by the user's own company **cannot be separated** (the form does not ask which company; maker names on MAUDE
  reports are free text). The answer says so (`own_maker_note`) and each quote shows the maker name as written.
- Recalls and 510(k)s: total (all dates) and the newest five, from `device/recall.json` and `device/510k.json`; each item is
  confirmed by the gate (recall / device claim against the fetched row) before it is returned.
- A section that openFDA could not give is `null` / empty with a `note`; if the main monthly counts cannot be read the answer is
  `502 {code: "unavailable"}`. Other errors: `422 invalid_input`, `429 rate_limited` (per address, default 6 an hour and 20 a
  day; `Retry-After`).
- CORS: only the origins in `MAUDESIGNAL_WEB_ORIGINS`, POST and OPTIONS, no credentials.

- Review round (Nov 1): the section headings say "MAUDE reports for this product code (any maker)" and "Recalls and 510(k)s for
  this product code" (the tool counts every maker and decides nothing about similarity). `sources.non_manufacturer.url` is `""`
  when no filer type other than a manufacturer exists (no query returns "0 reports"); the page then writes "None of the 121
  reports ..." and links `sources.buckets_url`, the by-filer-type query. A zero is never linked.
- Time limit: the whole search has a deadline (`MAUDESIGNAL_INVESTIGATE_DEADLINE_S`, default 30, at most 40); each openFDA call
  gets min(10 s, time left); keyword counts, filer types, recalls, 510(k)s and the type name run side by side. After the deadline
  the calls not started are skipped and `notes` says so. `502` only when the first monthly count fails; `503
  {code: "openfda_limited"}` when openFDA answers 429, and `504 {code: "investigate_timeout"}` when the whole request outruns its limit (deadline + 5 s; each openFDA call is also cut at 8 s of wall-clock time). An unexpected server error is a JSON 500 that still carries the CORS headers. The page gives up after 48 s with its own "took too long" message.
- The patient-data guard also refuses `name:` / `patient name` labels, and keywords never come from words after `name:` or from runs
  of two Capitalised words.
- The audit entry holds `description_hmac` (HMAC-SHA256 with the server pepper), not a plain hash.
- After a run the form collapses to "LLZ · your description · Edit" with jump links; the button becomes "Run again" and only Copy
  stays filled. The recorded example shows the stored copy's own date ("stored copy of 2026-10-27"), not a search time.

Without `VITE_MAUDESIGNAL_API_BASE` the page makes no request and shows the **Recorded example**: code LLZ and a sample
description, run by `scripts/record_investigate_example.py` over the stored copy of openFDA records in the demo database
(fetched 2026-10-27) into `src/fixtures/investigateExample.json`. Its counts are those of the stored copy (the label says so);
each link still opens the live query. The form is read-only there.

"Evidence for the complaint file" is built in the browser from the answer (`evidenceText` in `src/investigate/api.ts`): the
search date and time (UTC), product code and FDA name, the description as entered (marked "as entered by the user; not stored"),
every count with its openFDA query URL, the quotes, the not-by-manufacturer counts, the recalls and 510(k)s and the fixed
notice. Copy puts it on the clipboard; Download .txt saves `complaint-evidence-<CODE>-<date>.txt` (no description in the name).

### Connect: `GET /v1/connect`

The real API body: `{mcp_url, openapi_url, docs_url, auth_header: "X-API-Key", demo_key: str|null, demo_limits: {per_minute, per_day, live_model, note}, steps}`.
The page reads `demo_limits` (and says "No live Spark answers" unless `live_model` is true, with the per-minute and per-day numbers as sent). The
older names (`key_header`, `privacy_url`, `terms_url`, `limits: {read_only, live_spark, note}`) are still accepted as a fallback; without
`privacy_url` and `terms_url` the page uses `/privacy` and `/terms` on the MCP address's origin. The
"Connect to Muse" page shows these with a one-click Copy for the key. Any failure, or no API address, shows the fixed text: MCP URL
`https://maudesignal-api.vercel.app/mcp`, OpenAPI URL `https://maudesignal-api.vercel.app/openapi.json`, "Ask Charan for a key", and links
to `/privacy` and `/terms` on the API. Three steps: open Muse connectors, add the MCP URL, paste the key in the `X-API-Key` header. No OAuth.

## Make it yours (browser only) and the alert buddy

"Our devices" has a **Make it yours** button. A person types a company name and adds devices; their company then shows in the same
views as the simulated Demo MedTech Co. (table, status chips, alert counts, device pages), under the banner **"Your company — your data
stays in your browser"**. The simulated company stays the default for new visitors and keeps its banner "Simulated company — sample data.
Problem evidence is real FDA data." A switch ("Demo MedTech Co. (simulated)" / "Your company") goes between them. Code: `src/myCompany.ts`
(pure logic), `src/useMyCompany.tsx` (state), `src/components/MakeItYours.tsx` (UI).

**Storage.** `localStorage`, versioned keys: `ms-my-company-v1` (the company) and `ms-company-mode-v1` (`"mine"`; anything else = demo). Every
access is in try/catch. When storage is blocked the company lives in memory for the tab and the page says so ("kept in memory only"); a
stored value that fails validation is ignored. Nothing about the company or its devices is sent anywhere: no analytics event, no change to the
visit ping body (`{ref?, page, client_ts}`; the page name of the device view carries no device or company name), and the Web Analytics URL is
unchanged. The only network calls Make it yours can cause are the K-number look-up below and the existing label-photo call.

**Stored shape** (`ms-my-company-v1`, also the export file, plus `app` and `exported_utc`):
`{version: 1, company: str<=80, devices: [{id: "MY-NN", name: str<=120, product_code: "ABC"|null, k_number: "K123456"|null, added: "YYYY-MM-DD",
source: "code"|"k_number"|"csv"|"label"|"json", note: str|null, k_check: str, status: <one of the five statuses>, history: [{seq, date, from: str|null, to}]}]}`.
At most 200 devices; each device has a product code or a K-number. **Export JSON** writes `{app: "maudesignal-my-company", version: 1, exported_utc, company, devices}`;
**Import JSON** validates every field and names each problem (not JSON, wrong app/version, bad code or K-number, unknown status, duplicate id, a
history that goes backwards or does not end on the status); a valid file replaces the company after a confirm (no confirm when it is empty).
**Clear** asks first.

**Statuses** are the same five as the simulated company, with the same ranks, and only move forward (to a higher rank; never back, never
sideways). They are set by the person and kept only in this browser; the history on the device page says "kept only in this browser, not
hash-chained". A new device starts in "Needs review" only when its product code is flagged by the AI device sweep (a new kind of problem or
more serious than usual; the same stored data that drives the bell), otherwise in "Monitoring — nothing open". Nothing is guessed beyond that.

**Four ways to add a device.**
1. Product code: exactly 3 letters (upper-cased). A code the site has stored data for (sweep, briefs, the simulated company) is accepted
   plainly; any other 3-letter code is accepted with the note "not one this site has stored data for".
2. K-number (`K` + 6 digits): when `VITE_MAUDESIGNAL_API_BASE` is set and `GET /v1/connect` hands out a `demo_key`, one call
   `GET {api}/v1/tools/lookup_device?k_number=K123456` with the key in the `auth_header` (`X-API-Key`), `credentials: omit`. Only the
   K-number is sent (never the company name or the device list). The page reads the record from the top level or from `device`, `result`, `facts` or
   `record`: `device_name` (or `name`), `applicant`, `product_code`. A record stores "checked with the FDA 510(k) record K…"; an answer without a
   record stores "checked: no 510(k) record found"; no API address, no key, a non-2xx answer (including 404 when the tool is not deployed), a
   timeout (12 s) or a network error stores **"not checked yet"**. This path assumes the tool name and parameter above and that the API's CORS
   allows the `X-API-Key` header from the site's origin; both are the API track's to confirm.
3. CSV: columns `name`, `product_code`, `k_number` (header row required; `name` plus a code or a K-number per row; max 200 rows, 200 KB;
   BOM, CRLF and quoted commas handled). A preview with the valid rows and a line-numbered error per bad row is shown first; only valid rows are imported
   when the person presses Import. K-numbers in a file are stored as "not checked yet".
4. Label photo: only when an API address is set. The existing camera / upload goes to `POST /v1/live/label`; the possible matches are shown with
   "Confirm this match"; after one is confirmed an "Add to your company" button adds only that match (name, K-number, product code). A recorded run
   cannot be added.

**Evidence.** Real FDA evidence (report count, recalls, patterns with quotes, the gate lines) is attached to a device only where it is stored for its
product code: it is taken from the simulated company's stored evidence for that code (`demo_db` or `fetched`). Any other device shows "evidence not
fetched yet"; no number is estimated.

**Alert buddy** (`src/components/AlertBuddy.tsx`, `src/buddy.css`): an original SVG character (about 30 px) in the top bar. The count is the bell's
badge count (alerts not yet marked seen: sweep and brief signals flagged by the detector rules, plus "Needs review" devices of whichever company is shown). With 0 it is a calm
picture (`role="img"`, gentle breathing); with N > 0 it is a button that pulses in the token danger colour; click or Enter opens the first alert's panel (P2).
The count is shown on the bell only (no second badge); the buddy's `aria-label` carries it in words ("N alerts need a look"). The bubble "N alerts need a look"
opens once per browser session (sessionStorage key `ms-buddy-bubble-seen-v1`, in memory if blocked), hides itself after 4 s, shows again on hover or focus on wide
screens, and is never drawn below 640 px (it would cover the verification strip). The drawing is 36 px from 768 px up and 30 px below.
`prefers-reduced-motion: reduce` switches the animation off; the colour remains. Colours come from the design tokens only.
In the sidebar the Our devices row reads "Our devices" with a `simulated` or `yours` tag and the Needs review count of the company that is shown. The yours banner
(lock icon, success tint) differs from the simulated banner (amber); "Stays in this browser" repeats beside Add device, CSV import and the photo add. Below 480 px
the device table renders as stacked cards and the status chips scroll in one row. The clear confirm focuses "Keep it", offers "Export first" and uses the danger colour
for "Yes, clear it"; import errors list as "Row N: ..." under a heading.
A device you added has no stored alert detail of its own: its panel falls back to the sweep alert for the same product code (never to the simulated
company's alert) or says no stored detail exists.

## Tests

- Make it yours and the buddy (`web/`): `src/myCompany.test.ts` (codes, storage incl. blocked storage, CSV, import validation, export round-trip, clear, forward-only
  statuses, the K-number look-up with a fake fetch, the built company and alert counts), `src/myCompanyDom.test.tsx` (jsdom: every way to add, export / import / clear,
  blocked storage, the label match flow, buddy states, bubble, keyboard, reduced motion), `qa/e2e_m2.py` (Playwright against `qa/live_stub.py`, 390 and 1440, light and dark;
  screenshots `qa/screenshots/M2-*.png`).
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

## Live check through the MaudeSignal API (added Oct 29, B5)

The browser never calls openFDA (openFDA answered the preview's browser calls with 403).
"Check any device type" calls the API's public endpoint instead:

- Build-time env var `VITE_MAUDESIGNAL_API_BASE` on the web Vercel project: the API's
  origin, no trailing slash (for example `https://<api-project>.vercel.app`).
- Request: `GET {VITE_MAUDESIGNAL_API_BASE}/v1/public/check_device_type?product_code=XXX`
  (keyless, per-IP rate limit, 6-hour cache, CORS limited to the web origins in the API's
  `MAUDESIGNAL_WEB_ORIGINS`). Only the three-letter code is sent.
- Response: the connector answer model (`speakable`, `facts[{text, link}]`, `advisory`,
  `provenance`) plus `check` = `maudesignal.monitor.live_check.LiveCheck.to_dict()`
  (`product_code`, `as_of`, `window`, `classification`, `change`, `triggers`, counts,
  shares, `spike_ratio`, `prior_report_count`, `new_event_types`,
  `current_event_type_counts`, `queries[[label, url]]`). The UI renders figures and links
  from `check`; every query URL must start with `https://api.fda.gov/`.
- Fallback (no result is ever invented): base unset, network error, 8-second timeout,
  HTTP 429 or a malformed answer → the message with the link to the Streamlit app's live
  check. Client limit: 10 checks per browser session, 6-hour local cache per code.
- Withheld sentences: the API never returns a withheld sentence's text; the web app must
  not display one either (tested in `web/src/liveCheck.test.tsx`).
