# MaudeSignal — Complete Product Requirements Document (PRD)

**Product:** MaudeSignal
**Version:** 2.0
**Date:** May 2026
**Status:** Active — source of truth for all development

---

## 1. Vision & Positioning

**MaudeSignal** is an open-source, self-hosted Post-Market Surveillance (PMS) + Automated
Technical Documentation platform for **all medical devices** — hardware, SaMD, AI/ML-enabled,
IVD, and combination products.

It helps MedTech companies meet **FDA QMSR**, 21 CFR 820, EU MDR/IVDR, and ISO 13485
requirements while maintaining **complete data privacy and sovereignty**.

### Core Value Proposition
- **Secure by design**: Self-hosted default — customer data never leaves their environment.
- **All-in-one**: Signal detection + Automated Document Generation + FDA Compliance Checking.
- **Transparent & Auditable**: Skills-based AI with mandatory citation verification.
- **Cost-effective**: 30–50% lower than Greenlight Guru, Smarteeva, Veeva, or Qualio.

---

## 2. Key Differentiators

| Feature | MaudeSignal | Typical Competitors |
|---|---|---|
| Deployment | Self-hosted + Local LLM (default) | Mostly Cloud / SaaS |
| Data Privacy | 100% on-premise, zero vendor data sharing | Data uploaded to vendor servers |
| Device Coverage | All device types + specialized AI/ML taxonomy | Often general or AI-only |
| Technical Writing | Built-in PSUR, PMS Plan, CAPA auto-generation + FDA Checker | Limited or add-on |
| Transparency | Open-source core + auditable Skills | Closed black-box AI |
| Pricing | Much more affordable | $25k–$80k+/year |
| Validation Support | Full IQ/OQ/PQ Validation Package | Varies |

**Unique Extras**:
- True data sovereignty for security-conscious companies (air-gapped support via Ollama).
- Combined PMS + Technical Writing in one tool.
- Open-source foundation builds trust and community.

---

## 3. Target Users

| Persona | Role | Primary Need |
|---|---|---|
| RA/QA Manager | Primary | Reports for leadership and regulators |
| Quality Engineer | Daily user | Run analyses, manage signals |
| Regulatory Affairs Specialist | Periodic | Prepare submissions and PSURs |
| Company Admin | Setup & governance | Manage users, settings, audit |

**Target companies**: Small-to-large MedTech manufacturers, especially those finding incumbent
tools too expensive or too cloud-heavy.

---

## 4. Core Features — Phase 1 (MVP)

### F1. Data Ingestion
- MAUDE adverse event import via OpenFDA API (by product code)
- FDA Recalls API integration
- CSV / JSON upload for internal complaints
- Multiple product code / portfolio analysis

### F2. Analysis Engine
- **General Medical Device Failure Taxonomy**: hardware, usability, labeling, manufacturing,
  sterilization, packaging, software
- **AI/ML Specific Taxonomy**: drift, automation bias, performance degradation, cybersecurity,
  training data issues
- Signal detection and trend analysis
- Severity and causality assessment
- Subgroup analysis (age, gender, race, device version)

### F3. Documentation Automation
- Auto-generation of: PMS Plan, PSUR, PMCF Plan, CAPA inputs, Risk File updates
- **FDA Compliance Checker**: flags missing elements per 21 CFR 820.198, QMSR, Section 522
- Version control and comparison of generated documents
- PDF/Word/CSV export with professional formatting

### F4. Dashboard & Reporting
- Streamlit dashboard with sidebar navigation
- Executive summaries, visualizations, risk scoring cards
- Multi-tenant UI: company name banner, clear data isolation indicators
- Device portfolio view

### F5. Security & Multi-Tenancy
- **Database per tenant** (separate schema or SQLite file per company)
- Tenant ID enforced at every application and database layer
- RBAC: Admin, Analyst, Viewer, Auditor roles
- OAuth2 / OIDC authentication (Keycloak, Auth0, or Ory Kratos)
- SSO support (SAML, Azure AD, Okta)
- Audit logging: every action (who, what, when, which model) stored per tenant
- Session timeout (30 min default)

### F6. Regulatory Citation Verification (Hard Gate)
- Every user-facing string field passes through `regulatory-citation-verifier` Skill.
- Verifier uses only: openFDA, curated CFR Parts list, local FDA guidance index.
- No LLM training-data knowledge as verification source.

### F7. Reports & Export
- PSUR-style PDF reports via Jinja2 → WeasyPrint
- CSV export for raw signal data
- Professional formatting suitable for submission preparation

---

## 5. Phase 2–3 Features (Roadmap)

### Phase 2 (3–6 months)
- **Predictive Analytics**: Risk forecasting, proactive signal detection, trend prediction
- **AI Agent Framework**: Low-code agent builder for custom regulatory workflows
- **PMCF & Survey Tools**: Patient feedback collection, registry data import
- **Regulatory Intelligence**: Auto-alerts for new FDA guidances and recalls
- **Integrations**: Greenlight Guru, Veeva, MasterControl, ERP bidirectional sync
- **Scheduled Runs + Alerts**: Email, Slack, Teams notifications

### Phase 3 (6+ months)
- **Telemetry / Connected Device**: Real-time ingestion, algorithm drift monitoring
- **Advanced Automation**: Recall management workflows, complaint intake portal
- **Enterprise Modules**: Training management, Supplier Quality, Change Control,
  full CAPA lifecycle, 21 CFR Part 11 electronic signatures
- **Advanced Analytics**: Bias detection, subgroup performance analysis

---

## 6. Non-Functional Requirements

| Category | Requirement |
|---|---|
| Security | Multi-tenancy (separate DB per tenant), E2E encryption, local LLM priority |
| Performance | Handle 10,000+ records efficiently; async processing |
| Usability | Clean, professional medical-grade UI; WCAG 2.1 AA |
| Compliance | Full Validation Package (IQ/OQ/PQ, ISO 14971 risk assessment) |
| Deployment | Docker Compose single-command self-hosting |
| LLM | Provider-agnostic via `get_provider(config)`; temperature=0.0 for all analysis |
| Auditability | Every LLM call logged with model, tokens, confidence, timestamp |

---

## 7. Data Sources

### Currently Integrated
- OpenFDA MAUDE (adverse events by product code)

### Phase 1 Additions
- FDA Recalls API (`open.fda.gov/device/recall`)
- FDA 510(k) / PMA database (clearance history, predicates)

### Phase 2 Additions
- PubMed literature search (safety signals in published research)
- EUDAMED (EU device vigilance — partial public access)
- ClinicalTrials.gov (device-specific clinical studies)

### Phase 3
- Telemetry / connected device data ingestion (customer-provided)
- Social listening (with strict data quality controls)

---

## 8. Architecture

- **Frontend**: Streamlit (MVP) → React + FastAPI (Phase 2)
- **Backend**: Python 3.12 + FastAPI
- **Orchestration**: LangGraph + PydanticAI
- **LLM (local)**: Ollama (default for self-hosted; supports Llama 4, DeepSeek-R1, MedGemma)
- **LLM (cloud)**: Groq, Gemini, Anthropic (via `LLM_PROVIDER` env var)
- **Database**: PostgreSQL multi-tenant + SQLite fallback
- **Container**: Docker + Docker Compose
- **Auth**: OAuth2/OIDC

---

## 9. Pricing

| Tier | Price | Notes |
|---|---|---|
| Community | $0 | Self-hosted, limited devices |
| Starter | $9,000–$14,000/year | Up to 5 devices |
| Professional | $22,000–$35,000/year | Up to 25 devices |
| Enterprise | $45,000–$85,000+/year | Unlimited, custom SLA |
| Onboarding | $4,000–$12,000 one-time | Setup + validation support |

---

## 10. Risks & Mitigations

| Risk | Mitigation |
|---|---|
| LLM hallucinations | Mandatory citation hard-gating + human review workflow |
| Regulatory acceptance | Comprehensive Validation Package (IQ/OQ/PQ) |
| Data security breach | Strict multi-tenancy + self-hosted default + E2E encryption |
| Long sales cycles | Free pilots + strong case studies + pilot program |
| Brand & trust gap | Open-source transparency + auditable Skills architecture |

---

## 11. Roadmap

| Phase | Timeline | Milestones |
|---|---|---|
| Phase 1 (MVP) | Now → 8 weeks | Multi-tenancy, auth, general taxonomy, documentation generator, FDA checker, security hardening, validation package |
| Phase 2 | 3–6 months | Predictive AI, PMCF tools, regulatory intelligence, scheduling, integrations |
| Phase 3 | 6+ months | Telemetry, enterprise modules, advanced analytics |

---

## 12. Legal

See [DISCLAIMER.md](../DISCLAIMER.md).

MaudeSignal is a signal-review aid. Final regulatory responsibility remains with the
device manufacturer.
