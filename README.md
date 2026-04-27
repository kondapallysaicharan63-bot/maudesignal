# MaudeSignal

[![Open in GitHub Codespaces](https://github.com/codespaces/badge.svg)](https://codespaces.new/[your-username]/maudesignal)
[![CI](https://github.com/[your-username]/maudesignal/actions/workflows/ci.yml/badge.svg)](https://github.com/[your-username]/maudesignal/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)

**Open-source AI postmarket surveillance toolkit for FDA-cleared AI/ML medical devices.**

MaudeSignal ingests FDA MAUDE adverse event data, uses Claude with versioned Skills to extract AI-specific failure signals that MAUDE's native schema does not capture, and produces regulator-style safety reports with verified citations.

> ⚠️ **MaudeSignal is a research and signal-surfacing tool. It is NOT an FDA-cleared medical device, NOT a substitute for human regulatory judgment, and NOT legal or regulatory advice. Every finding requires human review before any regulatory action.**

---

## Why this exists

The FDA has cleared over 1,000 AI/ML-enabled medical devices. These devices are monitored through the FDA's MAUDE database — a reporting system built in the 1990s for mechanical device failures. **MAUDE has no fields** for AI-specific failures: concept drift, covariate shift, subgroup performance degradation, or automation bias. A deployed imaging AI whose sensitivity quietly drops from 85% to 72% over 18 months generates **zero** adverse event reports.

QMSR (effective Feb 2, 2026) mandates real-world performance monitoring for every medical device manufacturer — yet the open-source tooling to do this properly does not exist.

MaudeSignal is that tooling.

---

## What it does

1. **Ingests** MAUDE adverse event reports for configurable product codes via the openFDA API.
2. **Extracts** structured fields from unstructured MAUDE narratives using Claude + versioned Skills.
3. **Classifies** events into an AI-specific failure taxonomy MAUDE does not capture.
4. **Simulates & detects** model drift using statistical tests (KS, PSI).
5. **Verifies** every regulatory citation in every output against primary sources — zero hallucinations.
6. **Visualizes** signals in a local Streamlit dashboard.
7. **Generates** PSUR-style periodic safety reports with full source traceability.

---

## Status

🚧 **Pre-alpha — under active development.** MVP target: 8 weeks.

See [`docs/07_roadmap.md`](docs/07_roadmap.md) for the week-by-week build plan.

---

## Project documentation

MaudeSignal follows a documentation-first methodology. Before any code, we wrote 8 interlinked documents that define the vision, scope, requirements, architecture, risks, and roadmap:

| # | Document | What it defines |
|---|---|---|
| 1 | [Vision & Mission](docs/01_vision_mission.md) | Why this project exists |
| 2 | [Project Charter](docs/02_project_charter.md) | Scope, phases, commitments |
| 3 | [Requirements Spec](docs/03_requirements_spec.md) | 33 FRs, 17 NFRs, data requirements |
| 4 | [Skills Matrix](docs/04_skills_matrix.md) | Builder's learning plan |
| 5 | [Architecture](docs/05_architecture.md) | System design, Claude Skills |
| 6 | [Risk Register](docs/06_risk_register.md) | 34 risks, mitigations |
| 7 | [Roadmap](docs/07_roadmap.md) | Week-by-week execution |
| 8 | [Glossary](docs/08_glossary.md) | Regulatory + technical terms |

---

## Claude Skills

All LLM behavior in MaudeSignal is defined in versioned `SKILL.md` files, not inline prompts. This enforces reproducibility, auditability (ALCOA+), and clean separation of behavior from orchestration.

| Skill | Purpose | Status |
|---|---|---|
| [`regulatory-citation-verifier`](skills/regulatory-citation-verifier/SKILL.md) | Verifies every regulatory citation against primary sources | ✅ v1.0.0 |
| [`maude-narrative-extractor`](skills/maude-narrative-extractor/SKILL.md) | Extracts structured fields from MAUDE narratives | ✅ v1.0.0 |
| `severity-triage` | Standardizes severity to FDA MDR categories | 🚧 planned |
| `ai-failure-mode-classifier` | Assigns AI-specific failure taxonomy labels | 🚧 planned |
| `drift-analysis-interpreter` | Translates drift stats to regulatory language | 🚧 planned |
| `fda-guidance-retriever` | Grounded retrieval over FDA guidance corpus | 🚧 planned |
| `psur-report-drafter` | Composes PSUR-style periodic safety reports | 🚧 planned |

Build order (per [`docs/05_architecture.md`](docs/05_architecture.md) §7.4): citation verifier first (everything depends on it), PSUR drafter last (consumes everything).

---

## Quickstart (Codespaces — no local setup needed)

Click the **Open in GitHub Codespaces** badge above. You'll get a full development environment in your browser in about 2 minutes.

Once the Codespace loads:

1. **Add your Claude API key.** Click `.env` in the file explorer, replace the placeholder on the `ANTHROPIC_API_KEY` line. (Get a key from [console.anthropic.com](https://console.anthropic.com).)

2. **Verify the install** — run in the terminal:
   ```bash
   pytest tests/unit -v
   ```
   All tests should pass. No API cost.

3. **Ingest real MAUDE data** (free):
   ```bash
   maudesignal ingest --product-code QIH --limit 5
   ```

4. **Run Claude extraction** (~$0.05):
   ```bash
   maudesignal extract --product-code QIH --limit 3
   ```

5. **Check what happened:**
   ```bash
   maudesignal status
   ```

## Quickstart (local laptop)

```bash
git clone https://github.com/[username]/maudesignal.git
cd maudesignal

python -m venv .venv
source .venv/bin/activate      # or .venv\Scripts\activate on Windows
pip install -e ".[dev]"

cp .env.example .env
# Edit .env and add your ANTHROPIC_API_KEY

pytest tests/unit -v
maudesignal ingest --product-code QIH --limit 5
maudesignal extract --product-code QIH --limit 3
maudesignal status
```

---

## Tech stack

| Layer | Tool | Why |
|---|---|---|
| Language | Python 3.11+ | Strong typing, dominant in data/ML |
| LLM | **Provider-agnostic** (Groq / Anthropic / OpenAI) | Switch via `LLM_PROVIDER` env var |
| Default | Groq — Llama 3.3 70B Versatile | Free tier, strong structured-output |
| Alternates | Claude Sonnet / GPT-4o | Same pipeline, paid providers |
| Database | SQLite | Zero-config, portable, sufficient for MVP |
| Validation | Pydantic 2 | Schema-first, type-safe |
| Dashboard | Streamlit | Minimal frontend overhead |
| Drift | Evidently + SciPy | Industry-standard statistical drift tools |
| CLI | Typer | Modern, typed CLI from Python functions |
| Testing | pytest + coverage | Standard |
| Type checking | mypy (strict mode) | Bug prevention |
| Linting | ruff + black | Fast, opinionated |
| CI | GitHub Actions | Free for public repos |

---

## Contributing

MaudeSignal is built in the open as a portfolio project, but community contributions are welcome. See [`CONTRIBUTING.md`](CONTRIBUTING.md) (coming soon) for guidance.

**For feedback from regulatory affairs or post-market quality professionals:** this project is actively seeking your input. Please open an issue with the label `feedback-ra` or reach out via LinkedIn.

---

## License

[MIT](LICENSE) — free for commercial and personal use. See license for warranty disclaimer, especially the regulatory-use notice.

---

## Acknowledgments

- **FDA's openFDA team** for maintaining public APIs that make this work possible
- **Babic et al.** (*npj Digital Medicine*, 2025) for the foundational research on MAUDE's AI blind spots
- **Anthropic** for Claude and the Skills framework pattern

---

## Author

[Your Name] — M.S. Biomedical Engineering, San Jose State University
Contact: [your-email] | [LinkedIn URL]

---

*Built with an engineering approach to regulatory science — because patient safety deserves both.*
