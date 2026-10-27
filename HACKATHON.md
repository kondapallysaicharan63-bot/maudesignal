# Hackathon Build Manifest — Meta Global AI Developer Hackathon

**Event:** Meta Global AI Developer Hackathon (Oct 26 – Nov 4, 2026)
**Track:** Indie Developer, solo
**Problem statement:** Build for Your World

## What was built DURING the hackathon (new work — this is the submission)

Everything under `src/maudesignal/copilot/` was created during the event:

| File | What it is |
|---|---|
| `copilot/meta_provider.py` | Meta Model API provider (OpenAI-compatible client, streaming) implementing the existing `LLMProvider` interface |
| `copilot/copilot.py` | Conversational safety copilot: plain-English questions → streamed, grounded answers |
| `copilot/__init__.py` | Package exports |

Plus this manifest, the demo video, and the submission write-up.

## What is PRE-EXISTING (the base — NOT presented as hackathon work)

The `maudesignal` pipeline itself predates the hackathon (public repo, MIT):
openFDA MAUDE ingestion, LLM extraction via versioned Skills, severity
triage, 11-category AI failure-mode classifier, root-cause analysis,
alerting, Mann-Kendall trend + KS/PSI drift detection, PubMed/
ClinicalTrials sourcing, PSUR draft generation, and the Streamlit dashboard.

The copilot reads from that pipeline. It does not claim it.

## Framing (read this before judging)

- This is a **B2B regulatory tool for quality/regulatory professionals**.
  It analyzes device safety signals. It does **not** give medical advice,
  diagnoses, or treatment recommendations to patients, and it refuses
  such requests.
- No factual claim in a copilot answer is generated without grounding in a
  pipeline record or a verified primary source (citation hard-gate).
- Meta models used: Muse Spark series via the Meta Model API (Standard
  tier — never Contributor, which trains on your data). Chat model:
  `muse-spark-1.3` (latest, docs-recommended), base URL
  `https://api.meta.ai/v1`, streaming via `stream=True`.

## Planning docs (in this repo)

Full workflow, delivery plan, dev workflow, checklist, and skills
worksheet live under `docs/hackathon/` (mirrored from the workspace
planning docs). They describe the plan; this manifest describes what
was actually built. Workspace copies are canonical — repo copies are
re-pushed after planning changes.
