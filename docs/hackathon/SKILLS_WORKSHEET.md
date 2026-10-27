# SKILLS WORKSHEET — MaudeSignal + Copilot (Hackathon Build)

**Purpose:** one sheet tracking every Skill — what exists, what is wired,
what is missing, and what we add for the hackathon. Updated daily with the
checklist. "Skill" here = maudesignal's versioned prompt+schema units in
`skills/` (each has a SKILL.md + output schema), NOT generic AI features.

## A. EXISTING SKILLS (pre-hackathon — OLD work, never claimed as new)

| # | Skill | Version | Status (doc) | Wired in code? | Purpose (one line) | Depends on |
|---|---|---|---|---|---|---|
| 1 | maude-narrative-extractor | 1.0.0 | Active | YES — extraction chain step 1 | Extract structured fields from a MAUDE narrative | regulatory-citation-verifier |
| 2 | severity-triage | 1.0.0 | Active | YES — chain step 2 | Death / serious injury / malfunction / other per FDA MDR | regulatory-citation-verifier |
| 3 | ai-failure-mode-classifier | 1.0.0 | Active | YES — chain step 3 (skipped when not AI-related) | 11-category mutually-exclusive AI failure taxonomy + rationale + evidence quotes | regulatory-citation-verifier, narrative-extractor |
| 4 | root-cause-analyzer | 1.0.0 | Active | YES — analysis/root_cause.py, clusters of 3–10 excerpts | Root cause per failure-mode cluster | classifier, triage |
| 5 | drift-analysis-interpreter | 1.0.0 | "Skeleton (not wired)" in its doc — STALE | YES — wired via CLI `drift` + drift/interpreter.py (audit verified; doc is outdated) | Turn KS/PSI drift stats into regulatory language | regulatory-citation-verifier |
| 6 | trend-interpreter | 1.0.0 | Active | YES — forecasting/trend_detector.py | Turn Mann-Kendall + regression stats into PSUR-ready narrative | (stats upstream) |
| 7 | psur-report-drafter | 1.1.0 | Active | YES — report/psur_generator.py → Jinja2 → WeasyPrint PDF, stamped DRAFT — REQUIRES HUMAN REVIEW | Draft a PSUR section from all prior pipeline outputs | all prior stages |
| 8 | regulatory-citation-verifier | 1.0.0 | Active, CRITICAL — every downstream skill depends on it | NO — doc + exception class only; ZERO call sites in `src/`; validation test set (`tests/fixtures/citation_verifier_test_set.jsonl`) and guidance index (`data/fda_guidance_index.json`) DO NOT EXIST | Verify every citation (K-numbers via openFDA 510k, PMA, CFR regex, guidance index) or block it | — (it is the dependency) |

**Key fact:** every skill in rows 1–7 lists the citation verifier as a
dependency — but the verifier itself never runs. Building it as code
(Day 3) unlocks the whole set. That is the hackathon's trust story.

## B. MISSING SKILLS (planned, not built — OLD plan, NEW build if we do it)

| Skill | Status | Plan |
|---|---|---|
| fda-guidance-retriever | Planned in CLAUDE.md §7, never built | Build if time allows after Day 6; grounded retrieval over FDA guidance. NOT on the critical path — copilot retrieval works on stored signals first. |

## C. NEW COPILOT SKILLS TO ADD (hackathon work — NEW, Day 3–4)

| Skill | Purpose | Source pattern | Day | Status |
|---|---|---|---|---|
| signal-query | Copilot retrieves ranked signals from the store for a plain-English question | Aethel `tools/signal_query` | Day 3 | TO BUILD |
| capa-action | "Open a CAPA for this signal" — forward-only state machine + audit-first | Aethel `routes/capa.py` | Day 4 | TO BUILD |
| complaint-action | Advance a complaint through OPEN → CLOSED with audit trail | Aethel `routes/complaints.py` | Day 4 | TO BUILD |
| alert-action | File an alert via the notification rule engine (webhook) | Aethel `notification/rules.py` | Day 4–6 | TO BUILD |
| deadline-check | Check reporting deadlines/due dates for a signal or report | Aethel `tools/deadline_check` | Day 4 | TO BUILD |

Aethel's full tool set for reference (port selectively, not all):
signal_query, complaint_search, deadline_check, report_status,
analytics_query, product_lookup — all with advisory-only prompts and
`requires_human_review = True` on every answer.

## D. HOW SKILLS FLOW IN THE PRODUCT

1. Ingest (openFDA) → raw reports stored.
2. Extract: narrative → triage → classifier (Skills 1–3), JSON-validated,
   audit-logged, cost-capped. **NEW:** citation verifier runs here as code.
3. Analyze: root-cause (4), drift (5), trend (6).
4. Report: PSUR draft (7), human review gate.
5. Copilot (NEW): question → signal-query (C) → grounded answer with
   verified citations → optional actions (CAPA / alert / deadline) with
   audit trail. Daily monitor (NEW) repeats steps 1–3 automatically.

## E. WORKSHEET RULES

- Status column is the truth: if code doesn't call it, it is NOT "done",
  whatever the doc says (see skill 5's stale doc, skill 8's paper gate).
- Nothing here is a claim for the submission unless its Status is
  "wired + tested" with a test or live run behind it.
- Update this sheet every evening with the checklist. Missed skills roll
  to the next day explicitly.

## F. ADOPTED (independent review 2026-10-26 — adopted by Charan 2026-10-26)

Adopted into the day plan (WORKFLOW.md §6). Build status is tracked by
day as each item lands.

| Skill / feature | Purpose | Day | Status |
|---|---|---|---|
| claim-verifier (gate upgrade) | Recompute every number from stored records; verbatim-match every quote to a record ID; block on mismatch — gate checks claims, not just citation existence | Day 3 (inside gate) | ADOPTED |
| deterioration-detector | Define + compute: new-signal (first-seen code/mode), spike (count vs. trailing 4-week baseline), escalation (severity rose) → "3 new, 1 worsening" digest | Day 6 | ADOPTED |
| voice-query | Muse Voice Transcribe: speak a question → copilot answers; grant-free second Meta touchpoint (verify billing vs. $150 first) | Day 4–5 | ADOPTED |
| signal-compare | "Device X vs. its predicate/competitor product code?" from existing 510k catalog + stored signals | Day 4 | ADOPTED |
| overnight-digest | Monitor writes a dated digest (new, worsening, top alert, PSUR link); dashboard gets an "Overnight" page | Day 6 | ADOPTED |
| conversation-memory | Copilot remembers last product code/signal so follow-ups work (Streamlit session state) | Day 4 | ADOPTED |
| gate-adversarial-test-set | 30–50 cases: fake K-number, right K-number wrong device, hallucinated CFR, drifted quote, stale number | Day 3 | ADOPTED |
| accuracy-sample | Hand-check 20 extractions field-by-field; report one honest number (e.g., "19/20 fields correct") | Day 7 | ADOPTED |
| scheduled-monitor-action | Daily monitor as a GitHub Actions cron on the public repo, digest committed as artifact (capped: max 20 new records/day) | Day 6 | ADOPTED |
| rank-explainer | Every ranked signal carries its rank reason (severity × count × recency) | Day 3–4 | ADOPTED |

Cuts adopted: complaint-action (no complaint entity exists in
maudesignal); Day 6 triple-source → MHRA only; Spark Open demoted to
stretch goal; Aethel port simplified to one pattern module (forward-only
+ audit-first) applied to CAPA + alerts; deployment spike moved to Day
2–3; demo dataset seeded on Groq first, Meta proven on a subset before
becoming default; gate spec written Day 2 before Day 3 build; video
restructured as one analyst's Monday-morning story ending on an action,
not the drift chart; deployed public app stored-first, no key.
