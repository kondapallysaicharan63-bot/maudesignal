# Features & Requirements

## MVP Core Features (Phase 1)

### F1. Data Ingestion
- MAUDE database import by product code (OpenFDA)
- FDA Recalls API integration
- CSV / JSON upload for internal complaints
- Multiple product code / portfolio analysis

### F2. Analysis Engine

**General Medical Device Failure Taxonomy:**
- Hardware failure (mechanical, electrical, material)
- Usability / human factors
- Labeling / IFU deficiency
- Manufacturing / process defect
- Sterilization failure
- Packaging failure
- Software defect (non-AI)

**AI/ML Specific Failure Taxonomy:**
- Model drift (data, concept, performance)
- Automation bias / over-reliance
- Training data issues (bias, distribution shift)
- Cybersecurity vulnerability
- Explainability failure
- Out-of-distribution inputs

**Analysis capabilities:**
- Signal detection and trend analysis (Mann-Kendall + statistical tests)
- Severity and causality assessment
- Subgroup analysis (age, gender, race, device version, facility)
- Root cause clustering

### F3. Documentation Automation
- PMS Plan generation
- PSUR (Periodic Safety Update Report) drafting
- PMCF Plan generation
- CAPA input drafting
- Risk file update recommendations
- **FDA Compliance Checker**: flags gaps vs 21 CFR 820.198, QMSR, Section 522
- Document version control and comparison
- PDF / Word / CSV export

### F4. Dashboard
- Streamlit dashboard with role-based views
- Risk scoring cards (color-coded)
- Interactive charts (Plotly/Altair)
- Multi-tenant: company banner + isolated data
- Portfolio view (multiple devices)

### F5. Security & Multi-Tenancy
- Database per tenant (complete data isolation)
- OAuth2/OIDC + SSO
- RBAC (Admin, Analyst, Viewer, Auditor)
- Audit logging of all actions + LLM calls
- Session timeout

### F6. Reporting
- PSUR-style PDF reports
- Professional formatting for regulatory submission preparation
- CSV export for raw data

---

## Phase 2 Features

- Predictive risk analytics and signal forecasting
- AI Agent framework (low-code custom workflow builder)
- PMCF survey / patient feedback collection tools
- Regulatory intelligence (auto-alerts: new FDA guidances, recalls, EUDAMED updates)
- Scheduling (automated periodic runs + email/Slack/Teams alerts)
- API + integrations (Greenlight Guru, Veeva, MasterControl, ERP)
- PubMed literature signal scanning
- FDA 510(k)/PMA predicate comparison

---

## Phase 3 Features

- Telemetry / connected device data ingestion
- Algorithm drift real-time monitoring
- Recall management workflows
- Complaint intake portal (public-facing)
- Full CAPA lifecycle automation
- Training management module
- Supplier Quality module
- Change Control with impact assessment
- 21 CFR Part 11 electronic signatures
- Advanced bias detection + subgroup performance analytics

---

## Non-Functional Requirements

| Category | Requirement |
|---|---|
| Performance | 10,000+ records without degradation; async processing |
| Security | Multi-tenancy, E2E encryption, local LLM support |
| Usability | WCAG 2.1 AA; clean medical-grade UI |
| Compliance | IQ/OQ/PQ Validation Package provided |
| Deployment | Docker Compose single-command; no internet required (local LLM) |
| Auditability | Every LLM call logged: model, tokens, confidence, timestamp, tenant |
| Reproducibility | LLM temperature=0.0; deterministic analysis runs |
