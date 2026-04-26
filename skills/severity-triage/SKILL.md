# Skill: severity-triage

**Version:** 1.0.0
**Last Updated:** 2026-04-26
**Owner:** Sai Charan Kondapally
**Status:** Active
**Depends On:** `regulatory-citation-verifier` (v≥1.0.0)

---

## 1. Description

This Skill takes a MAUDE record (raw fields + narrative) and assigns a
**standardized severity category** following FDA Medical Device Reporting (MDR)
conventions, plus an explicit decision rationale and confidence score.

It exists because severity is a load-bearing field for everything downstream:
PSUR severity tables, drift cohort weighting, dashboard signal-vs-noise
filtering, and (most importantly) what a human reviewer triages first. A
mislabeled `serious_injury` that should have been `malfunction` wastes
reviewer time; a mislabeled `malfunction` that should have been
`serious_injury` is a safety failure. So this Skill is conservative,
narrative-driven, and refuses to over-extend.

This Skill **does not** classify into the AI failure taxonomy — that is the job
of `ai-failure-mode-classifier`. It also **does not** re-extract failure_mode,
patient_outcome, or device_problem — those are the job of
`maude-narrative-extractor`. This Skill answers exactly one question: how
serious was this event, by FDA MDR rules?

---

## 2. When to Use

### Activate this Skill when:
- A MAUDE record has been ingested (F1) and either has a non-empty narrative
  OR has a non-empty MAUDE `event_type`
- Re-triaging records where the prior extractor disagreed with MAUDE's native
  `event_type`
- Building the gold-set severity labels for benchmarking
- Auditing a batch of `serious_injury` extractions for over- or under-calling

### Do NOT activate this Skill when:
- The record is not a MAUDE MDR (different sources have different severity
  schemas — handle in their own Skill)
- Both narrative AND `event_type` are missing → return
  `severity = "insufficient_information"` directly without LLM call
- Assigning severity for **non-AI** taxonomy purposes (this Skill's output is
  taxonomy-agnostic; downstream classifiers are free to ignore it)

---

## 3. Inputs

### Required Input
```json
{
  "maude_report_id": "string",
  "event_description": "string (may be empty)",
  "mfr_narrative": "string (may be empty)",
  "event_type": "string (death | injury | malfunction | other | empty)",
  "patient_outcome_extracted": "string | null (output from maude-narrative-extractor, optional)",
  "product_code": "string (3 chars, e.g., QIH)"
}
```

### Input Preprocessing
- Concatenate `event_description` + `mfr_narrative` with `\n\n---\nMANUFACTURER NARRATIVE:\n`.
- Truncate to 6,000 characters at word boundary (severity decisions rarely need
  more context than this; smaller window than the extractor for cost reasons).
- Lowercase a working copy for keyword matching but pass the original-case
  narrative to the LLM.

---

## 4. Outputs

### Output Schema (see `schemas/output.schema.json`)
```json
{
  "maude_report_id": "string (matches input)",
  "triage_ts": "ISO-8601 UTC",
  "skill_name": "severity-triage",
  "skill_version": "1.0.0",
  "model_used": "string",

  "severity": "death | serious_injury | malfunction | other | insufficient_information",
  "severity_rationale": "string ≤300 chars — must cite narrative evidence",
  "evidence_quotes": ["array of ≤2 short narrative substrings supporting the decision"],

  "maude_event_type": "string — input passthrough",
  "agrees_with_maude_event_type": "boolean",
  "disagreement_explanation": "string | null (≤200 chars) — populated only when agrees_with_maude_event_type=false",

  "confidence_score": "number 0.0–0.95",
  "requires_human_review": "boolean",
  "triage_notes": "string | null"
}
```

### Severity Categories (the only 5 valid values)

| Category | Definition | Trigger evidence |
|---|---|---|
| `death` | Patient died OR death contributed to. | Explicit "death", "expired", "demise", "fatal" in narrative; OR MAUDE `event_type == "death"` AND no narrative contradiction |
| `serious_injury` | Significant injury, hospitalization, life-threatening event, permanent impairment, or intervention required to prevent the above. Maps to 21 CFR 803.3(w). | "hospitalized", "intubated", "intervention", "permanent deficit", "life-threatening", "ICU", "additional surgery", "delayed thrombectomy" |
| `malfunction` | Device failed but no patient injury occurred or was reported. | "alarm sounded then silenced", "replaced with backup", "no patient harm", "for info only", "device returned for analysis" |
| `other` | MAUDE-classified `other` events that don't fit the above; informational reports; user error; near-misses without injury. | MAUDE `event_type == "other"` AND no narrative evidence of injury |
| `insufficient_information` | Cannot determine severity from available evidence. | Narrative missing/empty AND `event_type` missing/empty; or pure equipment-return logs with no event description |

**Note vs `maude-narrative-extractor`:** that Skill historically emitted
`unknown` for the same condition. As of 2026-04-26, its schema accepts
both `unknown` (legacy) and `insufficient_information` (preferred), and
its procedure §5 step 4 documents the alias. The two values are
formally equivalent for downstream consumers. New extractions should
emit `insufficient_information`; pre-existing `unknown` extractions in
storage remain valid without re-extraction.

---

## 5. Procedure

1. **Validate input.**
   - If `maude_report_id` missing → return error `MISSING_ID`.
   - If `event_description`, `mfr_narrative`, AND `event_type` all empty →
     return `severity = "insufficient_information"`, `confidence = 0.20`,
     `requires_human_review = true`. Do not call LLM.

2. **Preprocess narrative** per §3.

3. **Apply hard rules first (no LLM needed for these).**
   - If narrative contains explicit unambiguous death markers ("patient died",
     "patient expired", "death of patient", "fatal outcome") → `severity = "death"`,
     confidence ≥ 0.85.
   - If MAUDE `event_type == "death"` AND narrative does not contradict
     (e.g., does not say "patient survived") → `severity = "death"`.
   - These rules exist because LLMs occasionally hedge on death calls; the
     hard rule prevents that.

4. **Otherwise call LLM with the §6 rules.**
   - Prompt the LLM with the narrative, the MAUDE `event_type`, and the
     5-category schema.
   - Require the LLM to return: chosen category, rationale ≤300 chars, and
     up to 2 short evidence quotes from the narrative.

5. **Validate LLM output.**
   - `severity` MUST be one of the 5 enum values. Anything else → set to
     `insufficient_information`, `requires_human_review = true`, and log the
     anomaly.
   - `evidence_quotes` MUST be substrings of the input narrative
     (verbatim or case-only-different). If not, drop the quote and lower
     confidence by 0.10.

6. **Reconcile with MAUDE `event_type`.**
   - Map MAUDE event_type to this Skill's enum:
     - `death → death`, `injury → serious_injury`, `malfunction → malfunction`,
       `other → other`.
   - If LLM-chosen severity matches → `agrees_with_maude_event_type = true`,
     `disagreement_explanation = null`.
   - If they disagree → `agrees_with_maude_event_type = false`. Populate
     `disagreement_explanation` with one sentence explaining why the
     narrative-based call differs from the MAUDE field.

7. **Compute `confidence_score`.**
   Anchors:
   - ≥0.90 — explicit, unambiguous evidence; agrees with MAUDE event_type
   - 0.75–0.89 — clear narrative evidence; minor ambiguity OR mild disagreement with MAUDE
   - 0.60–0.74 — meaningful ambiguity; `requires_human_review = true`
   - 0.30–0.59 — heavy reliance on MAUDE field; narrative thin
   - <0.30 — almost no evidence; should be `insufficient_information`

8. **Set `requires_human_review`.**
   - `true` if `confidence_score < 0.65`
   - `true` if `severity == "death"` and confidence < 0.90 (death calls
     deserve verification regardless of category confidence)
   - `true` if `agrees_with_maude_event_type == false`
   - `true` if `severity == "insufficient_information"`
   - `false` otherwise

9. **Citation check (MANDATORY).**
   - Pass `severity_rationale`, `disagreement_explanation`, `triage_notes`
     through `regulatory-citation-verifier`.
   - If verifier returns `safe_to_emit == false` → replace offending field
     with `[TRIAGE ERROR: unverified citation]` and set
     `requires_human_review = true`.

10. **Return** the full output object.

---

## 6. Rules & Constraints

### NEVER
- NEVER assign `death` without explicit narrative or MAUDE evidence. The
  absence of the word "survived" is not evidence of death.
- NEVER assign `serious_injury` based on the *type of device* alone (e.g.,
  "this is an implanted device, so any malfunction is serious"). The
  category is decided by patient impact, not device class.
- NEVER fabricate evidence quotes. Quotes must be verbatim substrings.
- NEVER override MAUDE `event_type == "death"` to `malfunction` without
  explicit narrative contradiction (e.g., narrative explicitly states the
  patient survived). Set `requires_human_review = true` for any death-event
  re-categorization.
- NEVER return `confidence_score = 1.0`. Cap at 0.95.
- NEVER use Claude's training-data knowledge of specific incidents to upgrade
  or downgrade severity.

### ALWAYS
- ALWAYS return `severity_rationale` referencing narrative evidence (or
  explicitly stating that the MAUDE event_type was the basis when narrative
  is empty).
- ALWAYS populate `evidence_quotes` if any narrative text exists; empty array
  is acceptable only when narrative is empty.
- ALWAYS set `agrees_with_maude_event_type` honestly — disagreement is fine,
  it just gates human review.
- ALWAYS pass output through `regulatory-citation-verifier` before emission.
- ALWAYS prefer `insufficient_information` over a guess.

### EDGE CASES

| Case | Handling |
|---|---|
| MAUDE `event_type == "injury"` but narrative describes only an alarm with no patient impact | `severity = "malfunction"`, `agrees_with_maude_event_type = false`, explain in `disagreement_explanation` |
| Narrative mentions "death" but in the manufacturer's name ("Death Industries") or as a metaphor | Disambiguate via context; if uncertain, fall back to MAUDE event_type and flag for review |
| Multiple patients mentioned with different outcomes | Use the most severe outcome; note multi-patient in `triage_notes` |
| Narrative is in a non-English language | `confidence_score ≤ 0.50`, `requires_human_review = true`, note language in `triage_notes` |
| MAUDE `event_type` is empty AND narrative is rich | LLM-only call; confidence cap 0.85 (no MAUDE corroboration) |
| Narrative says "patient was discharged in stable condition" after a hospitalization | `serious_injury` (hospitalization itself qualifies under 21 CFR 803.3(w)) |
| Narrative says "patient required additional unscheduled procedure" | `serious_injury` (intervention to prevent permanent impairment) |
| Pure equipment-return log: "Device returned for analysis. Awaiting investigation." | `severity = "insufficient_information"`, `confidence ≤ 0.40` |

---

## 7. Examples

See `examples/good.jsonl` (5 cases) and `examples/bad.jsonl` (5 anti-examples).

The good examples cover: clear death call, hospitalization → serious_injury,
silenced alarm → malfunction, MAUDE/narrative disagreement, equipment return
with no event.

The bad examples cover: death-from-absence-of-evidence, serious_injury from
device-class assumption, fabricated evidence quote, ignoring narrative
contradiction of MAUDE event_type, and using training-data knowledge.

---

## 8. Validation

This Skill is validated against the 100-record gold standard severity labels
at `tests/gold_set/severity_gold_100.jsonl`.

### Passing criteria:
- **Per-category accuracy ≥85%** across the gold set
- **Zero `death` calls without explicit evidence** (narrative or MAUDE)
- **`serious_injury` precision ≥90%** (false positives on this category cost
  reviewer time)
- **`requires_human_review` rate between 15% and 35%**

### Test structure:
- 30 clear-death records
- 30 clear-serious_injury records
- 25 clear-malfunction records
- 10 ambiguous records (expect `insufficient_information` or low confidence)
- 5 adversarial records (e.g., "death" used metaphorically)

**This Skill is not released to production until the gold-set validation
passes at the thresholds above.**

---

## 9. References

- 21 CFR Part 803 — Medical Device Reporting
- 21 CFR 803.3(w) — definition of "serious injury"
- FDA MAUDE data dictionary: https://open.fda.gov/apis/device/event/
- Document 3 §3.4 (Feature F3 — Classification requirements)
- Document 5 §7 (Skills architecture)

---

## 10. Related Skills

| Skill | Relationship |
|---|---|
| `regulatory-citation-verifier` | Hard dependency. Runs on every string field before emission. |
| `maude-narrative-extractor` | Upstream. Severity here may override the extractor's coarse `severity` field; both are stored. |
| `ai-failure-mode-classifier` | Sibling. Consumes this Skill's severity along with the extractor's other fields. |
| `psur-report-drafter` | Downstream. Severity drives PSUR section weighting. |

---

## 11. Changelog

- **v1.0.0** (2026-04-26) — Initial release. 5-category enum, narrative-driven
  triage with MAUDE event_type reconciliation, mandatory citation verification,
  hard rules for unambiguous death calls.

### Planned for v1.1.0
- Sub-categories within `serious_injury` (hospitalization vs life-threatening
  vs permanent impairment) for finer PSUR reporting
- Multi-patient severity aggregation rules
- Auto-detected non-English narrative routing to a translation pre-step
