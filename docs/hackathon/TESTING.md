# Testing report: all 21 test types

Status words: **PASS** = run, with the evidence named; **FAIL** = run and
failed (the failure is named); **PENDING** = included in the plan but not
done yet. A PENDING type is not counted as done anywhere in this repository.

Numbers come from runs on 2026-10-28 (this container: Python 3.13, Chromium
via Playwright; GitHub Actions: Python 3.11 and 3.12). Load and stress tests
never call Meta: the demo app holds no key, and seeded or recorded data stands
in for live answers, so no hackathon credit is spent on them.

| # | Type | Status | Evidence |
|---|---|---|---|
| 1 | Unit | PASS | `pytest tests/unit`: 2227 tests pass, 83.31% line + branch coverage (run 2026-10-31). Parsers and normalizers keep every adverse-event field (`test_ingestion_pipeline.py`, `test_report_sources.py`: report source stored and back-filled from the raw openFDA record) |
| 2 | Integration | PASS | `test_compliance_journey.py`: openFDA client (mock transport serving real stored MAUDE records) → ingestion → three Skills with their real schemas → SQLite → dashboard data → PSUR. Live services together in GitHub Actions: openFDA counts vs stored counts (`check_source_counts.py`, 0 mismatches), MHRA via GOV.UK (17 alerts stored), Meta (Record run) |
| 3 | System | PASS (product pages) / FAIL (20 classic-page tests, environment) | Playwright against the running app. Product pages: `tests/e2e/test_08_hackathon_pages.py`, 40 tests, all pass (Signals workspace, Copilot, Vision, Audit, every theme, top bar, keyboard, screen sizes, no sidebar in the public demo; 2026-10-29 layout). Classic pages `test_01` … `test_07`: 103 tests, 83 pass (2026-10-29: seven Dashboard tests that asserted always-zero tiles and the old sidebar status lines were replaced by tests that those are gone). **20 fail**: they expect LLM extraction rows or provider keys (`.env`) that the keyless demo database and this container do not hold — the same 20 fail on the code from before this session (run against commit 65c545a). One real regression (the top bar's theme picker was the first text input a test typed into) and two stale assumptions (the landing page; the keyless PSUR form) were fixed |
| 4 | Acceptance (UAT) | PENDING (external) | Internal acceptance criteria met: report-source counts equal openFDA's (`docs/hackathon/SOURCE_COUNTS.md`); every shown sentence matched to an FDA record by the gate; the PSUR and the evidence pack carry no decision on reportability or CAPA need. **External sign-off by practitioners (Harish / PSM QA) is awaited and not claimed.** |
| 5 | Smoke | PASS | CI (ruff, black, `mypy --strict`, tests on 3.11 and 3.12) green on the current head and on every pushed commit of 2026-10-28 except one: 39c13a2 failed `mypy` (a variable reused with another type in the gate's new number parsing) and the next commit, dcd6069, fixed it. CI on the bot's recording commits waits for maintainer approval (`action_required`). "Meta smoke test" green on every push; the keyless app boots and renders the Signals workspace |
| 6 | Sanity | PASS | Each fix shipped with the test that shows it: gate date false block (cases dt01/dt02), narrative withheld when empty (`test_empty_narrative_is_withheld_not_shown`), hand-check verdict keyed by sentence text (`test_a_re_recorded_sentence_is_checked_again`), number words in the gate (w01–w08), tool input fixes (`test_exploratory_findings_are_fixed`) |
| 7 | End-to-end | PASS | Compliance-officer journey, start extraction → check dashboard coverage → export a formatted PSUR (Markdown + PDF): `test_compliance_journey.py`. Browser journeys: Signals → Copilot → Signals › Evidence pack (PDF, review) → Audit |
| 8 | API | PASS | openFDA: request format, pagination, 404-as-empty, retries (`test_openfda_client.py`, `test_ingestion_pipeline.py`), live counts in Actions. Meta: chat + tool calls + strict JSON schema (`test_copilot_agent.py`), Voice Transcribe request format, validation and documented errors (`test_voice.py`), live smoke + Record runs. GOV.UK: response parsing, device-only filter, idempotent storage (`test_mhra.py`), live fetch in Actions. Rate limits: provider pool rotation on 429 (`test_provider_pool.py`), spend caps (`test_spend.py`) |
| 9 | Interface (UI) | PASS | Playwright: buttons, selectors, tabs and the theme picker respond on every product page; every theme loads from a link and paints the theme's colours; the picker switches theme and updates the link |
| 10 | Performance | PASS | Seeded data, `scripts/scale_test.py`: the weekly signal computation (now the Signals workspace) takes 0.07 s at 1,000 records (demo: 137); the gate checks a 6-sentence answer in 0.006 s. Browser: one user loads the home page then Copilot in 3.2 s (measured on the 2026-10-28 layout; re-run by `heavy-tests.yml`) |
| 11 | Load | PASS | `scripts/load_test.py`, keyless app, no Meta calls: 1 / 5 / 10 / 20 simultaneous browser sessions, 0 failures; slowest user 3.2 / 5.7 / 11.5 / 23.9 s (`docs/hackathon/load_results.json`). Browsers and server shared one machine, so these include client CPU |
| 12 | Stress | PASS (breaking point found) | 40 simultaneous sessions: 0 failures but the slowest user took 56.8 s, past the 30 s limit → breaking point between 20 and 40 users on one small server. Data: the Signals workspace passes 5 s between 50,000 (4.0 s) and 100,000 records (10.2 s). Live Meta was never stressed |
| 13 | Security | PASS | No key in any tracked file or in git history (pattern scan of every commit); `.env` git-ignored, `.env.example` holds empty values; keys only from env / Actions secrets, never echoed. `bandit -r src scripts`: 0 high, 1 medium (stdlib XML parse of PubMed responses — trusted NCBI source; accepted, listed), 11 low (reviewed: false positives such as a "pass" string). Manipulation: 130 adversarial gate cases (0 false passes), hash-chain tamper detection, memory changeable only by a named person (the model's tools are read-only), label photos refused while they carry metadata |
| 14 | Usability | PENDING (users) / internal review done | Internal heuristic review only (no user study): plain words replace jargon (reports suddenly increased / more serious than usual / new kind of problem), one hero tile says what to look at first and why, the four product pages sit in the top bar, more whitespace. A study with real PMS users is not done |
| 15 | Compatibility | PASS (Chromium, 4 sizes) / PENDING (cloud, other browsers) | No sideways scrolling and content renders at 390 × 844 (phone), 768 × 1024 (tablet), 1366 × 768 and 1920 × 1080 in Chromium. **Phone on the deployed app (Streamlit Cloud): PENDING, Charan to check. Firefox / Safari: not tested.** |
| 16 | Accessibility | PASS (basics) / PENDING (full WCAG audit) | WCAG AA contrast for every text pair in all five palettes (System follows the OS) (`test_theme.py`, main text 7:1); every visible control on the five pages has an accessible name; the top bar is reachable and operable by keyboard; focus outline on every control. Known gap: Streamlit's date picker adds a hidden native input without a name. **Full WCAG 2.2 audit with assistive technology: PENDING** |
| 17 | Scalability | PASS (demo scale) / PENDING (production) | Seeded growth 1k → 10k → 50k → 100k records: page 0.07 → 0.62 → 4.0 → 10.2 s, peak memory 64 → 341 MB; limit found at ~100k records for an interactive page (`docs/hackathon/scale_results.json`). **Production-scale proof: PENDING** |
| 18 | Regression | PASS | The full unit suite and CI run on every change; the product-page browser suite re-runs after each UI chunk; the classic pages were compared test by test with the pre-session code (above). New features did not break old parsing (ingestion / extraction / PSUR unit tests unchanged and passing) |
| 19 | Exploratory | PASS (bugs found and fixed) | Unscripted session, 2026-10-28: malformed JSON, wrong types, SQL- and HTML-looking input, path-like ids, empty results, wrong and lower-case device codes, an empty database. Found: (a) the gate let "thirty-three reports" / "1e3 reports" / "33 complaints" through without a count claim; (b) tools treated "llz" as unknown; (c) a string of codes was split into letters; (d) an empty CAPA-need evidence pack gave a misleading error; (e) duplicate adversarial ids. All fixed with tests |
| 20 | Alpha | PASS (Claude, local) / PENDING (Charan, deployed) | Claude tested every page and theme on the local keyless app. **Charan testing the deployed demo: PENDING** (deployed at the Streamlit Cloud link in the README) |
| 21 | Beta | PENDING | Limited external users (Harish / PSM QA) before release: replies awaited. Not claimed |

## Product-specific checks (in addition to the 21)

| Check | Result |
|---|---|
| Claim-level gate, adversarial set | 130 cases (84 must be withheld, 46 must pass): 0 false passes, 0 false blocks (`tests/unit/test_gate.py`) |
| Gate on real model output | fifth 2026-10-28 recording (run 40764365995), 28 answers (22 typed, 6 text-to-speech): 63/65 first pass (96.9%), 64/65 after repair; 1 false block (a year read as a count) found and fixed (dt03–dt05); 0 unparsed (fourth: 49/50) |
| Hand-check of recorded answers | 27 of 28 answers fully correct (96.4%); typed 21 of 22, text-to-speech 6 of 6; Oct-29 voice run 40965201781 (Charan's takes 1/4/6): 3 of 3, 8 of 8 sentences correct; 64 of 65 sentences correct, 1 incomplete (withheld by the false block), 0 wrong (checked by Claude against the database; Charan's independent check PENDING). Fourth: 24 of 24; third: 21 of 24 |
| Report sources vs openFDA | stored counts equal openFDA `count=report_source_code.exact` for every stored code |
| Audit trail | editing any stored entry breaks the chain at that entry; detected in the database and in exported trails |
| Spend caps | $1 and 20 Meta calls per browser session, $10 per day; no call starts once a cap is reached |
| MHRA labelling | MHRA alerts never enter a MAUDE number; every surface says "MHRA (UK)" |
| Label camera (live photos) | 7 of 7 read (run 40792998780); 4 correct, 1 left for a person, 1 nothing read, 1 misread (fields marked partly legible, no product code); no lot/serial stored; photos refused if they carry metadata (0 of 7 did) |
| Themes | WCAG AA in Light, Dark, Black, Pink, High contrast; System follows the OS |

## Where each test type runs (GitHub Actions)

| Test type(s) | Workflow · job | When |
|---|---|---|
| 1 Unit, 2 Integration (offline), 5 Smoke, 6 Sanity, 18 Regression | `ci.yml` · Tests & Type Checks (ruff, black, `mypy --strict`, `pytest tests/unit`, Python 3.11 + 3.12) | every push to `main` and `hackathon-day2`, every PR into `main`, on demand |
| 13 Security | `ci.yml` · Security (`scripts/scan_secrets.py` on every tracked file; bandit, fails on high severity) | same |
| 3 System, 7 End-to-end, 9 Interface, 15 Compatibility (Chromium, 4 sizes), 16 Accessibility (basics) | `ci.yml` · Browser tests: `tests/e2e/test_08_hackathon_pages.py` against the keyless app (blocking); classic pages `test_01`–`test_07` reported, not blocking (they need LLM extraction rows the demo database does not hold) | same |
| 2 Integration (live) and 8 API (live Meta, openFDA, GOV.UK) | `copilot-record.yml`, `vision-labels.yml`, `mhra-fetch.yml`, `monitor.yml`, `meta-smoke.yml` | on their triggers (record request, photos, schedule) |
| 10 Performance, 11 Load, 12 Stress, 17 Scalability | `heavy-tests.yml` (`scale_test.py`, `load_test.py` 1 → 40 sessions; results as an artifact) | on demand and weekly |
| 4 UAT, 14 Usability, 19 Exploratory, 20 Alpha, 21 Beta | people, not CI | PENDING as listed above |
