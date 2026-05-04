# MaudeSignal

[![CI](https://github.com/kondapallysaicharan63-bot/maudesignal/actions/workflows/ci.yml/badge.svg)](https://github.com/kondapallysaicharan63-bot/maudesignal/actions/workflows/ci.yml)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Tests](https://img.shields.io/badge/tests-189%20passing-brightgreen.svg)]()
[![Coverage](https://img.shields.io/badge/coverage-58%25-yellow.svg)]()

**Open-source AI postmarket surveillance toolkit for FDA-cleared AI/ML medical devices.**

> ⚠️ **MaudeSignal surfaces signals for human regulatory review. It is NOT an FDA-cleared device, NOT clinical decision support, and NOT a substitute for human regulatory judgment.**

---

## The problem

The FDA has cleared **1,000+ AI/ML-enabled medical devices** (295 in 2025 alone). They are monitored through MAUDE — a 1990s reporting system with **no fields for AI-specific failures**: drift, covariate shift, automation bias, subgroup performance loss. A deployed imaging AI whose sensitivity silently drops from 85% → 72% over 18 months generates **zero** adverse event reports.

**QMSR (effective February 2, 2026)** mandates real-world performance monitoring for every device manufacturer — yet the open-source tooling for the AI-specific case did not exist.

---

## What MaudeSignal does

```
openFDA MAUDE API
       │
       ▼
┌──────────────────┐    ┌───────────────────┐    ┌──────────────────────┐
│  1. Ingest       │───▶│  2. Extract        │───▶│  3. Triage severity  │
│  openFDA fetcher │    │  maude-narrative-  │    │  severity-triage     │
│  + FDA catalog   │    │  extractor Skill   │    │  Skill               │
└──────────────────┘    └───────────────────┘    └──────────────────────┘
                                                           │
                        ┌───────────────────┐             ▼
                        │  5. Root cause    │    ┌──────────────────────┐
                        │  root-cause-      │◀───│  4. Classify         │
                        │  analyzer Skill   │    │  ai-failure-mode-    │
                        └───────────────────┘    │  classifier Skill    │
                                │                └──────────────────────┘
                                ▼
┌──────────────────┐    ┌───────────────────┐    ┌──────────────────────┐
│  8. PSUR Report  │◀───│  7. Trend detect  │◀───│  6. Alerting         │
│  psur-report-    │    │  Mann-Kendall +   │    │  4 metrics, 3 chan-  │
│  drafter Skill   │    │  linear regression│    │  nels (console/      │
│  → PDF export    │    └───────────────────┘    │  Slack/email)        │
└──────────────────┘                             └──────────────────────┘
         │
         ▼
  External sources
  PubMed + ClinicalTrials.gov
```

| Step | What it produces |
|---|---|
| **Ingest** | Raw MAUDE reports + FDA AI/ML Device Catalog in SQLite |
| **Extract** | Structured fields: AI flag, device type, failure description, citations |
| **Severity triage** | Death / serious injury / malfunction / other — with justification |
| **Classify** | 11-category AI failure taxonomy (drift, automation bias, data quality…) |
| **Root cause** | Hypothesis + confidence for each failure-mode cluster |
| **Alert** | Threshold-based alerts on new reports, AI rate, severity rate, new failure modes |
| **Trend detect** | Mann-Kendall + linear regression; `trend-interpreter` Skill translates stats to regulatory language |
| **External sources** | PubMed citations + ClinicalTrials.gov trials fetched and stored |
| **PSUR draft** | 8-section periodic safety update report — Markdown + PDF, signal assessment, recommended actions |

### Citation hard-gate

Every string field in every Skill output is verified against **primary sources only** (openFDA, curated CFR Parts list, FDA guidance index) before reaching any user-facing surface. Hallucinated K-numbers, CFR citations, or guidance titles are **blocked** — not flagged, not warned — blocked.

---

## Status

**Alpha — all 5 pipeline phases complete.** Pilot v3 results (2026-05-02):

| Metric | Result |
|---|---|
| Extractions | 43 across 8 product codes |
| AI-related signal rate | 32.6% overall (100% for QIH radiology CAD) |
| Average confidence | 0.890 |
| LLM cost | **$0.00** (Gemini + Groq free tier) |
| Test suite | **189 passing**, 58% coverage |

---

## Tech stack

| Layer | Choice |
|---|---|
| Language | Python 3.11+, `mypy --strict`, `ruff` + `black` |
| LLM | Provider-agnostic — Groq (default, free), Anthropic, OpenAI, Gemini (free), or `pool` (multi-key rotation on 429) |
| Validation | Pydantic 2 + JSON Schema |
| Storage | SQLite via SQLAlchemy 2 |
| Drift | Evidently + SciPy (KS, PSI) |
| Statistics | Mann-Kendall trend test + linear regression (SciPy) |
| External APIs | NCBI E-utilities (PubMed), ClinicalTrials.gov v2 REST |
| Dashboard | Streamlit |
| CLI | Typer (`maudesignal` entry point) |
| Reports | Jinja2 → WeasyPrint (HTML → PDF) |
| CI | GitHub Actions (Python 3.11 + 3.12, ruff, black, mypy, pytest) |

### Skills (versioned LLM behavior contracts)

LLM behavior lives entirely in `skills/<name>/SKILL.md` — never inline strings. Each Skill ships with a JSON Schema, good + bad example pairs, and a version changelog.

| Skill | Version | Purpose |
|---|---|---|
| [`regulatory-citation-verifier`](skills/regulatory-citation-verifier/SKILL.md) | v1.0.0 | Hard gate — blocks hallucinated citations |
| [`maude-narrative-extractor`](skills/maude-narrative-extractor/SKILL.md) | v1.0.0 | Structured field extraction from MAUDE narratives |
| [`severity-triage`](skills/severity-triage/SKILL.md) | v1.0.0 | Death / serious injury / malfunction / other |
| [`ai-failure-mode-classifier`](skills/ai-failure-mode-classifier/SKILL.md) | v1.0.0 | 11-category AI failure taxonomy |
| [`root-cause-analyzer`](skills/root-cause-analyzer/SKILL.md) | v1.0.0 | Root cause hypothesis per failure-mode cluster |
| [`drift-analysis-interpreter`](skills/drift-analysis-interpreter/SKILL.md) | v1.0.0 | KS/PSI statistics → regulatory language |
| [`trend-interpreter`](skills/trend-interpreter/SKILL.md) | v1.0.0 | Trend stats → regulatory narrative + signal level |
| [`psur-report-drafter`](skills/psur-report-drafter/SKILL.md) | v1.0.0 | 8-section PSUR draft with signal assessment |

---

## Quickstart

### Requirements

- Python 3.11 or 3.12
- At least one LLM API key (Groq and Gemini both have free tiers)
- Optional: system GTK/Cairo libraries for PDF export via WeasyPrint

### Install

```bash
git clone https://github.com/kondapallysaicharan63-bot/maudesignal.git
cd maudesignal
python3.12 -m pip install -e ".[dev]"
cp .env.example .env          # add your API key(s)
```

### `.env` minimum

```env
LLM_PROVIDER=groq
GROQ_API_KEY=gsk_your_key_here
```

For the multi-key pool (extends free-tier capacity):

```env
LLM_PROVIDER=pool
PROVIDER_FALLBACK_ORDER=gemini,gemini2,groq,groq2
GEMINI_API_KEY=...
GEMINI_API_KEY_2=...
GROQ_API_KEY=...
GROQ_API_KEY_2=...
```

### Run the full pipeline

```bash
# 1. Ingest MAUDE reports and FDA AI/ML catalog
python3.12 -m maudesignal.cli ingest --product-code QIH --limit 20
python3.12 -m maudesignal.cli catalog fetch

# 2. Extract + classify + triage
python3.12 -m maudesignal.cli extract --product-code QIH --limit 10
python3.12 -m maudesignal.cli classify --product-code QIH
python3.12 -m maudesignal.cli triage --product-code QIH

# 3. Root cause analysis + alerting
python3.12 -m maudesignal.cli root-cause --product-code QIH
python3.12 -m maudesignal.cli alert check --product-code QIH

# 4. Trend detection + external sources
python3.12 -m maudesignal.cli forecast trends --product-code QIH
python3.12 -m maudesignal.cli sources fetch --query "AI radiology device failure" --product-code QIH

# 5. Generate PSUR draft + PDF
python3.12 -m maudesignal.cli psur generate QIH --device-name "AI Radiology CAD" --output reports/QIH_psur.pdf

# Check pipeline status
python3.12 -m maudesignal.cli status
```

---

## Dashboard

```bash
python3.12 -m streamlit run src/maudesignal/dashboard/app.py
```

Seven views:
- **Records** — filterable extraction table with FDA report detail panel
- **Severity** — severity distribution and breakdown
- **Failure Modes** — AI failure taxonomy across events
- **Drift** — confidence-score trend over time (KS / PSI)
- **Trends** — Mann-Kendall signal detection, regulatory narratives
- **Sources** — PubMed citations + ClinicalTrials.gov trials
- **PSUR Reports** — browse and view stored PSUR drafts

---

## CLI reference

```
maudesignal ingest          Fetch MAUDE reports from openFDA
maudesignal catalog fetch   Fetch FDA AI/ML Device Catalog
maudesignal extract         Run maude-narrative-extractor Skill
maudesignal classify        Run ai-failure-mode-classifier Skill
maudesignal triage          Run severity-triage Skill
maudesignal root-cause      Run root-cause-analyzer Skill
maudesignal alert add       Add an alert rule
maudesignal alert check     Evaluate alert rules and notify
maudesignal alert list      List configured alert rules
maudesignal forecast trends Run Mann-Kendall trend detection
maudesignal sources fetch   Fetch PubMed + ClinicalTrials sources
maudesignal sources list    List stored external sources
maudesignal psur generate   Generate PSUR draft (+ optional PDF)
maudesignal psur list       List stored PSUR drafts
maudesignal report          Generate legacy PSUR-style report (Markdown/PDF)
maudesignal drift           Run drift detection (KS + PSI)
maudesignal status          Show pipeline status summary
```

---

## Development

```bash
# Run tests
python3.12 -m pytest tests/ -v

# Type check
python3.12 -m mypy src/maudesignal

# Lint + format
python3.12 -m ruff check . && python3.12 -m black --check .
```

---

## Documentation

| | |
|---|---|
| Index of everything | [docs/00_master_plan.md](docs/00_master_plan.md) |
| Vision & non-goals | [docs/01_vision_mission.md](docs/01_vision_mission.md) |
| Requirements (FRs / NFRs) | [docs/03_requirements_spec.md](docs/03_requirements_spec.md) |
| System design | [docs/05_architecture.md](docs/05_architecture.md) |
| Roadmap | [docs/07_roadmap.md](docs/07_roadmap.md) |
| Pilot findings | [v1](docs/00_pilot_findings.md) · [v2](docs/00_pilot_findings_v2.md) · [v3](docs/00_pilot_findings_v3.md) |
| Repo conventions for AI assistants | [CLAUDE.md](CLAUDE.md) |

---

## License

[MIT](LICENSE) — free for commercial and personal use. See license for warranty disclaimer, especially the regulatory-use notice.

---

## Author

**Sai Charan Kondapally** — M.S. Biomedical Engineering, San Jose State University  
[GitHub](https://github.com/kondapallysaicharan63-bot) · open to regulatory affairs / post-market AI quality roles
