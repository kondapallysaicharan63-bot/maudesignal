# Development Roadmap

> **Pre-existing planning draft (May 2026), kept for history.** It describes plans, not what
> MaudeSignal does today. Today: U.S. FDA data (MAUDE, recalls, 510(k)). UK MHRA alerts
> appear as labelled regulator context only, not counted. EU data is not included yet.
> Current scope: [README](../README.md#today--tomorrow).

## Phase 1 — MVP (Now → 8 weeks)

**Goal**: Working product that a real MedTech QA team can use for PMS.

| Week | Milestone |
|---|---|
| 1–2 | Multi-tenancy foundation + Auth (OAuth2/RBAC) |
| 3–4 | General Device Failure Taxonomy + FDA Compliance Checker Skill |
| 5–6 | PSUR Generator (production-quality) + Document export |
| 7 | FDA Recalls API integration + dashboard multi-tenant UI |
| 8 | Security hardening + Validation Package + pilot customer onboarding |

**Key deliverables**:
- Complete data isolation per company
- RBAC with 4 roles
- General taxonomy covering all device types
- FDA Compliance Checker (gap analysis vs QMSR + 820)
- Production PSUR generator
- IQ/OQ/PQ Validation Package template
- Docker Compose deploy

---

## Phase 2 — Growth (3–6 months)

- Predictive analytics (risk forecasting, proactive signal detection)
- AI Agent framework (low-code custom workflow builder)
- PMCF survey and clinical data collection tools
- Regulatory Intelligence (auto-alerts: new guidances, recalls, EUDAMED)
- Scheduling (automated periodic analysis runs + email/Slack/Teams)
- API + integrations (Greenlight Guru, Veeva, MasterControl, ERP)
- PubMed literature signal scanning
- FDA 510(k)/PMA predicate comparison
- React frontend + FastAPI backend migration

---

## Phase 3 — Enterprise (6+ months)

- Telemetry / connected device data ingestion
- Real-time algorithm drift monitoring
- Recall management workflows
- Complaint intake portal (public-facing)
- Full CAPA lifecycle automation
- Training management module
- Supplier Quality management
- Change Control with full impact assessment
- 21 CFR Part 11 electronic signatures
- Advanced bias detection + subgroup performance analytics
- Deep ERP / eQMS bidirectional sync

---

## Success Metrics

| Metric | Phase 1 Target | Phase 2 Target |
|---|---|---|
| Pilot customers | 5–10 | 25+ |
| PSUR generation accuracy | Human review pass rate > 85% | > 95% |
| Signal detection recall | > 80% vs manual review | > 90% |
| Test coverage | ≥ 70% | ≥ 85% |
| Deployment time | < 15 min Docker setup | < 5 min |
