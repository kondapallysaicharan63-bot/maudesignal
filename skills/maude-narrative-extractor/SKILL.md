# Skill: maude-narrative-extractor

**Version:** 1.0.0
**Last Updated:** 2026-04-23
**Owner:** [Your Name]
**Status:** Active
**Depends On:** `regulatory-citation-verifier` (v≥1.0.0)

---

## 1. Description

This Skill reads the unstructured "Event Description" and "Manufacturer Narrative" text of a single MAUDE Medical Device Report (MDR) and extracts a structured record containing the failure mode, severity, patient outcome, device problem, AI-relatedness, and a confidence score.

It is the foundation on which every downstream Skill depends. Extraction quality directly determines classification quality, drift interpretation quality, and PSUR report quality.

**This Skill does NOT classify events into the AI failure taxonomy.** That is the job of `ai-failure-mode-classifier`. This Skill's `ai_related_flag` is a boolean signal only; the taxonomy assignment is a separate, specialized step.

---

## 2. When to Use

### Activate this Skill when:
- Processing a MAUDE record that has been ingested via the F1 ingestion module
- The record has a non-empty `event_description` or `mfr_narrative` field
- The record has passed data-quality checks (not flagged as corrupt or missing critical fields)
- Running the gold-set evaluation loop (benchmarking accuracy)

### Do NOT activate this Skill when:
- The input is not a MAUDE record (e.g., a recall notice, a 510(k) summary, a warning letter — each has its own extractor)
- Both narrative fields are missing or empty (log and skip the record, per DR-08)
- The record is a duplicate already extracted at the same Skill version (use cache)
- You are classifying into the AI failure taxonomy — use `ai-failure-mode-classifier` instead

---

## 3. Inputs

### Required Input
```json
{
  "maude_report_id": "string - unique MAUDE MDR identifier",
  "event_description": "string - free-text clinical narrative from the reporter",
  "mfr_narrative": "string - manufacturer's investigation narrative (may be empty)",
  "event_type": "string - MAUDE's native event type (death|injury|malfunction|other)",
  "product_code": "string - 3-character FDA product code (e.g., QIH)",
  "device_problem_codes": "array of IMDRF codes (may be empty)",
  "brand_name": "string - device brand name from MAUDE",
  "manufacturer": "string - reporting manufacturer"
}
```

### Input Preprocessing
- If `event_description` and `mfr_narrative` both present, they are concatenated with separator `\n\n---\nMANUFACTURER NARRATIVE:\n` before extraction.
- Truncate combined narrative to 8,000 characters at word boundary (Claude context budget). If truncated, set `narrative_truncated=true`.
- Strip PHI markers if present (MAUDE is already de-identified but double-check for stray names/MRNs per NFR-06; if found, log CRITICAL and skip).

---

## 4. Outputs

### Output Schema (see `schemas/output.schema.json`)
```json
{
  "maude_report_id": "string (matches input)",
  "extraction_ts": "ISO-8601 UTC",
  "skill_name": "maude-narrative-extractor",
  "skill_version": "1.0.0",
  "model_used": "string (e.g., claude-sonnet-4-6)",

  "failure_mode": "string | null (≤200 chars; short noun phrase)",
  "severity": "death | serious_injury | malfunction | other | unknown",
  "patient_outcome": "string | null (≤200 chars)",
  "device_problem": "string | null (≤200 chars; distinct from failure_mode)",

  "ai_related_flag": "true | false | null",
  "ai_related_rationale": "string ≤200 chars explaining the flag decision",

  "confidence_score": "number 0.0–1.0",
  "requires_human_review": "boolean",

  "narrative_excerpt": "string (first 500 chars of combined narrative)",
  "narrative_truncated": "boolean",

  "extraction_notes": "string | null (any caveats, ambiguities, or flags)"
}
```

### Field Definitions

| Field | Meaning | Format |
|---|---|---|
| `failure_mode` | What failed — a short noun phrase describing the proximate failure | "False negative on stroke detection" |
| `severity` | Standardized severity — see §5 procedure step 4 | Enum |
| `patient_outcome` | What happened to the patient | "Delayed diagnosis; patient recovered" |
| `device_problem` | What the device did wrong (device-centric vs. outcome-centric) | "Algorithm failed to flag hemorrhage" |
| `ai_related_flag` | Is this plausibly an AI/algorithm-related issue? | `true`/`false`/`null` |
| `ai_related_rationale` | Why the flag was set as it was | Short explanation |
| `confidence_score` | Extraction's self-assessed confidence | 0.0 (unsure) to 1.0 (certain) |

---

## 5. Procedure

1. **Validate input.**
   - If `event_description` and `mfr_narrative` are both empty/null → return error `MISSING_NARRATIVE`.
   - If `maude_report_id` is missing → return error `MISSING_ID`.

2. **Preprocess narrative.**
   - Concatenate `event_description` + `mfr_narrative` with the separator shown in §3.
   - Truncate to 8,000 chars on word boundary.
   - Record whether truncation occurred.

3. **Extract `failure_mode`.**
   - Identify the single most specific proximate failure described.
   - Write as a noun phrase, ≤200 characters.
   - If the narrative describes multiple failures, pick the one causally closest to patient impact.
   - If no failure is clearly described (e.g., narrative is only "Device returned for analysis"), return `null` and lower confidence.

4. **Extract `severity`.**
   - Map to FDA MDR categories:
     - `death` — narrative explicitly states patient death OR MAUDE `event_type == "death"`
     - `serious_injury` — significant injury, hospitalization, or permanent impairment
     - `malfunction` — device failed but no injury (mapped to MAUDE `event_type == "malfunction"`)
     - `other` — MAUDE `event_type == "other"`
     - `unknown` — narrative is ambiguous AND MAUDE `event_type` is missing
   - Prefer explicit narrative evidence over MAUDE's `event_type` field when they disagree; note the disagreement in `extraction_notes`.

5. **Extract `patient_outcome`.**
   - ≤200 chars describing what happened to the patient (not the device).
   - Use "No patient reported" if narrative describes device-only issue.
   - Use "Outcome not described" if the narrative omits patient follow-up.

6. **Extract `device_problem`.**
   - ≤200 chars describing what the device (or its software/algorithm) did wrong.
   - Distinct from `failure_mode`: `failure_mode` is the proximate event ("missed stroke"); `device_problem` is the mechanism ("algorithm produced false negative on LVO").

7. **Determine `ai_related_flag`.**
   - Set `true` if narrative mentions: algorithm, AI, machine learning, automated detection, triage software, CADe/CADx, model output, inference, neural network, deep learning, software-only function.
   - Set `false` if narrative clearly describes a purely mechanical or hardware failure (broken wire, battery, infusion pump occlusion) with no software component.
   - Set `null` if the narrative is too short or too generic to tell (e.g., "Device did not work as intended").
   - **Always write a rationale** (≤200 chars) in `ai_related_rationale`.

8. **Compute `confidence_score` (0.0–1.0).**
   Use these anchors:
   - `≥0.90` — All fields clearly and unambiguously extractable; narrative is specific and detailed
   - `0.75–0.89` — Most fields clear; minor ambiguity in one field
   - `0.60–0.74` — Meaningful ambiguity in 2+ fields OR narrative is vague; `requires_human_review = true`
   - `<0.60` — Too ambiguous to extract with confidence; `requires_human_review = true`, multiple fields may be `null`

9. **Set `requires_human_review`.**
   - `true` if `confidence_score < 0.60`
   - `true` if `failure_mode == null`
   - `true` if `severity == "unknown"` AND `event_type` was also missing
   - `true` if `ai_related_flag == null` AND the product code is a known AI/ML code
   - `false` otherwise

10. **Populate `narrative_excerpt`.**
    - First 500 characters of the combined preprocessed narrative.
    - Preserves a traceable trail from extraction back to source.

11. **Populate `extraction_notes`.**
    - Any caveats: narrative conflicts with MAUDE fields, multiple patients mentioned, unusual abbreviations, etc.
    - `null` if nothing notable.

12. **Citation check (MANDATORY).**
    - Before returning output, run the `regulatory-citation-verifier` Skill on every string field (`failure_mode`, `patient_outcome`, `device_problem`, `ai_related_rationale`, `extraction_notes`).
    - If verifier returns `safe_to_emit == false` → replace offending field with `[EXTRACTION ERROR: unverified citation]` and set `requires_human_review = true`.

13. **Return** the full output object.

---

## 6. Rules & Constraints

### NEVER
- NEVER infer a patient outcome not supported by the narrative (e.g., do not write "patient recovered" just because "death" wasn't mentioned).
- NEVER fabricate device details (model number, firmware version, anatomy affected) not present in the narrative.
- NEVER return `ai_related_flag = true` based on assumptions about the product code alone. The flag must be justified by narrative content.
- NEVER exceed 200 characters in any string field except `narrative_excerpt`, `narrative_truncated`, and `extraction_notes` — concision is a feature.
- NEVER return `confidence_score = 1.0`. Extraction is inherently uncertain; cap at 0.95.
- NEVER use Claude's training-data knowledge about specific devices or incidents to augment the extraction. Narrative text only.

### ALWAYS
- ALWAYS include `skill_version` and `model_used` in every output (FR-12 audit trail).
- ALWAYS record a rationale for `ai_related_flag`, even when `flag=null`.
- ALWAYS prefer `null` over a hallucinated value.
- ALWAYS flag for human review when uncertain — false positives on review are cheap; false negatives are dangerous.
- ALWAYS pass final output through `regulatory-citation-verifier` before emitting.

### EDGE CASES

| Case | Handling |
|---|---|
| Narrative is `"No event description provided"` | Return error `MISSING_NARRATIVE`; do not extract |
| Narrative describes multiple adverse events | Extract the most severe one; note others in `extraction_notes` |
| Narrative is in a non-English language | Set `confidence_score` ≤ 0.5, `requires_human_review=true`, note language in `extraction_notes` |
| Narrative mentions a device brand different from MAUDE `brand_name` | Note in `extraction_notes`; do not override MAUDE fields |
| Narrative explicitly states "no malfunction; reporting for awareness" | `failure_mode = "No malfunction reported"`, `severity = "other"`, `confidence ≥ 0.85` |
| Narrative is extremely short (<50 chars) | `confidence_score ≤ 0.55`; most fields likely `null` |
| Narrative mentions "software update" or "recall" | Extract normally; note in `extraction_notes` for cross-referencing |

---

## 7. Examples

### Example 1 — GOOD: Clear AI-related false negative
**Input (abbreviated):**
```json
{
  "maude_report_id": "MW5000123456",
  "event_description": "The CT scan was processed by the radiology triage software (AI algorithm). The software did not flag the scan as positive for large vessel occlusion. Patient presented with acute stroke symptoms. The stroke was later identified by the radiologist on routine read, but treatment was delayed by 42 minutes. Patient received thrombectomy with moderate residual deficit.",
  "mfr_narrative": "Investigation: algorithm review indicates the LVO was at the periphery of the detection map. Sensitivity in this anatomical region is known to be lower per labeling.",
  "event_type": "injury",
  "product_code": "QIH",
  "brand_name": "StrokeAI v2.1",
  "manufacturer": "AcmeMed AI"
}
```

**Expected output:**
```json
{
  "maude_report_id": "MW5000123456",
  "extraction_ts": "2026-04-23T14:22:18Z",
  "skill_name": "maude-narrative-extractor",
  "skill_version": "1.0.0",
  "model_used": "claude-sonnet-4-6",
  "failure_mode": "False negative for large vessel occlusion detection",
  "severity": "serious_injury",
  "patient_outcome": "Delayed thrombectomy by 42 min; moderate residual neurological deficit",
  "device_problem": "Algorithm failed to flag peripheral LVO on CT scan",
  "ai_related_flag": true,
  "ai_related_rationale": "Narrative explicitly references AI algorithm and detection map; manufacturer confirms algorithm sensitivity limitation",
  "confidence_score": 0.92,
  "requires_human_review": false,
  "narrative_excerpt": "The CT scan was processed by the radiology triage software (AI algorithm)...",
  "narrative_truncated": false,
  "extraction_notes": null
}
```

### Example 2 — GOOD: Ambiguous short narrative
**Input:**
```json
{
  "maude_report_id": "MW5000998877",
  "event_description": "Device did not work as expected.",
  "mfr_narrative": "",
  "event_type": "malfunction",
  "product_code": "QIH",
  "brand_name": "StrokeAI v2.1",
  "manufacturer": "AcmeMed AI"
}
```

**Expected output:**
```json
{
  "maude_report_id": "MW5000998877",
  "failure_mode": null,
  "severity": "malfunction",
  "patient_outcome": "No patient reported",
  "device_problem": "Unspecified — device did not work as expected",
  "ai_related_flag": null,
  "ai_related_rationale": "Narrative too generic to determine whether an AI/algorithm component was involved",
  "confidence_score": 0.35,
  "requires_human_review": true,
  "narrative_excerpt": "Device did not work as expected.",
  "narrative_truncated": false,
  "extraction_notes": "Narrative is too brief for substantive extraction. Review source for follow-up."
}
```

### Example 3 — GOOD: Clearly non-AI hardware failure on a non-AI code
**Input:**
```json
{
  "maude_report_id": "MW5000111222",
  "event_description": "Infusion pump alarm activated. Pump stopped delivering medication. Nurse replaced with backup pump. Patient stable, no adverse outcome.",
  "mfr_narrative": "Investigation confirmed occluded inline filter. No software issue.",
  "event_type": "malfunction",
  "product_code": "FRN",
  "brand_name": "InfuSafe 3000",
  "manufacturer": "Acme Pumps"
}
```

**Expected output (abbreviated):**
```json
{
  "failure_mode": "Occluded inline filter causing infusion interruption",
  "severity": "malfunction",
  "patient_outcome": "No adverse outcome; backup pump used",
  "device_problem": "Mechanical occlusion of inline filter",
  "ai_related_flag": false,
  "ai_related_rationale": "Narrative and manufacturer investigation explicitly identify a mechanical cause with no software involvement",
  "confidence_score": 0.90,
  "requires_human_review": false
}
```

### Example 4 — BAD: What this Skill must NOT do
**Input:** (Same as Example 2 — vague narrative)

**WRONG response:**
```json
{
  "failure_mode": "Algorithm failed to detect hemorrhage",   ← FABRICATED
  "patient_outcome": "Patient recovered without intervention",  ← FABRICATED
  "ai_related_flag": true,
  "confidence_score": 0.85
}
```

**Why wrong:** The narrative says only "Device did not work as expected." None of the specific details — hemorrhage, patient recovery, AI involvement — are supported. The extractor invented content to appear useful. This is exactly the failure mode this Skill exists to prevent.

**Correct response:** See Example 2 above — honest `null` fields, low confidence, flagged for human review.

### Example 5 — BAD: Over-extracting severity
**Input:**
```json
{
  "event_description": "Alarm sounded during procedure but was silenced by staff.",
  "event_type": "malfunction"
}
```

**WRONG:** `severity: "serious_injury"` (no injury described).
**CORRECT:** `severity: "malfunction"` (matches MAUDE event_type; no injury evidence in narrative).

---

## 8. Validation

This Skill is validated against the gold standard test set at `tests/gold_set/gold_100.jsonl`.

### Passing criteria (per FR-08):
- **Per-field accuracy ≥90%** across 100 hand-labeled records
- **Zero fabricated details** on a 50-sample blind audit (rationales must trace to narrative text)
- **Zero hallucinated citations** in any output field (enforced by mandatory citation verifier call)
- **`requires_human_review == true`** rate between 10% and 30% (too low = over-confident; too high = under-performing)

### Test structure:
- 50 "clear" records — expect high-confidence extractions matching human labels
- 30 "ambiguous" records — expect low-confidence, human-review flags
- 15 "edge case" records — short narratives, multi-event, non-English fragments
- 5 "adversarial" records — narratives designed to tempt fabrication

**This Skill is not released to production until the gold-set validation passes at the thresholds above.**

---

## 9. References

- Document 3 §3.2 (Feature F2 — Extraction requirements FR-08 to FR-12)
- Document 3 §5.2 (DR-03 Extraction Output Schema)
- Document 5 §7 (Skills architecture)
- MAUDE data dictionary: https://open.fda.gov/apis/device/event/
- FDA guidance: "AI-Enabled Device Software Functions" (2025 final)
- IMDRF Medical Device Adverse Event Terminology: https://www.imdrf.org/

---

## 10. Related Skills

| Skill | Relationship |
|---|---|
| `regulatory-citation-verifier` | Hard dependency. Runs on every string field before emission. |
| `severity-triage` | Specialized helper for FR-13's severity mapping (may be inlined for v1.0). |
| `ai-failure-mode-classifier` | Downstream. Consumes this Skill's output to assign AI failure taxonomy. |
| `psur-report-drafter` | Downstream. Uses aggregated extractions in PSUR sections. |

---

## 11. Changelog

- **v1.0.0** (2026-04-23) — Initial release. Supports 6 extracted fields, confidence scoring, human-review flagging, mandatory citation verification.

### Planned for v1.1.0 (deferred per Charter §4 cap)
- Language detection for non-English narratives with automatic translation
- Multi-event extraction (returning array of events per record)
- Temporal extraction (time-to-event, date-of-first-symptom)
- Cross-record deduplication (same event reported multiple times)
