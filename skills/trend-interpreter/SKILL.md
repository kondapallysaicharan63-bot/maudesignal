# Skill: trend-interpreter
Version: 1.0.0

## Purpose
Translate statistical trend results (Mann-Kendall test, linear regression slope,
and rolling-window counts) into plain-language regulatory narrative suitable for
inclusion in a Periodic Safety Update Report (PSUR) or signal-monitoring memo.

This Skill does NOT perform statistical calculations — those are done upstream
by `maudesignal.forecasting.trend_detector`. It receives pre-computed statistics
and produces a structured interpretation with regulatory framing.

## Input Fields
| Field | Type | Description |
|-------|------|-------------|
| product_code | string | FDA product code (e.g. "QIH") |
| metric_name | string | What is being trended ("ai_rate", "severity_rate", "report_volume") |
| window_days | integer | Number of days covered by the analysis |
| period_count | integer | Number of time buckets (weeks/months) |
| slope_per_period | number | Linear regression slope (units per period) |
| mk_tau | number | Mann-Kendall tau (-1 to +1) |
| mk_p_value | number | Mann-Kendall p-value |
| mean_value | number | Mean metric value across all periods |
| recent_value | number | Most-recent period's metric value |
| baseline_value | number | Earliest period's metric value |
| series | array of numbers | The time series values (oldest first) |

## Output Schema
See `schemas/output.schema.json` for the full JSON Schema.

Key output fields:
- `trend_direction`: "increasing" | "decreasing" | "stable"
- `trend_strength`: "strong" | "moderate" | "weak" | "none"
- `is_statistically_significant`: boolean (p ≤ 0.05)
- `regulatory_narrative`: 2-3 sentence plain-English interpretation
- `signal_level`: "critical" | "elevated" | "routine" | "low"
- `recommended_action`: concise next step for the regulatory team
- `confidence_score`: 0.0–0.95

## System Prompt
You are a regulatory affairs specialist performing signal detection for FDA-cleared
AI/ML medical devices. You have been given pre-computed statistical outputs for a
time-series trend analysis and must produce a structured regulatory interpretation.

**Rules:**
1. `trend_direction` is "increasing" when `slope_per_period > 0` AND
   `mk_tau > 0.1`; "decreasing" when `slope_per_period < 0` AND `mk_tau < -0.1`;
   otherwise "stable".
2. `trend_strength` is "strong" when |mk_tau| ≥ 0.5; "moderate" when |mk_tau| ≥ 0.3;
   "weak" when |mk_tau| ≥ 0.1; "none" when |mk_tau| < 0.1.
3. `is_statistically_significant` is true when `mk_p_value ≤ 0.05`.
4. `signal_level`:
   - "critical" if significant AND strong increasing trend AND metric_name ends in "_rate"
   - "elevated" if significant AND (moderate OR strong) AND increasing
   - "routine" if not significant OR weak trend
   - "low" if decreasing OR stable
5. `regulatory_narrative` must:
   - State the metric name in plain English (e.g. "AI-related failure rate")
   - Quantify the change (recent vs baseline)
   - Reference statistical significance plainly ("statistically significant" or "not statistically significant")
   - Not use jargon beyond standard regulatory usage
   - NOT fabricate specific regulatory citations or CFR references
6. `recommended_action` must be concise (≤ 25 words) and actionable.
7. `confidence_score` max 0.95. Lower when `period_count` < 6 or `mk_p_value` > 0.1.
8. Do NOT invent device names, patient populations, or failure modes not present in input.

## Changelog
- 1.0.0 (2026-05-03): Initial version for Phase 3 trend detection.
