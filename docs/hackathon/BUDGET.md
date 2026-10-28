# Meta API budget: the $150 credit

The $150 Meta Model API credit pays for every live call in this project. This
page covers what each call costs, the guards in code, what has been spent, and
how the rest is split.

**Rule:** every number on this page is either a price copied from the code
(which cites Meta's pricing pages), arithmetic on those prices, or a cost
printed by a real run. Amounts marked **PROPOSED** are spending decisions for
Charan to confirm. They are not measurements.

## 1. Prices used in code (Standard tier only; Contributor tier is refused)

| Model | Price | Where in code | Source |
|---|---|---|---|
| `muse-spark-1.3` (copilot, 510(k) reader, label reader, dossier narrative) | $1.25 per 1M input tokens, $4.25 per 1M output tokens | `copilot/meta_provider.py` `SPARK_USD_PER_M_INPUT/OUTPUT` | Meta pricing page, read 2026-10-27 |
| `muse-wonder-1.0` (dossier reviewer) | $4.00 / $20.00 per 1M input / output tokens | `dossier/review.py` `WONDER_USD_PER_M_*` | same page |
| `muse-voice-transcribe-1.0` | $0.18 per audio hour, whole seconds rounded down; failed requests and 429s not billed | `copilot/voice.py` `VOICE_USD_PER_AUDIO_HOUR` | https://dev.meta.ai/docs/speech-to-text (see `VOICE_API_NOTES.md`) |
| `sam-3.1` (label camera) | $2.50 per 1,000 images | `vision/sam.py` `SAM_USD_PER_IMAGE` | https://dev.meta.ai/docs/pricing-rate-limits |
| `muse-image-1.0` (optional cover, off by default) | $0.01 per image | `dossier/illustration.py` `USD_PER_IMAGE` | same page |

All of these are estimates from list prices. The Meta console balance is the
ground truth. Charan reads it, because it cannot be seen from the build
environment.

## 2. Output-cost ceiling per call (arithmetic on code limits, not measured)

Output tokens are capped by `max_tokens` in code, so the output side of each call has a hard ceiling:

| Call | `max_tokens` (code) | Output-cost ceiling |
|---|---|---|
| Copilot turn (`copilot/agent.py`) | 8,000 (was 1,500, then 4,000) | 8,000 × $4.25 / 1M = $0.0340 |
| 510(k) / label read (`vision/reader.py`, `vision/spark.py`) | 16,000 (was 4,096) | $0.0680 |
| Dossier narrative (`dossier/narrative.py`) | 16,000 (was 1,200, then 4,000) | $0.0680 |
| Dossier reviewer, Wonder (`dossier/review.py`) | 24,000 (was 4,000, then 16,000) | 24,000 × $20 / 1M = $0.4800 |

The caps were raised after the 2026-10-28 recordings (section 4): Muse Spark and
Muse Wonder count reasoning tokens toward `max_tokens`, and at the old caps the
narrative and the review used every token and returned no text; in the third
recording 4 copilot calls still stopped at 4,000. A cap is a ceiling: only the
tokens actually generated are paid for (the third recording averaged $0.0458 per
answer).

Input tokens have no ceiling in code (tool results and page images vary), so
the real per-answer cost comes from the recorded runs (section 4).

## 3. Guards in code

- **Recording runs**: the Record workflow runs only when `demo/RECORD_REQUEST`
  changes on a push. Every answer prints its cost, every transcript stores its
  token usage, and `scripts/hand_check.py` totals the recorded cost.
- **Public app** (`copilot/spend.py`, `dashboard/spend_ui.py`): every live call
  goes through a per-session guard. There are no accounts; a browser session is one user.

  | Cap | Default | Env var to tune it |
  |---|---|---|
  | Spend per browser session | $1.00 | `MAUDESIGNAL_CAP_SESSION_USD` |
  | Meta calls per browser session | 20 | `MAUDESIGNAL_CAP_SESSION_CALLS` |
  | Spend per UTC day, all sessions | $10.00 | `MAUDESIGNAL_CAP_DAILY_USD` |

  The guard checks before each call. A cap hit makes no Meta call and shows the
  recorded demo answer instead. Every call writes a `meta.usage` audit entry,
  and the first refusal writes `meta.cap_hit`. The sidebar shows what remains.
  The call that is running when a cap is crossed can overshoot by its own cost
  (bounded as in section 2).
- **Deployed app without a key**: it makes no live calls at all and costs $0.
  That is the default public setup.

## 4. Spend ledger (measured)

| Date (UTC) | Run | What ran | Estimated cost | Evidence |
|---|---|---|---|---|
| 2026-10-27 | Meta smoke test, run 40560284301 (3 attempts) | `models.list` + one streamed answer | not logged (the smoke test prints no token usage) | Actions log |
| 2026-10-27 | Record live Meta runs, run 40560284763 | copilot and dossier calls returned 404 (old key); 510(k) reader stopped before any model call (FDA refused the PDFs) | vision step printed `total estimated cost $0.0000`; copilot step printed none (the run stopped at the 404) | Actions log |
| 2026-10-28 | Record live Meta runs, run 40616911177 | 20 typed questions + 1 voice question (21 answers) | $0.7416 (sum of the transcripts' usage; the voice answer is $0.0359, of which transcription $0.000150) | `HAND_CHECK.md`, Actions log |
| 2026-10-28 | same run | 510(k) reader: K261677 read and checked; 4 others failed (no valid JSON) | $0.0662 logged for K261677; the 4 failed reads are **not logged** (the error is raised before the cost is counted) | Actions log |
| 2026-10-28 | same run | dossier narrative (Muse Spark) | 4,097 in / 1,200 out tokens → $0.0102 (arithmetic on the recorded tokens) | `demo/dossier/*-narrative.json` |
| 2026-10-28 | same run | dossier review (Muse Wonder) | $0.1927 (28,166 in / 4,000 out); output not parseable | `demo/dossier/*-review.json` |
| | **run total logged** | | **$1.0107**, plus the unlogged failed 510(k) reads; check the console balance | |
| 2026-10-28 | Record live Meta runs, run 40638240641 | 20 typed questions + 1 voice question (21 answers) | $1.0695 (sum of the transcripts' usage) | `HAND_CHECK.md`, Actions log |
| 2026-10-28 | same run | 510(k) reader: K031779 and K261677 read; 3 failed at the 4096-token cap | $0.1265 logged for the two reads; the 3 failed reads are **not logged** | Actions log |
| 2026-10-28 | same run | dossier narrative (Muse Spark) | 4,202 in / 4,000 out tokens → $0.0222 (arithmetic on the recorded tokens; no text returned) | `demo/dossier/*-narrative.json` |
| 2026-10-28 | same run | dossier review (Muse Wonder) | $0.4248 (28,261 in / 15,588 out); 4 findings | `demo/dossier/*-review.json`, Actions log |
| | **run total logged** | | **$1.6430**, plus the unlogged failed 510(k) reads | |
| 2026-10-28 | Record live Meta runs, run 40683010813 | 22 typed + 2 voice questions (24 answers) | $1.0988 (sum of the transcripts' usage) | `HAND_CHECK.md` |
| 2026-10-28 | same run | 510(k) reader: all 5 read | $0.4347 | Actions log |
| 2026-10-28 | same run | dossier narrative (Muse Spark) | 4,242 in / 6,995 out tokens → $0.0350 | `demo/dossier/*-narrative.json` |
| 2026-10-28 | same run | dossier review (Muse Wonder) | $0.2650 (28,303 in / 7,589 out); 0 findings | `demo/dossier/*-review.json` |
| | **run total logged** | | **$1.8335** | |
| 2026-10-28 | Record live Meta runs, run 40692882168 | 22 typed + 2 voice questions (24 answers) | $1.0372 (sum of the transcripts' usage) | `HAND_CHECK.md` |
| 2026-10-28 | same run | 510(k) reader: all 5 read | $0.3908 (sum of the five results' `cost_usd`) | `demo/vision/510k-*.json` |
| 2026-10-28 | same run | dossier narrative (Muse Spark) | 4,365 in / 8,266 out tokens → $0.0406 | `demo/dossier/*-narrative.json` |
| 2026-10-28 | same run | dossier review (Muse Wonder) | $0.2465 (28,303 in / 6,662 out); 0 findings | `demo/dossier/*-review.json` |
| | **run total logged** | | **$1.7151** | |
| | **logged so far, all runs** | | **$6.2023** of $150 (estimates from token counts × list prices; check the console balance) | |

## 5. Allocation of the $150 (PROPOSED: Charan to confirm)

| Bucket | Proposed cap | How it is held |
|---|---|---|
| Recording runs (demo transcripts, vision, dossier) until the Nov 1 video | to be set after the first measured run: (measured cost per run) × planned re-runs | push-gated workflow |
| Public live demo, if a key is ever added to the deployed app | at most `MAUDESIGNAL_CAP_DAILY_USD` per day (default $10) × days live | spend guard |
| Development and tuning calls | from the same measured per-answer cost | manual |
| Reserve for video day (Nov 1) and submission (Nov 4) | keep a reserve, size set after the first measured run | not spent without Charan's yes |

Worst case for the public app at the default caps: $10 per day. Lower
`MAUDESIGNAL_CAP_DAILY_USD` before adding a key to the deployed app if the
measured per-answer cost suggests less is enough.

## 6. When to stop and check

- After each Record run, add a row to section 4 and compare it with the console balance.
- If the console balance and the logged estimates disagree by more than the
  smallest recorded run cost, stop live runs until the difference is explained.
