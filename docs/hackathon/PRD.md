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
| 5 | Copilot tools (9), CAPA drafts with named-human approval, hash-chained audit trail | done | `copilot/tools.py`, `copilot/actions.py`, `Database.append_audit` / `verify_audit_chain` |
| 6 | Voice entries in the audit trail | done | `voice.transcribed` / `voice.rejected` entries linked to `copilot.answer`; recorded-run trails exported and re-verified on the Actions page (`copilot/audit_export.py`) |
| 7 | Voice query (Meta Voice Transcribe) | recorded (committed WAV) | `copilot/voice.py`; second 2026-10-28 run transcribed the committed placeholder WAV correctly and the answer passed the gate and the hand-check. New question (2026-10-28 wording review): “What changed this week? Did reports suddenly increase for any device?”, to be recorded in Charan's own voice; re-record after it lands |
| 8 | What-changed digest with why-ranked-first | done | `monitor/digest.py` (schema 1.2): fixed ranking key and a reason built from the detector's numbers, in plain words (reports suddenly increased / more serious than usual / new kind of problem); shown on the What changed page |
| 9 | Monitor cron (GitHub Actions, capped fetch) | **not done** | `.github/workflows/monitor.yml` exists. (a) `OPENFDA_API_KEY` secret: Charan updated it 2026-10-28; to be confirmed by the next smoke test log, which must print `OPENFDA_API_KEY: set` (the last log, 2026-10-27, printed `MISSING`). (b) GitHub fires `schedule` only from the default branch, `main`, which has only `ci.yml`, so the cron cannot run until `hackathon-day2` is the default branch or is merged to `main`. Counts as done when both hold and one scheduled run has committed a digest |
| 10 | Live-call spend caps ($1 and 20 calls per browser session, $10 per day; configurable) | done | `copilot/spend.py`, `dashboard/spend_ui.py`, `tests/unit/test_spend.py`; checked in the app with a fake key and the call cap at 0 (no call made, fallback shown) |
| 11 | $150 budget | done (ledger awaiting run) | `docs/hackathon/BUDGET.md` |
| 12 | 20-answer hand-check, one accuracy number | done: **19/21 answers fully correct (90.5%)** (second 2026-10-28 recording; first was 6/21) | `docs/hackathon/HAND_CHECK.md`: of 50 sentences, 48 correct, 1 incomplete (gate false block, fixed), 1 wrong (12-literature: said no relevant papers are on file; a claim-less negative cannot be gated) |
| 13 | Glassy UI: top navigation + digest hero instead of the old sidebar | **open** | not in any pushed branch: the app still uses sidebar navigation (`dashboard/app.py`). The e2e tests navigate by the sidebar and will be updated together with the new nav |
| 14 | MHRA source adapter | **held** (Day 6, adopted, not cut) | not started; will need a scope note next to the hackathon extension in `CLAUDE.md` §3 (which says U.S. FDA only) when it is built |
| 15 | Live Streamlit link | open | Charan's Streamlit Cloud account; entry point `streamlit_app.py`, branch `hackathon-day2` |
