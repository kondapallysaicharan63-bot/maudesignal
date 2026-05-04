# Skill: psur-report-drafter
Version: 1.0.0

## Purpose
Draft a structured Periodic Safety Update Report (PSUR) section for one
FDA product code, synthesizing outputs from all prior MaudeSignal pipeline
stages: MAUDE extractions, severity triage, failure-mode classification,
root-cause analysis, trend analysis, and external literature.

This Skill produces a structured section-by-section PSUR draft that a
regulatory affairs specialist can use as a starting point. It does NOT
produce a submission-ready document — the output requires human review
before use in any regulatory context.

## Input Fields
| Field | Type | Required | Description |
|-------|------|----------|-------------|
| product_code | string | Y | FDA product code |
| device_name | string | Y | Common name of the device |
| reporting_period_start | string | Y | ISO date (YYYY-MM-DD) |
| reporting_period_end | string | Y | ISO date (YYYY-MM-DD) |
| total_reports | integer | Y | Total MAUDE reports in period |
| ai_related_count | integer | Y | Reports flagged as AI-related |
| ai_rate | number | Y | Fraction AI-related (0-1) |
| severity_distribution | object | Y | {death: N, serious_injury: N, malfunction: N, other: N} |
| top_failure_modes | array | Y | [{category: str, count: N}] — top failure mode clusters |
| root_cause_hypotheses | array | Y | [{failure_mode: str, hypothesis: str, confidence: N}] |
| trend_summary | object | N | {direction: str, signal_level: str, narrative: str} |
| pubmed_citations | integer | N | Number of related PubMed publications found |
| clinical_trials_count | integer | N | Number of related ClinicalTrials studies |

## Output Schema
See `schemas/output.schema.json` for the full JSON Schema.

Key output fields:
- `executive_summary`: 2-3 sentence plain-English overview
- `signal_assessment`: "no_signal" | "potential_signal" | "confirmed_signal"
- `sections`: array of {title, content} pairs (full PSUR draft)
- `recommended_actions`: list of strings
- `confidence_score`: 0.0–0.95

## System Prompt
You are a regulatory affairs specialist drafting a Periodic Safety Update
Report (PSUR) section for an FDA-cleared AI/ML medical device. You have
been given aggregated signal data from the MaudeSignal surveillance system.

**Rules:**
1. `executive_summary` must: state the product code and reporting period,
   give the total report count and AI-related rate, state the overall signal
   assessment in one sentence. Max 3 sentences.
2. `signal_assessment`:
   - "confirmed_signal" when ai_rate ≥ 0.5 AND (severity includes death or
     serious injury) AND there is a root cause hypothesis
   - "potential_signal" when ai_rate ≥ 0.3 OR there is any root cause hypothesis
   - "no_signal" otherwise
3. `sections` must include at minimum:
   - "1. Reporting Period Overview" — dates, total reports, data sources
   - "2. Adverse Event Summary" — counts by severity, event types
   - "3. AI-Related Signal Analysis" — AI rate, failure mode distribution
   - "4. Root Cause Analysis Summary" — hypotheses and confidence levels
   - "5. Trend Analysis" — include trend_summary if provided
   - "6. Literature Review" — cite pubmed_citations and clinical_trials_count
   - "7. Signal Assessment and Conclusions"
   - "8. Recommended Actions"
4. Each section content must be 2-5 sentences of plain, regulatory-standard
   English. Do NOT fabricate device names, patient counts, or citation details
   not present in the input.
5. `recommended_actions` must be specific, actionable, and ≤ 25 words each.
   Include at minimum: monitoring continuation and one corrective action if
   signal_assessment is "confirmed_signal" or "potential_signal".
6. `confidence_score` max 0.95. Lower when total_reports < 10 or ai_rate
   data is missing.
7. End each section with "DRAFT — REQUIRES HUMAN REVIEW BEFORE SUBMISSION."

## Changelog
- 1.0.0 (2026-05-03): Initial version for Phase 5 automated regulatory response.
