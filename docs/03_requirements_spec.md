# Document 3: Requirements Specification (SRS-lite)

**Project Name:** SafeSignal
**Owner:** [Your Name]
**Version:** 1.0 (Draft)
**Date:** [Today's Date]
**References:** Document 1 (Vision), Document 2 (Charter & Scope)
**Status:** Draft

---

## 1. Purpose of This Document

This document translates the 7 in-scope features from Document 2 into **testable requirements**. Each requirement has a unique ID (`FR-XX` functional, `NFR-XX` non-functional, `DR-XX` data). Each is written in the format "The system shall [do X]" and has a defined acceptance test.

**Rule:** If a requirement cannot be verified pass/fail, it is rewritten until it can be.

This document is the bridge between Vision → Code. Every function you write should trace back to a requirement here.

---

## 2. Document Conventions

- **Shall** = mandatory requirement
- **Should** = recommended, not mandatory
- **May** = optional
- **FR-XX** = Functional Requirement
- **NFR-XX** = Non-Functional Requirement
- **DR-XX** = Data Requirement
- **AC-XX** = Acceptance Criteria

Each requirement includes:
- **ID**
- **Priority:** Must / Should / Could (MoSCoW)
- **Feature tag:** Which of F1–F7 it belongs to
- **Requirement statement**
- **Acceptance test**

---

## 3. Functional Requirements

### 3.1 Feature F1 — MAUDE Data Ingestion Module

#### FR-01: Product Code Ingestion
- **Priority:** Must
- **Feature:** F1
- **Requirement:** The system shall retrieve MAUDE adverse event reports from the openFDA API for any valid 3-character product code supplied by the user.
- **Input:** Product code (e.g., `"QIH"`)
- **Output:** Collection of raw MAUDE report JSON objects
- **Acceptance Test:** Given product code `QIH`, the system returns ≥1 valid MAUDE report and stores it to local SQLite without error.

#### FR-02: Configurable Date Range
- **Priority:** Must
- **Feature:** F1
- **Requirement:** The system shall support retrieval of reports filtered by a user-specified date range (start date, end date).
- **Input:** `--start-date YYYY-MM-DD --end-date YYYY-MM-DD`
- **Output:** Reports with `date_received` within the specified range
- **Acceptance Test:** Given date range `2024-01-01` to `2024-12-31`, system returns only reports within that range. Verified by SQL query on stored data.

#### FR-03: Pagination Handling
- **Priority:** Must
- **Feature:** F1
- **Requirement:** The system shall correctly paginate through multi-page openFDA responses to retrieve the complete result set, not just the first page.
- **Input:** Query returning >100 results
- **Output:** All matching records, not just first 100
- **Acceptance Test:** For a query known to return 500+ records, system stores ≥500 distinct records.

#### FR-04: Rate Limit & Retry Logic
- **Priority:** Must
- **Feature:** F1
- **Requirement:** The system shall detect HTTP 429 (rate limit) and 5xx responses, wait with exponential backoff, and retry up to 3 times before failing.
- **Acceptance Test:** Mock a 429 response; system retries with backoff (1s, 2s, 4s) and eventually succeeds without crashing.

#### FR-05: Local Caching
- **Priority:** Must
- **Feature:** F1
- **Requirement:** The system shall cache retrieved reports locally and shall not re-fetch reports already present in the local database unless explicitly forced with `--refresh` flag.
- **Acceptance Test:** Run ingestion twice; second run makes zero API calls (verify via log count) unless `--refresh` is specified.

#### FR-06: Raw + Normalized Storage
- **Priority:** Must
- **Feature:** F1
- **Requirement:** The system shall store (a) the original raw JSON payload and (b) a normalized set of key fields in SQLite tables. Raw data is immutable; normalized data may be reprocessed.
- **Acceptance Test:** SQLite DB contains two tables: `raw_reports` (JSON blob + metadata) and `normalized_events` (extracted structured fields).

#### FR-07: Multi-Code Batch Ingestion
- **Priority:** Should
- **Feature:** F1
- **Requirement:** The system shall support ingestion of multiple product codes in a single command.
- **Input:** `--product-codes QIH,QAS,QFM`
- **Acceptance Test:** Given 3 product codes, system ingests all 3 and separates data by code in storage.

---

### 3.2 Feature F2 — Claude-Powered Narrative Extraction

#### FR-08: Structured Field Extraction
- **Priority:** Must
- **Feature:** F2
- **Requirement:** The system shall use Claude (via Anthropic API) to extract the following structured fields from each MAUDE narrative: `failure_mode`, `severity`, `patient_outcome`, `device_problem`, `ai_related_flag`, `confidence_score`.
- **Input:** Raw MAUDE narrative text (string)
- **Output:** JSON object matching defined schema (see §5.2)
- **Acceptance Test:** On a hand-labeled 100-record gold set, extraction matches human labels with ≥90% per-field accuracy.

#### FR-09: Skill-Driven Behavior
- **Priority:** Must
- **Feature:** F2
- **Requirement:** Extraction behavior shall be defined exclusively in a versioned `SKILL.md` file (not inline in Python code). Changing behavior requires editing the Skill and incrementing its version.
- **Acceptance Test:** Grep the codebase — no multi-line prompts embedded in `.py` files. All prompts loaded from `skills/*/SKILL.md`.

#### FR-10: Structured JSON Output
- **Priority:** Must
- **Feature:** F2
- **Requirement:** Every extraction output shall conform to the JSON schema defined in `schemas/extraction_output.schema.json`. Malformed outputs shall be flagged and retried once, then marked as `extraction_failed`.
- **Acceptance Test:** 100% of outputs validate against the JSON schema or are explicitly marked as failures.

#### FR-11: Confidence Scoring
- **Priority:** Must
- **Feature:** F2
- **Requirement:** Each extraction shall include a `confidence_score` between 0.0 and 1.0 reflecting the extractor's certainty. Records with confidence <0.6 shall be flagged for human review.
- **Acceptance Test:** Every output has `confidence_score` field. Records <0.6 appear in a `review_queue` view.

#### FR-12: Audit Logging
- **Priority:** Must
- **Feature:** F2
- **Requirement:** Every LLM API call shall be logged with: timestamp, model name, model version, Skill name, Skill version, input hash, output hash, token count, cost estimate.
- **Acceptance Test:** Logs present in `logs/llm_calls.jsonl`; any extraction can be traced back to the exact Skill version used.

---

### 3.3 Feature F3 — AI-Specific Failure Taxonomy & Classifier

#### FR-13: Failure Taxonomy
- **Priority:** Must
- **Feature:** F3
- **Requirement:** The system shall classify extracted events into at least 5 AI-specific failure categories defined in `docs/08_glossary.md`:
  - `concept_drift`
  - `covariate_shift`
  - `subgroup_degradation`
  - `false_negative_pattern`
  - `false_positive_pattern`
  - `automation_bias`
  - `not_ai_related`
- **Acceptance Test:** Classifier outputs one or more of these labels for every event; totals align with taxonomy definitions.

#### FR-14: Multi-Label Classification
- **Priority:** Must
- **Feature:** F3
- **Requirement:** A single event may belong to multiple categories. The classifier shall support multi-label output.
- **Acceptance Test:** On test set, at least one event receives ≥2 labels.

#### FR-15: Classification Rationale
- **Priority:** Must
- **Feature:** F3
- **Requirement:** For every classification decision, the system shall produce a short human-readable rationale (≤200 characters) explaining why the label was assigned.
- **Acceptance Test:** Every classified record has a non-empty `rationale` field.

#### FR-16: Human Review Path
- **Priority:** Should
- **Feature:** F3
- **Requirement:** The classifier shall expose an interface for a human reviewer to accept, reject, or correct each classification, with corrections persisted for future reference.
- **Acceptance Test:** Reviewer can mark a record as corrected; correction is stored and does not get overwritten on re-runs.

---

### 3.4 Feature F4 — Drift Simulation Harness

#### FR-17: Synthetic Performance Data Generator
- **Priority:** Must
- **Feature:** F4
- **Requirement:** The system shall generate synthetic time-series performance data (accuracy, sensitivity, specificity) for a simulated deployed AI model over a configurable time window.
- **Acceptance Test:** Generates 365 days of daily metrics for at least 3 deployed-model scenarios.

#### FR-18: Injectable Drift Patterns
- **Priority:** Must
- **Feature:** F4
- **Requirement:** The generator shall support at least 3 drift patterns: gradual drift (linear decay), sudden drift (step change), and subgroup-specific drift (degradation in one demographic while overall is stable).
- **Acceptance Test:** Each pattern visible in generated data via plot; unit tests verify the expected shape.

#### FR-19: Drift Detection
- **Priority:** Must
- **Feature:** F4
- **Requirement:** The system shall apply statistical drift tests (at minimum Kolmogorov-Smirnov test and Population Stability Index) to detect injected drift.
- **Acceptance Test:** Detector identifies ≥80% of injected drift events within 30 days of their occurrence on the test set.

#### FR-20: Drift Alert Output
- **Priority:** Must
- **Feature:** F4
- **Requirement:** When drift is detected above a configurable threshold, the system shall emit a structured alert with: detection timestamp, drift type, affected metric, magnitude, severity level, and suggested review action.
- **Acceptance Test:** Alerts produced in JSON format per schema; visible in dashboard.

---

### 3.5 Feature F5 — Regulatory Citation Verifier

#### FR-21: 510(k) Number Verification
- **Priority:** Must
- **Feature:** F5
- **Requirement:** Any 510(k) number referenced in system output (e.g., `K123456`) shall be verified against the openFDA 510(k) API. Unverified numbers shall be replaced with `[UNVERIFIED CITATION]`.
- **Acceptance Test:** On a test input containing 10 real K-numbers and 5 fake ones, 100% of fakes are flagged; 100% of reals pass.

#### FR-22: FDA Guidance Title Verification
- **Priority:** Must
- **Feature:** F5
- **Requirement:** Any FDA guidance document referenced by title shall be verified against a local index of FDA guidance titles (scraped from fda.gov). Unverified titles shall be flagged.
- **Acceptance Test:** 10 real guidance titles verified; 5 hallucinated titles rejected.

#### FR-23: CFR Citation Verification
- **Priority:** Must
- **Feature:** F5
- **Requirement:** Any Code of Federal Regulations citation (e.g., `21 CFR 803.10`) shall be verified against a known-valid regex pattern AND an index of CFR sections relevant to medical devices.
- **Acceptance Test:** Valid CFR citations pass; malformed or non-existent ones flagged.

#### FR-24: Zero-Hallucination Guarantee
- **Priority:** Must (critical)
- **Feature:** F5
- **Requirement:** No system output shall contain an unverified regulatory citation. The citation verifier shall run as a mandatory pre-output check on every generated report or dashboard claim.
- **Acceptance Test:** On 200 generated outputs, zero contain unverified citations. Any failure = critical bug.

---

### 3.6 Feature F6 — Streamlit Dashboard

#### FR-25: Dashboard Entry Point
- **Priority:** Must
- **Feature:** F6
- **Requirement:** The dashboard shall launch via the command `streamlit run app.py` (or `safesignal dashboard`) and be accessible at `http://localhost:8501`.
- **Acceptance Test:** Fresh clone + install + command = working dashboard in <15 min total.

#### FR-26: Required Dashboard Views
- **Priority:** Must
- **Feature:** F6
- **Requirement:** The dashboard shall display the following 5 views, each on its own tab or page section:
  1. **Volume Trend** — adverse event count over time (monthly)
  2. **Severity Breakdown** — pie/bar chart by severity category
  3. **AI Failure Categories** — distribution across F3 taxonomy labels
  4. **Anomaly Alerts** — list of drift alerts and spike alerts
  5. **Data Export** — CSV/JSON download of filtered data
- **Acceptance Test:** Each view renders without error on the test dataset.

#### FR-27: Filtering
- **Priority:** Must
- **Feature:** F6
- **Requirement:** The dashboard shall support filtering by: product code, date range, severity level, and AI failure category.
- **Acceptance Test:** Each filter changes visible data correctly on manual test.

#### FR-28: Data Export
- **Priority:** Must
- **Feature:** F6
- **Requirement:** The user shall be able to export the current filtered view as CSV or JSON.
- **Acceptance Test:** Export button produces valid CSV and JSON files that open correctly in Excel and a JSON viewer.

#### FR-29: Performance
- **Priority:** Should
- **Feature:** F6
- **Requirement:** Dashboard views shall load in under 5 seconds for a dataset of up to 10,000 records.
- **Acceptance Test:** Stopwatch test on 10,000-record dataset: each view loads <5s.

---

### 3.7 Feature F7 — PSUR-Style Periodic Report Generator

#### FR-30: Report Generation Command
- **Priority:** Must
- **Feature:** F7
- **Requirement:** The system shall generate a periodic safety report via `safesignal report --product-code QIH --period 2024-Q4`.
- **Output:** Markdown file + PDF file in `reports/` directory
- **Acceptance Test:** Command succeeds; both files exist; PDF opens correctly.

#### FR-31: Required Report Sections
- **Priority:** Must
- **Feature:** F7
- **Requirement:** The generated report shall contain at minimum these sections:
  1. Executive Summary
  2. Reporting Period & Scope
  3. Event Volume & Trends
  4. Severity Analysis
  5. AI-Specific Failure Findings
  6. Drift & Anomaly Signals
  7. Recommendations for Human Review
  8. Data Sources & Methodology
  9. Appendix: Source Report IDs
- **Acceptance Test:** Every section present in output. Empty sections are acceptable; missing sections are not.

#### FR-32: Source Traceability
- **Priority:** Must
- **Feature:** F7
- **Requirement:** Every factual claim in the report shall cite its source (MAUDE report ID, or verified external source). The Appendix shall list every source report ID referenced.
- **Acceptance Test:** Randomly sample 20 factual claims; each has a traceable source. Zero fabricated citations.

#### FR-33: Human-in-the-Loop Disclaimer
- **Priority:** Must
- **Feature:** F7
- **Requirement:** Every generated report shall include a prominent disclaimer stating: "This report is a computational signal-surfacing aid. Every finding requires human regulatory review before any regulatory action."
- **Acceptance Test:** Text present and visible in first page of every report.

---

## 4. Non-Functional Requirements

### 4.1 Performance

#### NFR-01: End-to-End Pipeline Time
- **Requirement:** Full pipeline (ingestion → extraction → classification → dashboard-ready) shall complete in under 30 minutes for a single product code, 12 months of data.
- **Acceptance Test:** Stopwatch test on product code QIH, 12 months: ≤30 min.

#### NFR-02: Extraction Throughput
- **Requirement:** Extraction shall process at least 60 MAUDE narratives per minute using Claude Sonnet.
- **Acceptance Test:** Benchmark on 600-record batch: ≤10 min.

#### NFR-03: Dashboard Responsiveness
- **Requirement:** Dashboard initial load ≤5s; filter application ≤2s on 10,000-record dataset.

### 4.2 Reliability

#### NFR-04: Error Recovery
- **Requirement:** Any transient failure (network, API, disk) shall be retried automatically. The pipeline shall be resumable from the last successful record without reprocessing completed work.
- **Acceptance Test:** Kill the pipeline mid-run, restart, verify it resumes correctly.

#### NFR-05: Idempotency
- **Requirement:** Running the ingestion twice with identical parameters shall produce identical database state. No duplicate records.
- **Acceptance Test:** Run twice, count records: must be identical.

### 4.3 Security

#### NFR-06: No PHI Handling
- **Requirement:** The system shall not store, process, or log any Protected Health Information (PHI). If PHI is detected in input data, it shall be logged as a critical error and the record excluded.
- **Acceptance Test:** Manual review confirms MAUDE data is de-identified; spot check for names/MRNs.

#### NFR-07: API Key Management
- **Requirement:** API keys (Anthropic, openFDA) shall be loaded from environment variables or a `.env` file only. They shall never be hardcoded, logged, or committed to Git.
- **Acceptance Test:** `git log -p` search for common API key patterns returns zero matches. `.env` in `.gitignore`.

#### NFR-08: Logging Hygiene
- **Requirement:** Logs shall contain no API keys, no PHI, and no full narrative text (truncated to first 100 chars if needed for debugging).
- **Acceptance Test:** Log inspection shows no sensitive content.

### 4.4 Usability

#### NFR-09: CLI Clarity
- **Requirement:** All CLI commands shall support `--help` with clear usage examples. Errors shall be human-readable, not raw stack traces.
- **Acceptance Test:** `safesignal --help` and `safesignal ingest --help` display useful content.

#### NFR-10: Time-to-First-Result
- **Requirement:** A new user following the README shall be able to go from `git clone` to seeing their first dashboard view in ≤15 minutes, excluding API key provisioning.
- **Acceptance Test:** Stranger test — actually time someone unfamiliar with the project.

### 4.5 Maintainability

#### NFR-11: Type Safety
- **Requirement:** All Python code in `src/` shall pass `mypy --strict` without errors.
- **Acceptance Test:** CI runs `mypy --strict src/` and passes.

#### NFR-12: Code Formatting
- **Requirement:** All code shall pass `black` and `ruff` checks with default settings.
- **Acceptance Test:** CI runs both; passes.

#### NFR-13: Test Coverage
- **Requirement:** Core extraction and classification logic shall have ≥70% line coverage.
- **Acceptance Test:** `pytest --cov` reports ≥70% for `src/extraction/` and `src/classification/`.

### 4.6 Reproducibility

#### NFR-14: Deterministic Outputs
- **Requirement:** Given identical input and identical Skill versions, extraction shall produce outputs that agree on structured fields ≥95% of the time. (LLMs are non-deterministic; this is the realistic ceiling.)
- **Acceptance Test:** Run same input 10 times; structured fields match ≥95%.

#### NFR-15: Version Pinning
- **Requirement:** All Python dependencies and all Skill versions shall be pinned to exact versions in `pyproject.toml` and `skills/*/VERSION`.
- **Acceptance Test:** Fresh install on new machine produces identical behavior.

### 4.7 Documentation

#### NFR-16: README Completeness
- **Requirement:** The README shall contain: project description, motivation, architecture diagram, install steps, usage examples, demo GIF, contribution guide link, license.
- **Acceptance Test:** Checklist review by stranger.

#### NFR-17: Inline Documentation
- **Requirement:** Every public function shall have a Google-style docstring with purpose, args, returns, and one example where non-trivial.
- **Acceptance Test:** `pydocstyle src/` passes.

---

## 5. Data Requirements

### 5.1 Data Sources

#### DR-01: Input Data Sources
- **Primary:** openFDA Device Event API — `https://api.fda.gov/device/event.json`
- **Secondary:** openFDA 510(k) API — `https://api.fda.gov/device/510k.json`
- **Tertiary:** FDA Guidance Document index (scraped from fda.gov)

#### DR-02: Data Access Method
- Public REST API, no authentication required for MAUDE (an API key raises rate limits from 240/min to 120,000/day; recommended for production use).

### 5.2 Output Schemas

#### DR-03: Extraction Output Schema
Defined in `schemas/extraction_output.schema.json`:
```json
{
  "maude_report_id": "string (required)",
  "extraction_timestamp": "ISO-8601 datetime",
  "skill_name": "string",
  "skill_version": "semver string",
  "failure_mode": "string | null",
  "severity": "death | serious_injury | malfunction | other | unknown",
  "patient_outcome": "string | null",
  "device_problem_codes": "array of strings",
  "ai_related_flag": "boolean | null",
  "confidence_score": "number 0.0-1.0",
  "requires_human_review": "boolean",
  "narrative_excerpt": "string (first 500 chars only)",
  "model_used": "string (e.g., claude-opus-4-7)"
}
```

#### DR-04: Classification Output Schema
```json
{
  "maude_report_id": "string",
  "classification_timestamp": "ISO-8601",
  "labels": "array of taxonomy category strings",
  "rationale": "string (max 200 chars)",
  "classifier_version": "semver string",
  "reviewed_by_human": "boolean",
  "human_correction": "object | null"
}
```

#### DR-05: Drift Alert Schema
```json
{
  "alert_id": "UUID",
  "detected_at": "ISO-8601",
  "drift_type": "gradual | sudden | subgroup",
  "affected_metric": "string",
  "magnitude": "number",
  "severity": "low | medium | high | critical",
  "suggested_review_action": "string"
}
```

### 5.3 Storage

#### DR-06: Storage Layer
- **Database:** SQLite (file-based, `safesignal.db`)
- **Tables (minimum):** `raw_reports`, `normalized_events`, `extractions`, `classifications`, `drift_alerts`, `llm_audit_log`

#### DR-07: Data Retention
- Raw MAUDE data retained indefinitely.
- LLM audit logs retained for full project lifetime (audit trail requirement).
- Re-processable outputs (extractions, classifications) may be regenerated.

### 5.4 Data Quality

#### DR-08: Handling Missing Fields
- MAUDE reports with missing `event_description` shall be logged and skipped (not fed to extraction).
- Reports with missing `date_received` shall use `date_of_event` as fallback; if both missing, flag as `date_unknown`.

#### DR-09: Data Integrity Checks
- On every ingestion run, system shall log: total records fetched, total stored, total skipped, reasons for skips.

---

## 6. Acceptance Criteria (Roll-Up)

The system is accepted for release when all of the following are true:

### 6.1 Requirements Coverage
- [ ] All "Must" priority FRs pass their acceptance tests
- [ ] ≥90% of "Should" priority FRs pass
- [ ] All NFRs met except where explicitly documented as "future work"

### 6.2 Gold Standard Accuracy
- [ ] Hand-labeled 100-record gold set achieves:
  - Extraction field accuracy ≥90%
  - Classification agreement ≥80% with human reviewer
  - Citation verification accuracy 100%

### 6.3 End-to-End Demo
- [ ] A stranger can clone the repo, install dependencies, configure API keys, ingest data for product code QIH, and view results in the dashboard in ≤15 minutes (excluding data ingestion wall-clock time).

### 6.4 Zero-Hallucination Audit
- [ ] 200 randomly sampled outputs contain zero unverified regulatory citations.

### 6.5 Artifact Completeness
- [ ] All deliverables in Document 2 §6 exist.

---

## 7. Out-of-Scope Requirements (Explicitly Not in v1)

Listed here so they are remembered as deferred, not forgotten.

- User authentication and authorization
- Multi-tenant support
- Real-time streaming ingestion
- Active learning loop for classifier improvement
- HIPAA or 21 CFR Part 11 compliance certification
- Integration with commercial eQMS platforms
- Mobile or responsive UI
- Internationalization / translations
- Fine-tuned custom models (using Claude API only in v1)
- Integration with deployed model telemetry (simulated in v1 via F4)

---

## 8. Requirements Traceability Matrix

| Feature (Doc 2) | Functional Requirements | Non-Functional Requirements | Data Requirements |
|---|---|---|---|
| F1 — Ingestion | FR-01 to FR-07 | NFR-01, NFR-04, NFR-05 | DR-01, DR-02, DR-06, DR-08, DR-09 |
| F2 — Extraction | FR-08 to FR-12 | NFR-02, NFR-14 | DR-03 |
| F3 — Classification | FR-13 to FR-16 | NFR-14 | DR-04 |
| F4 — Drift Simulation | FR-17 to FR-20 | — | DR-05 |
| F5 — Citation Verifier | FR-21 to FR-24 | — | — |
| F6 — Dashboard | FR-25 to FR-29 | NFR-03, NFR-10 | — |
| F7 — PSUR Report | FR-30 to FR-33 | — | — |
| Cross-cutting | — | NFR-06 to NFR-13, NFR-15 to NFR-17 | DR-07 |

Every requirement in this document traces to at least one feature or cross-cutting concern.

---

## 9. Change Control

Changes to requirements follow the same process as the Charter (Document 2 §14):
1. Open a GitHub issue tagged `requirements-change`
2. Justify against goal ("does this improve my job prospects?")
3. Update traceability matrix
4. Version bump

---

## 10. What This Document Is and Is Not

**IS:**
- The testable specification of system behavior
- The basis for every acceptance test and unit test
- The reference during implementation ("which FR does this code satisfy?")

**IS NOT:**
- Architecture or design (→ Document 5)
- Implementation guide (→ the code itself)
- Weekly plan (→ Document 7)

---

**End of Document 3.**
