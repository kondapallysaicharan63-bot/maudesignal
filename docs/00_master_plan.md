# Document 0: Master Plan

**Project Name:** SafeSignal — Open-Source AI Postmarket Surveillance Toolkit
**Owner:** Sai Charan Kondapally
**Version:** 1.0
**Date:** 2026-04-26
**Status:** Active (post-pilot)
**References:** Documents 1–8 + `docs/00_pilot_findings.md`

---

## 1. Purpose of This Document

This is the single page that explains SafeSignal end-to-end: what it does, why it
exists, how the pieces fit together, what is built and what is not, and how the
remaining 8 weeks unfold.

If a recruiter, hiring manager, or contributor reads exactly one document in this
repository, this is the one. It links out to the deeper specifications when more
detail is needed (see Documents 1–8 in [docs/](.)).

This document does **not** replace the deeper docs — it indexes and reconciles
them with the reality that emerged from the Day 1 / Day 2 pilots.

---

## 2. Vision (One Paragraph)

The FDA has cleared over 1,000 AI/ML-enabled medical devices. They are monitored
through MAUDE — a 1990s reporting system with **no fields** for AI-specific
failures (drift, covariate shift, automation bias, subgroup performance loss).
QMSR (effective **February 2, 2026**) mandates real-world performance monitoring
for every device manufacturer. SafeSignal is the open-source toolkit that fills
this gap: it ingests MAUDE adverse event narratives, uses LLMs guided by versioned
Skills to extract AI-specific failure signals, verifies every regulatory citation,
and produces auditable regulator-style reports.

Detailed problem framing: see [01_vision_mission.md](01_vision_mission.md).

---

## 3. Multi-Provider LLM Strategy

SafeSignal is **provider-agnostic by design**. The same pipeline runs against any
of four LLM providers, selected via the `LLM_PROVIDER` environment variable.

| Provider | Default model | Cost | When to use |
|---|---|---|---|
| **Groq** (default) | `llama-3.3-70b-versatile` | $0.00 (free tier, ~14,400 req/day) | Bulk extraction, gold-set iteration, Codespaces demos |
| **Anthropic** | `claude-sonnet-4-6` | ~$3/$15 per Mtok | Highest extraction quality on ambiguous narratives, regulatory writeups |
| **OpenAI** | `gpt-4o-mini` | ~$0.15/$0.60 per Mtok | Cost-efficient mid-quality fallback |
| **Gemini** | `gemini-1.5-flash` | $0.00 (free tier, ~1,500 req/day) | Second free option for redundancy and head-to-head comparison |

The abstraction lives in [src/safesignal/extraction/llm_providers/](../src/safesignal/extraction/llm_providers/).
Every concrete provider implements the `LLMProvider` ABC in `base.py` and returns
a normalized `LLMResponse`. The Extractor never sees a vendor-specific type. This
gives the project three properties that matter for regulatory work:

1. **Reproducibility** — re-run the same Skill against a different provider to
   detect prompt-specific overfitting.
2. **Resilience** — a provider outage or pricing change does not stall the project.
3. **Cost discipline** — start free (Groq + Gemini), upgrade only where quality
   demands it.

See [05_architecture.md §7](05_architecture.md) for the full provider design.

---

## 4. Seven Core Features (F1–F7)

The full requirements specification is [03_requirements_spec.md](03_requirements_spec.md).
At the headline level, SafeSignal is seven features composed into one pipeline.

| # | Feature | What it does | Status |
|---|---|---|---|
| **F1** | **MAUDE Ingestion** | Pulls adverse event reports from openFDA for configured product codes; stores raw + parsed records; idempotent re-runs | ✅ Working (pilot validated on LLZ, QIH) |
| **F2** | **LLM-Powered Extraction** | Reads MAUDE narratives via the active LLM provider + `maude-narrative-extractor` Skill; emits structured records with confidence scores | ✅ Working (22 extractions, 0.90 avg confidence) |
| **F3** | **AI-Failure Taxonomy Classification** | Assigns each extracted record to one of 11 AI failure modes (false negative, drift, automation bias, …) | 🚧 Skill #4 (this PR) |
| **F4** | **Drift Simulation & Detection** | Synthesizes drift on labeled cohorts; runs KS / PSI tests; flags statistically significant changes | 📋 Planned (Week 5) |
| **F5** | **Citation Verification** | Validates every K-number, PMA, CFR section, and guidance title in every output against primary sources before emission | ✅ Working (`regulatory-citation-verifier` v1.0.0) |
| **F6** | **Streamlit Dashboard** | Local dashboard: volume trends, severity breakdown, AI failure categories, anomaly alerts, exportable report | 📋 Planned (Week 6) |
| **F7** | **PSUR Report Generator** | Composes EU-MDR-style periodic safety reports from aggregated extractions + verified citations; renders to Markdown / PDF | 📋 Planned (Week 6–7) |

**Composition order:** F1 → F2 → F3 → F4 → F5 (gate) → F6/F7 (presentation). F5
is a hard gate on every artifact F6 / F7 emit — no unverified citation reaches
a user-facing surface.

---

## 5. Seven Planned Skills

All LLM behavior lives in versioned `SKILL.md` files (see [04_skills_matrix.md](04_skills_matrix.md)
and [05_architecture.md §7](05_architecture.md)). Skills are composable; the
build order respects the dependency graph (verifier first, drafter last).

| # | Skill | Role | Version | Status |
|---|---|---|---|---|
| 1 | `regulatory-citation-verifier` | Hard safety gate. Every string field on every output passes through this Skill before emission. Verifies K-numbers, PMAs, CFR sections, FDA guidance titles. | 1.0.0 | ✅ Built |
| 2 | `maude-narrative-extractor` | Reads MAUDE event_description + mfr_narrative, emits structured failure_mode, severity, patient_outcome, ai_related_flag, confidence_score | 1.0.0 | ✅ Built |
| 3 | `severity-triage` | Standardizes severity to FDA MDR categories (`death`, `serious_injury`, `malfunction`, `other`, `insufficient_information`) with explicit decision rules | 1.0.0 | 🚧 This PR |
| 4 | `ai-failure-mode-classifier` | Assigns one of 11 AI failure taxonomy labels to each extracted record (false_negative_clinical, automation_bias, algorithm_drift, …) | 1.0.0 | 🚧 This PR |
| 5 | `drift-analysis-interpreter` | Translates KS/PSI statistics + cohort metadata into regulator-readable language with appropriate hedging | — | 📋 Week 5 |
| 6 | `fda-guidance-retriever` | Grounded retrieval over the local FDA guidance corpus; returns only verifiable hits | — | 📋 Week 6 |
| 7 | `psur-report-drafter` | Composes the periodic safety report from aggregated extractions + drift findings + verified citations | — | 📋 Week 7 |

---

## 6. Eight-Week Roadmap

The full week-by-week plan is in [07_roadmap.md](07_roadmap.md). This is the
milestone view.

| Week | Phase | Headline Deliverable | Gate |
|---|---|---|---|
| **Week 1** | Phase 0 — Foundations | Documents 1–8 frozen; 3+ customer discovery calls; openFDA pilot query; Skill stubs | **Gate 0:** problem validation passes |
| **Week 2** | Phase 1 — Ingestion + Gold Set | F1 working end-to-end; 100-record hand-labeled gold set; Pydantic schemas for DR-03 | — |
| **Week 3** | Phase 1 — Extraction + Verifier | F2 + F5 live; Skills #1 and #2 at v1.0.0; gold-set extraction accuracy ≥80% | **Gate 1:** extraction quality |
| **Week 4** | Phase 2 — Classification | F3 live; Skills #3 (severity-triage) and #4 (ai-failure-mode-classifier) at v1.0.0; classifier accuracy ≥80% on labeled subset | — |
| **Week 5** | Phase 2 — Drift | F4 live; synthetic drift cohorts; KS/PSI flagging; Skill #5 v1.0.0 | **Gate 2:** drift detection works on synthetic ground truth |
| **Week 6** | Phase 3 — Surfaces | F6 dashboard; F7 PSUR draft generator; Skills #6 and #7 v1.0.0 | — |
| **Week 7** | Phase 3 — Polish | README polish; demo video; CI green; tests at ≥70% coverage; gold-set accuracy at ≥90% | **Gate 3:** demo-ready |
| **Week 8** | Phase 4 — Launch | Public LinkedIn post; Hacker News / r/medicaldevices submission; first 5 outreach-driven informational interviews | **Exit Gate:** the email in [01_vision_mission.md §4](01_vision_mission.md) is sendable |

Hard stop: **end of Week 10**. After that, maintenance mode. See [02_project_charter.md §16](02_project_charter.md).

---

## 7. Pilot Findings (Day 1 + Day 2 — Empirical Validation)

The full report is in [00_pilot_findings.md](00_pilot_findings.md). The headline numbers:

- **22 structured extractions** across two product codes (LLZ imaging diagnostic, QIH stroke triage CAD)
- **11 AI-related signals identified** (50% of records) — these are the regulatory signals MAUDE cannot natively surface
- **11 hardware/mechanical failures** correctly classified as **non-AI** (balanced discrimination, no flag bias)
- **0 inconclusive extractions** — the model committed on every record
- **Average confidence: 0.90**
- **Total LLM cost: $0.00** (Groq Llama-3.3-70B-Versatile, free tier)

### Why this matters for the project thesis

Before the pilot, the claim that "MAUDE has an AI blind spot" rested on Babic et
al. (2025) and inference. After the pilot, on real records pulled live from
openFDA: half of randomly sampled imaging-AI adverse event reports contain
software / algorithm failure signals that MAUDE's native event_type field does
not capture. The regulatory gap is not theoretical — it shows up immediately on
small samples. This is the empirical evidence that justifies the remaining
7 weeks of build.

The balanced 11/11 split also rules out the obvious failure mode (the extractor
flagging everything as AI-related). It distinguishes power-cord failures from
algorithm failures cleanly.

---

## 8. Regulatory Context: QMSR (February 2, 2026)

The Quality Management System Regulation (QMSR) replaces 21 CFR Part 820 with a
framework that aligns FDA quality expectations to ISO 13485:2016 and adds
explicit real-world performance monitoring obligations for medical device
manufacturers. **Effective date: February 2, 2026.**

For AI/ML-enabled devices, QMSR turns three previously-optional practices into
compliance expectations:

1. **Postmarket performance monitoring** — manufacturers must demonstrate active
   surveillance, not just reactive complaint handling.
2. **Real-world signal detection** — monitoring must be capable of detecting
   degradation that does not look like a discrete malfunction (the exact gap
   SafeSignal addresses).
3. **Documented quality processes** — every signal must trace to a verifiable
   source artifact, with a reviewable audit trail.

SafeSignal is **not a QMSR-compliant eQMS**. It is a signal-surfacing tool that
produces the kind of artifacts a QMSR-compliant program needs: structured
extractions, verified citations, and reproducible reports. It is intended to
sit alongside an existing quality system, not replace one.

QMSR background: [08_glossary.md](08_glossary.md) and FDA's QMSR Final Rule
preamble (2024).

---

## 9. Disclaimer — What SafeSignal Is Not

> ⚠️ **SafeSignal is a research and signal-surfacing tool. It is NOT an
> FDA-cleared medical device. It is NOT clinical decision support. It is NOT
> a substitute for human regulatory judgment, and it is NOT legal or
> regulatory advice. Every finding requires human review before any
> regulatory action.**

Specifically, SafeSignal:

- ❌ Does **not** advise patient care or recommend clinical decisions
- ❌ Does **not** require its own 510(k) or De Novo authorization
- ❌ Does **not** handle PHI (MAUDE is already de-identified and public)
- ❌ Does **not** replace an eQMS, MDR submission system, or complaint-handling
   workflow
- ❌ Does **not** generate regulatory submissions on the user's behalf
- ❌ Does **not** speak for the FDA, any manufacturer, or any reporter

Outputs are **starting points for human regulatory review**, with every claim
traceable to its source MAUDE record and every regulatory citation verified
against a primary source. The human-in-the-loop principle is non-negotiable
(Guiding Principle #2 in [01_vision_mission.md §7](01_vision_mission.md)).

The full non-goals list lives in [01_vision_mission.md §6](01_vision_mission.md).

---

## 10. How to Read the Rest of the Repo

| If you want to know… | Read |
|---|---|
| Why this project exists | [01_vision_mission.md](01_vision_mission.md) |
| Scope, phases, commitments | [02_project_charter.md](02_project_charter.md) |
| Functional + non-functional requirements | [03_requirements_spec.md](03_requirements_spec.md) |
| Builder learning plan | [04_skills_matrix.md](04_skills_matrix.md) |
| System design + Skills architecture | [05_architecture.md](05_architecture.md) |
| Risks + mitigations | [06_risk_register.md](06_risk_register.md) |
| Week-by-week execution plan | [07_roadmap.md](07_roadmap.md) |
| Regulatory + technical glossary | [08_glossary.md](08_glossary.md) |
| Empirical pilot results | [00_pilot_findings.md](00_pilot_findings.md) |
| LLM behavior contracts | [skills/](../skills/) |
| Code | [src/safesignal/](../src/safesignal/) |
| Repo conventions for AI assistants | [CLAUDE.md](../CLAUDE.md) |

---

## 11. Change Control

Any change to this master plan must be:

1. Committed with a meaningful Git message
2. Reflected in a version bump (1.0 → 1.1 minor, → 2.0 major)
3. Justified against the core goal: *does this still serve the user, the
   QMSR-driven regulatory gap, and the 8-week runway?*

---

**End of Document 0.**
