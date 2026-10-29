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
| `question-take1.wav` | Q1: What changed this week for LLZ? Did reports suddenly increase? | "What changed this week for LLG? devices? devices? The report suddenly increases?" | Heard LLG; asked about LLZ (shown on screen) | 4 of 4 sentences matched |
| `question-take6.wav` | Q2: Which reports about LLZ devices were not filed by a manufacturer? | "which report about LLZ device were not filled by manufacturer?" | LLZ (heard correctly) | 1 of 1 |
| `question-take4.wav` | Q3: My colleague says LLZ had 50 injury reports last week. Is it true? | "My colleague says LLC had 50 injury reported last week. week. Is it true?" | Heard LLC; asked about LLZ (shown on screen) | 3 of 3 |

How each take was chosen, from the Voice Transcribe results of GitHub Actions run
40965201781: Q1 had two takes; the other was heard as "allergy device" and named no
product code. Q2 had three; take 6 is the only one heard with the right code and a clean
sentence. Q3 had two; the other was heard as "15 injuries", which changes the claim the
question tests, while take 4 kept "50".

Product-code correction (`src/maudesignal/copilot/product_code.py`): only a three-letter
code written in capitals is a candidate, so ordinary words ("any", "the", "all", "new",
"Jan", "pos") are never touched. A code that is itself known (stored in the demo database
or on the seed list, for example LLN) is never changed. An unknown code is replaced only
when it is one letter from exactly one code that has records on file. In these recorded
runs the correction was applied and the screen states it ("Heard LLG; asked about LLZ
(one letter different; the only close code on file)."). In live mode with the mic nothing
is applied automatically: the page shows "Heard LLG. Did you mean LLZ?" with the buttons
"Ask about LLZ" and "Ask as heard (LLG)", and the question is sent only after a click.

Scope of the stored answers: Q2's answer says all 121 stored LLZ reports were filed by a
manufacturer. That is the stored demo sample of 121 LLZ reports, not openFDA as a whole
(19,970 LLZ reports, 99.3% manufacturer-filed, `docs/hackathon/SOURCE_COUNTS.md`).

## Text-to-speech samples (not a person)

`question-a.wav` … `question-e.wav` are ElevenLabs text-to-speech samples ("Adam"), not
a real practitioner. The early clip `question.wav` (wording the product no longer uses)
was removed so recording runs cannot recreate it; its old transcript `00-voice-main` is
kept for the audit trail but is never shown.

## What the Copilot list shows and hides

Shown: the three recordings above (`00-voice-take1`, `-take4`, `-take6`) and the
text-to-speech question `00-voice-d` (no recording of Charan's covers it).

Hidden from the Copilot list, the Signals answers and the quota fallback (one list,
`DISPLAY_EXCLUDED_LABELS` in `src/maudesignal/dashboard/copilot_pages.py`; the files stay
on disk and their hash chains are still verified on the Audit page, which says so):

| Label | Why hidden |
|---|---|
| `00-voice-main` | early test whose question uses wording the product no longer uses |
| `00-voice-a`, `00-voice-b` | text-to-speech greetings that ask nothing |
| `00-voice-c` | text-to-speech question superseded by `take1` |
| `00-voice-e` | text-to-speech question superseded by `take4` |
