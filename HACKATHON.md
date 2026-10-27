# Hackathon Build Manifest — Meta Global AI Developer Hackathon

**Event:** Meta Global AI Developer Hackathon (Oct 26 – Nov 4, 2026)
**Track:** Indie Developer, solo
**Problem statement:** Build for Your World

## What was built DURING the hackathon (new work — this is the submission)

Everything under `src/maudesignal/copilot/`, `src/maudesignal/gate/` and
`src/maudesignal/monitor/` was created during the event:

| File | What it is |
|---|---|
| `copilot/meta_provider.py` | Meta Model API provider (OpenAI-compatible client, streaming) implementing the existing `LLMProvider` interface |
| `copilot/copilot.py` | Conversational safety copilot: plain-English questions → streamed, grounded answers |
| `copilot/__init__.py` | Package exports |
| `copilot/agent.py` | Muse Spark tool-use loop → structured answer (sentences + claims) → claim-level gate → one repair turn with the gate's recomputed values → unrepaired sentences withheld; every answer written to the audit trail |
| `copilot/tools.py` | 6 deterministic tools the model calls: overnight signals, product summary, report search, report fetch, MDR deadline clock (21 CFR 803.50 / 803.53, advisory), CAPA draft |
| `copilot/actions.py` | CAPA drafts: audit-first, forward-only (`draft → approved / rejected`), only a named human can decide |
| `copilot/transcript.py` | Records real Muse Spark runs so the keyless public demo replays them honestly |
| `skills/safety-copilot/` | Versioned behavior contract (prompt, output schema, examples) for the copilot |
| `gate/` (`gate.py`, `claims.py`, `evidence.py`, `cfr.py`, `loader.py`) | **Claim-level citation gate.** Recomputes counts/shares from stored records, verbatim-matches quotes to the cited report (a real quote pinned to the wrong report is blocked), checks 510(k) numbers against the catalog, allowlists 21 CFR sections (blocks QS-reg sections superseded by QMSR on 2026-02-02), and blocks numbers / ids / CFR cites that carry no structured claim. Deterministic, no model calls. The `regulatory-citation-verifier` Skill spec pre-existed with zero call sites; this is its enforcement. |
| `tests/fixtures/gate/adversarial.jsonl` + `tests/unit/test_gate.py` | 54 adversarial cases (fabricated / drifted quotes, wrong-record quotes, stale and inflated numbers, fake and mismatched K-numbers, hallucinated and superseded CFR, untagged mentions): 0 false pass, 0 false block |
| `dashboard/copilot_pages.py` | New dashboard pages: **Overnight** digest, **Copilot** (recorded runs + live "try to fool the gate" playground + live mode when a key is present), **Actions & Audit** (approve/reject CAPA drafts, hash-chain verification) |
| `storage`: `CapaDraftRecord`, `ActionAuditRecord` + DB methods | CAPA draft table and append-only, SHA-256 hash-chained audit trail with tamper detection |
| `scripts/record_demo_transcripts.py`, `.github/workflows/copilot-record.yml`, `demo/` | Records the demo questions through the real Muse Spark copilot in GitHub Actions (key from repository secrets, never in code) |
| `.github/workflows/meta-smoke.yml`, `test_meta_connection.py` | Meta Model API smoke test (`models.list` + streaming) run with repository secrets |
| `tests/unit/test_copilot_agent.py` | Agent loop, repair turn, withheld sentences, CAPA approval rules, audit tamper detection, tools, transcripts (scripted fake client — no credits) |
| `monitor/deterioration.py` | Deterministic per-product-code detector: last 7 days vs trailing 4-week baseline → `new_signal` / `spike` / `severity_escalation` / `stable`, returning every count, share and report id used |
| `monitor/digest.py` | Overnight digest ("N new, M worsening") rendered to Markdown + JSON with a fixed advisory footer; no LLM |
| `monitor/fetch.py` | Capped, whole-day incremental openFDA fetch (reuses the existing ingestion pipeline) |
| `monitor/__init__.py` | Package exports |
| `cli.py` → `maudesignal monitor` | New CLI command: optional capped fetch → detect → `digests/YYYY-MM-DD.{md,json}` |
| `scripts/seed_demo_data.py` | Keyless seeding of the demo DB from live openFDA via the existing ingestion + catalog code |
| `data/demo/maudesignal_demo.db`, `data/demo/SEED_MANIFEST.json` | 137 real MAUDE reports (LLZ Jul–Aug 2026 complete window; all QIH, MYN, POK reports) + manifest of the exact queries |
| `digests/2026-08-24.*`, `digests/2026-08-31.*` | Two digests generated from the seeded data |
| `.github/workflows/monitor.yml` | Daily cron + manual dispatch running the monitor; commits the digest back (`chore(monitor):`) |
| `tests/unit/test_monitor.py` | Tests for detector, digest, fetch and CLI |
| `streamlit_app.py`, `requirements.txt` | Streamlit Community Cloud entry point and dependency file for the keyless public demo (installs this repo; dependencies stay in `pyproject.toml`) |
| `tests/unit/test_dashboard_default_db.py` | Tests that the dashboard falls back to the demo DB only when nothing else is configured |
| `docs/architecture.mmd`, `docs/architecture.svg` | Architecture diagram (Mermaid source + rendered SVG) of the hackathon flow |

Small changes to pre-existing modules made during the event (to support the
monitor, or bugs it exposed): `Database.list_event_facts` / `max_date_received`
/ `list_product_codes`; `OpenFDAClient.count_by_date_received`;
`config.openfda_api_key_from_env`; fix — openFDA date-range queries were sent
with `+` encoded as `%2B` (HTTP 500); fix — live openFDA `event_type` is a
string, so ingestion had been storing single letters (`"m"`, `"i"`); fix —
structlog captured `sys.stderr` once, so logging crashed after the stream was
closed (the 4 failing CI tests); `Database.date_received_lookup`; dashboard
package import made lazy so submodules don't re-run the app;
`dashboard/app.py` `_load_db` now opens `data/demo/maudesignal_demo.db` when
`MAUDESIGNAL_DB_PATH` is unset and `data/maudesignal.db` does not exist
(stored-first public deploy); `.streamlit/config.toml` gained `headless = true`;
`README.md` rewritten for the hackathon (pre-existing pipeline section kept,
trimmed, with stale CLI commands and test counts corrected); `CLAUDE.md` gained a
"Hackathon extension (Oct 2026)" note and the `safety-copilot` Skill row;
pre-hackathon root-level debug scripts and logs removed (public-repo hygiene),
with their ruff excludes in `pyproject.toml` replaced by per-file ignores for the
remaining smoke-test and screenshot scripts.

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

## Planning docs

The day-by-day planning docs are kept outside the public repo. This manifest
describes what was actually built.
