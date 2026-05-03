# Skill: root-cause-analyzer

**Version:** 1.0.0
**Last Updated:** 2026-05-02
**Status:** Active
**Depends On:** `ai-failure-mode-classifier` (v≥1.0.0), `severity-triage` (v≥1.0.0)

---

## 1. Description

Given a cluster of MAUDE adverse event reports for the same device sharing the
same AI failure-mode category, this Skill synthesizes a structured root-cause
hypothesis: *why* is this failure mode occurring, *who* is affected, and *what*
investigation is recommended.

This Skill operates on **aggregated clusters**, not individual records. It reads
across N narrative excerpts and severity/outcome data to identify patterns a
single-record extractor cannot see.

**This Skill does NOT extract from raw narratives.** That is the job of
`maude-narrative-extractor`. This Skill receives pre-extracted structured data.

---

## 2. When to Use

### Activate when:
- A product code has ≥3 extractions sharing the same `failure_mode_category`
- Running a root-cause analysis pass (`maudesignal analyze root-cause`)
- A new cluster crosses the minimum-size threshold after an ingest+extract cycle

### Do NOT activate when:
- Cluster size < 3 (insufficient evidence — return `requires_human_review=true`)
- `failure_mode_category` is `not_ai_related`
- The cluster contains records from multiple distinct devices (split by device first)

---

## 3. Inputs

```json
{
  "product_code": "string — FDA 3-char code",
  "device_name": "string — brand or generic device name",
  "failure_mode_category": "string — from ai-failure-mode-classifier enum",
  "cluster_size": "integer — number of records in cluster",
  "narrative_excerpts": "array[string] — up to 10 narrative_excerpt fields from extractions",
  "severity_distribution": "object — {death: int, serious_injury: int, malfunction: int, other: int}",
  "date_range_days": "integer — span of cluster (first to last event date)"
}
```

---

## 4. Outputs

See `schemas/output.schema.json`.

Key fields:
- `root_cause_hypothesis` — concise mechanistic explanation of WHY the failures occur
- `contributing_factors` — ordered list of up to 4 specific causal factors
- `affected_population` — who is most at risk (patient type, clinical context)
- `recommended_investigation` — concrete next steps for the manufacturer/FDA reviewer
- `confidence_score` — [0.0, 0.95]; should be low (< 0.6) for clusters < 5
- `requires_human_review` — true if cluster < 5 or evidence is contradictory

---

## 5. Reasoning Rules

1. **Cite evidence**: every factor in `contributing_factors` must be traceable to
   at least one narrative excerpt.
2. **Be specific**: "algorithm underperforms on atypical presentations" is better
   than "model accuracy issue."
3. **Distinguish correlation from causation**: use "associated with" not "caused by"
   unless mechanism is explicit in the narratives.
4. **Regulatory language**: `recommended_investigation` must reference applicable
   FDA guidance actions (CAPA, PMS study, field safety corrective action).
5. **Confidence floor**: cluster_size < 5 → confidence_score ≤ 0.60.
6. **No fabrication**: do not invent technical details not present in the excerpts.

---

## 6. System Prompt

```
You are a regulatory affairs AI expert analyzing FDA MAUDE adverse event clusters
for AI/ML medical devices. You receive a cluster of structured failure data for
one device and one failure-mode category, and you produce a structured root-cause
analysis in JSON.

Rules:
- Be specific: reference narrative evidence, not general AI failure concepts.
- Use regulatory language appropriate for an FDA post-market surveillance report.
- confidence_score ≤ 0.60 when cluster_size < 5.
- contributing_factors: ordered list, most likely first, max 4 items.
- requires_human_review: true if cluster_size < 5 OR evidence is conflicting.
- Do not fabricate technical details not present in the input narratives.
- Output valid JSON matching the schema exactly. No markdown fences.
```

---

## 7. Changelog

| Version | Date | Change |
|---------|------|--------|
| 1.0.0 | 2026-05-02 | Initial release |
