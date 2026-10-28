# Hackathon PRD: feature status

Meta Global AI Developer Hackathon, Oct 26 – Nov 4, 2026. The pre-existing
product PRD (`docs/PRD-*.md`) describes the original maudesignal product and
is not hackathon work. This page lists what the hackathon build covers, with
the evidence for each status. Fixed dates: **video Nov 1**, **submission
Nov 4, 9 PM ET**. Work is pulled forward whenever it is ready; it does not wait
for its planned day.

Status words: **done** = built, tested, and it works without a key;
**built, awaiting run** = the code is done and the real numbers come from the
next live Record run; **open** = not built yet; **held** = adopted and
scheduled, not cut.

| # | Feature | Status | Evidence |
|---|---|---|---|
| 1 | Five new pages: What changed, Copilot, Actions & Audit, Dossier, Vision | done | `dashboard/copilot_pages.py`, `dossier_pages.py`, `vision_pages.py`; Playwright `tests/e2e/test_08_hackathon_pages.py` (23 passed on the keyless demo app, 2026-10-28) |
| 2 | 510(k) summary reader (Muse Spark, two reads, field check) and label camera (SAM 3.1) | partly recorded: 2 of 5 | `vision/`; the 5 PDFs are committed in `docs/510k/`. Second 2026-10-28 run: K031779 read (100% read agreement, 10/10 fields verified) and K261677 (80%, 8 verified, 2 conflicts flagged for a human); K043333, K210666, K190442 stopped at the reader's own 4096-token default, now 16000; re-record pending |
| 3 | Signal Evaluation & CAPA dossier PDF, Muse Spark narrative, Muse Wonder reviewer | done (deterministic part); review recorded, narrative re-record pending | `dossier/`; demo page shows 16/16 figures re-verified and the audit chain intact (e2e). Second run: Muse Wonder review returned 4 findings ($0.4248), all four fixed in code; the narrative used all 4000 tokens with no text and the old build showed it as passed: now withheld with a reason, cap 16000 (review 24000) |
| 4 | Claim-level citation gate | done | 101-case adversarial set `tests/fixtures/gate/adversarial.jsonl` (62 must block, 39 must pass); `tests/unit/test_gate.py`: 118 passed, 0 false pass / 0 false block. First live run found unparsed replies passing (fixed in `copilot/agent.py`); second live run: 45/48 first pass, 49/50 final, and one false block on a date before "reports" (fixed, cases d01/d02) |
| 5 | Copilot tools (13), CAPA-need evidence packs with named-human approval, hash-chained audit trail | done | `copilot/tools.py` (incl. `my_device_types`, `compare_signals`, `mhra_alerts`), `copilot/actions.py`, `Database.append_audit` / `verify_audit_chain` |
| 6 | Voice entries in the audit trail | done | `voice.transcribed` / `voice.rejected` entries linked to `copilot.answer`; recorded-run trails exported and re-verified on the Actions page (`copilot/audit_export.py`) |
| 7 | Voice query (Meta Voice Transcribe) | code done; new samples awaiting the next Record run | `copilot/voice.py`; two ElevenLabs text-to-speech samples from Charan (`demo/voice/question-a.wav`, `question-b.wav`, converted to mono 16 kHz, pass the local format check); the workflow transcribes and answers each. Not a real practitioner's voice, and the demo does not say it is. The old robotic placeholder was removed; Piper is not used |
| 8 | What-changed digest with why-ranked-first | done | `monitor/digest.py` (schema 1.2): fixed ranking key and a reason built from the detector's numbers, in plain words (reports suddenly increased / more serious than usual / new kind of problem); shown on the What changed page |
| 9 | Monitor cron (GitHub Actions, capped fetch) | **not done** | `.github/workflows/monitor.yml` exists. (a) `OPENFDA_API_KEY` secret: Charan updated it 2026-10-28; confirmed present: the 2026-10-28 Record run log shows `OPENFDA_API_KEY: ***` (GitHub masks a non-empty secret). (b) GitHub fires `schedule` only from the default branch, `main`, which has only `ci.yml`, so the cron cannot run until `hackathon-day2` is the default branch or is merged to `main`. Counts as done when both hold and one scheduled run has committed a digest |
| 10 | Live-call spend caps ($1 and 20 calls per browser session, $10 per day; configurable) | done | `copilot/spend.py`, `dashboard/spend_ui.py`, `tests/unit/test_spend.py`; checked in the app with a fake key and the call cap at 0 (no call made, fallback shown) |
| 11 | $150 budget | done (ledger awaiting run) | `docs/hackathon/BUDGET.md` |
| 12 | 20-answer hand-check, one accuracy number | done: **19/21 answers fully correct (90.5%)** (second 2026-10-28 recording; first was 6/21) | `docs/hackathon/HAND_CHECK.md`: of 50 sentences, 48 correct, 1 incomplete (gate false block, fixed), 1 wrong (12-literature: said no relevant papers are on file; a claim-less negative cannot be gated) |
| 13 | Clean layout + design system, theme picker (Light, Dark, Black, System, Pink, High contrast), top navigation | done | `design-system/` (Charan's design: bento, Paper/Night/High contrast; Black and Pink added in `tokens.json`), `dashboard/theme.py`, `dashboard/streamlit_bridge.css`; top bar (wordmark, five product pages, theme picker, dateline), hero tile for the top signal; WCAG AA contrast checked for every theme in `tests/unit/test_theme.py`; Playwright theme tests |
| 14 | MHRA (UK) device alerts adapter | code done; first fetch runs in Actions (`mhra-fetch.yml`) | `sources/mhra.py` (GOV.UK search API, device alerts only), stored as `mhra_alert` sources, quotes gated (`source_id: mhra:<id>`), copilot tool `mhra_alerts`, labelled section on What changed; scope note in `CLAUDE.md` §3. This container cannot reach gov.uk, so tests use recorded-format fixtures |
| 15 | Live Streamlit link | open | Charan's Streamlit Cloud account; entry point `streamlit_app.py`, branch `hackathon-day2` |
| 16 | Copilot memory (device types you choose, pinned notes) + signal compare | done | `copilot/memory.py` (state replayed from the hash-chained audit trail, entity `MEMORY`; only a named person changes it), `monitor/compare.py` (deterministic side-by-side), "Compare the device types you choose" on What changed; `tests/unit/test_memory_compare.py` |
| 17 | Streaming in the live copilot | done | `CopilotAgent.ask(on_event=…)` streams model / tool / gate / repair progress into a status panel; only gate-verified sentences are then streamed word by word (`stream_verified`) |
