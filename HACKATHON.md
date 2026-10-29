# Hackathon Build Manifest — Meta Global AI Developer Hackathon

**Event:** Meta Global AI Developer Hackathon (Oct 26 – Nov 4, 2026)
**Track:** Indie Developer, solo
**Problem statement:** Build for Your World

## What was built DURING the hackathon (new work — this is the submission)

Everything under `src/maudesignal/copilot/`, `src/maudesignal/gate/` and
`src/maudesignal/monitor/` was created during the event:

| File | What it is |
|---|---|
| `copilot/meta_provider.py` | Meta Model API provider (OpenAI-compatible client, streaming) implementing the existing `LLMProvider` interface |
| `copilot/__init__.py` | Package exports |
| `copilot/agent.py` | Muse Spark tool-use loop → structured answer (sentences + claims) → claim-level gate → one repair turn with the gate's recomputed values → unrepaired sentences withheld; every answer written to the audit trail |
| `copilot/tools.py` | 13 deterministic tools (first six listed here) the model calls: what changed this week, product summary, report search, report fetch, MDR deadline clock (21 CFR 803.50 / 803.53, advisory), CAPA-need evidence pack |
| `copilot/actions.py` | CAPA-need evidence packs: audit-first, forward-only (`draft → approved / rejected`), only a named human can decide. Whether a CAPA is required is decided by the company's own CAPA-need form |
| `copilot/transcript.py` | Records real Muse Spark runs so the keyless public demo replays them honestly |
| `skills/safety-copilot/` | Versioned behavior contract (prompt, output schema, examples) for the copilot |
| `gate/` (`gate.py`, `claims.py`, `evidence.py`, `cfr.py`, `loader.py`) | **Claim-level citation gate.** Recomputes counts/shares from stored records, verbatim-matches quotes to the cited report (a real quote pinned to the wrong report is blocked), checks 510(k) numbers against the catalog, allowlists 21 CFR sections (blocks QS-reg sections superseded by QMSR on 2026-02-02), and blocks numbers / ids / CFR cites that carry no structured claim. Deterministic, no model calls. The `regulatory-citation-verifier` Skill spec pre-existed with zero call sites; this is its enforcement. |
| `tests/fixtures/gate/adversarial.jsonl` + `tests/unit/test_gate.py` | 54 adversarial cases (fabricated / drifted quotes, wrong-record quotes, stale and inflated numbers, fake and mismatched K-numbers, hallucinated and superseded CFR, untagged mentions): 0 false pass, 0 false block |
| `dashboard/workspace.py` | **Signals** workspace (list and detail): the device types with what changed this week on the left; the selected one's why-flagged header, reports (who filed them), recorded copilot answers, CAPA-need evidence pack with Accept/Reject, and MHRA (UK) context on the right |
| `dashboard/copilot_pages.py` | **Copilot** (recorded answers as a list, live "try to fool the gate" playground, live mode when a key is present), **Audit** (CAPA-need decisions, one hash-verified trail) |
| `storage`: `CapaDraftRecord`, `ActionAuditRecord` + DB methods | CAPA-need evidence pack table and append-only, SHA-256 hash-chained audit trail with tamper detection |
| `scripts/record_demo_transcripts.py`, `.github/workflows/copilot-record.yml`, `demo/` | Records the demo questions through the real Muse Spark copilot in GitHub Actions (key from repository secrets, never in code) |
| `.github/workflows/meta-smoke.yml`, `test_meta_connection.py` | Meta Model API smoke test (`models.list` + streaming) run with repository secrets |
| `tests/unit/test_copilot_agent.py` | Agent loop, repair turn, withheld sentences, CAPA approval rules, audit tamper detection, tools, transcripts (scripted fake client — no credits) |
| `copilot/voice.py` | Second Meta AI surface: spoken question → **Muse Voice Transcribe** (`POST /v1/asr/transcribe`, `muse-voice-transcribe-1.0`) → transcript text → the same copilot + claim-level gate. Audio never goes to the chat model. Local WAV validation before upload, $0.18/audio-hour cost estimate, key never logged |
| `dashboard/copilot_pages.py` (voice) | "Ask live" mic input when a key is present; recorded runs show "🎙 Heard: …" so the analyst sees what was transcribed |
| `scripts/record_demo_transcripts.py --voice-file`, `demo/voice/question-a.wav`, `question-b.wav` | Records the spoken demo question through Voice Transcribe + Muse Spark in CI (key from secrets). Both WAVs are ElevenLabs text-to-speech samples, not a real practitioner |
| `tests/unit/test_voice.py` | 29 tests: request format, errors, validation, voice → gated answer end to end (mock transport, no network) |
| `docs/hackathon/VOICE_API_NOTES.md` | What Meta's Voice Transcribe docs say vs what is unverified |
| `monitor/deterioration.py` | Deterministic per-product-code detector: last 7 days vs trailing 4-week baseline → `new_signal` / `spike` / `severity_escalation` / `stable`, returning every count, share and report id used |
| `monitor/digest.py` | What-changed digest ("New kind of problem: N · More serious than usual: M · Reports suddenly increased: K") rendered to Markdown + JSON with a fixed advisory footer; no LLM |
| `monitor/fetch.py` | Capped, whole-day incremental openFDA fetch (reuses the existing ingestion pipeline) |
| `monitor/live_check.py`, `dashboard/live_check_ui.py` | **Check any device type**: any FDA product code, live from openFDA counts (about 5 requests, no report text, nothing stored, no model), the same four detector rules (a 300-case test checks both agree), and the openFDA query behind every figure. Cached 6 h per code; 10 checks per browser session |
| `monitor/__init__.py` | Package exports |
| `cli.py` → `maudesignal monitor` | New CLI command: optional capped fetch → detect → `digests/YYYY-MM-DD.{md,json}` |
| `scripts/seed_demo_data.py` | Keyless seeding of the demo DB from live openFDA via the existing ingestion + catalog code |
| `data/demo/maudesignal_demo.db`, `data/demo/SEED_MANIFEST.json` | 137 real MAUDE reports (LLZ Jul–Aug 2026 complete window; all QIH, MYN, POK reports) + manifest of the exact queries |
| `digests/2026-08-24.*`, `digests/2026-08-31.*` | Two digests generated from the seeded data |
| `.github/workflows/monitor.yml` | Daily cron + manual dispatch running the monitor; commits the digest back (`chore(monitor):`) |
| `tests/unit/test_monitor.py` | Tests for detector, digest, fetch and CLI |
| `streamlit_app.py`, `requirements.txt` | Streamlit Community Cloud entry point and dependency file for the keyless public demo (installs this repo; dependencies stay in `pyproject.toml`) |
| `tests/unit/test_dashboard_default_db.py` | Tests that the dashboard falls back to the demo DB only when nothing else is configured |
| `docs/architecture.mmd`, `docs/architecture.svg` | Architecture diagram (Mermaid source + rendered SVG) of the hackathon flow |

Small changes to pre-existing modules made during the event (to support the
monitor, or bugs it exposed): `Database.list_event_facts` / `max_date_received`
/ `list_product_codes`; `OpenFDAClient.count_by_date_received`, `count_field`, `total` (and the public `build_query` alias);
`config.openfda_api_key_from_env`; fix — openFDA date-range queries were sent
with `+` encoded as `%2B` (HTTP 500); fix — live openFDA `event_type` is a
string, so ingestion had been storing single letters (`"m"`, `"i"`); fix —
structlog captured `sys.stderr` once, so logging crashed after the stream was
closed (the 4 failing CI tests); `Database.date_received_lookup`; dashboard
package import made lazy so submodules don't re-run the app;
`dashboard/app.py` `_load_db` now opens `data/demo/maudesignal_demo.db` when
`MAUDESIGNAL_DB_PATH` is unset and `data/maudesignal.db` does not exist
(stored-first public deploy); `.streamlit/config.toml` gained `headless = true`;
`README.md` rewritten for the hackathon (pre-existing pipeline section kept,
trimmed, with stale CLI commands and test counts corrected); `CLAUDE.md` gained a
"Hackathon extension (Oct 2026)" note and the `safety-copilot` Skill row;
pre-hackathon root-level debug scripts and logs removed (public-repo hygiene),
with their ruff excludes in `pyproject.toml` replaced by per-file ignores for the
remaining smoke-test and screenshot scripts.

### Added Oct 27 (PRD v2: scattered sources, vision, audit-ready dossier)

| File | What it is |
|---|---|
| `copilot/agent.py` (F2) | Final answer uses Meta's strict `json_schema` `response_format` (no tools on that call); `structured_output` and `reasoning_effort` options |
| `skills/safety-copilot` 1.1.0 | Strict-mode schema with 9 claim kinds as `anyOf` branches |
| `copilot/tools.py` | 3 new tools — `recalls`, `device_510k`, `literature` (9 total), reading stored data only |
| `sources/openfda_sources.py`, `scripts/seed_sources.py` | openFDA device recall + 510(k) fetchers into `external_sources`; demo DB now holds 566 recalls (every recall for the demo codes), 266 510(k) records, 20 PubMed abstracts |
| `gate/` (recall, recall-count, literature claims) | Recall numbers / counts and PMIDs verified against stored data; quotes from abstracts and recall reasons; K-number check falls back to stored 510(k) records; untagged recall numbers and PMIDs blocked. Adversarial set now 89 cases, 0 false pass / 0 false block |
| `vision/` (`fda_pdf.py`, `reader.py`, `spark.py`, `verify.py`, `openfda510k.py`, `pipeline.py`, `images.py`) + `skills/fda-document-reader/` | Muse Spark reads 510(k) summary page images (two independent reads); accuracy check gives each field VERIFIED / CONFLICT / UNVERIFIABLE from read agreement, openFDA and the PDF text layer — conflicts flagged "low clarity — human check", never silently resolved |
| `vision/sam.py`, `vision/label.py` + `skills/device-label-reader/` | SAM 3.1 locates a device label in a photo → Muse Spark reads the crop → K-number / GTIN check → that device's signals; lot/serial session-only |
| `dossier/` (`builder.py`, `figures.py`, `chart.py`, `mdr.py`, `model.py`, `render.py`, `service.py`, `templates/`) | Signal Evaluation & CAPA-need Evidence PDF built like a controlled quality record (document control, approval block modeled on 21 CFR 11.50, ISO 13485 §8.5.2 CAPA record, Form 3500A-mapped MDR worksheet marked not for submission, audit appendix). Every printed number carries a claim the gate re-verifies |
| `dossier/narrative.py` + `skills/dossier-narrative/` | Muse Spark narrative behind the gate; withheld sentences shown with reasons |
| `dossier/review.py` + `skills/dossier-reviewer/` | Muse Wonder 1.0 independent reviewer (PDF input); findings only, stored in the audit trail |
| `dossier/illustration.py` + `skills/dossier-cover-illustration/` | Optional Muse Image cover, off by default, captioned "not evidence" |
| `dashboard/dossier_pages.py`, `dashboard/vision_pages.py` | Dossier and Vision pages (stored-first replay without a key) |
| `scripts/build_demo_dossier.py`, `scripts/record_vision_runs.py`, `demo/dossier/*.pdf`, `docs/dossier_sources.md`, `docs/hackathon/VISION_API_NOTES.md`, `packages.txt` | Demo builds, regulatory sources, Meta API notes, poppler for Streamlit Cloud |
| `tests/unit/test_scattered_sources.py`, `test_vision.py`, `test_dossier.py` | Tests for all of the above (scripted clients / mock transports, no network) |

Small pre-existing changes: `Database.delete_external_sources`, `Database.list_raw_reports`;
`sources/pubmed.py` fetches real abstracts and retries once on 429; dashboard wiring in `app.py`.

### Added Oct 27, later (polish before the live recording)

| File | What it is |
|---|---|
| `monitor/digest.py` (schema 1.2), `catalog/names.py` | Flagged codes ranked by a fixed, documented key; each rank carries a "why" sentence built from the detector's numbers; digest names the FDA device type and the brands on this window's reports. The Signals workspace shows why each device type is flagged; the `overnight_signals` tool returns the ranking |
| `copilot/voice.py`, `copilot/audit_export.py` | Each spoken question appends a hash-chained `voice.transcribed` entry (model, audio SHA-256, duration, text heard) linked to its `copilot.answer`; silence appends `voice.rejected`. Recording runs export their trail; the Actions page re-verifies and shows it |
| `scripts/hand_check.py`, `docs/hackathon/HAND_CHECK.md` | Hand-check worksheet for every recorded answer: gate pass rates computed from the recorded transcripts, every cited id looked up in stored records, a hand-verdict column per sentence |
| `vision/browser_fetch.py` | Headless-Chromium fallback for 510(k) PDFs that FDA refuses to plain HTTP clients; the recorder skips (not fails) a K-number whose PDF cannot be obtained |
| `scripts/record_demo_transcripts.py`, `.github/workflows/copilot-record.yml` | 20 typed demo questions; one failed question no longer stops a run; commit step hardened |
| `copilot/spend.py`, `dashboard/spend_ui.py` | Live-call caps per browser session ($1 and 20 Meta calls, whichever first) and per day ($10), configurable by env vars; a cap hit makes no call and shows the recorded answer; usage in the audit trail; quota in the sidebar |
| `tests/e2e/test_08_hackathon_pages.py` | Playwright tests for the product pages (Signals, Copilot, Vision, Audit), expected values computed from the demo DB |
| `docs/hackathon/BUDGET.md`, `docs/hackathon/PRD.md` | $150 budget (prices from code, measured ledger) and feature status with evidence |

Small pre-existing changes: `catalog/fetcher.py` no longer writes made-up names for
fallback product codes (names come from the openFDA classification endpoint, or the
code is skipped); demo DB catalog corrected (LLZ/MYN/POK carry FDA classification
names, 15 placeholder rows removed; recorded in `SEED_MANIFEST.json`); dashboard
tables in `app.py` show the brand written on each report.

### Added Oct 28 (PRD v2.1)

| File | What it is |
|---|---|
| `monitor/sources.py`, `gate` `source_count` claim, `copilot/tools.py` `report_sources` | F12 report-source filter: openFDA `report_source_code` stored on every event (backfilled from stored raw records), counts per device type, the reports not filed by a manufacturer, a gated claim kind and 10 adversarial cases |
| `scripts/check_source_counts.py`, `docs/hackathon/SOURCE_COUNTS.md` | Stored source counts compared with openFDA's own counts each recording run |
| `docs/VALIDATION_EVIDENCE.md` | Intended use, deterministic vs model-generated, test evidence, known limits, what a manufacturer would still do |
| `skills/safety-copilot` 1.2.2, `dossier-narrative` 1.1.1, `dossier-reviewer` 1.1.1 | "CAPA-need evidence pack" wording; the copilot never decides CAPA need, reportability or device similarity |

Small pre-existing changes: `NormalizedEventRecord.report_source` column (with a
one-time `ALTER TABLE` + backfill in `Database`), `ingestion/pipeline.py` stores it.

Plus this manifest, the demo video, and the submission write-up.

### Added Oct 28, later (design system, themes, memory, compare, MHRA)

| File(s) | What |
|---|---|
| `design-system/` (from Charan's design branch) | Bento layout, editorial Paper/Night/High-contrast tokens, Newsreader + Geist, component markup. Black and Pink themes added to `tokens.json` (same token names, AA contrast) |
| `dashboard/theme.py`, `dashboard/streamlit_bridge.css` | Theme picker in the top bar (Light, Dark, Black, System, Pink, High contrast; `?theme=` link); Streamlit widgets coloured from the tokens |
| `dashboard/app.py` | Top bar (wordmark, Signals · Copilot · Vision · Audit, theme picker), dateline with one framing line; classic tools only with `?tools=all` |
| `dashboard/copilot_pages.py` | Hero tile for the top signal; "Compare the device types you choose"; "Remember these device types"; MHRA (UK) context section; live Ask streams progress and verified sentences |
| `copilot/memory.py` | Memory replayed from the hash-chained audit trail (`MEMORY` entries): device types a named person chose, pinned notes |
| `monitor/compare.py` | Deterministic side-by-side numbers for chosen device types |
| `sources/mhra.py`, `scripts/fetch_mhra_alerts.py`, `.github/workflows/mhra-fetch.yml`, `data/demo/mhra_queries.json` | MHRA (UK) device safety alerts via the GOV.UK search API, stored as gated, labelled context |
| `copilot/tools.py`, `skills/safety-copilot` 1.3.0 | Tools `my_device_types`, `compare_signals`, `mhra_alerts` (13 tools) |
| `copilot/agent.py` | `ask(on_event=…)` progress events for streaming |
| `demo/voice/question-a.wav`, `question-b.wav` | Charan's two ElevenLabs text-to-speech samples (greetings; not a real practitioner) |
| `demo/voice/question.wav`, `question-c.wav`, `question-d.wav`, `question-e.wav` | Charan's ElevenLabs text-to-speech product questions (voice "Adam"; not a real practitioner), recorded as `00-voice-main`, `-c`, `-d`, `-e` |
| `tests/unit/test_theme.py`, `test_memory_compare.py`, `test_mhra.py` | Contrast for every theme, memory/compare/tools/streaming, MHRA parsing/storage/gate |
| `tests/unit/test_compliance_journey.py` | Offline end-to-end: openFDA (mock transport, real records) → ingestion → three Skills (real schemas) → SQLite → dashboard → PSUR Markdown + PDF |
| `scripts/scale_test.py`, `scripts/load_test.py` | Seeded scalability/stress (breaking point ~100k records) and concurrent-session load (no Meta calls) |
| `docs/hackathon/TESTING.md` | All 21 test types with PASS / FAIL / PENDING and evidence |
| `scripts/prepare_label_photo.py`, `.github/workflows/vision-labels.yml`, `demo/vision/labels/README.md` | Label photos: metadata stripped before commit; separate SAM + Spark run when photos are pushed |
| `gate/gate.py` (number words) | Counts written in words or scientific notation are detected (found by exploratory testing) |
| `docs/hackathon/SUBMISSION_DRAFT.md` | Submission draft and video script v3 — not submitted |

## What is PRE-EXISTING (the base — NOT presented as hackathon work)

The `maudesignal` pipeline itself predates the hackathon (public repo, MIT):
openFDA MAUDE ingestion, LLM extraction via versioned Skills, severity
triage, 11-category AI failure-mode classifier, root-cause analysis,
alerting, Mann-Kendall trend + KS/PSI drift detection, PubMed/
ClinicalTrials sourcing, PSUR draft generation, and the Streamlit dashboard.

The copilot reads from that pipeline. It does not claim it.

## Framing (read this before judging)

- This is a **B2B regulatory tool for quality/regulatory professionals**.
  It analyzes device safety signals. It does **not** give medical advice,
  diagnoses, or treatment recommendations to patients, and it refuses
  such requests.
- No factual claim in a copilot answer is generated without grounding in a
  pipeline record or a verified primary source (citation hard-gate).
- Meta models used: `muse-voice-transcribe-1.0` (Voice Transcribe, `POST https://api.meta.ai/v1/asr/transcribe`) for spoken questions, and the
  Muse Spark series via the Meta Model API (Standard
  tier — never Contributor, which trains on your data). Chat model:
  `muse-spark-1.3` (latest, docs-recommended), base URL
  `https://api.meta.ai/v1`, streaming via `stream=True`.

## Planning docs

The day-by-day planning docs are kept outside the public repo. This manifest
describes what was actually built.
