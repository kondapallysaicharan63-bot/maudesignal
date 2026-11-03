# Test report — 2026-11-03 (local build only)

Branch `ccr-7cf96849-d3onnc`, base `origin/main` fd39235. **Nothing in this report was run against a
deployed build: the branch is not pushed.** Every "PASS" below means "passed locally on the
named run". Raw outputs: `release-out/2026-11-03/`. Browser script:
`scripts/release/e2e_pms.py`. This build is **not validated**.

## Result per test (A–O)

| Test | Result | What was run (evidence) |
|---|---|---|
| A. Unit + regression | **PASS** | Python 3.12: 2,572 passed, 0 skipped, coverage 85% line + branch (pytest-cov, rounded) (`pytest-py312.txt`). Python 3.11: 2,571 passed, **1 skipped** (`test_ai_sweep.py:28`, `lxml` not installed in the 3.11 venv; it ran on 3.12) (`pytest-py311.txt`). ruff, black, mypy clean (`ruff.txt`, `black.txt`, `mypy.txt`; run on the 3.12 venv only, not repeated on 3.11). Web: 722 passed in 34 files, `tsc -b` clean (`vitest.txt`, `tsc.txt`). One earlier failure, now fixed: see "Failures found and fixed". |
| B. Gate adversarial | **PASS** | 139 cases (90 must be withheld, 49 must pass): 0 false pass, 0 false block (`gate-adversarial.json`, `gate-adversarial-console.txt`). 9 added today: report-mix share (wrong = block, true = pass), true quote pinned to the wrong report, number with no claim, date-shifted year (names requested year = block; names none = pass + "Dates used"), zero on a NoData range, zero outside the stored window without a note, true zero inside the window. |
| C. Integration offline | **PASS** | `tests/unit/test_compliance_journey.py` (1 test, offline) passed on its own (`pytest-C.txt`). I did not re-read what it covers beyond its name and docstring. |
| D. Playwright | **PASS (Chromium only)** for the page and click path; see M for the one failed check | `e2e_pms.py`: 90 passed, 1 failed, 1 skipped (`e2e-pms.json`, `e2e-pms.md`, `shots/`). Ten pages load with no JS error: Home, Signals, Copilot (/chat), Vision, Audit, Board, Validation, Investigate, /pms-workflow, /roi. Path clicked: Investigate → evidence pack → accept (audit #1) → note to file → four downloads (md, pdf, csv, audit json) → Board New → Under review → Note to file → reload keeps status. Expected values computed from `alerts.json`, `manifest.json`, `sweep.json`, `lifecycle.json` and the demo DB. Firefox and WebKit not run. Served from a static build (`web/dist`), not from Vercel. |
| E. Desktop check | **PASS** | See below. |
| F. Live Q&A failure | **PASS (mocked API)** | Browser: forced 504 `live_timeout`, 500 and 429 on `/v1/live/ask` against a live-mode bundle. Each showed the fallback panel, no live-mode answer, four lookups returning stored data with no extra request, Retry (disabled on cap), and `live_failure` + `fallback_choice` rows in the audit. Unit: `pms.test.tsx` F tests. The real model was not called. |
| G. Keyword matching | **NOT RUN** | P1 item 13 (problem-term split, "Why matched") is not built. |
| H. Data-date | **PARTIAL** | Browser: banner present with values equal to the DB / manifest / sweep file on Signals, All alerts (sweep), Investigate, Board, Validation. HTML of the dossier PDF carries it (`test_dossier_carries_the_data_as_of_banner`). Investigate marks months inside the 62-day reporting window with a "reporting delay" tag (unit-tested). **Not verified in a browser:** the banner over live Copilot answers and on recorded threads; the Streamlit pages; the rendered PDF file itself. |
| I. Deployment | **PENDING** | Needs a push. Not started: Vercel web, Vercel API, Streamlit, env check, `smoke.py`, live-check workflow. Fresh sweep attempted: openFDA returned 403 `API_KEY_MISSING` for the sweep's date query (the key is only in GitHub secrets), so the stored 2026-10-30 sweep stays, labelled Stored. |
| J. Audit + tamper | **PASS** | Status change, accept and note-to-file each appear with name and timestamp; chain re-verifies on display ("Chain verified: 3 entries"). A tampered copy (entry 2 actor changed) in a separate browser context showed "Chain broken at entry #2". Python: `test_pms.py` tamper test breaks at seq 2. Browser hash proven equal to the Python hash by a vector test. |
| K. Cost + caps | **PASS (unit level)** | 94 cap / ledger tests passed (`pytest-K.txt`): a cap hit makes no call and is audited. Not driven in a running app. Code defaults: keyed ask $0.25/call and $2.00/day; live website $3.00/day total; Streamlit copilot $1 and 20 calls per session, $10/day. The brief's "$10/day" applies to the Streamlit copilot only. |
| L. Security + privacy | **PASS (unit level)** | 73 tests passed (`pytest-L.txt`) including patient data refused (422), key in query string rejected (400), wrong key 401, repeated wrong keys 429. Not re-run against a deployed API. Label-photo lot/serial handling not re-tested today. |
| M. Accessibility + front end | **FAIL (1 check) + SKIPPED (1)** | **Failed:** 6 buttons on `/investigate` measure 40 px, below the 44 px target (the jump links "Not filed by a manufacturer", "Reports", "Recalls and 510(k)s", "Evidence", "Evidence pack", and "Show all N months"). These are existing Investigate UI; left for the UI session. My Board and Validation buttons were fixed to 44 px. Board controls reachable by keyboard: pass. **Skipped:** six themes and AA contrast on the new pages (existing contrast scripts not re-run). Board and Validation are reachable from the sidebar and footer without a sweep or simulated profile: pass. |
| N. Validation-style | **PARTIAL** | Matrix, IQ/OQ below. **PQ not done by a human.** |
| O. Regression + cut | **PASS for what exists** | A and D re-run after the last change (final runs above). No P1 was started, so nothing was cut. I (deploy) not re-run. |

## Failures found and fixed during this run

1. `tests/unit/test_release_tools.py::test_the_real_adversarial_set_has_no_false_pass_or_false_block` failed on Python 3.11 and 3.12 after the 9 new gate cases: `scripts/release/gate_adversarial.py` ignored each case's `shifts` / `no_data`, so the cases that depend on a tool note were judged without it and the release check no longer agreed with `test_gate.py`. Fixed in `421a3d9`; passes on both.
2. Browser audit appends could lose an entry when two clicks happened together (both read the same chain tail). Found by the fallback test; fixed by queueing appends (`074cc69`).
3. Numbers I had typed on the Validation page before measuring (2,587 / 735 / 135 gate cases / $10 daily cap) did not match the runs. Replaced with the measured values above; a test now pins the gate count on the page to the fixture.
4. Playwright local server returned HTML for Vercel's `/_vercel/insights/script.js`, producing a false "Unexpected token '<'" on every page. Test artifact, not a product defect; the server now answers 404 for it.

## E. Desktop check (Folarin method)

- Alert: `brief:2026-08-31:LLZ`, "reports suddenly increased", week 2026-08-25 to 2026-08-31, baseline 2026-07-28 to 2026-08-24.
- Counts shown by the app: 33 this week, 35 in the baseline, weekly mean 8.75, 3.77×.
- Reproduced by hand from `data/demo/maudesignal_demo.db` (SQL on `raw_reports`): 33, 35, 35/4 = 8.75, 33/8.75 = 3.77. **Match: yes.**
- Reproduced from live openFDA (`count` queries on `device_report_product_code:LLZ` + `date_received`): 33 and 35. **Match: yes.**
- Report 50515470, received 2026-08-31, Malfunction, product LLZ (openFDA record agrees on date, type, code).
- Quote: "Philips identified a software defect in ISCV (IntelliSpace Cardiovascular) system wherein unable to fetch images for some records." Found verbatim in the stored narrative and in the live openFDA record (`mdr_text`). **Match: yes.**
- Limit: one alert, retrospective, checked by Claude. Not an independent check.

## Traceability (PRD item → test → result → evidence)

| PRD | Requirement | Test(s) | Result | Evidence |
|---|---|---|---|---|
| 8 | "Report mix changed" wording, rule unchanged | A, B, D | PASS | `test_pms.py::test_report_mix_sentence_exact_form`, `test_old_label_is_gone_from_user_facing_files`; `e2e-pms.md` Home check |
| 8/9 | Sweep date one source of truth; fresh run | A | PARTIAL | label pinned by `test_sweep_date_is_one_source_of_truth`; **fresh sweep not done** (403) |
| 18 | Validation page | A, D | PASS (local) | `pms.test.tsx`, `e2e-pms.md` |
| 19 | PMS Board | D, J | PASS (local) | `e2e-pms.md`, `shots/board-after.png` |
| 20 | Note to File export | D, J | PASS (local) | `e2e-pms.md`, `shots/note-export.png` |
| 21 | Escalation / risk / recall checklists | A | PASS (unit) | `test_pms.py`, `pms.test.tsx`; no decision sentence in any section |
| 22 | Live-model fallback | F | PASS (mocked API) | `e2e-pms.md` F rows, `shots/fallback-timeout.png` |
| 23 | Data-as-of banner | H | PARTIAL | see H |
| 24 | Measured ROI | — | **OPEN** | method recorded in `measurements.json`, `measurements: []`; needs Charan's timed, screen-recorded runs |
| 25 | Export version / commit / date / blank number | D | PASS (local) | `e2e-pms.md` CSV, audit and note rows |
| 26 | Trial protocol | D | PASS (page) | Validation page; the submission quoting it is Charan's step |
| 27 | Pitch corrections; non-manufacturer first | D | PASS (local) | `e2e-pms.md` Home and Investigate rows |

## IQ / OQ / PQ

- **IQ (install as documented), local:** `pip install -e ".[dev,connector]"` into fresh Python 3.11 and 3.12 virtual environments, `npm ci`, `npm run build` (v2 default) all succeeded (`web-build.txt`). Deployed install: pending.
- **OQ (each P0 function as specified), local build:** by `e2e_pms.py` and the unit suites. Deployed OQ: pending.
- **PQ: not done.** The fixed LLZ task and one flagged alert end to end by a person on the deployed build, following the steps, has not happened. The script above is not a PQ.

## Known limits that remain open (not reworded away)

- API limits, cost totals, cache and audit are per server instance and in memory (reset on cold start).
- No login and no Part 11 signature. The Board and its audit trail live in one browser (localStorage); another browser or device sees none of it.
- Demo universe is 4 product codes / 137 stored reports.
- Negative answers are not gated; completeness is not gated.
- No denominator: counts are not rates.
- Own-company separation is impossible from MAUDE alone.
- Hand-check 27/28 is retrospective, fixed demo questions, checked by Claude; Charan's independent check is pending. Not a field accuracy rate.
- Not covered today: Firefox/WebKit, six-theme contrast on new pages, deployed environments, a keyed live model call, a PDF-file visual check.
- Recorded digests and demo label-match JSON were relabelled by text replacement (the rule text), not regenerated; recorded Muse Spark transcripts were left verbatim.
- `/investigate` jump buttons are 40 px (see M).
- P1 (Morning Brief Agent, keyword match-reason, known-effects note) not built.
