# MaudeSignal

[![CI](https://github.com/kondapallysaicharan63-bot/maudesignal/actions/workflows/ci.yml/badge.svg)](https://github.com/kondapallysaicharan63-bot/maudesignal/actions/workflows/ci.yml)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

**Every morning, MaudeSignal shows where reports suddenly increased, where they are more serious than usual and where there is a new kind of problem, for the device types you choose — your competitors' devices and reports about your device you didn't file. It only shows facts it can match to the FDA record. People make every decision.**

> **What this is:** a B2B tool for postmarket-surveillance (PMS) and
> regulatory-affairs teams at medical-device makers, working on public openFDA
> MAUDE adverse-event data.
> **What it is not:** medical advice, clinical decision support, or an
> FDA-cleared device. It never decides whether an event is reportable or
> whether a CAPA is needed, and it does not define "similar devices": it works
> on the device types you choose.
> **People decide:** whether a CAPA is required is decided by the company's own
> CAPA-need form; MaudeSignal prepares evidence only, and a named person accepts
> it. Nothing is filed with FDA automatically.

Validation facts (what is deterministic, what a model writes, what is tested,
what a manufacturer would still do): [docs/VALIDATION_EVIDENCE.md](docs/VALIDATION_EVIDENCE.md).

---

## The problem

- Device makers already know their own complaints: they file them. What is
  hard to see is what happens to **other companies' devices of the same type**
  and the reports about **their own device filed by someone else** — a user
  facility such as a hospital, a voluntary reporter, a distributor. Those sit
  among tens of thousands of public MAUDE reports. openFDA's counts by report
  source for the demo device types are in
  [docs/hackathon/SOURCE_COUNTS.md](docs/hackathon/SOURCE_COUNTS.md).
- Reading MAUDE by hand is slow; a general-purpose chatbot is faster but can
  make up numbers, quotes and regulation citations, which a regulated
  workflow cannot accept.

## What it does (Monday morning)

1. **What changed this week.** A deterministic monitor (no model) compares
   the last 7 days of openFDA reports with the 4 weeks before, for the device
   types (FDA product codes) you choose, and flags three things: **reports
   suddenly increased**, **more serious than usual**, or a **new kind of
   problem**. On the demo data: *"LLZ: reports suddenly increased — 33 this
   week vs a weekly mean of 8.75 (3.77x)"*
   ([digests/2026-08-31.md](digests/2026-08-31.md)), with the reason it is
   ranked first.
2. **Who filed the reports.** Counts per device type by openFDA report source
   (manufacturer, user facility, voluntary, distributor) and a filterable list
   of the reports **not filed by a manufacturer**. On the demo data all 33 LLZ
   reports this week, and all 121 stored, were filed by manufacturers; the
   non-manufacturer reports on file are 3 MYN, 3 QIH and 1 POK (all voluntary).
3. **Ask the copilot,** typed or by voice. Muse Spark calls 13 tools over
   stored MAUDE reports, FDA recalls, 510(k) records and PubMed abstracts and
   answers in a strict JSON schema: sentences, each tagged with the claims it
   makes.
4. **The gate checks every claim.** A made-up quote or count is withheld with
   the reason (*"claimed 500, records show 121"*); a reply that does not parse
   is withheld too. The model gets one repair turn with the gate's values.
5. **CAPA-need evidence pack.** The copilot can prepare the evidence (the
   supporting reports and a problem statement); a named person accepts or
   rejects it on the Actions page. The model cannot.
6. **Evidence pack (PDF).** *Signal Evaluation & CAPA-need Evidence*, laid out
   like a controlled quality record: document control, signal evaluation,
   evidence table, the ISO 13485:2016 §8.5.2 sections left blank for the CAPA
   owner, an MDR worksheet mapped to FDA Form 3500A (stamped *not for
   submission*) and the audit trail. Every printed number is re-verified by the
   gate. **Muse Wonder 1.0** reviews the whole PDF before a person accepts it.
7. **Vision.** Muse Spark reads FDA 510(k) summary PDFs (many are scanned)
   twice, independently; a field is *verified* only if both reads agree and
   openFDA / the PDF text layer agree, otherwise it is flagged for a person.
   A photo of a device label → **SAM 3.1** finds the label → Muse Spark reads
   it → the K-number is checked against FDA.
8. **Audit trail.** Every answer, spoken question, live-call cost and decision
   is appended to a SHA-256 hash-chained log; the dashboard re-verifies it.

## How it's different

Other tools summarize MAUDE with AI and add a review step — for example
[DeviceWatch](https://devicewatch.app/data) (AI summaries of MAUDE records;
public pricing from $499/month),
[Basil Systems](https://www.businesswire.com/news/home/20251006297490/en/Basil-Systems-Launches-Safety-Signaling-Solution-to-Proactively-Detect-and-Prevent-Medical-Device-Risks)
(AI safety signaling across regulatory and adverse-event records) and
[Complizen](https://www.complizen.ai/platform) (AI answers drawing on FDA
guidance, 510(k) history and MAUDE). MaudeSignal differs in three ways:

- **It withholds what it cannot match.** Every number is recomputed, every
  quote matched word for word, every report id, 510(k), recall, PMID and CFR
  section checked against stored FDA records — or the sentence is not shown.
  Adversarial set: 109 cases, 0 false passes, 0 false blocks.
- **It reads scanned 510(k) documents with a two-read accuracy check.**
- **It is open source and self-hostable** (MIT), on public FDA data only.

## Real-run numbers (2026-10-28, third recording)

From [`demo/transcripts/`](demo/transcripts/), [`demo/vision/`](demo/vision/),
[`demo/dossier/`](demo/dossier/) and the hand-check
[`docs/hackathon/HAND_CHECK.md`](docs/hackathon/HAND_CHECK.md):

| | |
|---|---|
| Recording run | GitHub Actions run 40692882168 (fourth recording, 2026-10-28): 24 copilot answers (22 typed, 2 spoken) |
| Gate, first pass | 49/50 sentences passed (98.0%); after the one repair turn: 50/50 |
| Replies that never parsed | 0 of 24; 0 answers stopped by the token cap |
| Hand-check | **24 of 24 answers fully correct (100%)**; typed questions only: 22 of 22. All 50 sentences checked against the demo database by Claude; an independent check by Charan is pending. Earlier recordings: 21/24, 19/21, 6/21 |
| Cost per answer | $0.0432 (24 answers, $1.0372) |
| 510(k) reading | **5 of 5 summaries read**: the two reads agree on 100% of fields for K031779, K190442, K210666 and K261677 and 80% for K043333; fields that disagree with each other or with openFDA (3 conflicts, 1 unverifiable across the five) are flagged for a person, never guessed |
| Evidence pack (PDF) | Muse Spark summary: 5 sentences shown, 0 withheld, in plain words (no "spike"); Muse Wonder review: 0 findings |
| Report sources vs openFDA | 0 mismatches |

The three answers that were wrong or incomplete in the third recording are
fixed: the literature tool now ranks papers by matching terms (12-literature
cites four stored PMIDs), the recalls tool filters by keyword (18-trap-recall
names a stored IntelliSpace Cardiovascular recall and still refuses to confirm a
class that is not stored), and the larger token cap let 13-llz-severity answer
(0% Injury/Death this week vs 2.9% in the 4 weeks before). The two spoken clips
were greetings, not product questions; Voice Transcribe heard both correctly and
the copilot claimed no facts.

## Tomorrow

- **Buyer:** PMS / RA teams at small and mid-size device makers.
- **Open source, self-hosted:** free.
- **Hosted plan:** priced in the range practitioners we spoke to quoted,
  about $200–300/month, against existing tools from $499/month.
- **Pilot metric:** time to prepare the signal-evidence section for the device types you choose
  in a PMS report, with and without MaudeSignal.

## How Meta AI is used

| Step | Meta model / API | Why |
|---|---|---|
| Answering a question | **Muse Spark 1.3** (`muse-spark-1.3`) via the **Meta Model API** (OpenAI-compatible, `https://api.meta.ai/v1`) | Tool calling over 10 deterministic tools; **strict `json_schema` structured output** (sentences + typed claims, [`skills/safety-copilot`](skills/safety-copilot/SKILL.md)); a **repair turn** after a gate block, fed the gate's reasons and recomputed values |
| Reading scanned FDA documents | **Muse Spark 1.3 image understanding** ([`skills/fda-document-reader`](skills/fda-document-reader/SKILL.md)) | 510(k) summary pages → structured fields with per-field legibility; two independent reads + openFDA + text layer decide VERIFIED / CONFLICT / UNVERIFIABLE |
| Device-label camera | **SAM 3.1** (`sam-3.1`) + **Muse Spark 1.3 vision** | SAM locates the label in the photo, Spark reads the crop, the K-number / GTIN is checked against FDA |
| Dossier narrative | **Muse Spark 1.3** ([`skills/dossier-narrative`](skills/dossier-narrative/SKILL.md)) | One-page summary drafted as claims and passed through the gate |
| Independent reviewer | **Muse Wonder 1.0** (`muse-wonder-1.0`, PDF input, 1M context) | Reads the full dossier PDF + cited reports and lists unsupported or contradicted statements before a person accepts the evidence; never edits the record |
| Cover illustration (optional, off by default) | **Muse Image 1.0** | Non-evidentiary cover art, captioned "AI-generated illustration — not evidence"; never inside evidence sections |
| Spoken questions | **Meta Voice Transcribe** (`muse-voice-transcribe-1.0`) | Ask by voice; only the transcript text reaches Muse Spark, and it goes through the same copilot and gate |
| Recording the public demo | All of the above in GitHub Actions ([`copilot-record.yml`](.github/workflows/copilot-record.yml)), key from repository secrets | The public, keyless app replays real runs instead of mocked ones |

**Standard tier only.** Never the Contributor tier, which trains on your data.
The key is read from `META_MODEL_API_KEY`, never committed or logged.

## Architecture

```mermaid
flowchart LR
    subgraph data["Data (public openFDA, no PHI)"]
        FDA["openFDA MAUDE API"] --> ING["Ingestion<br/>(pre-existing)"]
        ING --> DB[("SQLite<br/>reports + 510(k) catalog")]
    end

    subgraph changes["What changed (no LLM)"]
        DB --> MON["monitor/<br/>reports suddenly increased ·<br/>more serious than usual ·<br/>new kind of problem"]
        MON --> DIG["Digest<br/>digests/YYYY-MM-DD.md"]
    end

    subgraph copilot["Copilot (Meta Model API)"]
        Q["Analyst question"] --> SPARK["Muse Spark 1.3<br/>tool calling"]
        SPARK <--> TOOLS["13 deterministic tools<br/>signals, summary, search, report,<br/>report sources, recalls, 510(k),<br/>literature, MDR clock, compare,<br/>my device types, MHRA (UK) alerts,<br/>CAPA-need evidence pack"]
        TOOLS --> DB
        SPARK --> ANS["Structured answer<br/>sentences + claims"]
        ANS --> GATE{"Claim-level gate<br/>recompute numbers ·<br/>verbatim quotes · ids · CFR"}
        GATE -- "blocked: reasons +<br/>recomputed values" --> REPAIR["One repair turn"]
        REPAIR --> SPARK
        GATE -- "verified sentences only" --> UI["Streamlit dashboard"]
    end

    DIG --> UI
    UI --> ACT["A named person accepts / rejects<br/>CAPA-need evidence pack"]
    ACT --> AUDIT[("Hash-chained<br/>audit trail")]
    GATE --> AUDIT
```

Source: [docs/architecture.mmd](docs/architecture.mmd) · rendered:
[docs/architecture.svg](docs/architecture.svg)

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

**Adversarial test set:** [109 cases](tests/fixtures/gate/adversarial.jsonl)
(68 must block, 41 must pass): fabricated and drifted quotes, real quotes on
the wrong report, stale / inflated counts, wrong shares, fake and mismatched
K-numbers, hallucinated and superseded CFR sections, fake recall numbers and
PMIDs, real ones on the wrong product or year, wrong report-source counts,
untagged mentions (including "N hospital reports"), dates that look like counts,
and counts written in words or scientific notation ("thirty-three reports", "1e3 reports").
Result: **0 false passes, 0 false blocks**
([`tests/unit/test_gate.py`](tests/unit/test_gate.py), 126 tests).

Real verdicts on the demo database (137 MAUDE reports):

| Sentence / claim | Verdict |
|---|---|
| Quote taken from report 25675105, attributed to 25675105 | ✅ pass |
| The same quote attributed to report 25675201 | ⛔ `quote is real but belongs to 25675105, not 25675201` |
| "the AI failed to flag the hemorrhage" attributed to 25675105 | ⛔ `quote not found verbatim in 25675105` |
| "LLZ had 500 reports" | ⛔ `claimed 500, records show 121` |
| "Open a CAPA under 21 CFR 820.100" | ⛔ `superseded by QMSR (ISO 13485 clauses 8.5.2/8.5.3) on 2026-02-02` |
| "About 40% of LLZ reports were malfunctions" (no claim attached) | ⛔ `ungrounded: 40% has no share claim` |

## Quickstart (about 2 minutes, no API key)

```bash
git clone https://github.com/kondapallysaicharan63-bot/maudesignal.git
cd maudesignal
python3.12 -m venv .venv && source .venv/bin/activate
pip install -e .

# What-changed digest from the committed demo database (no network, no LLM)
maudesignal monitor --no-fetch

# Dashboard on the demo database: What changed, Copilot, Actions & Audit pages
streamlit run streamlit_app.py
```

The demo database ([`data/demo/maudesignal_demo.db`](data/demo/)) holds 137
real MAUDE reports fetched without a key from openFDA (LLZ complete for
Jul–Aug 2026; all QIH, MYN and POK reports). The exact queries are in
[`SEED_MANIFEST.json`](data/demo/SEED_MANIFEST.json). With no
`MAUDESIGNAL_DB_PATH` set and no local `data/maudesignal.db`, the dashboard
opens this database automatically. Without a key, the Copilot page replays
recorded Muse Spark runs (from [`demo/transcripts/`](demo/), once recorded)
and lets you try to fool the gate live. Set `META_MODEL_API_KEY` to ask live
questions.

**Live demo:** _[Streamlit Community Cloud link — pending deploy]_

**Deploy (Streamlit Community Cloud):** entry point `streamlit_app.py`,
dependencies from `requirements.txt`, no secrets required.

## Built during the hackathon vs pre-existing

Built during the Meta Global AI Developer Hackathon (Oct 26 – Nov 4, 2026):
the copilot, the citation gate, the daily what-changed monitor and report-source
filter, the five new dashboard pages (What changed, Copilot, Actions & Audit,
Dossier, Vision), voice questions, the evidence-pack PDF, the CAPA-need
evidence and audit tables, the live-call spend caps and the keyless demo deploy. The
openFDA pipeline below predates the event. The file-by-file list is in
[HACKATHON.md](HACKATHON.md).

## Tests

**698 unit tests pass, 77% line + branch coverage** (2026-10-28); all 21 test types
are reported in [docs/hackathon/TESTING.md](docs/hackathon/TESTING.md)
(`pytest tests/unit`; CI also runs ruff, black and `mypy --strict` on Python
3.11 and 3.12).

```bash
pip install -e ".[dev]"
pytest tests/unit
ruff check . && black --check . && mypy src/maudesignal
```

---

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
| [`safety-copilot`](skills/safety-copilot/SKILL.md) | v1.0.0 | **Hackathon.** Copilot behaviour contract: tools, structured claims, advisory-only rules |
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
| Pilot findings | [v1](docs/00_pilot_findings.md) · [v2](docs/00_pilot_findings_v2.md) · [v3](docs/00_pilot_findings_v3.md) |
| Repo conventions for AI assistants | [CLAUDE.md](CLAUDE.md) |
| Disclaimer | [DISCLAIMER.md](DISCLAIMER.md) |

## License

[MIT](LICENSE). openFDA data is public domain; see [DISCLAIMER.md](DISCLAIMER.md)
for the regulatory-use notice.

## Author

**Saicharan Kondapally**, M.S. Biomedical Engineering, San Jose State
University · [GitHub](https://github.com/kondapallysaicharan63-bot)
