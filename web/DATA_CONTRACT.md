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
| Vision runs | `demo/vision/510k-*.json`, `demo/vision/label-*.json`, images `demo/vision/labels/*.jpg` |
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
label's `sam` field.

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

## Tests

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

## `company.json` (added Oct 30, A6; "Does this apply to us?")

Written by `maudesignal.company.export_company(load_company())` (Track A); the web exporter
copies it to `web/public/data/company.json` as stored. **Simulated company, real FDA
evidence**: every name, owner, model, status and date is sample data; every report, recall,
count and quote is stored openFDA data. Inputs: `demo/company/company.json` (devices),
`demo/company/audit.json` (hash-chained status history), `demo/company/evidence/<code>.json`
(fetched evidence, from `scripts/fetch_company_evidence.py`), the demo database (read-only,
codes LLZ, QIH, MYN, POK) and `demo/investigations/*weekly-llz.json` (reused groups).

```json
{"schema_version": "1.0", "generated_utc": "...",
 "banner": "Simulated company — sample data. Problem evidence is real FDA data.",
 "company": "Demo MedTech Co. (simulated)",
 "statuses": [{"label": "Needs review", "rank": 1}, {"label": "Testing in progress", "rank": 2},
              {"label": "Already covered", "rank": 3}, {"label": "Not applicable to our device", "rank": 3},
              {"label": "Monitoring — nothing open", "rank": 4}],
 "devices": [{
   "id": "DMC-01", "name": "Halcyon ViewStation", "model": "HV-200", "product_code": "LLZ",
   "owner": "Mara Ellison (simulated)",
   "device_type": {"name": "System, Image Processing, Radiological" | null, "source": "..." | null,
                   "query_url": "https://api.fda.gov/device/classification.json?search=product_code:LLZ"},
   "sweep": {"file": "demo/sweep/ai-device-sweep.json", "product_code": "LLZ", "as_of": "20260930",
             "classification": "stable|spike|severity_escalation|new_signal", "triggers": [],
             "current_count": 12, "baseline_count": 288, "prior_report_count": 19958, "query_url": "..."} | null,
   "status": {"label": "Testing in progress", "set_by": "Mara Ellison (simulated)", "date": "2026-10-19",
              "detail": "owner ...; due 2026-11-20", "details": {"owner": "...", "due_date": "2026-11-20"}} | null,
   "history": [{"seq": 1, "date": "2026-10-12", "ts": "...", "actor": "...", "action": "register|change",
                "from_status": null, "to_status": "Needs review", "details": {}, "note": "", "entry_hash": "..."}],
   "evidence": {"origin": "demo_db|fetched|missing", "available": true, "note": null, "fetched_utc": null,
                "report_count": {"value": 121, "gate": "pass", "reason": "recomputed 121"} | null,
                "window": {"date_from": "20260701", "date_to": "20260831"} | null,
                "queries": [{"label": "...", "url": "https://api.fda.gov/..."}],
                "recalls": {"stored": 561, "matched_total": 561, "gate": "pass", "reason": "...",
                            "latest": [{"recall_number": "Z-0186-2027", "recalling_firm": "...", "status": "...",
                                        "date_initiated": "20260905", "excerpt": "verbatim, gate-checked" | null,
                                        "url": "https://www.accessdata.fda.gov/..." | null}]} | null,
                "gate_totals": {"pass": 11, "block": 0}},
   "patterns": [{"id": "LLZ-inv-1", "label": "...", "basis": "weekly investigator group, recorded run ...; count recomputed | keyword rules v1.0 (rule-id)",
                 "count": 3, "report_ids": ["50503662"], "first_received": "20260825", "last_received": "20260828",
                 "quotes": [{"report_id": "50503662", "text": "verbatim sentence", "url": "https://www.accessdata.fda.gov/.../detail.cfm?mdrfoi__id=50503662"}],
                 "links": [{"label": "MAUDE report 50503662", "url": "..."}],
                 "gate": {"count": "pass", "reason": "recomputed 3 from 3 listed report ids",
                          "quotes_passed": 2, "quotes_withheld": 0}}]
 }],
 "audit": {"file": "demo/company/audit.json", "chain_ok": true, "first_bad_seq": null,
           "entries": [{"seq": 1, "ts": "...", "actor": "...", "action": "company.status.register",
                        "entity_id": "DMC-01", "payload_json": "...", "prev_hash": "GENESIS", "entry_hash": "..."}]},
 "notes": ["DQK: evidence not fetched yet; no count, pattern or quote is shown for it."]}
```

Rules:

- The banner string is shown on every screen that renders this file. The words "safe",
  "unsafe" and "compliant" are never shown (the exporter withholds a quote that contains one).
- `audit.chain_ok` is **re-verified at export** by recomputing every SHA-256 hash
  (`copilot.audit_export.verify_entries`), not copied from the file's `chain_ok_at_export`.
  The web app may re-verify with the same rule: `entry_hash = sha256(prev_hash + json.dumps({"ts",
  "actor", "action", "entity_id", "payload": payload_json}, sort_keys=True))`, first `prev_hash`
  `"GENESIS"`, `ts` as `datetime.isoformat()`.
- A status is set by a named simulated person (`actor` ends with "(simulated)"), never by the tool,
  and only moves forward in rank (Needs review 1 → Testing in progress 2 → Already covered /
  Not applicable 3 → Monitoring 4; equal or lower rank is rejected). The history is the audit
  entries of that device, in order.
- Missing evidence: a code with no stored evidence has `evidence.available: false`,
  `evidence.note: "evidence not fetched yet"`, `patterns: []`, `report_count: null`,
  `recalls: null`, and a line in `notes[]`. `device_type.name` is `null` until the fetched
  classification exists. Nothing is estimated or invented.
- Every count about real reports/recalls (`report_count`, pattern `count`, `recalls.stored`)
  carries its gate verdict and is recomputed from the stored records at export; a pattern whose
  count the gate does not pass is left out, a quote it does not pass is dropped (`quotes_withheld`).
  Pattern groups come from the recorded weekly-investigator run when one exists (LLZ), otherwise from
  documented keyword rules (`maudesignal.company.patterns.RULES`, no model).
- No lot or serial number, no patient field and no API key is exported.
