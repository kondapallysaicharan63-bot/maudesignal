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
| 1 | Five new pages: Overnight, Copilot, Actions & Audit, Dossier, Vision | done | `dashboard/copilot_pages.py`, `dossier_pages.py`, `vision_pages.py`; Playwright `tests/e2e/test_08_hackathon_pages.py` (22 passed on the keyless demo app) |
| 2 | 510(k) summary reader (Muse Spark, two reads, field check) and label camera (SAM 3.1) | partly recorded: 1 of 5 | `vision/`; the 5 PDFs are committed in `docs/510k/`. 2026-10-28: K261677 read (80% read agreement; 8 fields verified, 2 conflicts flagged for a human); the other 4 returned no valid JSON at the 4096-token cap (now 16000) |
| 3 | Signal Evaluation & CAPA dossier PDF, Muse Spark narrative, Muse Wonder reviewer | done (deterministic part); narrative and review returned no text on 2026-10-28 (token cap), re-record pending | `dossier/`; demo page shows 16/16 figures re-verified and the audit chain intact (e2e). Narrative used all 1200 tokens and review all 4000 with no output; caps now 4000 / 16000 |
| 4 | Claim-level citation gate | done | 89-case adversarial set `tests/fixtures/gate/adversarial.jsonl` (55 must block, 34 must pass); `tests/unit/test_gate.py` run 2026-10-27: 106 passed, confusion matrix 0 false pass / 0 false block. The live run found a bypass one layer up: the agent turned a reply that never parsed into one claim-less sentence, which passed (11 answers). Fixed in `copilot/agent.py` (withheld, repair turn) with regression tests |
| 5 | Copilot tools (9), CAPA drafts with named-human approval, hash-chained audit trail | done | `copilot/tools.py`, `copilot/actions.py`, `Database.append_audit` / `verify_audit_chain` |
| 6 | Voice entries in the audit trail | done | `voice.transcribed` / `voice.rejected` entries linked to `copilot.answer`; recorded-run trails exported and re-verified on the Actions page (`copilot/audit_export.py`) |
| 7 | Voice query (Meta Voice Transcribe) | transcription recorded; answer re-record pending | `copilot/voice.py`; 2026-10-28 heard “what came in overnight is is anything worsening?” (3.28 s, $0.000150) from the committed WAV; the copilot reply did not parse. Charan's Piper WAV not pushed yet |
| 8 | Overnight digest with why-ranked-first | done | `monitor/digest.py` (schema 1.1): fixed ranking key and a reason built from the detector's numbers; shown on the Overnight page |
| 9 | Monitor cron (GitHub Actions, capped fetch) | **not done** | `.github/workflows/monitor.yml` exists. (a) `OPENFDA_API_KEY` secret: Charan updated it 2026-10-28; to be confirmed by the next smoke test log, which must print `OPENFDA_API_KEY: set` (the last log, 2026-10-27, printed `MISSING`). (b) GitHub fires `schedule` only from the default branch, `main`, which has only `ci.yml`, so the cron cannot run until `hackathon-day2` is the default branch or is merged to `main`. Counts as done when both hold and one scheduled run has committed a digest |
| 10 | Live-call spend caps ($1 and 20 calls per browser session, $10 per day; configurable) | done | `copilot/spend.py`, `dashboard/spend_ui.py`, `tests/unit/test_spend.py`; checked in the app with a fake key and the call cap at 0 (no call made, fallback shown) |
| 11 | $150 budget | done (ledger awaiting run) | `docs/hackathon/BUDGET.md` |
| 12 | 20-answer hand-check, one accuracy number | done for the 2026-10-28 recording: **6/21 answers fully correct (28.6%)**; re-record pending | `docs/hackathon/HAND_CHECK.md`: of 30 shown sentences, 12 correct, 1 incomplete, 6 misleading (window ended after the data), 11 not answers (reply never parsed, yet counted as passed by the old gate). No sentence stated a false fact. Fixes: unparsed replies withheld + repair turn; copilot cap 1500 → 4000; `overnight_signals` uses the latest stored date |
| 13 | Glassy UI: top navigation + digest hero instead of the old sidebar | **open** | not in any pushed branch: the app still uses sidebar navigation (`dashboard/app.py`). The e2e tests navigate by the sidebar and will be updated together with the new nav |
| 14 | MHRA source adapter | **held** (Day 6, adopted, not cut) | not started; will need a scope note next to the hackathon extension in `CLAUDE.md` §3 (which says U.S. FDA only) when it is built |
| 15 | Live Streamlit link | open | Charan's Streamlit Cloud account; entry point `streamlit_app.py`, branch `hackathon-day2` |
