# MaudeSignal

[![CI](https://github.com/kondapallysaicharan63-bot/safesignal/actions/workflows/ci.yml/badge.svg)](https://github.com/kondapallysaicharan63-bot/safesignal/actions/workflows/ci.yml)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

**Open-source AI postmarket surveillance toolkit for FDA-cleared AI/ML medical devices.**

> ⚠️ **MaudeSignal surfaces signals for human regulatory review. It is NOT an FDA-cleared device, NOT clinical decision support, and NOT a substitute for human regulatory judgment.**

---

## The problem

The FDA has cleared **1,000+ AI/ML-enabled medical devices** (295 in 2025 alone). They are monitored through MAUDE — a 1990s reporting system with **no fields for AI-specific failures**: drift, covariate shift, automation bias, subgroup performance loss. A deployed imaging AI whose sensitivity silently drops from 85% → 72% over 18 months generates **zero** adverse event reports.

**QMSR (effective February 2, 2026)** mandates real-world performance monitoring for every device manufacturer — yet the open-source tooling for the AI-specific case did not exist.

---

## What MaudeSignal does

1. **Ingests** MAUDE adverse event reports for any product code via openFDA
2. **Extracts** structured fields from unstructured narratives via versioned LLM Skills
3. **Triages severity** to FDA MDR categories with explicit decision rules
4. **Classifies** events into an 11-category AI failure taxonomy MAUDE cannot capture
5. **Verifies** every regulatory citation against primary sources — zero hallucinated K-numbers, CFR sections, or guidance titles
6. **Detects drift** with KS / PSI tests on labeled cohorts *(planned, Week 5)*
7. **Generates** PSUR-style periodic safety reports with full source traceability *(planned, Week 6–7)*

### What's different

|  | DeviceWatch | Legacy eQMS (MasterControl, Veeva) | **MaudeSignal** |
|---|---|---|---|
| Open-source | ❌ | ❌ | ✅ MIT |
| AI-specific failure taxonomy | ❌ | ❌ | ✅ 11 categories |
| Versioned, auditable LLM Skills | ❌ | ❌ | ✅ ALCOA+ aligned |
| Citation verification (zero-hallucination gate) | ? | ❌ | ✅ Hard gate |
| Multi-provider, free-tier capable | ❌ | ❌ | ✅ Groq + Gemini + paid options |
| Reproducible methodology | partial | ❌ | ✅ Gold-set evaluated |

---

## Status

🚧 **Pre-alpha — under active development.** Pilot results: **22 extractions, 50% AI-related signal rate, 0.90 average confidence, $0.00 LLM cost** (Groq free tier). Multi-key fallback pool exercised live with real free-tier 429 rotation. See [docs/00_pilot_findings.md](docs/00_pilot_findings.md) and [docs/00_pilot_findings_v2.md](docs/00_pilot_findings_v2.md).

---

## Tech stack

| Layer | Choice |
|---|---|
| Language | Python 3.11+, mypy --strict, ruff + black |
| LLM | **Provider-agnostic** — Groq (default, free), Anthropic, OpenAI, Gemini (free), or `pool` (multi-key fallback) |
| Validation | Pydantic 2 + JSON Schema |
| Storage | SQLite via SQLAlchemy 2 |
| Drift | Evidently + SciPy (KS, PSI) |
| Dashboard | Streamlit |
| CLI | Typer (`maudesignal` entry point) |
| Reports | Jinja2 → WeasyPrint (Markdown / HTML → PDF) |
| Tests | pytest + coverage (≥70% on core extraction) |

LLM behavior lives entirely in versioned `skills/<name>/SKILL.md` files — never inline strings. Every Skill ships with a JSON Schema, good + bad example pairs, and a changelog.

| Skill | Status |
|---|---|
| [`regulatory-citation-verifier`](skills/regulatory-citation-verifier/SKILL.md) | ✅ v1.0.0 |
| [`maude-narrative-extractor`](skills/maude-narrative-extractor/SKILL.md) | ✅ v1.0.0 |
| [`severity-triage`](skills/severity-triage/SKILL.md) | ✅ v1.0.0 |
| [`ai-failure-mode-classifier`](skills/ai-failure-mode-classifier/SKILL.md) | ✅ v1.0.0 |
| [`drift-analysis-interpreter`](skills/drift-analysis-interpreter/SKILL.md) | ✅ v1.0.0 (skeleton) |
| `fda-guidance-retriever` | 📋 planned |
| `psur-report-drafter` | 📋 planned |

---

## Quickstart (5 commands)

```bash
git clone https://github.com/kondapallysaicharan63-bot/safesignal.git && cd safesignal
python3.12 -m pip install -e ".[dev]"
cp .env.example .env  # add at least one provider key (Groq is free)
python3.12 -m maudesignal.cli ingest --product-code QIH --limit 5
python3.12 -m maudesignal.cli extract --product-code QIH --limit 3
```

**Multi-key fallback pool** (extends free-tier capacity by rotating across 5+ keys on 429):

```bash
LLM_PROVIDER=pool PROVIDER_FALLBACK_ORDER=gemini,gemini2,groq,groq2 \
  python3.12 -m maudesignal.cli extract --product-code QIH --limit 50
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
| Pilot findings | [docs/00_pilot_findings.md](docs/00_pilot_findings.md), [v2](docs/00_pilot_findings_v2.md) |
| Repo conventions for AI assistants | [CLAUDE.md](CLAUDE.md) |

---

## License

[MIT](LICENSE) — free for commercial and personal use. See license for warranty disclaimer, especially the regulatory-use notice.

---

## Author

**Sai Charan Kondapally** — M.S. Biomedical Engineering, San Jose State University
[GitHub](https://github.com/kondapallysaicharan63-bot) · open to regulatory affairs / post-market AI quality roles
