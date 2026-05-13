# Risks & Mitigations

## Product Risks

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| LLM hallucinated regulatory citations | High | Critical | Mandatory citation hard-gate (verifier Skill); human review workflow |
| Regulatory non-acceptance of AI-generated documents | Medium | High | Clear disclaimers; Validation Package; docs are drafts for human review |
| Data breach (multi-tenant isolation failure) | Low | Critical | DB-per-tenant; middleware enforcement; penetration testing |
| Model drift in signal detection | Medium | Medium | Evidently monitoring; drift-analysis-interpreter Skill; alerts |
| Performance degradation with large datasets | Medium | Medium | Async processing; pagination; benchmark tests for 10k+ records |

## Business Risks

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Long sales cycles (6–12 months in MedTech) | High | High | Free pilots; strong case studies; target smaller companies first |
| Brand/trust gap vs established vendors | High | Medium | Open-source transparency; auditable Skills; pilot program |
| Competition from incumbents copying features | Medium | Medium | Move fast on differentiators (local LLM, all-device, price) |
| Developer resource constraints | Medium | High | Narrow scope (F1–F7 only); modular Skills reduce complexity |

## Legal & Compliance Risks

| Risk | Mitigation |
|---|---|
| Tool used as clinical decision support | Explicit disclaimer on every generated output; "decision-support only" framing |
| PHI accidentally ingested | MAUDE is pre-anonymized; PHI detection logging; immediate CRITICAL log + record skip |
| Regulatory citation errors | Citation verifier hard gate; only verified sources (openFDA, CFR, FDA guidance index) |
| Export control issues | All local data; no cross-border data transfer in self-hosted mode |

## Technical Risks

| Risk | Mitigation |
|---|---|
| Skill prompt changes breaking existing extractions | Version pinning; gold-set evaluation; semver bumps |
| Provider API deprecation | Provider-agnostic factory; 4 providers + local Ollama fallback |
| SQLite limitations at scale | PostgreSQL migration path documented; multi-tenant schema already designed |
