# User Stories & Acceptance Criteria

## Personas

| Persona | Role | Primary Need |
|---|---|---|
| RA/QA Manager | Primary decision-maker | Reports for leadership and regulators |
| Quality Engineer | Daily operator | Run analyses, manage signals |
| RA Specialist | Submission prep | PSURs, PMCF, compliance checking |
| Company Admin | Governance | Users, settings, audit |

---

## Phase 1 — Must-Have Stories

### Authentication & Multi-Tenancy

**US-01**: As a Company Admin, I can create my organization's tenant so that my team's data is completely isolated from other companies.
- Acceptance: Each tenant has a separate database; no cross-tenant query is possible.
- Acceptance: A clear "Viewing: [Company Name]" banner appears on every screen.

**US-02**: As a Company Admin, I can invite team members and assign RBAC roles (Admin, Analyst, Viewer, Auditor) so that access is appropriately controlled.
- Acceptance: Viewer cannot trigger analysis or generate documents.
- Acceptance: Auditor can see audit logs but cannot modify data.

**US-03**: As a user, I can log in via SSO (Azure AD / Okta) so that I don't need a separate password.

---

### Data Ingestion

**US-04**: As a Quality Engineer, I can import MAUDE adverse events by product code so that I have the complete public signal picture.
- Acceptance: Import completes for 1,000 records in < 2 minutes.

**US-05**: As a Quality Engineer, I can upload internal complaint records (CSV/JSON) so that I can combine it with MAUDE for a complete analysis.
- Acceptance: CSV columns are mapped to the standard schema via a guided mapper.

**US-06**: As an RA Manager, I can run a portfolio analysis across multiple product codes so that I get a single cross-device risk view.

---

### Analysis

**US-07**: As a Quality Engineer, I can run signal detection on a date range so that I identify statistically significant trends.
- Acceptance: Mann-Kendall p-value and trend direction are shown.

**US-08**: As a Quality Engineer, I can view failure mode classification for each event using the General Device Taxonomy and AI/ML Taxonomy so that I understand root cause distribution.

**US-09**: As an RA Specialist, I can run the FDA Compliance Checker on a generated report so that I get a clear gap list before regulatory submission.
- Acceptance: Each gap references the specific 21 CFR section or QMSR clause.
- Acceptance: Citation verifier has passed for every flagged reference.

---

### Documentation

**US-10**: As an RA Specialist, I can generate a PSUR draft with one click so that I have a professional starting point for submission preparation.
- Acceptance: Output includes all mandatory PSUR sections per MDR Annex III / QMSR.
- Acceptance: All regulatory citations have passed the citation verifier gate.

**US-11**: As an RA Manager, I can export any generated document as PDF or Word so that I can share it with my team and regulators.

**US-12**: As a Quality Engineer, I can view version history and compare two document versions so that I track changes over time.

---

### Reporting & Dashboard

**US-13**: As an RA Manager, I can see an overall Risk Score on the dashboard so that I know at a glance if my device portfolio is in a good state.
- Acceptance: Risk score is color-coded (Green/Yellow/Red) with a one-line explanation.

**US-14**: As any user, I can export signal data to CSV so that I can do my own analysis in Excel.

---

## Phase 2 — Nice-to-Have Stories

**US-15**: As an RA Specialist, I receive an automated email alert when a new high-severity signal is detected so that I can respond quickly.

**US-16**: As an RA Manager, I can compare signals across device versions so that I can assess whether a design change improved safety.

**US-17**: As a Quality Engineer, I can see regulatory intelligence updates (new FDA guidances, recalls) relevant to my product codes so that I stay current without manual monitoring.

**US-18**: As an RA Specialist, I can collect PMCF survey data within the platform so that I have a complete post-market evidence picture in one place.
