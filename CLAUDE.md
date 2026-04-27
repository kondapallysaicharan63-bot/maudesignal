# CLAUDE.md — Repo Conventions for AI Assistants

This file is read by Claude Code (and other AI coding assistants) at the
start of each session. It captures what is non-obvious from the code
alone: the project's purpose, non-goals, conventions, and the things that
have hurt previous sessions when missed.

If you are an AI assistant working in this repo: **read this file fully
before making changes.** If you are a human contributor, this is also a
fast way to ramp.

---

## 1. What SafeSignal Is

Open-source AI postmarket surveillance toolkit for FDA-cleared AI/ML
medical devices. Pipeline: ingest MAUDE adverse event reports from
openFDA → extract structured fields via an LLM Skill → classify into an
AI-failure taxonomy MAUDE does not natively capture → verify every
regulatory citation → render a Streamlit dashboard and a PSUR-style
report.

Built as an open-source portfolio project under an 8-week build window
(see [docs/07_roadmap.md](docs/07_roadmap.md)). Already through Day 1 +
Day 2 pilots: 22 extractions, 50% AI-related signal rate, 0.90 average
confidence, $0.00 LLM cost (Groq free tier). See
[docs/00_pilot_findings.md](docs/00_pilot_findings.md) and
[docs/00_master_plan.md](docs/00_master_plan.md).

---

## 2. Local Development Setup Notes

Laptop-specific quirks that future Claude Code sessions need to know
**before** running any Python command in this repo.

### 2.1 Two Python versions are installed — `python` is the wrong one

This laptop has both:

- **Python 3.6** at `C:\Python\Python36-64\` (legacy, do not use)
- **Python 3.12** (Microsoft Store install)

The bare `python` command resolves to **Python 3.6**, which is too old
for this project (`Python 3.11+` is required — see §4 Tech Stack).

**Always invoke Python 3.12 explicitly as `python3.12`.** Never use bare
`python` or `py` — they pick up the 3.6 install and imports / installs
will silently target the wrong interpreter.

### 2.2 Installing packages

Use `python3.12 -m pip install ...` for every install. Do not use bare
`pip` — it is bound to the 3.6 install.

```bash
python3.12 -m pip install -e .
python3.12 -m pip install <some-package>
```

### 2.3 The `safesignal` CLI is not on PATH

The Microsoft Store Python 3.12 installs console scripts to:

```
C:\Users\konda\AppData\Local\Packages\PythonSoftwareFoundation.Python.3.12_qbz5n2kfra8p0\LocalCache\local-packages\Python312\Scripts
```

This directory is **not** on `PATH` by default, so typing `safesignal`
in a fresh shell will fail with "command not found."

Two ways to invoke the CLI:

**(a) Prepend the Scripts dir to PATH for the current session (PowerShell):**

```powershell
$env:Path = "C:\Users\konda\AppData\Local\Packages\PythonSoftwareFoundation.Python.3.12_qbz5n2kfra8p0\LocalCache\local-packages\Python312\Scripts;" + $env:Path
safesignal --help
```

**(b) Call as a module (works from any shell, no PATH change needed):**

```bash
python3.12 -m safesignal --help
```

Option (b) is preferred for one-off / scripted invocations because it
needs no setup. Option (a) is preferred for an interactive session
where you'll run many `safesignal` commands in a row.

---

## 3. What SafeSignal Is NOT (Hard Boundaries)

These are not aesthetic preferences — they are constraints that shape
what is acceptable code.

- ❌ **Not clinical decision support.** Outputs are signals for human
  regulatory review. Never write code that frames the tool as advising
  clinical care.
- ❌ **Not an FDA-cleared device.** No 510(k), no De Novo, no PMA. The
  tool is meta — it analyzes adverse events for cleared devices.
- ❌ **Not a PHI-handling system.** MAUDE data is already de-identified
  and public. If you find code that looks like it touches PHI, stop and
  flag.
- ❌ **Not a SaaS.** No user accounts, auth, billing, multi-tenant. Pure
  open-source CLI + dashboard, runs on a laptop.
- ❌ **Not multi-regulator.** U.S. FDA / MAUDE only. No EU MDR, Health
  Canada, PMDA, China NMPA.
- ❌ **Not an eQMS.** Not competing with Greenlight Guru / MasterControl
  / Veeva. Sits alongside an existing quality system.
- ❌ **Not a chatbot.** Structured pipelines only. No conversational
  surfaces.

Full list: [docs/01_vision_mission.md §6](docs/01_vision_mission.md).

---

## 4. Tech Stack

| Layer | Choice | Notes |
|---|---|---|
| Language | Python 3.11+ | `mypy --strict` is enforced |
| LLM (primary) | Groq Llama-3.3-70B-Versatile | Free tier; default provider |
| LLM (alternates) | Anthropic Claude, OpenAI GPT, Google Gemini | Selected via `LLM_PROVIDER` env var |
| Validation | Pydantic 2 | Schema-first |
| Storage | SQLite via SQLAlchemy 2 | Zero-config, sufficient for MVP |
| Drift | Evidently + SciPy | KS, PSI |
| Dashboard | Streamlit | Minimal frontend overhead |
| CLI | Typer | `safesignal` entry point |
| Reports | Jinja2 → WeasyPrint | Markdown/HTML → PDF |
| Tests | pytest + coverage | ≥70% coverage target on core extraction |
| Lint | ruff + black | Configured in `pyproject.toml` |

The exact pin set lives in [pyproject.toml](pyproject.toml).

---

## 5. Repository Layout

```
safesignal/
├── docs/                       # Documentation-first source of truth
│   ├── 00_master_plan.md       # Single-page index of everything
│   ├── 00_pilot_findings.md    # Day 1 + Day 2 empirical results
│   ├── 01_vision_mission.md    # Why this exists
│   ├── 02_project_charter.md   # Scope, phases
│   ├── 03_requirements_spec.md # FRs / NFRs / data requirements
│   ├── 04_skills_matrix.md     # Builder learning plan
│   ├── 05_architecture.md      # System design + Skills architecture
│   ├── 06_risk_register.md
│   ├── 07_roadmap.md           # Week-by-week
│   └── 08_glossary.md
├── skills/                     # Versioned LLM behavior contracts
│   ├── regulatory-citation-verifier/   # ✅ v1.0.0
│   ├── maude-narrative-extractor/      # ✅ v1.0.0
│   ├── severity-triage/                # ✅ v1.0.0
│   └── ai-failure-mode-classifier/     # ✅ v1.0.0
│   #   each Skill has:
│   #     SKILL.md, VERSION,
│   #     schemas/output.schema.json,
│   #     examples/good.jsonl, examples/bad.jsonl
├── src/safesignal/             # Code lives here (src layout)
│   ├── cli.py                  # Typer entry point
│   ├── config.py               # Env / .env loading
│   ├── common/                 # Exceptions, shared types
│   ├── ingestion/              # F1 — openFDA fetcher
│   ├── extraction/
│   │   ├── extractor.py
│   │   └── llm_providers/
│   │       ├── base.py                 # LLMProvider ABC
│   │       ├── anthropic_provider.py
│   │       ├── openai_provider.py
│   │       ├── groq_provider.py
│   │       ├── gemini_provider.py      # ✅ added with Gemini support
│   │       └── __init__.py             # get_provider(config) factory
│   ├── classification/         # F3 (planned)
│   ├── drift/                  # F4 (planned)
│   ├── verification/           # F5 — citation verifier
│   ├── dashboard/              # F6 (planned, Streamlit)
│   └── reports/                # F7 (planned, PSUR)
├── tests/                      # pytest, gold sets, fixtures
├── pyproject.toml              # Project + tool config
├── README.md                   # Public-facing
└── CLAUDE.md                   # This file
```

---

## 6. Conventions That Are Not Optional

### 6.1 LLM behavior lives in Skills, not inline strings

Every prompt or LLM behavior contract goes in `skills/<skill-name>/SKILL.md`
with a corresponding `VERSION`, JSON Schema, and good/bad example pairs.
Do not write inline prompt strings in Python code; load them via the
Skill files. This is non-negotiable for ALCOA+ auditability and for the
gold-set evaluation loop.

When changing a Skill: bump `VERSION`, update the changelog at the bottom
of `SKILL.md`, and ensure the schema and examples still match.

### 6.2 The citation verifier is a HARD GATE

`regulatory-citation-verifier` runs on every string field of every output
before that output is emitted to a user-facing surface. If you see code
emitting a string field without passing it through the verifier, that is
a bug — fix it.

The verifier MUST NOT use LLM training-data knowledge as a verification
source. Only openFDA, the curated CFR Parts list, and the local FDA
guidance index file count as primary sources.

### 6.3 The pipeline is provider-agnostic

Never import `anthropic`, `openai`, `groq`, or `google.generativeai`
directly in extraction / classification code. Go through
`safesignal.extraction.llm_providers.get_provider(config)` which returns
an `LLMProvider`. Each concrete provider only handles vendor SDK
translation; retries, audit logging, and JSON validation live above the
provider layer.

### 6.4 Type discipline

`pyproject.toml` enforces `mypy --strict`. Every public function has
typed params and return; no implicit `Any`. Optional is explicit. Run
`mypy src/safesignal` before committing.

### 6.5 Style

`ruff` + `black` are authoritative. Line length 100. Docstrings are
Google-style (`pyproject.toml [tool.ruff.lint.pydocstyle]`). Run
`ruff check . && black --check .` before committing.

### 6.6 Determinism for reproducibility

Default LLM `temperature=0.0`. Never set a non-zero temperature in
extraction or classification code without an explicit comment justifying
it. The whole point of the gold-set evaluation loop is reproducibility.

### 6.7 No PHI, ever

MAUDE is already de-identified. If you find what looks like a name, MRN,
or date of birth in the data, log a CRITICAL and skip the record.
SafeSignal does not handle PHI under any circumstances.

---

## 7. The Skills (Build Order Matters)

| Skill | Status | Why this order |
|---|---|---|
| `regulatory-citation-verifier` | ✅ v1.0.0 | Everything depends on it; built first |
| `maude-narrative-extractor` | ✅ v1.0.0 | Foundation extraction; produces the records every other Skill consumes |
| `severity-triage` | ✅ v1.0.0 | Standardizes severity for downstream cohort analysis |
| `ai-failure-mode-classifier` | ✅ v1.0.0 | Assigns the AI taxonomy MAUDE cannot |
| `drift-analysis-interpreter` | 📋 planned | Translates KS/PSI stats into regulator language |
| `fda-guidance-retriever` | 📋 planned | Grounded retrieval over FDA guidance corpus |
| `psur-report-drafter` | 📋 planned | Final composer; consumes everything |

If you need to add a new Skill, follow the structure of the four built
Skills and update the table above.

---

## 8. Configuration

Config is loaded from environment / `.env` via `safesignal.config.Config`.

Required keys (depending on `LLM_PROVIDER`):

| Provider | Required env var |
|---|---|
| `groq` (default) | `GROQ_API_KEY` |
| `anthropic` | `ANTHROPIC_API_KEY` |
| `openai` | `OPENAI_API_KEY` |
| `gemini` | `GEMINI_API_KEY` |

Other useful env vars: `LLM_PROVIDER`, `GROQ_MODEL`, `OPENAI_MODEL`,
`CLAUDE_MODEL_EXTRACTION`. See `safesignal/config.py` for the
authoritative list.

---

## 9. What NOT to Do

- ❌ Do not write inline prompt strings in Python. Use a Skill.
- ❌ Do not bypass `regulatory-citation-verifier` for any user-facing
  string field.
- ❌ Do not import LLM vendor SDKs directly in extraction or
  classification code. Use `get_provider(config)`.
- ❌ Do not set non-zero LLM `temperature` without an explicit
  justifying comment.
- ❌ Do not add PHI handling, multi-tenant, auth, or SaaS scaffolding.
- ❌ Do not add a new regulator (EU MDR, Health Canada, etc.) without
  going through scope review in the Charter.
- ❌ Do not add features beyond F1–F7. The 8-week scope is fixed.
- ❌ Do not return `confidence_score = 1.0` from any Skill. Cap at 0.95.
- ❌ Do not use LLM training-data knowledge as a citation verification
  source.
- ❌ Do not auto-amend git commits to "fix" pre-commit hook failures —
  fix the underlying issue and create a new commit.
- ❌ Do not add a CHANGELOG.md, CONTRIBUTING.md, or other meta-doc unless
  asked. Keep the doc surface tight.

---

## 10. Common Tasks

### Run the test suite
```bash
pytest tests/ -v
```

### Type-check
```bash
mypy src/safesignal
```

### Lint
```bash
ruff check . && black --check .
```

### Ingest + extract a small batch (free, no cost)
```bash
safesignal ingest --product-code QIH --limit 5
safesignal extract --product-code QIH --limit 3
safesignal status
```

### Switch LLM provider
```bash
LLM_PROVIDER=gemini GEMINI_API_KEY=xxxx safesignal extract --limit 3
```

---

## 11. Where to Look First

| Question | File |
|---|---|
| What does the project do at a high level? | [README.md](README.md) |
| What are the goals and non-goals? | [docs/01_vision_mission.md](docs/01_vision_mission.md) |
| What is the index for everything? | [docs/00_master_plan.md](docs/00_master_plan.md) |
| What does each requirement mean? | [docs/03_requirements_spec.md](docs/03_requirements_spec.md) |
| How is the system designed? | [docs/05_architecture.md](docs/05_architecture.md) |
| What does an LLM Skill look like? | [skills/maude-narrative-extractor/SKILL.md](skills/maude-narrative-extractor/SKILL.md) |
| How do I add a provider? | [src/safesignal/extraction/llm_providers/base.py](src/safesignal/extraction/llm_providers/base.py) + the existing four providers |
| What did the pilot find? | [docs/00_pilot_findings.md](docs/00_pilot_findings.md) |

---

**Bottom line:** SafeSignal is a regulatory-rigorous, narrowly-scoped,
documentation-first project. Stay inside the boundaries above and the
work compounds. Step outside them and you create rework that the
8-week budget cannot absorb.
