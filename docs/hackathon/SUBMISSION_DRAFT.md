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
- **Live demo:** _[Streamlit Cloud link — pending deploy]_ (keyless: recorded
  Muse runs, no live model calls unless a key is set).
- **Video:** _[link — to be recorded Nov 1]_

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
- Tests: 701 unit tests, 77% coverage; Playwright on every page and theme; all 21
  test types reported, with the external ones marked PENDING
  [`docs/hackathon/TESTING.md`].
- Spend so far: about $8.35 of the $150 credit (estimates) [`docs/hackathon/BUDGET.md`].

## Video script v3 (from Charan's v2, updated to the build) — 2:45 target, 3:00 cap

Changes from v2: "Overnight" → "What changed" and plain words throughout; the
"reports we didn't file" beat uses MYN/QIH (all 121 stored LLZ reports were filed
by the manufacturer); the gate line uses the real recorded numbers; the voice
line says "hears the question" (the clip is text-to-speech, not a practitioner).
Charan's v2 wording is kept everywhere else.

| Time | Screen | Voiceover (Charan) |
|---|---|---|
| 0:00–0:12 | Title → framing banner | "I'm Charan. MaudeSignal helps medical-device safety teams watch FDA data. It's a B2B tool — not medical advice — and people make every decision." |
| 0:12–0:30 | Stat card: "LLZ (imaging software): 19,970 FDA reports — 99.3% filed by manufacturers about their own devices" | "Device makers already know their own complaints — they're the ones who report them to FDA. What they can't easily see is what's happening to other companies' devices of the same type, and the few reports about their device filed by hospitals or users. That's buried in tens of thousands of reports." |
| 0:30–0:50 | **What changed** page: hero "Reports suddenly increased — LLZ, 3.77×: 33 reports this week · weekly mean 8.75 before"; then **Who filed the reports** with "Not filed by a manufacturer" for MYN / QIH (3 voluntary reports each) | "Monday morning. For the device types I chose, it compared this week with the last four. Reports suddenly increased for one type: 33 against a normal 9. And here are reports that weren't filed by the manufacturer." |
| 0:50–1:15 | **Copilot**: voice question (Heard: …) → answer with Verified pills + FDA links | "I just ask. Meta's Voice Transcribe hears the question, Muse Spark looks through FDA reports, recalls, 510(k)s and papers — and every number and quote comes back tied to the exact FDA record." |
| 1:15–1:50 | **Gate playground**: "LLZ had 50 injury reports" and "21 CFR 820.100" → Withheld with reasons | "If anything — the model or a colleague — states something the records don't support, it's withheld, with the reason: the records show 2 LLZ injury reports, and 820.100 was replaced this February. In our latest recording, 63 of 65 sentences matched the FDA records on the first try, and every answer was checked by hand against the records." |
| 1:50–2:10 | **Vision**: 510(k) summary fields Verified / Conflict; label photo → SAM box → device found | "It also reads scanned FDA documents and device labels — Muse Spark reads, SAM finds the label — and anything unclear is flagged for a person, never guessed." |
| 2:10–2:35 | **Dossier** PDF (Signal Evaluation & CAPA-need Evidence) → Wonder review → **Actions & Audit**: type name → Accept → "Hash chain intact" | "For the jump it prepares a CAPA-need evidence pack in a quality-record layout; Muse Wonder reviews it first. Whether a CAPA is needed is our decision, on our own form — I accept, and every step is logged." |
| 2:35–2:55 | Architecture, 2 lines | "Built this week on four Meta models — Muse Spark, Muse Wonder, Voice Transcribe and SAM — on my open-source MaudeSignal pipeline. Live demo and code below." |

**Before recording:** (1) voice beat: use `demo/voice/question-c.wav` ("What
changed this week? Did reports suddenly increase for any device?"), recorded as
`00-voice-c`, answered correctly; do not use `question.wav` ("What came in
overnight? Is anything worsening?" — both words are on the drop list). The
clips are ElevenLabs text-to-speech, so say "Voice Transcribe hears the
question", not that a practitioner asked it. (2) Vision beat: use `label-thermometer-1.jpg` (SAM box → HoMedics TIE-240 →
FDA product code FLL); (3) the deployed link. Check the "2 LLZ injury reports" line against the
gate playground on the day.

## Not done / still needed from Charan

- Deployed Streamlit link; external beta and expert sign-off (Harish / PSM QA).
- Making `hackathon-day2` the default branch (or an OK to merge) so the daily
  monitor cron can run.
- The final submit click.
