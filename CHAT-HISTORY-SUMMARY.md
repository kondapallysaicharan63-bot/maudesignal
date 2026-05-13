# MaudeSignal - Full Project Context & Master Instructions

## Project Overview
I am building **MaudeSignal** — an open-source, self-hosted Post-Market Surveillance (PMS) +
Automated Technical Documentation platform for **all medical devices** (hardware, SaMD, AI/ML,
IVD, combination products).

### Core Goals
- Strong focus on **data privacy** (self-hosted, local LLM support, multi-tenancy)
- Automated signal detection from OpenFDA (MAUDE) + internal complaints
- Automated document generation (PSUR, PMS Plan, PMCF, CAPA, etc.)
- Built-in **FDA Compliance Checker**
- Lower cost + better privacy than Greenlight Guru, Smarteeva, Veeva, Qualio

## Current Status (as of May 2026)
- Two Claude Code agents configured in `.claude/agents/`:
  1. `validator.md` — FDA Process Validation Agent (FTI: Feature / Test / Integration checks)
  2. `builder.md` — PRD-reading Worker Agent (implements features per spec)
- Existing Skills pipeline: narrative extractor, severity triage, AI failure classifier,
  citation verifier, drift interpreter, trend interpreter, root-cause analyzer, PSUR drafter
- CLI (`maudesignal`) with 27 commands across 5 sub-apps
- Streamlit dashboard at `src/maudesignal/dashboard/app.py`
- SQLite/SQLAlchemy storage with 13 ORM models

## Expanded Vision (from planning sessions)
The product is expanding beyond AI/ML-only focus to cover:
- All device types (hardware, SaMD, IVD, combination)
- Enterprise multi-tenancy (each company gets completely isolated data)
- RBAC + SSO authentication
- FDA Compliance Checker (gap analysis vs 21 CFR 820, QMSR)
- Competitive pricing against Greenlight Guru / Smarteeva / Qualio

## Tech Stack
- **Backend**: FastAPI + Python 3.12
- **Orchestration**: LangGraph + PydanticAI (structured output)
- **LLM (local)**: Ollama (default for self-hosted customers)
- **LLM (cloud)**: Groq, Gemini, Anthropic (selectable via `LLM_PROVIDER`)
- **Frontend**: Streamlit (MVP) → React later
- **Database**: PostgreSQL (multi-tenant) + SQLite fallback
- **Container**: Docker Compose
- **Auth**: OAuth2/OIDC (Keycloak or Auth0)

## Agent Instructions
You are the **Senior AI Engineering Partner** for this project.

1. Always treat `docs/PRD-Complete.md` as the source of truth for requirements.
2. Read `CLAUDE.md` before any code change for non-negotiable repo conventions.
3. Keep every Skill focused, low-token, structured JSON output via Pydantic.
4. Prioritize security, auditability, and regulatory safety in all decisions.
5. When creating code, update the relevant docs and Skill versions.

## Current Build Priority
1. Multi-tenancy foundation (tenant isolation at DB + app layer)
2. Authentication (OAuth2 + RBAC roles: Admin, Analyst, Viewer, Auditor)
3. General Device Failure Taxonomy (expand beyond AI/ML)
4. FDA Compliance Checker Skill
5. PSUR Generator Skill (production-quality)
6. FDA Recalls API integration
7. Dashboard multi-tenant UI (company banner, tenant switcher)

## Data Sources Already Integrated
- OpenFDA MAUDE (adverse events)

## Data Sources to Add (Priority Order)
1. FDA Recalls API (`open.fda.gov/device/recall`)
2. FDA 510(k) / PMA database
3. PubMed literature search
4. EUDAMED (EU device vigilance, partial public)
5. Telemetry / internal data upload (Phase 2)

## Agent Coordination
- **builder** agent: reads this file + `docs/PRD-Complete.md` + `CLAUDE.md`, then implements
- **validator** agent: runs FTI check (Feature / Test / Integration) after every build

**Start working: read `docs/PRD-Complete.md` first, then give me the next 5 priority tasks.**
