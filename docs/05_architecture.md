# Document 5: Technical Architecture

**Project Name:** MaudeSignal
**Owner:** [Your Name]
**Version:** 1.0 (Draft)
**Date:** [Today's Date]
**References:** Documents 1–4
**Status:** Draft

---

## 1. Purpose of This Document

This document is the technical blueprint. It defines:

- System context (what interacts with what)
- Internal components (what the system is made of)
- Data flow (how information moves)
- Tech stack (what we build with, and why)
- Claude Skills architecture (`SKILL.md` files — the LLM behavior contracts)
- Folder structure
- Key design decisions and their rationale

**This is drawn before code is written.** Once approved, the code is expected to match this document. Deviations require an update here first.

---

## 2. System Context Diagram

**Who/what interacts with MaudeSignal:**

```
                         ┌─────────────────────┐
                         │     openFDA API     │
                         │  (MAUDE, 510(k),    │
                         │  Guidance index)    │
                         └─────────┬───────────┘
                                   │ (pulls data)
                                   │
                         ┌─────────▼───────────┐
                         │                     │
   ┌──────────────┐      │                     │      ┌──────────────┐
   │  User (RA /  │◄────►│     MaudeSignal      │◄────►│  Anthropic   │
   │  QA analyst) │      │   (local system)    │      │  Claude API  │
   └──────────────┘      │                     │      └──────────────┘
     CLI + Browser       │                     │
                         └─────────┬───────────┘
                                   │
                                   │ (writes)
                                   ▼
                         ┌─────────────────────┐
                         │  Local SQLite DB    │
                         │  + Reports folder   │
                         │  + Audit logs       │
                         └─────────────────────┘
```

**External systems:**
- openFDA API — data source (read-only)
- Anthropic Claude API — inference provider (stateless)
- User — single operator, local machine

**Boundaries:**
- MaudeSignal does NOT talk to any cloud storage
- MaudeSignal does NOT send user data to any third party other than Claude (input narratives only)
- MaudeSignal does NOT receive or store PHI (MAUDE is already de-identified)

---

## 3. Component Architecture

MaudeSignal is a monolith with clearly separated modules. Each module corresponds to one or more features from Documents 2 and 3.

```
┌─────────────────────────────────────────────────────────────┐
│                        MaudeSignal                           │
│                                                             │
│  ┌──────────────┐   ┌──────────────┐   ┌────────────────┐   │
│  │  ingestion/  │──►│  storage/    │◄──│  extraction/   │   │
│  │  (F1)        │   │  (SQLite)    │   │  (F2)          │   │
│  └──────────────┘   └──────┬───────┘   └────────┬───────┘   │
│                            │                    │           │
│                            ▼                    ▼           │
│                     ┌──────────────┐   ┌────────────────┐   │
│                     │ classifier/  │◄──│    skills/     │   │
│                     │ (F3)         │   │  SKILL.md      │   │
│                     └──────┬───────┘   │  definitions   │   │
│                            │           └────────────────┘   │
│                            ▼                                │
│                     ┌──────────────┐   ┌────────────────┐   │
│                     │ drift/ (F4)  │   │ verifier/ (F5) │   │
│                     └──────┬───────┘   └────────┬───────┘   │
│                            │                    │           │
│                            ▼                    ▼           │
│                     ┌──────────────┐   ┌────────────────┐   │
│                     │ dashboard/   │   │  report/ (F7)  │   │
│                     │ (F6)         │   │                │   │
│                     └──────────────┘   └────────────────┘   │
└─────────────────────────────────────────────────────────────┘
```

### 3.1 Module Responsibilities

| Module | Feature | Responsibility | Depends On |
|---|---|---|---|
| `ingestion/` | F1 | Pull MAUDE via openFDA, handle pagination/retries, store raw | `storage/` |
| `storage/` | cross-cutting | SQLite schema + ORM layer, idempotent writes | — |
| `extraction/` | F2 | LLM-driven structured extraction from narratives | `storage/`, `skills/`, `verifier/` |
| `skills/` | cross-cutting | Versioned `SKILL.md` files loaded at runtime | — |
| `classifier/` | F3 | Multi-label AI failure-mode taxonomy | `storage/`, `skills/` |
| `drift/` | F4 | Synthetic performance simulator + drift detectors | `storage/` |
| `verifier/` | F5 | Regulatory citation verification against primary sources | `storage/`, openFDA |
| `dashboard/` | F6 | Streamlit UI | `storage/` |
| `report/` | F7 | PSUR-style Markdown + PDF generation | `storage/`, `verifier/` |

### 3.2 Dependency Rules (Keep It Clean)

1. **`storage/` is the hub.** Everything reads/writes through it. No module talks to the DB directly.
2. **`skills/` is a pure resource.** Loaded by modules that use LLMs. Not a runtime dependency itself.
3. **`verifier/` runs last.** Before any output hits a user, it passes through `verifier/`.
4. **`dashboard/` and `report/` are read-only.** They do not write to storage.
5. **No circular imports.** Ingestion doesn't know about dashboard. Dashboard doesn't know about ingestion.

---

## 4. Data Flow — End-to-End

The happy path: raw MAUDE report → structured, classified, verified output in dashboard.

```
1. User runs:  maudesignal ingest --product-code QIH --months 12
         │
         ▼
2. ingestion/ calls openFDA API (paginated)
         │
         ▼
3. Raw JSON stored in  storage.raw_reports  (SQLite)
         │
         ▼
4. User runs:  maudesignal process
         │
         ▼
5. extraction/ loads each narrative from  raw_reports
         │
         ▼
6. extraction/ loads SKILL.md (maude-narrative-extractor v1.x)
         │
         ▼
7. extraction/ calls Claude API with Skill-defined prompt
         │
         ▼
8. extraction/ validates output against JSON schema (DR-03)
         │
         ▼
9. verifier/ checks any regulatory citations in output
         │
         ▼
10. Structured extraction stored in  storage.extractions
         │
         ▼
11. classifier/ loads extracted records; assigns taxonomy labels
         │
         ▼
12. Classifications stored in  storage.classifications
         │
         ▼
13. drift/ (parallel branch) simulates or reads deployed-model metrics
         │
         ▼
14. drift/ emits alerts to  storage.drift_alerts
         │
         ▼
15. User runs:  maudesignal dashboard
         │
         ▼
16. dashboard/ reads from storage and renders 5 Streamlit views
         │
         ▼
17. User runs:  maudesignal report --period 2024-Q4
         │
         ▼
18. report/ builds PSUR-style Markdown/PDF, citations verified
```

Each arrow above is a testable boundary — a candidate for a unit or integration test.

---

## 5. Tech Stack (with Justifications)

### 5.1 Core Stack

| Layer | Technology | Version | Why this choice |
|---|---|---|---|
| Language | Python | 3.11+ | Dominant in data/ML; strong typing via `typing`; Claude SDK native |
| LLM provider | Anthropic Claude | `claude-opus-4-7`, `claude-sonnet-4-6` | Best for structured extraction; audit-friendly; aligns with product identity |
| Database | SQLite | stdlib | Zero-config; perfect for laptop MVP; single-file portability |
| ORM | SQLAlchemy (Core, not ORM) | 2.x | Explicit, typed, avoids magic; easier to audit |
| HTTP client | `httpx` | latest | Modern, async-capable, cleaner than `requests` |
| Data wrangling | `pandas` | 2.x | Standard; fine at MVP scale |
| Validation | `pydantic` | 2.x | Schema enforcement for LLM outputs |
| Dashboard | Streamlit | 1.x | 50 lines → working dashboard; zero frontend work |
| Drift detection | `evidently` + `scipy` | latest | Industry-standard drift lib + statistical primitives |
| PDF generation | `reportlab` or `weasyprint` | latest | Markdown → PDF for F7 reports |
| CLI framework | `typer` | latest | Modern, typed CLI generation from Python functions |
| Testing | `pytest` + `pytest-cov` | latest | Standard |
| Typing | `mypy` strict | latest | Catches bugs before runtime; NFR-11 |
| Linting | `ruff` + `black` | latest | Fast, opinionated, CI-ready |
| CI | GitHub Actions | — | Free for public repos |
| Packaging | `pyproject.toml` + `uv` or `pip` | — | Modern Python packaging standard |

### 5.2 What We Explicitly Do NOT Use (And Why)

| Technology | Why not |
|---|---|
| Postgres / MySQL | Overkill for laptop MVP; SQLite is more portable |
| Docker | Not needed for single-user local tool; adds complexity |
| FastAPI | No API surface needed; CLI + Streamlit is enough |
| React / Next.js | Streamlit covers UI; React is not worth the time |
| Redis / message queues | No async coordination needed |
| AWS / cloud | No deployment; no egress cost; no compliance overhead |
| Kubernetes | Absurd for this scope; mentioned only to preemptively exclude |
| LangChain / LlamaIndex | Hides what matters; we want explicit Claude API calls + Skills |
| Fine-tuned models | Pure prompt/Skill engineering in v1 |

### 5.3 LLM Model Selection Policy

- **Bulk extraction:** `claude-sonnet-4-6` (cost-effective, high quality)
- **Complex reasoning / failure classification:** `claude-opus-4-7` (best reasoning)
- **Citation verification:** Rule-based + targeted Claude calls only where needed

Model choice is recorded per extraction for audit (FR-12).

---

## 6. Folder Structure

```
maudesignal/
├── README.md
├── LICENSE                          # MIT
├── pyproject.toml
├── .env.example
├── .gitignore
│
├── docs/                            # 8 project documents + extras
│   ├── 00_customer_discovery.md
│   ├── 01_vision_mission.md
│   ├── 02_project_charter.md
│   ├── 03_requirements_spec.md
│   ├── 04_skills_matrix.md
│   ├── 05_architecture.md           # <-- this file
│   ├── 06_risk_register.md
│   ├── 07_roadmap.md
│   ├── 08_glossary.md
│   ├── 09_whitepaper.md             # final writeup
│   └── 10_retrospective.md          # post-project reflection
│
├── skills/                          # Claude SKILL.md files
│   ├── maude-narrative-extractor/
│   │   ├── SKILL.md
│   │   ├── VERSION
│   │   ├── examples/
│   │   │   ├── good.jsonl
│   │   │   └── bad.jsonl
│   │   └── schemas/
│   │       └── output.schema.json
│   ├── ai-failure-mode-classifier/
│   │   └── SKILL.md
│   ├── severity-triage/
│   │   └── SKILL.md
│   ├── regulatory-citation-verifier/
│   │   └── SKILL.md
│   ├── drift-analysis-interpreter/
│   │   └── SKILL.md
│   ├── fda-guidance-retriever/
│   │   └── SKILL.md
│   └── psur-report-drafter/
│       └── SKILL.md
│
├── schemas/                         # JSON schemas for all structured outputs
│   ├── extraction_output.schema.json
│   ├── classification_output.schema.json
│   └── drift_alert.schema.json
│
├── src/
│   └── maudesignal/
│       ├── __init__.py
│       ├── cli.py                   # typer CLI entry points
│       ├── config.py
│       ├── ingestion/
│       ├── storage/
│       ├── extraction/
│       ├── classifier/
│       ├── drift/
│       ├── verifier/
│       ├── dashboard/
│       │   └── app.py
│       ├── report/
│       └── common/                  # logging, types, exceptions
│
├── tests/
│   ├── unit/
│   ├── integration/
│   ├── fixtures/                    # sample MAUDE records, mock responses
│   └── gold_set/                    # hand-labeled 100-record test set
│
├── data/                            # gitignored — local DB, logs, reports
│   ├── maudesignal.db
│   ├── logs/
│   └── reports/
│
├── scripts/                         # one-off utilities
│   ├── build_gold_set.py
│   └── benchmark_extraction.py
│
└── .github/
    └── workflows/
        ├── test.yml
        ├── lint.yml
        └── typecheck.yml
```

---

## 7. Claude Skills Architecture

This is the most important architectural decision in the project. Every LLM behavior lives in a versioned `SKILL.md` file — **not** as an inline Python string.

### 7.1 Why Skills Matter

1. **Reproducibility:** Versioned behavior → same input + same Skill version = same output class
2. **Auditability:** Regulators can read the Skill to understand how the system reasons
3. **Iteration:** Improve a Skill without touching Python code
4. **Separation of concerns:** Behavior vs. orchestration are cleanly split
5. **ALCOA+ alignment:** Attributable, Legible, Contemporaneous, Original, Accurate — Skills make all five achievable

### 7.2 SKILL.md Template (Canonical Structure)

Every SKILL.md file follows this exact structure:

```markdown
# Skill: [skill-name]

**Version:** X.Y.Z (semver)
**Last Updated:** YYYY-MM-DD
**Owner:** [Name]
**Status:** Draft | Active | Deprecated

## Description
One-paragraph explanation of what this Skill does and when it triggers.

## When to Use
- Explicit trigger conditions
- Examples of inputs that activate this Skill
- Examples of inputs that should NOT activate this Skill (and what should instead)

## Inputs
- Expected input format (with schema reference if applicable)
- Required fields
- Optional fields

## Outputs
- Exact output schema (reference the file in schemas/)
- Example output

## Procedure
Numbered, deterministic steps the Skill must follow.
1. Do X
2. Check Y
3. If Z condition, handle this way
4. Otherwise, handle that way

## Rules & Constraints
- NEVER do this
- ALWAYS do that
- Edge cases and how to handle them
- What to output when input is malformed

## Examples

### Good Example 1
**Input:** ...
**Output:** ...
**Why good:** ...

### Bad Example 1
**Input:** ...
**Wrong output:** ...
**Why wrong:** ...
**Correct output:** ...

(Minimum 3 good examples and 2 bad examples per Skill.)

## Validation
How to verify the Skill's output is correct. Reference test fixtures.

## References
- Links to FDA guidance, papers, standards that ground the Skill
- Related Skills

## Changelog
- v1.0.0 (2026-XX-XX): Initial version
- v1.1.0 (2026-XX-XX): Added X
```

### 7.3 The 7 Skills

| # | Skill | Purpose | Priority |
|---|---|---|---|
| 1 | `regulatory-citation-verifier` | Verify/reject all regulatory citations (blocks hallucinations) | **First** — everything depends on it |
| 2 | `maude-narrative-extractor` | Extract structured fields from MAUDE narratives | Core |
| 3 | `severity-triage` | Standardize severity to FDA MDR categories | Core |
| 4 | `ai-failure-mode-classifier` | Assign AI-specific failure taxonomy labels | Core (differentiator) |
| 5 | `drift-analysis-interpreter` | Translate statistical drift results to regulatory language | Supporting |
| 6 | `fda-guidance-retriever` | RAG over FDA guidance corpus with grounded citations | Supporting |
| 7 | `psur-report-drafter` | Compose periodic safety report from structured data | Final output |

### 7.4 Build Order (Strict)

1. **regulatory-citation-verifier** (first — everything depends on it)
2. **maude-narrative-extractor**
3. **severity-triage**
4. **ai-failure-mode-classifier**
5. **drift-analysis-interpreter** (parallel-able with 4)
6. **fda-guidance-retriever** (when RAG corpus is ready)
7. **psur-report-drafter** (last — consumes outputs of all above)

### 7.5 Skill Versioning

- Semantic versioning: `MAJOR.MINOR.PATCH`
  - MAJOR — output schema changes (breaking)
  - MINOR — new capability, backward-compatible
  - PATCH — bug fix, no behavior change expected
- Version stored in `skills/<name>/VERSION` file
- Logged with every LLM call (FR-12)
- Skill changes committed via Git with changelog entry

---

## 8. Database Schema (v1)

### 8.1 Tables

**`raw_reports`** — immutable source of truth
```
maude_report_id   TEXT PRIMARY KEY
product_code      TEXT
date_received     TEXT
date_of_event     TEXT
raw_json          TEXT (full openFDA JSON)
fetched_at        TEXT (ISO datetime)
```

**`normalized_events`** — cleaned fields for querying
```
maude_report_id   TEXT PRIMARY KEY
product_code      TEXT
event_type        TEXT (death|injury|malfunction|other)
event_date        TEXT
narrative         TEXT
manufacturer      TEXT
brand_name        TEXT
```

**`extractions`** — structured LLM outputs
```
extraction_id     TEXT PRIMARY KEY (UUID)
maude_report_id   TEXT (FK)
extraction_ts     TEXT
skill_name        TEXT
skill_version     TEXT
output_json       TEXT (validated against schema)
confidence_score  REAL
model_used        TEXT
requires_review   INTEGER (0 or 1)
```

**`classifications`**
```
classification_id     TEXT PRIMARY KEY
maude_report_id       TEXT (FK)
labels                TEXT (JSON array)
rationale             TEXT
classifier_version    TEXT
reviewed_by_human     INTEGER
human_correction      TEXT (JSON or NULL)
```

**`drift_alerts`**
```
alert_id              TEXT PRIMARY KEY
detected_at           TEXT
drift_type            TEXT
affected_metric       TEXT
magnitude             REAL
severity              TEXT
suggested_action      TEXT
```

**`llm_audit_log`** — ALCOA+ trail
```
call_id               TEXT PRIMARY KEY
ts                    TEXT
skill_name            TEXT
skill_version         TEXT
model                 TEXT
input_hash            TEXT
output_hash           TEXT
input_tokens          INTEGER
output_tokens         INTEGER
cost_estimate_usd     REAL
```

---

## 9. Key Design Decisions (and Rationales)

| # | Decision | Rationale | Alternative considered |
|---|---|---|---|
| D1 | SQLite over Postgres | Single-user MVP; zero infra | Postgres (rejected: overkill) |
| D2 | Streamlit over React | Ship speed; no frontend distraction | React (rejected: 2–3 weeks cost) |
| D3 | Skills in Markdown over prompts in code | Auditability, versioning | Prompts inline (rejected: non-auditable) |
| D4 | Claude only (no GPT/Gemini) | Focus; one provider, one audit trail | Multi-model (rejected: complexity) |
| D5 | CLI-first over GUI-first | Reproducible; scriptable; demo-friendly | GUI-first (rejected: slower to iterate) |
| D6 | Verifier as mandatory gate | Non-negotiable for regulatory credibility | Best-effort verification (rejected) |
| D7 | Monolith over microservices | MVP scope; single developer | Microservices (rejected: absurd) |
| D8 | No cloud deployment | Lower risk, faster iteration, no costs | SaaS (rejected: not v1 scope) |
| D9 | No real-time ingestion | Daily batch is sufficient for postmarket use | Streaming (rejected: no need) |
| D10 | Explicit schemas + pydantic | Regulatory audit + type safety | Duck-typed dicts (rejected) |

---

## 10. Error Handling & Observability

### 10.1 Error Taxonomy

| Category | Example | System behavior |
|---|---|---|
| Transient (retry) | 429 rate limit, 500 upstream | Backoff + retry up to 3 |
| Permanent (fail loudly) | Invalid API key, malformed schema | Log + abort |
| Data quality (skip) | Missing narrative, corrupt JSON | Log + skip record |
| Citation failure | Unverified K-number | Flag `[UNVERIFIED]`, do not emit to user |

### 10.2 Logging

- All logs JSON-structured (`structlog` or native `logging` with JSON formatter)
- Log levels: `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL`
- Separate audit log (`llm_audit_log`) from operational log
- Never log API keys, full narratives, or PHI

---

## 11. Security Considerations

- `.env` in `.gitignore` (standard)
- API keys only from env vars — never hardcoded (NFR-07)
- No PHI processing (NFR-06)
- Output sanitization: no user-provided strings injected into dashboards without escaping
- Claude API calls only on de-identified MAUDE data

---

## 12. Performance Budget

| Operation | Target | Rationale |
|---|---|---|
| Ingest 1 product code, 12 months | ≤10 min | API-bound, cached |
| Extract 1 narrative | ≤2 sec | Sonnet latency |
| Classify 1 record | ≤1 sec | Opus reasoning |
| Dashboard load (10K records) | ≤5 sec | NFR-03 |
| Full pipeline end-to-end | ≤30 min per product code | NFR-01 |

---

## 13. Testing Strategy

- **Unit tests** — each module's pure functions
- **Integration tests** — module boundaries (ingestion → storage; extraction → storage)
- **Gold-set evaluation** — hand-labeled 100 records; run extraction; compute accuracy
- **Citation verification tests** — known-real K-numbers pass; known-fake ones fail
- **Regression tests** — when a bug is fixed, a test is added to prevent recurrence
- **CI runs on every PR:** tests + lint + typecheck

---

## 14. Architectural Anti-Patterns We Avoid

- ❌ God-objects — every module has a single responsibility
- ❌ Inline LLM prompts — all behavior in Skills
- ❌ Unstructured LLM outputs — every output validated against JSON schema
- ❌ Silent failure — all errors logged; citation failures bubble up
- ❌ Non-idempotent operations — re-running produces same state
- ❌ Shared mutable state across modules — only storage is shared, and read-only for most

---

## 15. Open Questions for Implementation

These are explicit unknowns to resolve in early weeks:

- Should extraction run in parallel (async) or serial? (Start serial; parallelize if NFR-02 requires.)
- How will you scrape the FDA guidance title index? (Manual dump in v1; automate if needed.)
- Do we want Markdown PSUR only, or Markdown + PDF? (Both per FR-30; defer PDF polish if time-constrained.)

---

## 16. Architecture Review Checkpoint

At end of Week 2 (before heavy build), review this document against what you've actually built. If divergent, either update the code or update the doc. **Never let them silently diverge.**

---

**End of Document 5.**
