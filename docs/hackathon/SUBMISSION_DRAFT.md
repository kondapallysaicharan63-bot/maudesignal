# Submission draft (NOT submitted)

Prepared for the Meta Global AI Developer Hackathon, Solo Indie Dev track.
**Charan submits; nothing here has been sent.** Every number below comes from a
recorded run or a test in this repository (sources in brackets).

## Project

- **Name:** MaudeSignal
- **One line:** A safety copilot for medical-device quality and regulatory teams:
  every morning it shows, for the device types you choose, where FDA adverse-event
  reports suddenly increased, are more serious than usual, or show a new kind of
  problem — and it only shows facts it can match to the FDA record. People make
  every decision.
- **What it is not:** medical advice, clinical decision support or an FDA-cleared
  device. It never decides reportability or whether a CAPA is needed, and does not
  define "similar devices". Demo data is public FDA data (MAUDE, recalls, 510(k))
  plus PubMed; MHRA (UK) alerts appear as labelled context only. No EU MDR or other
  regulator coverage is claimed.
- **Contributors:** Charan (GitHub `kondapallysaicharan63-bot`), solo. Built with
  Claude Code as a coding assistant.
- **Repository:** https://github.com/kondapallysaicharan63-bot/maudesignal
  (branch `hackathon-day2`; what was built during the hackathon is listed in
  `HACKATHON.md`).
- **Live demo:** https://maudesignal-4vniqswm9ptaxqtf2iawox.streamlit.app/ (keyless: recorded
  Muse runs, no live model calls unless a key is set).
- **Video:** _[link — Charan records the voiceover over the 2:52 walkthrough. Deadline: our notes say Oct 30, 11:15 PM PT; a copy of the rules says Wed Nov 4, 9 PM ET. Confirm on the official page.]_

## Meta models used

| Model | Where | Evidence |
|---|---|---|
| Muse Spark 1.3 | Copilot (13 deterministic tools, strict JSON answers checked sentence by sentence), 510(k) summary reader (two independent reads), evidence-pack summary | `demo/transcripts/`, `demo/vision/`, `demo/dossier/` |
| Muse Wonder 1.0 | Independent review of the evidence-pack PDF before a person accepts it | `demo/dossier/*-review.json` |
| Voice Transcribe | Spoken questions → the same gated copilot | `demo/transcripts/*00-voice-*.json` |
| SAM 3.1 | Finds the label in a device photo before Muse Spark reads it | `demo/vision/label-*.json`: 7 photos read, thermometer → product code FLL |

## Results (real runs, 2026-10-28)

- Gate on live answers: 63 of 65 sentences matched the FDA records on the first
  try (96.9%), 64 of 65 after one repair turn, across 28 answers including 6
  spoken (run 40764365995) [`docs/hackathon/HAND_CHECK.md`]. The one withheld
  sentence was true (a year read as a count) and the gate was fixed.
- Every answer checked by hand against the database: 27 of 28 fully correct,
  none wrong; spoken questions 6 of 6 [same]. _(Checked by Claude; Charan
  to re-check before quoting this as a person's check.)_
- Adversarial gate set: 112 made-up or tricky sentences, 0 let through wrongly, 0
  blocked wrongly [`tests/unit/test_gate.py`].
- 510(k) summaries: 5 of 5 read; two reads agree on 80–100% of fields (100% on 4 of
  5), the rest are flagged for a person [`demo/vision/`].
- Report sources vs openFDA: 0 mismatches [`docs/hackathon/SOURCE_COUNTS.md`].
- Tests: 706 unit tests, 77% coverage; Playwright on every page and theme; all 21
  test types reported, with the external ones marked PENDING
  [`docs/hackathon/TESTING.md`].
- Spend so far: about $8.35 of the $150 credit (estimates) [`docs/hackathon/BUDGET.md`].
- AI device sweep (GitHub Actions run 40836844281, 2026-10-29): FDA's AI-Enabled
  Medical Device List has 1,614 devices across 181 product codes; all 181 checked on
  openFDA for 2026-09-24 – 09-30 (the latest week) against the 4 weeks before; 6
  flagged: 3 reports suddenly increased, 2 more serious than usual, 1 new kind of
  problem; 0 errors [`docs/hackathon/AI_SWEEP.md`, `demo/sweep/ai-device-sweep.json`].
- Any device type can be checked live on the Signals page (openFDA counts, the same
  four rules; a 300-case test checks it agrees with the stored-records detector).

## Why it matters (impact)

Public figures, with their source type; dollar market sizes are left out because
published estimates disagree by almost three times.

- FDA receives over two million medical device reports a year
  ([openFDA](https://open.fda.gov/apis/device/event), FDA).
- FDA's AI-Enabled Medical Device List has 1,614 devices across 181 product codes (read
  by our sweep on 2026-10-29), and grows by about 300 a year (third-party counts:
  [ai2.work](https://ai2.work/blog/fda-ai-device-list-hits-1-524-as-radiology-dominates-but-evidence-lags),
  [IntuitionLabs](https://intuitionlabs.ai/articles/fda-ai-medical-device-tracker)).
- MAUDE has no field for an AI-specific failure such as drift; MaudeSignal adds an
  AI-failure taxonomy (peer-reviewed and industry sources say the current system is
  insufficient for AI/ML devices).
- For one AI product code (LLZ), 19,970 reports on openFDA, 99.3% filed by a manufacturer
  [`docs/hackathon/SOURCE_COUNTS.md`, our run]. The demo's stored sample is smaller (121 LLZ
  reports); figures in recorded answers name that scope.
- Who uses it: regulatory and quality (postmarket / complaint-handling) leads at makers
  of FDA-cleared AI devices, many of them small teams. MDR, CAPA and complaint-handling
  procedures are long-standing top FDA inspection findings; QMSR (in force 2 Feb 2026)
  brings ISO 13485 into Part 820.

## How it differs from existing tools

AI tools over MAUDE already exist: Basil Systems (Safety Signaling, Oct 2025), Redica
Systems (Post-Market Intelligence), DeviceWatch (MAUDE AI summaries). They describe
their output as grounded; none of their public pages shows a check per sentence.
MaudeSignal:

1. **Shows what it refused to say.** Every sentence goes through a deterministic gate
   that recomputes counts and shares, matches quotes to the cited report, and checks
   510(k) numbers and CFR sections. Blocked sentences stay visible, struck out, with the
   reason; Muse Spark gets one repair turn.
2. **Names AI failures** that MAUDE cannot.
3. **Starts from the device in hand:** SAM 3.1 + Muse Spark read a device label and open
   that device's signals.
4. **Free and open source**, runs on a laptop; every step is in a tamper-evident audit
   trail.

## Bonus prizes it fits

- **Best Agentic Use-Case:** Muse Spark plans and calls 13 deterministic tools, answers
  as structured claims, is gated, and repairs its own withheld sentences; evidence-pack
  drafting and Muse Wonder review follow, with a named person deciding.
- **Best Creative Build (Muse Wonder / Muse Image):** Muse Wonder reviews the
  evidence-pack PDF as an independent second reader.
- Most Viral / Community Vote: need Charan's post and gallery link (draft below).

## Video script v4 — 2:53, recorded by `scripts/record_walkthrough.py`

The video shows only what was built during the event: the app runs in demo mode
(`?tools=demo`: Signals, Copilot, Vision, Audit). `walkthrough-script.md` from the
recorder has the exact start times; read along with `walkthrough.mp4`.

| Starts | Screen | Voiceover (Charan) |
|---|---|---|
| 0:00 | Title card | "I'm Charan. MaudeSignal helps medical-device safety teams watch FDA data. Not medical advice: a person makes every decision." |
| 0:09 | Problem card (2M+ reports a year; 1,614 AI devices on FDA's list; 19,970 LLZ reports) | "FDA gets over two million device reports a year, and its list of AI devices has 1,614 entries. MAUDE has no field for an AI failure." |
| 0:21 | Signals: "Across FDA's AI device list" (6 of 181 flagged), LLZ increase, then MYN → "Not filed by a manufacturer" | "Monday morning. Across all 181 AI device types on FDA's list, 6 were flagged in openFDA's latest week. For the types I chose, LLZ reports suddenly increased: 33 against a normal 9. And here are the reports the manufacturer didn't file." |
| 0:43 | Copilot: spoken question "my colleague says LLZ had 50 injury reports…" → "That claim is not correct" | "I can just ask. Meta's Voice Transcribe hears the question; Muse Spark calls tools over the stored FDA records. A colleague's claim of 50 injuries? The records say otherwise." |
| 1:04 | Copilot: typed trap answer, "after a repair turn", first-pass expander with the withheld sentence | "Every sentence passes a gate that recomputes each number from the records. Here Spark itself said something the records didn't support. The gate withheld it and showed why; Spark got one repair turn, and anything still unmatched stays struck out." |
| 1:27 | Try to fool the gate: CFR 820.100 → superseded by QMSR | "You can try to fool it yourself: cite 21 CFR 820.100, and it's blocked, because QMSR replaced it this February." |
| 1:46 | Vision: two-read agreement; label camera → thermometer → product code FLL | "Muse Spark reads scanned 510(k) summaries twice and compares the reads. Point a camera at a device label: SAM finds it, Spark reads it, and you land on that device's signals. Anything unclear goes to a person." |
| 2:10 | Evidence pack + Muse Wonder review → Audit "Hash chain intact" | "It drafts a CAPA-need evidence pack, Muse Wonder reviews it independently, and every step goes into an audit trail that shows if anything was changed." |
| 2:40 | Close card + links | "AI tools that summarize MAUDE already exist. MaudeSignal shows you which of its own sentences it refused to say, and why." |

Optional: replace the first sentence with one line on why you know this problem
firsthand (the problem statement is "Build for Your World").

## X post draft (not posted — Charan posts)

> I built MaudeSignal for the Meta Global AI Developer Hackathon: a safety copilot for
> medical-device teams on public FDA data. Muse Spark answers with tools, and a gate
> recomputes every number from the FDA records. What it can't match, it refuses to
> say, and shows you why. Voice Transcribe, SAM 3.1 and Muse Wonder too.
> It checked all 181 AI device types on FDA's list against openFDA: 6 were flagged in
> the latest week. Try any device type yourself:
> Demo: https://maudesignal-4vniqswm9ptaxqtf2iawox.streamlit.app/
> Code: https://github.com/kondapallysaicharan63-bot/maudesignal
> [attach the 2:53 video]

## Not done / still needed from Charan

- External beta and expert sign-off (Harish / PSM QA).
- Making `hackathon-day2` the default branch (or an OK to merge) so the daily
  monitor cron can run.
- The final submit click.
