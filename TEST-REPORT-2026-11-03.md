# Test report — 2026-11-03 (local build only)

Branch `ccr-7cf96849-d3onnc`, based on `origin/main` fd39235 (re-fetched overnight: main has not
moved, so no rebase was needed). **Nothing here was run against a deployed build: the branch is not
pushed.** "PASS" means "passed locally on the named run". Raw outputs: `release-out/2026-11-03/`.
Browser scripts: `scripts/release/e2e_pms.py` (website) and `tests/e2e/test_08_hackathon_pages.py`
(Streamlit). This build is **not validated**.

## Result per test (A–O)

| Test | Result | What was run (evidence) |
|---|---|---|
| A. Unit + regression | **PASS** | One clean overnight run. Python 3.12: **2,574 passed**, 0 skipped, coverage 85% line + branch (pytest-cov, rounded) (`pytest-py312.txt`). Python 3.11: **2,573 passed, 1 skipped** (`test_ai_sweep.py:28`, `lxml` not installed in the 3.11 venv) (`pytest-py311.txt`). ruff, black, mypy clean (`ruff.txt`, `black.txt`, `mypy.txt`; run on the 3.12 venv only). Web: **722 passed** in 34 files, `tsc -b` clean (`vitest.txt`, `tsc.txt`). Streamlit browser file: **44 passed, 1 skipped** (a live openFDA check refused with 403 from this network) (`pytest-streamlit-e2e.txt`). |
| B. Gate adversarial | **PASS** | **139 cases** (90 must be withheld, 49 must pass): 0 false pass, 0 false block (`gate-adversarial.json`, `-console.txt`). 9 added today: report-mix share (wrong = block, true = pass), true quote pinned to the wrong report, number with no claim, date-shifted year (names the requested year = block; names none = pass + "Dates used"), zero on a NoData range, zero outside the stored window without a note, true zero inside the window. |
| C. Integration offline | **PASS** | `tests/unit/test_compliance_journey.py` (1 test) passed on its own (`pytest-C.txt`). I did not re-read what it covers beyond its docstring. |
| D. Playwright | **PASS (Chromium only)** except the known M failure | `e2e_pms.py` on a static local build: **94 passed, 1 failed, 1 skipped** (`e2e-pms.json`, `e2e-pms.md`, `shots/`). Ten pages load with no JS error: Home, Signals, Copilot (/chat), Vision, Audit, Board, Validation, Investigate, /pms-workflow, /roi. Path clicked: Investigate → pack → accept (audit #1) → note to file → four downloads (md, pdf, csv, audit json) → Board New → Under review → Note to file → reload keeps status. Expected values come from `alerts.json`, `manifest.json`, `sweep.json`, `lifecycle.json` and the demo DB. Firefox/WebKit not run. |
| E. Desktop check | **PASS — Claude-only check, not an independent person check** | `desktop-check.txt`. Alert `brief:2026-08-31:LLZ` (reports suddenly increased). App: 33 this week, 35 in the baseline, mean 8.75, 3.77×. Demo DB by hand: 33, 35, 8.75, 3.77. Live openFDA counts: 33 and 35. Report 50515470 (2026-08-31, Malfunction, LLZ): the quote "Philips identified a software defect in ISCV (IntelliSpace Cardiovascular) system wherein unable to fetch images for some records." is verbatim in the demo DB narrative and in the live openFDA record. |
| F. Live Q&A failure | **PASS (mocked API; real model NOT called)** | Browser, live-mode bundle, `/v1/live/ask` mocked to 504 `live_timeout`, 500 and 429. Each: fallback panel, any answer shown is mode `recorded` (none live), four lookups (live check, stored reports, recalls, product summary) return stored data with no extra request, Retry re-asks (disabled on the cap), `live_failure` + `fallback_choice` rows in the audit; the stored-recall total shown equals `alerts.json`. Unit: `pms.test.tsx`. |
| G. Keyword matching | **NOT RUN** | P1 item 13 (problem-term split, "Why matched") is not built. |
| H. Data-date | **PASS (local), with proof; deployed pending** | (a) Website, browser: banner on Signals, All alerts (sweep), Investigate, Board, Validation, **over the Copilot answer** (all three forced-failure runs) and on a **recorded thread**; dates equal the demo DB / manifest / sweep file. (b) **Streamlit, browser:** Signals and Copilot show "Data as of" = demo DB newest report date, "Live check: none on this page"; Signals has the link to `https://maudesignal-app.vercel.app/board` and the top bar has no Board (`tests/e2e/test_08_hackathon_pages.py::TestDataAsOfBanner`). (c) **Rendered PDF files:** `build_demo_dossier.py --no-live` produced the draft and approved PDFs (WeasyPrint); `pdftotext` shows "Data as of: 2026-08-31 … not because risk is zero … Live check: none in this document." (`pdf-banner-draft.txt`, `pdf-banner-approved.txt`). Months inside the 62-day reporting window get a "reporting delay" tag on Investigate: unit-tested only, not asserted in a browser. |
| I. Deployment | **PENDING** | Needs a push. Not started: Vercel web, Vercel API, Streamlit Cloud, env check, `smoke.py`, live-check workflow. Fresh sweep: openFDA refuses the sweep's date-range `count` query without a key (403 `API_KEY_MISSING`) while small keyless queries return 200; that is expected in this sandbox. The stored 2026-10-30 sweep stays labelled **Stored**; a fresh sweep is **pending in GitHub Actions after a push**. |
| J. Audit + tamper | **PASS** | Status change, accept and note-to-file each appear with name and timestamp; "Chain verified: 3 entries" on display. A tampered copy (entry 2) in a separate browser context shows "Chain broken at entry #2". Python tamper test breaks at seq 2. Browser hash equals the Python hash (vector test). |
| K. Cost + caps | **PASS (unit level)** | 94 cap and ledger tests passed (`pytest-K.txt`): a cap hit makes no call and is audited. Not driven in a running app. Caps in the code (environment can override): keyed ask $0.25 per call and $2.00 a day; live website $3.00 a day in total; Streamlit copilot $1 and 20 calls per session and $10 a day. |
| L. Security + privacy | **PASS (unit level)** | 73 tests passed (`pytest-L.txt`): patient data refused (422), key in query string rejected (400), wrong key 401, repeated wrong keys 429. Not re-run against a deployed API. |
| M. Accessibility + front end | **1 FAIL + 1 SKIP (both belong to the UI session)** | **FAIL (known, existing UI, not fixed here):** 6 controls on `/investigate` are 40 px, under the 44 px target: the jump links "Not filed by a manufacturer", "Reports", "Recalls and 510(k)s", "Evidence", "Evidence pack" and "Show all N months". **SKIP:** AA contrast in the six themes on the new pages was not run. My Board and Validation buttons are 44 px; the Board is keyboard-reachable; Board and Validation are in the sidebar and footer without a sweep or simulated profile. |
| N. Validation-style | **PARTIAL** | Matrix and IQ/OQ below. **PQ: NOT DONE BY A PERSON.** |
| O. Regression + cut | **PASS for what exists** | A and D re-run after the last code change (the numbers above). No P1 was started, so nothing was cut. I (deploy) was not run. |

## Failures found and fixed during this work

1. `tests/unit/test_release_tools.py::test_the_real_adversarial_set_has_no_false_pass_or_false_block` failed on Python 3.11 and 3.12 after the 9 new gate cases: `scripts/release/gate_adversarial.py` ignored each case's `shifts` / `no_data`, so the release check no longer agreed with `test_gate.py`. Fixed in `421a3d9`.
2. Browser audit appends could lose an entry when two clicks happened together. Found by the fallback test; fixed by queueing appends (`074cc69`).
3. Numbers I had typed on the Validation page before measuring (2,587 / 735 / 135 gate cases / "$10 overall") did not match the runs. Replaced with the measured values; a test pins the gate count on the page to the fixture.
4. The local Playwright server returned HTML for Vercel's `/_vercel/insights/script.js`, a false "Unexpected token '<'" on every page. Test artefact; the server now answers 404 for it.
5. Environment: the venv's Playwright expected headless-shell build 1248, the container has 1243. I linked 1248 → 1243 under `/opt/pw-browsers` (outside the repo) to run the existing Streamlit e2e file.

## Chase items

- **Rebase:** `origin/main` is still fd39235. No rebase.
- **PRD gate count:** `docs/hackathon/PRD.md` has a dated note: row 4's 112 was written 2026-10-29 (git); the same fixture had 130 later that day and **139 on 2026-11-03**. README and TESTING.md now say 139 (130 until 2026-11-02).
- **Secret scan:** `scripts/scan_secrets.py`: 0 hits. Separate scan of every tracked text file in HEAD: 0 hits. 866 vs 865 earlier: the 866 was commit `2de7d44`; the 865 was commit `421a3d9`, which deleted exactly one file, `src/maudesignal/dashboard/pms_pages.py`. `.env` is gitignored and absent. Matches are never printed.
- **Relabelled files** (`relabel-proof.txt`): 8 `data/monitor/**` files and 4 changed `demo/vision/label-match-*.json` are identical to their originals after the label substitution alone. `digests/2026-08-24|31` were regenerated with `maudesignal monitor --no-fetch` on a copy of the demo DB; a test pins them to a fresh run. `demo/transcripts/` (recorded Muse Spark runs) has no diff.

## Traceability (PRD item → test → result → evidence)

| PRD | Requirement | Test(s) | Result | Evidence |
|---|---|---|---|---|
| 8 | "Report mix changed" wording, rule unchanged | A, B, D | PASS | `test_pms.py` (sentence, old-label grep, digests), `e2e-pms.md` |
| 8/9 | Sweep date one source of truth; fresh run | A | PARTIAL | label pinned by `test_sweep_date_is_one_source_of_truth`; **fresh sweep PENDING** (Actions) |
| 18 | Validation page | A, D | PASS (local) | `pms.test.tsx`, `e2e-pms.md` |
| 19 | PMS Board | D, J | PASS (local) | `e2e-pms.md`, `shots/board-after.png` |
| 20 | Note to File export | D, J | PASS (local) | `e2e-pms.md`, `shots/note-export.png` |
| 21 | Escalation / risk / recall checklists | A | PASS (unit) | `test_pms.py`, `pms.test.tsx`; no decision sentence in any section |
| 22 | Live-model fallback | F | PASS (mocked API) | `e2e-pms.md` F rows, `shots/fallback-timeout.png` |
| 23 | Data-as-of banner | H | PASS (local) | see H (a)(b)(c) |
| 24 | Measured ROI | — | **OPEN** | method recorded in `measurements.json` (`measurements: []`); Charan records the timed runs |
| 25 | Export version / commit / date / blank number | D | PASS (local) | `e2e-pms.md` CSV, audit and note rows |
| 26 | Trial protocol | D | PASS (page) | Validation page; the submission quoting it is Charan's |
| 27 | Pitch corrections; non-manufacturer first | D | PASS (local) | `e2e-pms.md` Home and Investigate rows |

## IQ / OQ / PQ

- **IQ (install as documented), local:** `pip install -e ".[dev,connector]"` into fresh Python 3.11 and 3.12 venvs, `npm ci`, `npm run build` all succeeded (`web-build.txt`). Deployed install: pending.
- **OQ (each P0 function as specified), local build:** `e2e_pms.py`, the Streamlit browser file and the unit suites. Deployed OQ: pending.
- **PQ: NOT DONE BY A PERSON.** The fixed LLZ task and one flagged alert end to end by a person on the deployed build has not happened. The scripts above are not a PQ.

## Known limits that remain open (not reworded away)

- API limits, cost totals, cache and audit are per server instance and in memory (reset on cold start).
- No login and no Part 11 signature. The Board and its audit trail live in one browser (localStorage).
- Demo universe is 4 product codes / 137 stored reports.
- Negative answers are not gated; completeness is not gated.
- No denominator: counts are not rates.
- Own-company separation is impossible from MAUDE alone.
- Hand-check 27/28 is retrospective, fixed demo questions, checked by Claude; Charan's independent check is pending. Not a field accuracy rate. The desktop check (E) is also Claude-only.
- Not covered: Firefox/WebKit, six-theme contrast on new pages, deployed environments, a keyed live model call.
- Delay tag on recent months is unit-tested only.
- `/investigate` jump buttons are 40 px (M).
- P1 (Morning Brief Agent, keyword match-reason, known-effects note) not built.

## Morning deploy checklist for Charan (prepared, NOT run)

1. Say **push** for this branch only (`ccr-7cf96849-d3onnc`). Do not merge to `main` until the checks below pass.
2. GitHub Actions: CI (Python 3.11 + 3.12, ruff, black, mypy, tests, e2e) green on the branch.
3. API: `GET https://maudesignal-api.vercel.app/v1/health` → `status: ok`, `version: 0.1.0`.
4. Web (`maudesignal-app.vercel.app`): Home shows the headline and the complaint card first; sweep label says **Stored** with the 2026-10-30 date; open `/board` and `/validation`; run `scripts/release/smoke.py` and the live-check workflow, record both runs.
5. Streamlit app: data-as-of banner on Signals and Copilot, and the link to the website's `/board`.
6. Run the fresh AI-device sweep workflow (needs the `OPENFDA_API_KEY` secret) and re-check the Stored label.
7. Charan: the timed LLZ ROI runs, the PQ, and the video/submission approvals.
