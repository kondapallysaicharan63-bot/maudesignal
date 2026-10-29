# Voice questions for the copilot demo

Spoken questions are sent to Meta Voice Transcribe; the transcript ("Heard: …") goes
to the same Muse Spark copilot and claim gate as a typed question. Recorded runs are in
`demo/transcripts/*-00-voice-*.json` with their hash-chained audit trails
(`audit-00-voice-*.json`).

## Charan's own voice (3 takes, public with consent)

Charan Kondapally recorded these questions himself and **consents to these three
recordings of his voice being public** in this repository (decision of 2026-10-29).
The other four takes he recorded were removed from the branch.

| File | Question | Heard by Voice Transcribe (recorded 2026-10-29) | Product code | Gate (final) |
|---|---|---|---|---|
| `question-take1.wav` | Q1: What changed this week for LLZ? Did reports suddenly increase? | "What changed this week for LLG? devices? devices? The report suddenly increases?" | heard LLG → used LLZ (corrected, shown on screen) | 4 of 4 sentences matched |
| `question-take6.wav` | Q2: Which reports about LLZ devices were not filed by a manufacturer? | "which report about LLZ device were not filled by manufacturer?" | LLZ (heard correctly) | 1 of 1 |
| `question-take4.wav` | Q3: My colleague says LLZ had 50 injury reports last week. Is it true? | "My colleague says LLC had 50 injury reported last week. week. Is it true?" | heard LLC → used LLZ (corrected, shown on screen) | 3 of 3 |

How each take was chosen, from the Voice Transcribe results of GitHub Actions run
40965201781: Q1 had two takes; the other was heard as "allergy device" and named no
product code. Q2 had three; take 6 is the only one heard with the right code and a clean
sentence. Q3 had two; the other was heard as "15 injuries", which changes the claim the
question tests, while take 4 kept "50".

Product-code correction (`src/maudesignal/copilot/product_code.py`) only replaces a
heard code that is one letter away from exactly one stored code; the screen shows
heard → suggested → used, and ties or distant codes are never changed.

## Text-to-speech samples (not a person)

`question-a.wav` … `question-e.wav` are ElevenLabs text-to-speech samples ("Adam"), not
a real practitioner. The early clip `question.wav` (wording the product no longer uses)
was removed so recording runs cannot recreate it; its old transcript `00-voice-main` is
kept for the audit trail but is never shown.
