# System Architecture

## High-Level Design

```
┌─────────────────────────────────────────────────┐
│                  Streamlit UI (MVP)              │
│             React + FastAPI (Phase 2)            │
└─────────────────────┬───────────────────────────┘
                      │
┌─────────────────────▼───────────────────────────┐
│              FastAPI Backend                     │
│   Auth (OAuth2/OIDC) │ RBAC │ Tenant Middleware  │
└──────┬──────────────────────────────────┬────────┘
       │                                  │
┌──────▼──────────┐             ┌─────────▼────────┐
│  Analysis       │             │  Document        │
│  Pipeline       │             │  Generator       │
│  (LangGraph)    │             │  (Jinja2/PDF)    │
└──────┬──────────┘             └──────────────────┘
       │
┌──────▼──────────────────────────────────────────┐
│              Skills Layer (PydanticAI)           │
│  narrative-extractor │ severity-triage           │
│  ai-failure-classifier │ citation-verifier       │
│  fda-compliance-checker │ psur-drafter           │
│  root-cause-analyzer │ drift-interpreter         │
└──────┬──────────────────────────────────────────┘
       │
┌──────▼──────────────────────────────────────────┐
│              LLM Provider Layer                  │
│   Ollama (local) │ Groq │ Gemini │ Anthropic     │
│            via get_provider(config)              │
└──────┬──────────────────────────────────────────┘
       │
┌──────▼──────────────────────────────────────────┐
│           Data Layer (Multi-Tenant)              │
│   PostgreSQL (enterprise) │ SQLite (default)     │
│   Separate schema/DB per tenant                 │
└─────────────────────────────────────────────────┘
```

---

## Folder Structure

```
maudesignal/
├── CLAUDE.md                   ← AI assistant instructions (non-negotiable)
├── CHAT-HISTORY-SUMMARY.md     ← Project context for AI agents
├── DISCLAIMER.md               ← Legal disclaimer
├── README.md                   ← Public landing page
├── docker-compose.yml
├── pyproject.toml
│
├── docs/                       ← All documentation
│   ├── PRD-Complete.md         ← MASTER PRD (source of truth)
│   ├── PRD-Features.md
│   ├── PRD-Security.md
│   ├── PRD-Architecture.md
│   ├── PRD-UI-UX.md
│   ├── PRD-Roadmap.md
│   ├── PRD-User-Stories.md
│   ├── PRD-Competitive-Analysis.md
│   ├── PRD-Risks-Mitigations.md
│   ├── PRD-Testing-Validation.md
│   ├── PRD-Future-Roadmap.md
│   ├── PRD-Data-Model.md
│   ├── PRD-Pricing.md
│   ├── API-Spec.md
│   ├── Deployment.md
│   └── VALIDATION-PACKAGE-README.md
│
├── skills/                     ← LLM behavior contracts
│   ├── maude-narrative-extractor/
│   ├── severity-triage/
│   ├── ai-failure-mode-classifier/
│   ├── regulatory-citation-verifier/
│   ├── root-cause-analyzer/
│   ├── drift-analysis-interpreter/
│   ├── trend-interpreter/
│   ├── psur-report-drafter/
│   └── fda-compliance-checker/      ← TO BUILD
│
├── src/maudesignal/            ← Source code (src layout)
│   ├── cli.py
│   ├── config.py
│   ├── ingestion/
│   ├── extraction/
│   │   └── llm_providers/
│   ├── classification/
│   ├── drift/
│   ├── verification/
│   ├── dashboard/
│   ├── reports/
│   ├── tenants/                ← TO BUILD (multi-tenancy)
│   └── auth/                   ← TO BUILD (OAuth2 + RBAC)
│
├── tests/
├── validation_package/         ← IQ/OQ/PQ templates
└── .claude/agents/             ← AI agent definitions
    ├── builder.md
    └── validator.md
```

---

## Deployment Options

### 1. Self-Hosted (Default — Recommended)
```bash
git clone https://github.com/your-org/maudesignal.git
cd maudesignal
docker compose up -d
# Dashboard at http://localhost:8501
```

Requirements: Docker + Docker Compose, 8GB RAM min (16GB recommended), GPU optional for local LLMs.

### 2. Local Development
```bash
python3.12 -m pip install -e .
python3.12 -m streamlit run src/maudesignal/dashboard/app.py
```

### 3. Enterprise Hosted (Future)
- AWS / Azure private VPC
- Customer-managed encryption keys
- Strict tenant isolation + dedicated infrastructure per customer

---

## Key Design Decisions

| Decision | Choice | Reason |
|---|---|---|
| LLM abstraction | `get_provider(config)` factory | Provider-agnostic, testable, auditable |
| Prompt storage | `skills/*/SKILL.md` files | Version-controlled, auditable, ALCOA+ |
| Multi-tenancy | DB per tenant | Strongest isolation, simplest audit trail |
| Temperature | 0.0 always | Reproducibility for regulatory auditability |
| Citation gate | Hard gate on all string outputs | Prevents hallucinated regulatory citations |
