# Submission form answers

Copy-paste blocks for the Meta Global AI Developer Hackathon form. Built solo by
Saicharan Kondapally. Every number below points to a file in this repo.

## Project name

```text
MaudeSignal
```

## Tagline

```text
When a complaint arrives, MaudeSignal finds the matching FDA evidence in one question, prepares PMS evidence, and keeps every fact traceable for audit.
```

## Short description (under 150 words)

```text
MaudeSignal is a postmarket surveillance aid for quality and regulatory teams at medical device makers. I built a Muse Spark 1.3 copilot that answers questions about public FDA MAUDE adverse event reports through 13 deterministic tools over stored records. A claim gate then recomputes every number and matches every quote and report id to the stored FDA record; any sentence it cannot match is withheld, with the reason. Questions can be typed or spoken (Voice Transcribe 1.0). Muse Spark also reads 510(k) summary pages, and SAM 3.1 crops device labels for it to read. An evidence pack PDF gets an independent Muse Wonder 1.0 review (findings only). A SHA-256 hash-chained audit trail records every action, and a named person makes every decision. Nothing is filed with FDA. Not medical advice. This build is not validated.
```

## Links

```text
Live app: https://maudesignal-app.vercel.app
Repo: https://github.com/kondapallysaicharan63-bot/maudesignal
Demo video: _(paste the public video link)_
MCP: https://maudesignal-api.vercel.app/mcp (6 read-only tools). Submitted to Meta's Muse Connector Program — pending review.
```

## Meta models used (all Standard tier)

```text
- Muse Spark 1.3 (muse-spark-1.3): copilot answers, the connector's ask, the evidence-pack summary, 510(k) summary and label reading
- Muse Wonder 1.0 (muse-wonder-1.0): independent review of the evidence-pack PDF, findings only
- Voice Transcribe 1.0 (muse-voice-transcribe-1.0): spoken questions to text
- SAM 3.1 (sam-3.1): finds the label in a device photo before Muse Spark reads the crop
- Muse Image 1.0 (muse-image-1.0): optional evidence-pack cover illustration, off by default, captioned "AI-generated illustration — not evidence"
All calls use the Standard tier of the Meta Model API, never the Contributor tier.
```

Code ids checked in `src/maudesignal/` (`copilot/agent.py`, `dossier/review.py`,
`copilot/voice.py`, `vision/sam.py`, `dossier/illustration.py`).

## What is live and what is recorded in the demo video

```text
- Q1 (MYN): Muse Spark 1.3 · Live. Answer: 20.0% of stored MYN reports are injuries (1 of 5). Cost shown: $0.0202.
- Q2 (LLZ trap question): Live. Muse Spark timed out, so the answer shown is the gate-checked tool facts: 121 stored LLZ reports, 2 of them injuries. The false claim in the question is not confirmed. Cost shown: $0.0181.
- Phone: Muse Spark 1.3 · Live. Cost shown: $0.0230.
- MCP: a tools/call to the connector, live.
- Label reading was cut from the video because the live read timed out.
- Source for the live clips: the screen recordings and saved API replies from the 2026-11-04 recording runs on build 5fbdde1 (GitHub Actions workflow "Record live clips", branches `record/final` and `media/*`). The costs above are the ones the app showed on screen in those runs.
Narration is my own voice cloned in ElevenLabs; it is not a live recording.
```

## Numbers and their sources

| Number | Source |
|---|---|
| LLZ, stored week Aug 25–31, 2026: 33 reports vs a weekly average of 8.75 (stored snapshot) | [`digests/2026-08-31.md`](../digests/2026-08-31.md), [`api/examples.json`](../api/examples.json) |
| MYN: 20.0% of stored reports are injuries (1 of 5) | [`demo/transcripts/20261028T204101Z-16-myn-share.json`](../demo/transcripts/20261028T204101Z-16-myn-share.json) |
| LLZ: 121 stored reports, 2 injuries | [`demo/transcripts/20261028T203740Z-06-trap.json`](../demo/transcripts/20261028T203740Z-06-trap.json), [`data/demo/SEED_MANIFEST.json`](../data/demo/SEED_MANIFEST.json) |
| 27 of 28 recorded answers fully correct. That was Claude's hand-check, not a person's. | [`docs/VALIDATION_EVIDENCE.md`](VALIDATION_EVIDENCE.md), [`docs/hackathon/HAND_CHECK.md`](hackathon/HAND_CHECK.md) |
| Keyword measurement: 11 of 121 stored LLZ reports matched; 8 of the 11 were the same problem (72.7%). Adjudicated by Claude, not a person. | [`web/public/data/keyword_measurement.json`](../web/public/data/keyword_measurement.json) |
| 13 copilot tools | [`src/maudesignal/copilot/tools.py`](../src/maudesignal/copilot/tools.py) (`TOOLS`) |
| 6 MCP tools, all read-only | [`api/mcp-manifest.json`](../api/mcp-manifest.json) |

Data dates: the demo answers come from a stored snapshot of public openFDA data; the newest
stored report was received Aug 31, 2026 ([`data/demo/SEED_MANIFEST.json`](../data/demo/SEED_MANIFEST.json)).
The live openFDA checks are separate and are dated when they run.

## Validation and review

```text
This build is not validated. The answer hand-check and the keyword measurement were done by Claude, not by a person; the Muse Wonder findings are a model's review, not a human review. Three reviewers gave feedback, in three rounds. No trial or pilot was run. In order: Srinivas Sreepada (regulatory expert), Hemadri Doma (software validation), Folarin Erogbogbo (professor; a limited desktop check, not validation). They gave feedback as individuals, in a personal capacity. Outputs are signals for a person in quality or regulatory to review; nothing is filed with FDA, and it is not medical advice.
```

## Narration

```text
Narration is my own voice cloned in ElevenLabs; it is not a live recording.
```
