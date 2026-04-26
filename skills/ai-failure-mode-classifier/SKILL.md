# Skill: ai-failure-mode-classifier

**Version:** 1.0.0
**Last Updated:** 2026-04-26
**Owner:** Sai Charan Kondapally
**Status:** Active
**Depends On:** `regulatory-citation-verifier` (v≥1.0.0), `maude-narrative-extractor` (v≥1.0.0)

---

## 1. Description

This Skill assigns each MAUDE record (post-extraction) to **one of 11
mutually-exclusive AI failure mode categories**. It is the central act that
makes SafeSignal worth building: MAUDE's native `event_type` field has 4
options (death / injury / malfunction / other), none of which describe *how
the AI failed*. This Skill produces the AI-specific taxonomy MAUDE cannot.

It is downstream of `maude-narrative-extractor` (which decides whether the
event is plausibly AI-related at all) and `severity-triage` (which decides
clinical impact). This Skill answers a different question: **given that a
record has been extracted, what kind of AI failure is this?**

Categories are deliberately scoped so that one category gets the dominant
signal — multi-label classification adds reviewer cognitive load without
improving regulatory utility. Records that genuinely describe two failure
modes get the most causally-proximate one with the secondary noted in
`secondary_modes_observed`.

---

## 2. When to Use

### Activate this Skill when:
- A MAUDE record has been processed by `maude-narrative-extractor` AND
  - `ai_related_flag == true`, OR
  - `ai_related_flag == null` AND product_code is a known AI/ML code (the
    classifier may decide `not_ai_related` and that is a valid output)
- Re-classifying a batch after a taxonomy update (with version bump)
- Building the AI-failure cohort for the dashboard (F6) or PSUR (F7)

### Do NOT activate this Skill when:
- `ai_related_flag == false` from the extractor → the record is already
  classified as non-AI; trust the extractor and skip
- The extractor's `confidence_score < 0.5` → re-run the extractor first;
  classifying low-confidence extractions amplifies error
- For severity assignment — that's `severity-triage`'s job

---

## 3. Inputs

### Required Input
```json
{
  "maude_report_id": "string",
  "event_description": "string (may be empty)",
  "mfr_narrative": "string (may be empty)",
  "extracted_failure_mode": "string | null (from maude-narrative-extractor)",
  "extracted_device_problem": "string | null",
  "ai_related_flag": "boolean | null (from extractor)",
  "ai_related_rationale": "string",
  "product_code": "string"
}
```

### Input Preprocessing
- Concatenate narrative fields (same separator as `maude-narrative-extractor`).
- Truncate to 6,000 chars at word boundary.
- Pass the extractor's `failure_mode` and `device_problem` as additional
  context to the LLM, but the classifier MUST ground its decision in the
  narrative — not just the extractor's summary.

---

## 4. Outputs

### Output Schema (see `schemas/output.schema.json`)
```json
{
  "maude_report_id": "string",
  "classification_ts": "ISO-8601 UTC",
  "skill_name": "ai-failure-mode-classifier",
  "skill_version": "1.0.0",
  "model_used": "string",

  "failure_mode_category": "one of 11 enum values (see §5)",
  "category_rationale": "string ≤300 chars — must cite narrative evidence",
  "evidence_quotes": ["≤2 verbatim narrative substrings"],

  "secondary_modes_observed": ["array of 0–2 additional categories observed"],
  "is_multi_mode": "boolean — true if secondary_modes_observed is non-empty",

  "confidence_score": "number 0.0–0.95",
  "requires_human_review": "boolean",
  "classification_notes": "string | null"
}
```

### The 11 Categories (mutually exclusive primary assignment)

| # | Category | Definition | Typical narrative cue |
|---|---|---|---|
| 1 | `false_negative_clinical` | AI missed a finding that a clinician (or follow-up) later identified as present | "Algorithm did not flag…", "missed by CAD…", "subsequent review identified…" |
| 2 | `false_positive_clinical` | AI flagged a finding that follow-up confirmed was not present | "Flagged as positive but follow-up imaging negative…" |
| 3 | `algorithm_drift` | Performance degradation over time, batch-level (not a single false-negative event) | "Sensitivity has declined since deployment…", "Performance below labeling…", "trended downward over Q3" |
| 4 | `data_pipeline_error` | Wrong / corrupted / mis-routed input data caused incorrect output (DICOM corruption, misrouted study, wrong-patient merge) | "Patient records merged automatically", "DICOM header malformed", "image was for wrong patient" |
| 5 | `automation_bias` | Clinician deferred to AI output despite contradicting evidence; AI output drove the wrong decision | "Physician relied on AI flag…", "treatment initiated based on alert…", "AI override not exercised…" |
| 6 | `software_bug` | Deterministic non-ML software defect (not the trained model) — UI freeze, crash, deterministic miscalculation | "Software crashed mid-read", "UI hung", "calculation error in scoring module" |
| 7 | `output_validation_error` | Algorithm produced syntactically wrong output that failed downstream validation (missing fields, malformed report, NaN scores) | "Score returned as NaN", "Outbound report missing required field", "output failed schema check" |
| 8 | `integration_failure` | AI worked, downstream system did not (PACS rejected, RIS did not display, alert did not fire) | "Alert was generated but not displayed", "PACS did not receive…", "results not propagated to EMR" |
| 9 | `bias_or_fairness` | Performance differs by patient subgroup (age, sex, race, anatomy, ethnicity) and the gap is identified | "Worse performance in pediatric population", "Sensitivity lower in dense breast tissue", "subgroup analysis revealed…" |
| 10 | `other_ai_related` | Genuinely AI-related but does not fit any of the above. Use sparingly; ≥10% of outputs in this category triggers a taxonomy review. | "Algorithm produced unexpected behavior in edge case not covered by labeling" |
| 11 | `not_ai_related` | After narrative review, the failure has no AI/algorithm component (extractor's flag was wrong or null). Honest classifier output, not a failure of this Skill. | "Power cord damaged", "Display screen cracked", purely mechanical |

---

## 5. Procedure

1. **Validate input.**
   - If `maude_report_id` missing → return error `MISSING_ID`.
   - If `extracted_failure_mode` AND `extracted_device_problem` AND narrative
     are all empty/null → return error `INSUFFICIENT_INPUT`.

2. **Preprocess narrative** per §3.

3. **Apply skip rule (no LLM needed).**
   - If `ai_related_flag == false` from the extractor with confidence ≥ 0.80
     AND the narrative has no software-related keywords → return
     `failure_mode_category = "not_ai_related"`, confidence = 0.90,
     `requires_human_review = false`. (This Skill exists to make taxonomy
     decisions, not to second-guess the upstream extractor on clear cases.)

4. **Call LLM with the §6 rules.**
   - Prompt: narrative + extractor's `failure_mode` + `device_problem` +
     the 11-category schema with definitions and cues.
   - Require: chosen category, rationale ≤300 chars, ≤2 evidence quotes,
     up to 2 secondary modes if genuinely present.

5. **Validate LLM output.**
   - `failure_mode_category` MUST be one of the 11 enum values. Any other
     value → set to `other_ai_related`, `requires_human_review = true`,
     log anomaly.
   - `evidence_quotes` MUST be substrings of the input narrative
     (or of `extracted_failure_mode` / `extracted_device_problem` if narrative
     is empty). Drop fabricated quotes; lower confidence by 0.10 each.
   - `secondary_modes_observed` MUST not include the primary category and
     MUST not exceed 2 entries.

6. **Apply consistency rules.**
   - If primary == `not_ai_related`: `secondary_modes_observed` MUST be empty
     and `is_multi_mode = false`.
   - If primary == `algorithm_drift`: at least one evidence quote should
     reference a temporal pattern ("over time", "since deployment",
     "trended", "declined"). If none, downgrade confidence by 0.10.
   - If primary == `automation_bias`: at least one evidence quote should
     reference physician/staff action driven by the AI output. If none,
     reconsider — automation bias requires both an AI output AND a human
     deferral to it.
   - If primary == `bias_or_fairness`: requires identification of the
     subgroup. Without it, reclassify as `other_ai_related`.

7. **Compute `confidence_score`.**
   - ≥0.85 — narrative explicitly supports the category cue; minimal
     ambiguity
   - 0.70–0.84 — category clear from extractor's failure_mode but narrative
     thinner
   - 0.55–0.69 — multi-mode genuinely possible; primary chosen by causal
     proximity but other modes plausible
   - <0.55 — `requires_human_review = true`; consider `other_ai_related`
     as a fallback if no category fits cleanly

8. **Set `requires_human_review`.**
   - `true` if `confidence_score < 0.65`
   - `true` if `failure_mode_category == "other_ai_related"` (always —
     this category is a flag for taxonomy review)
   - `true` if `is_multi_mode == true` AND any secondary mode has
     comparable evidence to the primary
   - `true` if extractor's `ai_related_flag` was `null` AND classifier
     chose anything other than `not_ai_related`
   - `false` otherwise

9. **Citation check (MANDATORY).**
   - Pass `category_rationale`, `classification_notes`, and each
     `evidence_quotes` entry through `regulatory-citation-verifier`.
   - On `safe_to_emit == false` → replace offending field with
     `[CLASSIFICATION ERROR: unverified citation]` and set
     `requires_human_review = true`.

10. **Return** the full output object.

---

## 6. Rules & Constraints

### NEVER
- NEVER assign a category based on the product code alone. Product code
  is a prior, not evidence.
- NEVER assign `algorithm_drift` from a single-event narrative. Drift is a
  *trend* claim and requires temporal evidence.
- NEVER assign `automation_bias` without evidence that a clinician deferred
  to the AI output (not just that the AI was used).
- NEVER assign `bias_or_fairness` without an identified subgroup. "AI
  performed poorly" is not bias evidence; "AI performed poorly in pediatric
  cohort" is.
- NEVER fabricate evidence quotes. Verbatim substrings only.
- NEVER use Claude's training-data knowledge of specific devices to assign
  categories. The narrative is the ground truth.
- NEVER return `confidence_score = 1.0`. Cap at 0.95.
- NEVER assign more than one primary category. Use `secondary_modes_observed`
  for genuine multi-mode cases.

### ALWAYS
- ALWAYS provide a category rationale that references narrative evidence.
- ALWAYS prefer `other_ai_related` (with `requires_human_review = true`)
  over forcing a record into a category that does not fit. Honest "doesn't
  fit" is better than wrong taxonomy.
- ALWAYS pass output through `regulatory-citation-verifier`.
- ALWAYS honor the upstream extractor's `ai_related_flag = false` when its
  confidence is high — this Skill does not exist to second-guess clear
  hardware failures.

### EDGE CASES

| Case | Handling |
|---|---|
| Narrative describes both a false negative AND automation bias (clinician relied on the negative AI output) | Primary = `false_negative_clinical` (causally upstream), secondary = `automation_bias`, `is_multi_mode = true` |
| Extractor's `failure_mode` says "false negative" but narrative is purely about a software crash | Trust the narrative: `software_bug`. Note the extractor disagreement in `classification_notes`. |
| Narrative describes wrong-patient record merge | `data_pipeline_error` (this is the canonical example) |
| Narrative says "algorithm performed unexpectedly" with no further detail | `other_ai_related` with low confidence and `requires_human_review = true` |
| `ai_related_flag` was `null` and classifier finds clear hardware cause | Return `not_ai_related` with rationale; this corrects the extractor's uncertainty |
| Narrative describes a recall or safety communication, not an event | Return error `OUT_OF_SCOPE`; recalls go through a different pipeline |

---

## 7. Examples

See `examples/good.jsonl` (5 cases) and `examples/bad.jsonl` (5 anti-examples).

The good examples cover: clear false negative, false positive with automation
bias as secondary, data pipeline error (wrong-patient merge), software bug
on AI-hosting workstation classified as `not_ai_related`, and an algorithm
drift case with proper temporal evidence.

The bad examples cover: drift assigned from a single event, automation bias
without clinician deferral evidence, bias_or_fairness without an identified
subgroup, fabricated quote, and category-from-product-code.

---

## 8. Validation

This Skill is validated against `tests/gold_set/ai_failure_classifier_gold_100.jsonl`.

### Passing criteria:
- **Top-1 accuracy ≥80%** across the gold set
- **Top-2 accuracy ≥92%** (primary OR secondary matches gold label)
- **`other_ai_related` rate ≤15%** of outputs (higher means taxonomy is
  too narrow; trigger taxonomy review)
- **`not_ai_related` rate matches extractor's `ai_related_flag = false` rate
  within ±5 pp** (consistency check across the two Skills)
- **Zero fabricated evidence quotes** on a 50-sample blind audit

### Test structure:
- 30 records pre-labeled to one of categories 1–4 (most common modes)
- 25 records pre-labeled to categories 5–8 (mid-frequency modes)
- 15 records pre-labeled to `bias_or_fairness` or `algorithm_drift` (rare,
  high-stakes)
- 20 records pre-labeled to `other_ai_related` or `not_ai_related`
- 10 adversarial records (multi-mode, ambiguous, training-data baits)

**This Skill is not released to production until the gold-set validation
passes at the thresholds above.**

---

## 9. References

- Document 3 §3.4 (Feature F3 — Classification requirements)
- Document 5 §7 (Skills architecture)
- Babic et al., *npj Digital Medicine* (2025) — AI/ML device adverse event
  patterns
- FDA "AI-Enabled Device Software Functions" guidance (2025 final)
- IMDRF Medical Device Adverse Event Terminology

---

## 10. Related Skills

| Skill | Relationship |
|---|---|
| `regulatory-citation-verifier` | Hard dependency. Runs on every string field before emission. |
| `maude-narrative-extractor` | Upstream. Provides `ai_related_flag`, `failure_mode`, `device_problem`. |
| `severity-triage` | Sibling. Severity does not affect classification. |
| `drift-analysis-interpreter` | Downstream consumer. `algorithm_drift` cases feed drift cohort prep. |
| `psur-report-drafter` | Downstream. Categories drive PSUR taxonomy tables. |

---

## 11. Changelog

- **v1.0.0** (2026-04-26) — Initial release. 11-category taxonomy, mutually
  exclusive primary with up to 2 secondary observations, mandatory citation
  verification, consistency rules for drift / automation bias / bias_or_fairness.

### Planned for v1.1.0
- Add `cybersecurity_related` category if MAUDE patterns emerge
- Confidence calibration against gold set (Platt scaling)
- Cross-Skill consistency check with `severity-triage` on
  `false_negative_clinical` + `serious_injury` co-occurrence patterns
