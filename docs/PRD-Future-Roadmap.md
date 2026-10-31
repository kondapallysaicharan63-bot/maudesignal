# Future Roadmap & Competitive Parity

> **Pre-existing planning draft (May 2026), kept for history.** It describes plans, not what
> MaudeSignal does today. Today: U.S. FDA data (MAUDE, recalls, 510(k)). UK MHRA alerts
> appear as labelled regulator context only, not counted. EU data is not included yet.
> Current scope: [README](../README.md#today--tomorrow).

## Strategic Goal (2026–2027)
Match or exceed Smarteeva/Greenlight Guru in AI depth while maintaining the self-hosted
privacy advantage. Become the best open/self-hosted PMS option with predictive analytics,
clinical data capabilities, and enterprise integrations.

---

## Key Future Features

### 1. Predictive Analytics & AI Agents
- **Risk Forecasting**: Predict potential signal escalations 30–90 days ahead based on trends
- **Proactive Signal Detection**: Alert before a signal reaches statistical significance
- **AI Agent Builder**: Low-code interface for custom regulatory workflows
  - Example: "When severity=CRITICAL AND failure_mode=drift → auto-draft CAPA input AND alert RA Manager"
- **Auto-suggested CAPA actions** with explanations and regulatory backing

### 2. PMCF & Clinical Data Collection
- Integrated survey forms for PMCF (ISO 14155-aligned)
- Patient / clinician feedback module linked directly to PMS analysis
- Registry data import (national device registries)
- ePRO/eCOA data capture interface

### 3. Real-World Data & Telemetry
- IoT / connected device telemetry ingestion API
- Continuous algorithm performance monitoring (for AI/ML devices)
- Real-time drift detection with configurable alert thresholds
- Integration with device manufacturer data lakes

### 4. Regulatory Intelligence
- Automatic monitoring of new FDA guidances, 510(k) decisions, recalls
- EUDAMED vigilance data integration (as EU public access expands)
- Push notifications to relevant users when their product codes are affected
- Regulatory change impact assessment (which documents need updating?)

### 5. Advanced Automation
- Recall management workflow (detection → notification → CAPA → closure)
- Complaint intake portal (public-facing, for post-market feedback collection)
- Full CAPA lifecycle with traceability from signal to closure
- Automated periodic analysis scheduling (daily/weekly/monthly runs)

### 6. Enterprise Modules
- Training management (link SOPs to personnel, track completion)
- Supplier Quality management (link supplier events to device signals)
- Change Control with full impact assessment (risk, regulatory, document)
- 21 CFR Part 11 electronic signatures on all generated documents
- Advanced audit management (internal + external audit scheduling + reports)
- Management Review dashboard automation

---

## Competitive Parity Timeline

| Feature | MaudeSignal Target | Primary Competitor |
|---|---|---|
| Predictive analytics | Phase 2 (Q3 2026) | Smarteeva (now) |
| PMCF surveys | Phase 2 (Q3 2026) | Greenlight Guru (now) |
| Regulatory intelligence | Phase 2 (Q4 2026) | Qualio (now) |
| Telemetry ingestion | Phase 3 (2027) | ComplianceQuest (beta) |
| Training management | Phase 3 (2027) | MasterControl (now) |
| Electronic signatures | Phase 3 (2027) | All major competitors |

---

## Our Permanent Differentiators
These are things we can do that cloud-only competitors structurally cannot:

1. **Complete data sovereignty** (self-hosted + local LLM) — no cloud vendor can claim this
2. **Open-source auditable Skills** — transparent AI behavior for regulatory trust
3. **Sub-$15k entry pricing** — 30–50% cheaper than any comparable tool
4. **Air-gapped operation** — works with zero internet connectivity (Ollama + offline FDA index)
