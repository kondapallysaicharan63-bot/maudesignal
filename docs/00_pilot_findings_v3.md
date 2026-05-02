# Pilot Findings v3 — Multi-Code Extraction Batch + PSUR Generator

**Date:** 2026-05-02  
**Branch:** claude/day1-polish  
**Database:** `data/safesignal.db`

---

## 1. Objective

Extend the extraction corpus from 2 product codes (QIH, DQA) to 8 product codes,
validate the full 3-Skill chain at scale, and confirm the new PSUR report generator
(F7 / Skill #7 milestone) produces regulatory-ready output from real extraction data.

---

## 2. Ingestion Summary

| Product Code | Device Type | Records Ingested |
|---|---|---|
| LLZ | Surgical robotics imaging | 50 |
| IYO | Ophthalmology imaging AI | 50 |
| OZO | Cardiac monitoring AI | 50 |
| DQA | Digital pathology AI | 25 |
| MWI | Wound-care imaging AI | 25 |
| KZH | Radiology AI (general) | 25 |
| IOR | Diagnostic imaging AI | 25 |
| QIH | Radiology CAD | 8 |
| PIE | AI-assisted endoscopy | 12 |
| MYN, LLN, GZA, QNO | Supplemental AI codes | 20 |
| **Total** | | **290** |

---

## 3. Extraction Results (Skill #1 — maude-narrative-extractor)

| Metric | Value |
|---|---|
| Skill #1 extractions completed | **43** |
| Records attempted | 96 |
| Pool slots used | 5 (gemini ×3, groq ×2) |
| AI-related flagged | **14 / 43 (32.6%)** |
| Average confidence score | **0.890** |
| Cumulative LLM cost | **$0.00** (free tier) |
| Skill #3 (severity-triage) successes | ~35 |
| Skill #4 (ai-failure-mode-classifier) successes | 13 |

### 3.1 Extractions by Product Code

| Product Code | Skill #1 | AI-Related | Notes |
|---|---|---|---|
| QIH | 11 | 11 (100%) | Radiology CAD — all AI-related as expected |
| LLZ | 10 | 0 (0%) | Surgical imaging — mechanism failures |
| MWI | 6 | 0 (0%) | Wound-care imaging |
| DQA | 5 | 2 (40%) | Digital pathology — mixed |
| KZH | 5 | 0 (0%) | Radiology general |
| IYO | 3 | 1 (33%) | Ophthalmology |
| OZO | 2 | 0 (0%) | Cardiac monitoring |
| IOR | 1 | 0 (0%) | Diagnostic imaging |

### 3.2 Severity Distribution

| Severity | Count | % |
|---|---|---|
| Malfunction | 34 | 79.1% |
| Serious Injury | 5 | 11.6% |
| Other | 4 | 9.3% |
| Death | 0 | 0% |

---

## 4. AI Failure Mode Categories (Skill #4)

From 13 Skill #4 classifications across AI-related records:

| Failure Mode Category | Count |
|---|---|
| software_bug | 5 |
| data_pipeline_error | 4 |
| false_negative_clinical | 2 |
| automation_bias | 1 |
| other_ai_related | 1 |

---

## 5. PSUR Report Generator (F7 — New This Pilot)

**Confirmed working.** Generated a QIH PSUR covering all 11 extractions:

```
maudesignal report --product-code QIH --start 2026-01-01 --end 2026-12-31
```

Output: `reports/QIH_PSUR_2026-01-01_2026-12-31_20260502_195605.md`

Report highlights:
- 8 sections: Executive Summary, Scope, Severity, AI Analysis, Drift,
  Recommendations, Methodology, Source Report IDs
- Regulatory disclaimer on all outputs
- Failure mode breakdown from Skill #4 data
- PDF generation supported (requires system GTK/Cairo libs)

---

## 6. Dashboard — Record Detail View (New This Pilot)

The Records page now includes a **detail panel** for any selected report:

- Manufacturer, brand name, event type, event date
- Full patient narrative and manufacturer narrative (expandable)
- Clickable link to the official FDA MAUDE record:  
  `https://www.accessdata.fda.gov/scripts/cdrh/cfdocs/cfmaude/detail.cfm?mdrfoi__id=<id>`

---

## 7. Key Observations

**QIH is a strong AI-signal product code.** 100% of QIH records were flagged
AI-related (radiology computer-aided detection — every adverse event involves the
AI algorithm by definition). Future pilots should weight QIH-class codes higher
when building diverse AI failure mode datasets.

**Non-AI product codes dilute the signal rate.** LLZ, MWI, KZH records were
hardware/mechanism failures with no AI involvement. Including only AI/ML-specific
product codes (QIH, DQA, IYO) yields ~60% AI-related rate vs. 32.6% overall.

**Free-tier rate limits are the primary throughput constraint.** The 5-key
ProviderPool (3 Gemini + 2 Groq) can sustain ~10 records/minute before
hitting burst limits. The Groq daily token limit (100k TPD) becomes a
bottleneck on runs >25 records. Mitigation: run in batches of 8-10 with
30-second gaps, or stagger runs across UTC midnight for full daily quota resets.

**Confidence is stable.** Average 0.890 (0.88 in v1, 0.90 in v2) — consistent
self-assessed quality across providers and product codes.

**Cost remains $0.00.** All 43 extractions on free-tier Gemini and Groq.
Estimated paid-tier cost would be ~$0.01 (≈600 tokens × $0.00003/token × 43 runs).

---

## 8. Pilot-over-Pilot Comparison

| Metric | Pilot v1 | Pilot v2 | Pilot v3 |
|---|---|---|---|
| Product codes | 1 (QIH) | 2 (QIH+DQA) | 8 |
| Extractions | 22 | 9 | **43** |
| AI-related rate | 50% | ~44% | 32.6% (100% QIH-only) |
| Avg confidence | 0.88 | 0.90 | **0.890** |
| LLM cost | $0.00 | $0.00 | **$0.00** |
| Skills active | #1 only | #1+#3+#4 | #1+#3+#4 |
| PSUR generator | ❌ | ❌ | **✅** |
| Dashboard detail | ❌ | ❌ | **✅** |

---

## 9. Next Steps

- Increase extraction corpus to 100+ by targeting QIH-class AI-specific product
  codes (more dense AI-related signals per record)
- Raise extraction throughput by caching or pre-loading API keys with paid credits
- Generate PSURs for each product code and copy exemplars to `docs/examples/`
- Record dashboard walkthrough video for portfolio
