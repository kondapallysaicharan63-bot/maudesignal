# MaudeSignal

[![CI](https://github.com/kondapallysaicharan63-bot/maudesignal/actions/workflows/ci.yml/badge.svg)](https://github.com/kondapallysaicharan63-bot/maudesignal/actions/workflows/ci.yml)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

**When a complaint arrives, MaudeSignal finds the matching FDA evidence in one question, prepares PMS evidence, and keeps every fact traceable for audit.**

- **This build is not validated.** A validation path to FDA AI/ML guidance (GMLP principles,
  lifecycle guidance) is on the roadmap.
- Not medical advice, not clinical decision support, not an FDA-cleared device and not a
  compliance tool.
- Outputs are signals for a person in quality or regulatory to review. A named person
  makes every decision.
- Nothing is filed with FDA.

Built solo by Saicharan Kondapally for the Meta Global AI Developer Hackathon.

- Live demo: <https://maudesignal-app.vercel.app> (no key needed; answers without a model
  key are recorded runs, labelled "recorded" with their date)
- Demo video: _(link added at submission)_

## Pre-existing vs built Oct 26 – Nov 4, 2026

**Pre-existing (before the event):** openFDA MAUDE ingestion, the LLM extraction Skills
(narrative extraction, severity triage), the 11-category AI failure-mode classifier, and
the Streamlit dashboard (since updated with the hackathon pages).

**Built during the hackathon:**

- Muse Spark copilot with a deterministic claim gate (every number recomputed, every quote
  and record id matched to the stored FDA record, or the sentence is withheld)
- Voice questions (Voice Transcribe, then the same copilot and gate)
- Device-label reader (SAM 3.1 crop, then Muse Spark) and 510(k) summary reader (two
  independent Muse Spark reads, checked against openFDA and the PDF text layer)
- Evidence pack PDF (*Signal Evaluation & CAPA-need Evidence*) with an independent
  Muse Wonder review (findings only)
- SHA-256 hash-chained audit trail
- Web app (`web/`) and read-only REST API (`api/`)
- Morning brief `/daily` (stored exports, every number linked to its openFDA query)
- EU workflow `/eu`: where the same steps sit in an EU MDR PMS workflow. FDA data only;
  no EUDAMED data in this build
- Keyword measurement on the stored LLZ reports (shown on `/validation`)
- Interactive owl dock (Noctua) that opens the PMS board
- MCP connector (6 read-only tools). Submitted to Meta's Muse Connector Program — pending review.

File-by-file list: [HACKATHON.md](HACKATHON.md).

## Meta models used (all Standard tier)

All calls go through the Meta Model API (`https://api.meta.ai/v1`, key from
`META_MODEL_API_KEY`, never committed or logged). Standard tier only, never the
Contributor tier, which trains on your data.

| Model | Code id | What it does here |
|---|---|---|
| Muse Spark 1.3 | `muse-spark-1.3` | Copilot answers (tool calling, strict JSON schema of sentences + claims, one repair turn after a gate block); the connector's `ask`; the weekly investigator and recall sweep; the evidence-pack summary; reads 510(k) summary pages and label crops ([`copilot/agent.py`](src/maudesignal/copilot/agent.py), [`vision/spark.py`](src/maudesignal/vision/spark.py)) |
| Muse Wonder 1.0 | `muse-wonder-1.0` | Independent review of the evidence-pack PDF; lists findings, never edits the record ([`dossier/review.py`](src/maudesignal/dossier/review.py)) |
| Voice Transcribe 1.0 | `muse-voice-transcribe-1.0` | Spoken questions to text; only the text reaches Muse Spark ([`copilot/voice.py`](src/maudesignal/copilot/voice.py)) |
| SAM 3.1 | `sam-3.1` | Finds the label in a device photo before Muse Spark reads the crop ([`vision/sam.py`](src/maudesignal/vision/sam.py)) |
| Muse Image 1.0 | `muse-image-1.0` | Optional evidence-pack cover illustration, **off by default**, captioned "AI-generated illustration — not evidence" ([`dossier/illustration.py`](src/maudesignal/dossier/illustration.py)) |

## Tools

**Copilot tools (13, deterministic, over stored records)** — [`copilot/tools.py`](src/maudesignal/copilot/tools.py):

| Tool | Purpose |
|---|---|
| `overnight_signals` | What changed this week: reports suddenly increased, report mix changed, or a new kind of problem |
| `product_summary` | Report counts and event-type shares for one product code, plus its 510(k) devices |
| `search_reports` | Search stored MAUDE reports; narrative excerpts quotable with their report id |
| `get_report` | Full stored narrative for one MAUDE report id |
| `deadline_check` | Advisory MDR due date from an awareness date (30 calendar days or 5 work days); does not decide reportability |
| `draft_capa` | Records a CAPA-need evidence pack (supporting report ids + factual problem statement) for a named person to accept or reject; it does not decide that a CAPA is needed |
| `recalls` | FDA device recalls for one product code, newest first |
| `device_510k` | 510(k) record for one K-number, and recalls citing it |
| `literature` | Stored PubMed abstracts for a product code or keywords |
| `report_sources` | Who filed the stored reports (manufacturer, user facility, voluntary, distributor) |
| `my_device_types` | The device types a person chose to watch, and pinned notes |
| `compare_signals` | Device types side by side for the current 7-day window |
| `mhra_alerts` | Stored MHRA (UK) device safety alerts; UK context only, never counted |

**MCP connector tools (6, all read-only)** — [`api/mcp-manifest.json`](api/mcp-manifest.json):

| Tool | Purpose |
|---|---|
| `what_changed_this_week` | Device types with a change in the latest stored week, or one product code |
| `check_device_type` | Live openFDA counts for one product code, latest week vs the four weeks before |
| `ask` | Free-text question; Muse Spark answers through the copilot tools and the claim gate |
| `get_report` | One stored MAUDE report: key fields and the start of the narrative, word for word |
| `recalls` | FDA recalls on file for a product code, newest first |
| `lookup_device` | Up to 3 possible openFDA records for a device in hand (name, model, K-number, UDI); no model call; a person confirms the match |

## Architecture

```text
openFDA ──> stored snapshot (SQLite, data/demo/) ──> deterministic tools ──> Muse Spark 1.3
                                                                                  │
                                       claim gate (recompute numbers, match quotes and ids)
                                                                                  │
                                          web app / REST API / MCP connector ──> audit trail
                                                                                  (SHA-256 hash chain)
```

The gate makes no model calls; a sentence it cannot match is withheld, with the reason.
Diagram source: [docs/architecture.mmd](docs/architecture.mmd).

## Tests

- Python unit tests: **2626 passed**, 84.92% line + branch coverage (`pytest tests/unit`, 2026-11-04)
- Web unit tests: **777 passed in 39 files** (`cd web && npx vitest run`, 2026-11-04)
- Release check: run on every release candidate (see .github/workflows/release-check.yml).
  It covers lint, `mypy --strict`, unit tests, web tests, API contract and security
  checks, and browser end-to-end tests (chromium, firefox, webkit; 1440 and 390 px; light
  and dark).

## Data dates

- The demo answers come from a **stored snapshot** of public openFDA data
  ([`data/demo/SEED_MANIFEST.json`](data/demo/SEED_MANIFEST.json)): 137 MAUDE reports; the
  newest stored report was received **Aug 31, 2026**.
- The live openFDA checks (Investigate a complaint, `check_device_type`) are separate and
  are dated when they run.

## Evidence of quality

- 27 of 28 recorded answers were fully correct. That was Claude's hand-check, not a person's.
  (Fifth recording, 2026-10-28; [docs/hackathon/HAND_CHECK.md](docs/hackathon/HAND_CHECK.md).)
- Keyword measurement: 11 of 121 stored LLZ reports matched; 8 of the 11 were the same problem (72.7%), adjudicated by Claude, not a person.
  ([`web/public/data/keyword_measurement.json`](web/public/data/keyword_measurement.json).)
- Gate adversarial set: 139 cases (90 must be withheld, 49 must pass), 0 false passes,
  0 false blocks ([`tests/fixtures/gate/adversarial.jsonl`](tests/fixtures/gate/adversarial.jsonl)).
- Muse Wonder findings on the evidence pack are a model's review, not a human review.

## Reviewers

Three reviewers gave feedback, in three rounds. No trial or pilot was run.

1. **Srinivas Sreepada** — regulatory expert
2. **Hemadri Doma** — software validation
3. **Folarin Erogbogbo** — professor; a limited desktop check, not validation

They gave feedback as individuals, in a personal capacity.

---

## Links

| | |
|---|---|
| Website | <https://maudesignal-app.vercel.app> |
| Morning brief (stored exports, every number linked to its openFDA query) | <https://maudesignal-app.vercel.app/daily> |
| EU MDR: workflow relevance only (FDA data only, no EUDAMED data) | <https://maudesignal-app.vercel.app/eu> |
| Limits and the LLZ keyword measurement | <https://maudesignal-app.vercel.app/validation> |
| API (read-only REST + MCP) | <https://maudesignal-api.vercel.app> (`/v1/health`, `/docs-page`, `/mcp`) |
| Muse connector | Submitted to Meta's Muse Connector Program — pending review. Form answers: [docs/hackathon/MUSE_CONNECTOR.md](docs/hackathon/MUSE_CONNECTOR.md) |
| Streamlit dashboard | <https://maudesignal-4vniqswm9ptaxqtf2iawox.streamlit.app/> |
| What was built during the hackathon | [HACKATHON.md](HACKATHON.md) |
| What is deterministic, what a model writes, what is tested | [docs/VALIDATION_EVIDENCE.md](docs/VALIDATION_EVIDENCE.md) |

## How MaudeSignal fits your PMS workflow (F26)

Post-market surveillance in most companies is reactive (a complaint arrives, someone
investigates) and periodic (trend review, PMS board, PSUR or PMSR, management review, audit).
The website page `/pms-workflow` (v2 layout) maps that order step by step and, for each
step, shows: what is done by hand today, what MaudeSignal does, what stays human, and related
clauses (ISO 13485 section 8.2.1 to 8.2.3 and 8.5.2; 21 CFR 820, 803, 806 and 7; ISO 14971).
The map lists what MaudeSignal does at each step: a search of problems reported on other makers' devices of the same type (FDA data),
Investigate a complaint (new), the weekly change check and AI-device sweep (the proactive
extra), the claim gate, the CAPA-need evidence PDF with an independent Muse Wonder review,
human approval and a hash-chained audit trail, and a decision path on simulated devices
(new, simulated). The decision, the signature and any filing stay human: MaudeSignal does not
decide, and nothing is filed with FDA. The page does not say that any step satisfies a clause.

## Numbers (each from a file in this repo)

| Number | Source file |
|---|---|
| Demo database: 137 real MAUDE reports (LLZ 121) | [`data/demo/SEED_MANIFEST.json`](data/demo/SEED_MANIFEST.json) |
| LLZ, stored week Aug 25–31, 2026: 33 reports vs a weekly average of 8.75 (3.77x) | [`digests/2026-08-31.md`](digests/2026-08-31.md) |
| Recorded cost of a typed question: average $0.048, highest $0.098 (22 typed answers) | `cost_usd` in [`demo/transcripts/`](demo/transcripts/) (the `2026*.json` files except `00-voice-*`) |
| Recorded cost of a spoken question: average $0.037 (9 voice answers) | `cost_usd` in [`demo/transcripts/`](demo/transcripts/) (`2026*-00-voice-*.json`) |
| Recorded cost of a label photo: average $0.012 (7 photos; SAM 3.1 $0.0025 + Muse Spark read) | `trace[].cost_usd` in `demo/vision/label-match-*.json` ([`demo/vision/`](demo/vision/)) |
| Chat answer tiers, estimate on a 20-question sample: $0.048 per question before, $0.012 after (upper bound; 5 of 20 reach Muse Spark) | [`docs/hackathon/CHAT_TIERS.md`](docs/hackathon/CHAT_TIERS.md) |
| Gate adversarial set: 139 cases (90 must be withheld, 49 must pass), 0 false passes, 0 false blocks | [`tests/fixtures/gate/adversarial.jsonl`](tests/fixtures/gate/adversarial.jsonl), [`tests/unit/test_gate.py`](tests/unit/test_gate.py) |
| Weekly investigator, one recorded LLZ run: $0.224989 | [`demo/investigations/20261030T010942Z-weekly-llz.json`](demo/investigations/20261030T010942Z-weekly-llz.json) |
| Daily ceiling on all live Meta calls together: $3.00 per UTC day | [`src/maudesignal/connector/callcap.py`](src/maudesignal/connector/callcap.py) (`MAUDESIGNAL_LIVE_DAILY_USD`) |

## How to run it

**1. No install:** open the [website](https://maudesignal-app.vercel.app). With no
model key on the server, chat, voice and camera replay recorded runs, labelled "recorded".

**2. On a laptop, no key (about 2 minutes):**

```bash
git clone https://github.com/kondapallysaicharan63-bot/maudesignal.git
cd maudesignal
python3.12 -m venv .venv && source .venv/bin/activate
pip install -e .

# What-changed digest from the committed demo database (no network, no model)
maudesignal monitor --no-fetch

# Dashboard on the demo database: Signals, Copilot, Vision, Audit
streamlit run streamlit_app.py
```

The demo database ([`data/demo/maudesignal_demo.db`](data/demo/)) holds 137
real MAUDE reports fetched without a key from openFDA (LLZ complete for
Jul–Aug 2026; all QIH, MYN and POK reports). The exact queries are in
[`SEED_MANIFEST.json`](data/demo/SEED_MANIFEST.json). With no
`MAUDESIGNAL_DB_PATH` set and no local `data/maudesignal.db`, the dashboard
opens this database automatically. Without a key, the Copilot page replays
recorded Muse Spark runs from [`demo/transcripts/`](demo/transcripts/) and lets you try
to fool the gate live.

**3. Live answers (costs money):** set `META_MODEL_API_KEY` to ask live questions. Every
live Meta call counts against the daily ceiling above.

**Deploy (Streamlit Community Cloud):** entry point `streamlit_app.py`,
dependencies from `requirements.txt`, no secrets required. Your own Vercel copy:
see [Deploy your own copy](#deploy-your-own-copy).

## Limits

- **Not medical advice** and not clinical decision support. Outputs are signals for a
  person in quality or regulatory to review.
- **Not an FDA-cleared device** and **not a compliance tool.** It never decides whether an
  event is reportable or whether a CAPA is needed; a named person decides, and nothing is
  filed with FDA.
- **U.S. FDA data only** (MAUDE, recalls, 510(k)). UK MHRA alerts are shown as labelled
  regulator context and are never counted.
- **Recorded vs live.** Without a model key, answers are recorded runs and say "recorded"
  with their date; a live answer is labelled live. The demo database is a stored snapshot,
  not live openFDA.
- **$3/day cap** on all live Meta calls together (each call reserves its worst case first).
- **Not built:** team accounts or SSO (today: a public demo key plus personal keys, no
  logins). A shared Upstash store for rate limits, caches and the audit log is supported by
  the code but not turned on for the public copy.

## Today / Tomorrow

Today: U.S. FDA data (MAUDE, recalls, 510(k)). UK MHRA alerts appear as labelled regulator context only, not counted. No EU, Canadian or Australian data is included.

### Tomorrow — what reviewers asked for next

By reviewer, credited as individuals in a personal capacity (see Acknowledgements below).

- **Srinivas Sreepada (regulatory expert):** a PMS board and note-to-file record you can sign, FDA
  escalation and recall assessments, risk, and the workflow map. The map and a first decision path on
  simulated devices are built; saving your own decisions is not.
- **Hemadri Doma (software validation):** a complaints-team record that Investigate a
  complaint can feed (the known-effects record), and validation to FDA AI standards before an auditor would accept
  the tool. Validation path to FDA AI/ML guidance (GMLP principles, lifecycle guidance) is on the roadmap; this build is
  not validated.
- **A PMS practitioner (Oct 27):** a user-entered list of device types to watch, taken from your own clinical
  evaluation report.

### Acknowledgements

Three reviewers gave feedback, in three rounds. No trial or pilot was run. They are credited as
individuals, in a personal capacity. Their feedback shaped the decision workflow, the
complaint-investigation page and the workflow map.

1. **Srinivas Sreepada** — regulatory expert: PMS board, note to file, FDA escalation and recall
   assessment, risk; reactive PMS, workflow map.
2. **Hemadri Doma** — software validation: complaints-team / known-effects record; validation to
   FDA AI standards before an auditor would accept the tool.
3. **Folarin Erogbogbo** — professor: a limited desktop check, not validation.

Earlier feedback: **a PMS practitioner (Oct 27)** — who files the reports, and what a company's own
CAPA form decides.

### Tomorrow — not built yet

Reviewer feedback (Oct 31 and Nov 1) shaped the complaint-investigation, workflow-map and
device-profile pages. What is NOT built yet:

- **Your own complaint system.** "Investigate a complaint" searches public FDA data only. It does not hold your
  complaints, cannot separate your own company's reports from other makers' (maker names on MAUDE are free text),
  and has no MDR clock; reportability is assessed by your team.
- **Investigate as a Muse connector (MCP) tool.** `POST /v1/investigate` (REST, in the OpenAPI document) exists and the
  website page uses it; the MCP tool for the Muse connector is next.
- **Decision paths on every signal and on your own devices.** Decision paths exist for the simulated devices'
  stored signals; saving your own board decisions (with e-signatures) is not built.
- **Validation.** Validation path to FDA AI/ML guidance (GMLP principles, lifecycle guidance) is on the roadmap; this build is not validated.

---

## The problem

- **Companies know their competitors. What they cannot see is: (1) reports about
  their own device filed by hospitals, users or distributors that never reached
  their complaint team, and (2) the same failure mode emerging on other makers'
  devices of the same type before it hits their device.** Those sit among tens of
  thousands of public MAUDE reports. openFDA's counts by report source for the
  demo device types are in
  [docs/hackathon/SOURCE_COUNTS.md](docs/hackathon/SOURCE_COUNTS.md).
- PMS is reactive first. MaudeSignal does not replace complaint handling; it
  speeds the investigation step after a complaint arrives, and flags a code
  before the next complaint arrives.
- Reading MAUDE by hand is slow; a general-purpose chatbot is faster but can
  make up numbers, quotes and regulation citations, which a regulated
  workflow cannot accept.

## What it does (Monday morning)

1. **What changed this week.** A deterministic monitor (no model) compares
   the last 7 days of openFDA reports with the 4 weeks before, for the device
   types (FDA product codes) you choose, and flags three things: **reports
   suddenly increased**, **report mix changed**, or a **new kind of
   problem**. On the demo data: *"LLZ: reports suddenly increased — 33 this
   week vs a weekly mean of 8.75 (3.77x)"*
   ([digests/2026-08-31.md](digests/2026-08-31.md)), with the reason it is
   ranked first.
2. **Any device type, live.** Type any FDA product code on the Signals page:
   MaudeSignal asks openFDA for counts (about 5 requests, no report text,
   nothing stored, no model) and applies the same four rules, with a link to
   the openFDA query behind every figure. A weekly GitHub Actions job runs the
   same check for every product code on FDA's AI-Enabled Medical Device List
   ([docs/hackathon/AI_SWEEP.md](docs/hackathon/AI_SWEEP.md)).
3. **Who filed the reports.** Counts per device type by openFDA report source
   (manufacturer, user facility, voluntary, distributor) and a filterable list
   of the reports **not filed by a manufacturer**. On the demo data all 33 LLZ
   reports this week, and all 121 LLZ reports in the stored demo sample, were filed by
   manufacturers (openFDA as a whole: 19,970 LLZ reports, 99.3% manufacturer-filed); the
   non-manufacturer reports on file are 3 MYN, 3 QIH and 1 POK (all voluntary).
4. **Ask the copilot,** typed or by voice. Muse Spark calls 13 tools over
   stored MAUDE reports, FDA recalls, 510(k) records and PubMed abstracts and
   answers in a strict JSON schema: sentences, each tagged with the claims it
   makes.
5. **The gate checks every claim.** A made-up quote or count is withheld with
   the reason (*"claimed 500, records show 121"*); a reply that does not parse
   is withheld too. The model gets one repair turn with the gate's values.
6. **CAPA-need evidence pack.** The copilot can prepare the evidence (the
   supporting reports and a problem statement); a named person accepts or
   rejects it in the Signals workspace (Evidence pack tab); the Audit page keeps the trail. The model cannot.
7. **Evidence pack (PDF).** *Signal Evaluation & CAPA-need Evidence*, laid out
   like a controlled quality record: document control, signal evaluation,
   evidence table, the ISO 13485:2016 §8.5.2 sections left blank for the CAPA
   owner, an MDR worksheet mapped to FDA Form 3500A (stamped *not for
   submission*) and the audit trail. Every printed number is re-verified by the
   gate. **Muse Wonder 1.0** reviews the whole PDF before a person accepts it.
8. **Vision.** Muse Spark reads FDA 510(k) summary PDFs (many are scanned)
   twice, independently; a field is *verified* only if both reads agree and
   openFDA / the PDF text layer agree, otherwise it is flagged for a person.
   A photo of a device label → **SAM 3.1** finds the label → Muse Spark reads
   it → the K-number is checked against FDA.
9. **Audit trail.** Every answer, spoken question, live-call cost and decision
   is appended to a SHA-256 hash-chained log; the dashboard re-verifies it.

## How it's different

- **It withholds what it cannot match.** Every number is recomputed, every
  quote matched word for word, every report id, 510(k), recall, PMID and CFR
  section checked against stored FDA records — or the sentence is not shown.
  Adversarial set: 139 cases, 0 false passes, 0 false blocks.
- **It reads scanned 510(k) documents with a two-read accuracy check.**
- **It writes down the search protocol** behind each answer (dataset, filters, dates,
  counts) so a person can repeat it.
- **It is open source and self-hostable** (MIT), on public FDA data only.

### Three agentic workflows (status)

| Workflow | Command | Status |
|---|---|---|
| Weekly investigator: for a device type the weekly check flagged, Muse Spark pulls the new reports, groups them by kind of problem, checks recalls, 510(k)s and non-manufacturer reports, and writes the digest entry through the gate | `maudesignal investigate` | Built and tested with mocked model calls (`tests/unit/test_weekly_investigator.py`). One real recording is stored: `demo/investigations/20261030T010942Z-weekly-llz.json` (LLZ; 7 of 7 sentences and 9 of 9 claims passed the gate on the first pass; $0.224989). |
| Recall-triggered sweep: Muse Spark reads a recall's reason and searches stored narratives for the same problem; quotes matched word for word, counts recomputed by the gate | `maudesignal recall-sweep` | Built and tested with mocked model calls (`tests/unit/test_recall_sweep.py`). Real recordings pending. |
| Search protocol: every tool call's dataset, filters, dates and counts, listed as a search-methodology appendix in the evidence-pack PDF | part of the dossier build | Built and tested (`tests/unit/test_search_protocol.py`). |

Recordings of the first two run in GitHub Actions
(`.github/workflows/investigator-record.yml`) with the repository's model key;
until a recording is committed, nothing here is shown as a real run.

## Real-run numbers (2026-10-28, fifth recording)

From [`demo/transcripts/`](demo/transcripts/), [`demo/vision/`](demo/vision/),
[`demo/dossier/`](demo/dossier/) and the hand-check
[`docs/hackathon/HAND_CHECK.md`](docs/hackathon/HAND_CHECK.md):

| | |
|---|---|
| Recording run | GitHub Actions run 40764365995 (fifth recording, 2026-10-28): 28 copilot answers (22 typed, 6 text-to-speech clips, mostly not shown in the app any more) |
| Gate, first pass | 63/65 sentences passed (96.9%); after one repair turn: 64/65 (one true sentence wrongly withheld — a year read as a count; fixed in the gate since) |
| Replies that never parsed | 0 of 28; 0 answers stopped by the token cap |
| Hand-check | **27 of 28 answers fully correct (96.4%)**; typed 21 of 22, text-to-speech clips 6 of 6. Of 65 sentences: 64 correct, 1 incomplete (the wrongly withheld one); none wrong. Checked against the demo database by Claude, not a person; my own independent check is pending. Earlier recordings: 24/24, 21/24, 19/21, 6/21 |
| Cost per answer | $0.0454 (28 answers, $1.2717) |
| 510(k) reading | **5 of 5 summaries read**: the two reads agree on 100% of fields for K031779, 90% for K190442, K210666 and K261677, and 80% for K043333; the 6 conflicting fields are flagged for a person, never guessed |
| Label camera (SAM 3.1 + Muse Spark) | **7 of 7 photos read**: 4 devices read correctly (CareSens N, HoMedics thermometer ×2, Welch Allyn 802 LTR), thermometers matched to FDA product code FLL; 1 left for a person to pick; 1 returned nothing (rotated label); 1 misread (Welch module: wrong text, every field marked only partly legible, no product code); no lot/serial stored |
| Evidence pack (PDF) | Muse Spark summary: 5 sentences shown, 0 withheld, in plain words (no "spike"); Muse Wonder review: 0 findings (the previous recording had 2, a high one on section 4.1 and a medium one on the section 4 title; both fixed by the reword). Recorded 2026-10-31 for the current pack (SER-LLZ-20260831-001) |
| Report sources vs openFDA | 0 mismatches |

Oct-29 voice run (GitHub Actions run 40965201781, 3 answers, stored in the repo
alongside the fifth recording; the table above stays the fifth recording's): the gate passed
8 of 8 sentences, first pass and final. All 8 sentences were hand-checked against the demo
database by Claude, not a person (8 correct, 0 wrong); my own independent check is pending.

Spoken questions: the spoken questions the app and the walkthrough show are my own
recordings, public with my consent (`demo/voice/question-take1.wav`, `-take4.wav`,
`-take6.wav`). They were not heard word for word: Voice Transcribe wrote "LLG" and "LLC"
for LLZ and added stray words ("devices? devices?", "week. week."). The product code is
corrected by a fixed one-letter rule (`src/maudesignal/copilot/product_code.py`), and the
screen states it ("Heard LLG -> did you mean LLZ? The answer used LLZ (one letter
different; the only close code on file)."); the heard text is kept next to the question.
The correction is never silent: in live mode the analyst confirms it before anything is sent,
and the stored demo shows both codes and says which one the recorded answer used. Take 4 is the "50 injury reports" trap
the copilot rejects: 33 reports, 0 injuries (in the stored demo sample). Take 6's answer, "all 121 stored LLZ
reports were filed by a manufacturer", is about the stored demo sample of 121 LLZ reports,
not openFDA as a whole (19,970 LLZ reports, 99.3% manufacturer-filed). The earlier
text-to-speech clips (ElevenLabs, not a person) are kept only in the audit trail, except
one question (`question-d`) that none of my recordings covers. The one incomplete
answer (06-trap) lost a true sentence because the gate read "August 31, 2026,
all malfunction" as a count of 2026; the gate now treats a year after a month
as a date (adversarial cases dt03–dt05).

## The citation gate

[`src/maudesignal/gate/`](src/maudesignal/gate/) is deterministic and makes no
model calls. For every sentence the copilot wants to show:

- **counts** are recomputed from stored records and must match exactly;
  **shares** must be within 0.5 percentage points;
- **quotes** must appear verbatim in the narrative of the report they are
  attributed to (a real quote pinned to the wrong report is blocked);
- **510(k) numbers** must exist in the catalog or stored openFDA 510(k)
  records and match the stated product code / device name; **MAUDE report
  ids**, **FDA recall numbers** and **PubMed PMIDs** must exist in stored data
  (and match the stated product code / year); recall counts are recomputed;
- **21 CFR sections** must be on a curated allowlist; QS-reg sections
  superseded by QMSR on 2026-02-02 are blocked with the reason;
- **report-source counts** (who filed the reports) are recomputed from the
  stored openFDA `report_source_code`;
- a sentence that mentions a number, K-number, report id or CFR section
  **without** a matching structured claim is blocked as ungrounded.

**Adversarial test set:** [139 cases](tests/fixtures/gate/adversarial.jsonl)
(90 must block, 49 must pass): fabricated and drifted quotes, real quotes on
the wrong report, stale / inflated counts, wrong shares, fake and mismatched
K-numbers, hallucinated and superseded CFR sections, fake recall numbers and
PMIDs, real ones on the wrong product or year, wrong report-source counts,
untagged mentions (including "N hospital reports"), dates that look like counts,
and counts written in words or scientific notation ("thirty-three reports", "1e3 reports").
Result: **0 false passes, 0 false blocks**
([`tests/unit/test_gate.py`](tests/unit/test_gate.py), 156 tests on 2026-11-04).

Real verdicts on the demo database (137 MAUDE reports):

| Sentence / claim | Verdict |
|---|---|
| Quote taken from report 25675105, attributed to 25675105 | ✅ pass |
| The same quote attributed to report 25675201 | ⛔ `quote is real but belongs to 25675105, not 25675201` |
| "the AI failed to flag the hemorrhage" attributed to 25675105 | ⛔ `quote not found verbatim in 25675105` |
| "LLZ had 500 reports" | ⛔ `claimed 500, records show 121` |
| "Open a CAPA under 21 CFR 820.100" | ⛔ `superseded by QMSR (ISO 13485 clauses 8.5.2/8.5.3) on 2026-02-02` |
| "About 40% of LLZ reports were malfunctions" (no claim attached) | ⛔ `ungrounded: 40% has no share claim` |

## Deploy your own copy

[![Deploy with Vercel](https://vercel.com/button)](https://vercel.com/new/clone?repository-url=https://github.com/kondapallysaicharan63-bot/maudesignal&project-name=maudesignal-web&root-directory=web&env=VITE_MAUDESIGNAL_API_BASE&envDescription=Base%20URL%20of%20your%20own%20MaudeSignal%20API%20project)

Two Vercel projects from the same repository: the website (`web/`) and the read-only API
(repository root, `api/index.py`). Nothing is deployed for you and no key is in the repository.

1. **Website.** Click the button above (root directory `web`, framework Vite). Set
   `VITE_MAUDESIGNAL_API_BASE` to your API project's URL once step 2 exists. Left empty, the
   website still shows the stored data; live chat, voice and camera then use
   recorded runs.
2. **API.** Import the same repository a second time with the root directory left at the
   repository root. Add these environment variables in Project > Settings > Environment Variables:
   `MAUDESIGNAL_API_KEYS` (a key you generate, as `label=KEY`), `MAUDESIGNAL_KEY_PEPPER` (a long
   random string), `MAUDESIGNAL_WEB_ORIGINS` (your website URL), `OPENFDA_API_KEY` (optional, higher
   openFDA quota). Leave `META_MODEL_API_KEY` unset to answer from recorded runs; set it, together
   with a private Blob store (`BLOB_READ_WRITE_TOKEN`), only when you accept the cost: every Meta
   call is held to a daily ceiling (`MAUDESIGNAL_LIVE_DAILY_USD`, default $3.00).
3. **Check it.** Open `<your API URL>/v1/health`, then `<your API URL>/docs-page`; add
   `<your API URL>/mcp` to your MCP client with your key (the website's Connect page shows config
   snippets). Turn Vercel Authentication off for production so visitors do not meet a login page.

Full variable list and limits: [`docs/hackathon/MUSE_CONNECTOR.md`](docs/hackathon/MUSE_CONNECTOR.md).

### Self-hosted company mode (audit full text)

For a company's own deployment only. By default, and always on the public demo, the audit chain
keeps an `ask` question as its SHA-256 and length, never its text; the public privacy page and the
connector questionnaire describe that default. A company running its own copy for its own staff
can have each `ask` entry (REST and MCP, with a key) also keep the question text and the answer's
spoken text (`question_text`, `answer_text`, `full_text: "stored"`). The text is inside the hashed
record, so `/v1/audit/recent` still re-verifies the chain, and that list (full keys only) shows
the text only for entries where it was stored. When the mode is on, the served `/privacy` page and
the `/v1/audit/recent` description say so; when it is off they are the public demo's, unchanged.

It fails closed. A flag is on when its value is `1`, `true`, `yes` or `on` (any case); anything
else, or unset, is off. Full text turns on only when **all** of these hold:

- `MAUDESIGNAL_AUDIT_FULL_TEXT` is on, **and** `MAUDESIGNAL_SELF_HOSTED` is on;
- no public signal: `MAUDESIGNAL_DEMO_KEYS` unset or empty (and no demo key configured),
  `MAUDESIGNAL_PUBLIC_DEMO` not on, `VERCEL_ENV` not `production`, and `MAUDESIGNAL_WEB_ORIGINS`
  unset or empty.

Otherwise the mode stays off and, if it was asked for, startup logs `audit_full_text_refused`
naming each failing condition (never a value). A question or answer that looks like patient
details (email, phone, ID or record number, date of birth, a titled name, an age) is never
stored: the entry keeps the hash and `full_text: "withheld_possible_patient_details"`. The
website's live routes (`/v1/live/*`) never store question text in either mode. MaudeSignal is
still not a PHI system; this mode is for questions about public MAUDE data. Code:
[`src/maudesignal/connector/audit_mode.py`](src/maudesignal/connector/audit_mode.py).

## Pipeline (pre-existing)

The base `maudesignal` pipeline: ingest MAUDE reports from openFDA, extract
structured fields with an LLM, triage severity, classify into an 11-category
AI failure taxonomy, cluster root causes, detect trends (Mann-Kendall + linear
regression) and drift (KS / PSI), pull PubMed and ClinicalTrials.gov sources,
and draft a PSUR-style report (Markdown + optional PDF). LLM behaviour lives in
versioned Skills (`skills/<name>/SKILL.md` + JSON Schema + good/bad examples),
never in inline strings. The extraction layer is provider-agnostic: Groq
(default), Anthropic, OpenAI, Gemini, or a multi-key `pool` that rotates on
rate limits.

| Skill | Version | Purpose |
|---|---|---|
| [`safety-copilot`](skills/safety-copilot/SKILL.md) | v1.3.6 | **Hackathon.** Copilot behaviour contract: tools, structured claims, advisory-only rules |
| [`regulatory-citation-verifier`](skills/regulatory-citation-verifier/SKILL.md) | v1.0.0 | Citation rules; enforced in code by `gate/` (hackathon) |
| [`maude-narrative-extractor`](skills/maude-narrative-extractor/SKILL.md) | v1.0.0 | Structured fields from MAUDE narratives |
| [`severity-triage`](skills/severity-triage/SKILL.md) | v1.0.0 | Death / serious injury / malfunction / other |
| [`ai-failure-mode-classifier`](skills/ai-failure-mode-classifier/SKILL.md) | v1.0.0 | 11-category AI failure taxonomy |
| [`root-cause-analyzer`](skills/root-cause-analyzer/SKILL.md) | v1.0.0 | Root-cause hypothesis per failure-mode cluster |
| [`drift-analysis-interpreter`](skills/drift-analysis-interpreter/SKILL.md) | v1.0.0 | KS/PSI statistics → regulatory language |
| [`trend-interpreter`](skills/trend-interpreter/SKILL.md) | v1.0.0 | Trend statistics → regulatory narrative |
| [`psur-report-drafter`](skills/psur-report-drafter/SKILL.md) | v1.1.0 | PSUR draft with signal assessment |

### Running the pipeline (needs an LLM key for the extraction steps)

```bash
cp .env.example .env            # e.g. LLM_PROVIDER=groq and GROQ_API_KEY=...

maudesignal ingest --product-code QIH --limit 20      # openFDA → SQLite
maudesignal catalog update                            # FDA AI/ML device catalog
maudesignal extract --product-code QIH --limit 10     # extract → triage → classify
maudesignal analyze root-cause --product-code QIH
maudesignal alert check --product-code QIH
maudesignal forecast trends QIH
maudesignal drift --product-code QIH
maudesignal sources fetch pubmed --query "AI radiology device failure" --product-code QIH
maudesignal psur generate QIH --device-name "AI Radiology CAD" --output reports/QIH_psur.pdf
maudesignal status
```

`maudesignal --help` lists every command. PDF export needs the system
libraries WeasyPrint uses (Pango/Cairo); without them the PDF step is skipped
and Markdown is still produced.

### Documentation

| | |
|---|---|
| Hackathon build manifest | [HACKATHON.md](HACKATHON.md) |
| Vision & non-goals | [docs/01_vision_mission.md](docs/01_vision_mission.md) |
| Requirements | [docs/03_requirements_spec.md](docs/03_requirements_spec.md) |
| System design (pre-hackathon) | [docs/05_architecture.md](docs/05_architecture.md) |
| Repo conventions for AI assistants | [CLAUDE.md](CLAUDE.md) |
| Disclaimer | [DISCLAIMER.md](DISCLAIMER.md) |

## License

[MIT](LICENSE). openFDA data is public domain; see [DISCLAIMER.md](DISCLAIMER.md)
for the regulatory-use notice.

## Author

**Saicharan Kondapally**, M.S. Biomedical Engineering, San Jose State
University · [GitHub](https://github.com/kondapallysaicharan63-bot)
