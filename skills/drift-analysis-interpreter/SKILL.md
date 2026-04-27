# Skill: drift-analysis-interpreter

**Version:** 1.0.0
**Last Updated:** 2026-04-27
**Owner:** Sai Charan Kondapally
**Status:** Skeleton (not wired into pipeline; Week 5 deliverable)
**Depends On:** `regulatory-citation-verifier` (v≥1.0.0)

---

## 1. Description

Takes the numeric output of an MaudeSignal drift analysis (mean shift, KS-test
statistic + p-value, PSI, cohort sizes) and produces a short, regulator-readable
interpretation: what changed, by how much, whether it's statistically and
practically meaningful, and what the appropriate next step is. Pure
text-generation Skill — no model claims about *causes*; it stays inside the
numbers it's given.

This Skill exists because raw KS / PSI numbers do not communicate to most
regulatory readers, and because every conversion of stats into prose is a
hallucination risk that this codebase will not absorb. The Skill is the
single place where we control how that translation happens.

---

## 2. When to Use

### Activate when:
- An F4 drift run has completed and emitted a `DriftResult` record
- A PSUR draft (F7) needs the prose interpretation of a flagged drift cohort

### Do NOT activate when:
- Drift stats are missing or incomplete (return error `INSUFFICIENT_INPUT`)
- The cohort has fewer than the documented minimum sample size (caller's job to gate)
- For naming / labeling drift categories — that's `ai-failure-mode-classifier`

---

## 3. Inputs

```json
{
  "metric_name": "string (e.g. 'sensitivity', 'specificity', 'volume_per_week')",
  "baseline_value": "number",
  "current_value": "number",
  "ks_statistic": "number | null",
  "ks_p_value": "number | null",
  "psi": "number | null",
  "n_baseline": "integer",
  "n_current": "integer",
  "cohort_label": "string (e.g. 'QIH all sites Q4-2025 vs deployment')"
}
```

---

## 4. Outputs

See `schemas/output.schema.json`.

```json
{
  "interpretation_ts": "ISO-8601 UTC",
  "skill_name": "drift-analysis-interpreter",
  "skill_version": "1.0.0",
  "model_used": "string",

  "verdict": "stable | drift_suspected | drift_confirmed | insufficient_data",
  "headline": "string ≤200 chars — one-sentence summary",
  "narrative": "string ≤800 chars — 2–4 sentence prose interpretation",
  "recommended_action": "monitor | investigate | escalate | none",

  "evidence": {
    "delta_pct": "number | null",
    "ks_statistic": "number | null",
    "ks_p_value": "number | null",
    "psi": "number | null"
  },
  "confidence_score": "number 0.0–0.95",
  "requires_human_review": "boolean"
}
```

---

## 5. Procedure (sketch)

1. Validate input — at least one of (KS, PSI) and both n_* ≥ documented minimum.
2. Compute delta_pct between baseline_value and current_value.
3. Decide verdict:
   - `insufficient_data` if n_baseline or n_current is below minimum
   - `drift_confirmed` if ks_p_value < 0.01 AND |delta_pct| ≥ 5
   - `drift_suspected` if 0.01 ≤ ks_p_value < 0.05, or PSI ≥ 0.2
   - `stable` otherwise
4. Generate `headline` and `narrative` from a deterministic template that
   only references the supplied numbers — no inferred mechanisms, no
   speculation about causes.
5. `recommended_action`:
   - `escalate` for `drift_confirmed` on a clinical metric (sensitivity/specificity)
   - `investigate` for `drift_suspected`
   - `monitor` for `stable` with non-zero PSI
   - `none` otherwise
6. Citation check on every string field (mandatory).
7. Return.

---

## 6. Rules & Constraints

- NEVER infer a *cause* of drift. The Skill describes magnitude + significance only.
- NEVER override `insufficient_data` with a verdict if either n_* < minimum.
- NEVER claim a drift is "small" or "not meaningful" if PSI ≥ 0.2 — that crosses the standard reporting threshold.
- NEVER cap `delta_pct` direction (positive = current > baseline, always).
- ALWAYS include `n_baseline` and `n_current` in the narrative, so a reader can sanity-check the claim.
- ALWAYS run final output through `regulatory-citation-verifier`.

---

## 7. Examples

See `examples/good.jsonl` (3 cases) and `examples/bad.jsonl` (3 anti-examples).

---

## 8. Validation (planned)

Will validate against `tests/gold_set/drift_interpretation_gold_30.jsonl` once
the gold set is built (Week 5). Passing thresholds TBD.

---

## 9. References

- 21 CFR Part 820.250 (statistical methods)
- FDA "AI-Enabled Device Software Functions" (2025) — performance monitoring section
- Evidently drift documentation
- PSI thresholds: <0.1 stable, 0.1–0.2 minor, ≥0.2 significant

---

## 10. Related Skills

| Skill | Relationship |
|---|---|
| `regulatory-citation-verifier` | Hard dependency. Final string-field gate. |
| `ai-failure-mode-classifier` | Sibling. `algorithm_drift` category cases feed inputs here. |
| `psur-report-drafter` | Downstream. Consumes interpretations into PSUR drift section. |

---

## 11. Changelog

- **v1.0.0** (2026-04-27) — Skeleton release. Schema + examples committed; not
  wired into pipeline. Implementation deferred to Week 5 per roadmap.
