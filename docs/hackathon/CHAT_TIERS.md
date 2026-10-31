# Chat answer tiers

HACKATHON-BUILT — Meta Global AI Developer Hackathon (Oct 26 – Nov 4, 2026).

The website chat (`POST /v1/live/ask`) and the connector's `ask` tool (REST `/v1/tools/ask`
and MCP `tools/call ask`) check four kinds of answer in order. Only the last one calls a model.
Every response says which tier answered (`tier`) and what it cost (`cost_usd`).

| Tier | When | Model | Cost | Badge in the web chat | Daily live limit | Spend ledger (`callcap`) |
|---|---|---|---|---|---|---|
| 1 `canned` | greetings (English, Hindi, Telugu, typos), thanks, bye, who are you, what can you do, help, "is this medical advice", where the data comes from, privacy, a request for medical advice, "is X safe", off-topic | none | $0 | No FDA facts in this message | not used | not touched |
| 2 `direct` | one simple intent: alerts, what changed (this week, for X), check product code X, recalls for X, show report N, my devices, AI sweep, who filed X reports, 510(k) for a K-number | none | $0 | Direct FDA lookup — no AI | not used | not touched |
| 3 `cache` | the same normalised question (and chosen product code) answered live in the last 6 hours | none | $0 | Answered earlier today | not used | not touched |
| 4 `live` | everything else: open questions, comparisons, "why", follow-ups that need earlier turns, voice, photo | Muse Spark | real cost shown | Live answer (or Recorded run) | one used | every call reserved first, as before |

Code: router `src/maudesignal/connector/tiers.py`, tier 2 `direct.py`, tier 3
`answer_cache.py`, wiring `chat.py` (connector) and `live.py` (website). Switch: the env var
`MAUDESIGNAL_CHAT_TIERS=0` sends every typed question to tier 4 as before.

## Tier 1: canned

Fixed text in `tiers.py` (not a model prompt), with four suggestion chips. A request for medical
advice gets "I can't give medical advice — please ask a clinician." No canned text contains a
number, a fact about a device, or the words approved, validated, compliant, safe or unsafe (a
test checks this). A greeting before a real question ("hi, what changed for LLZ?") is dropped
and the question is routed on its own.

**Medical advice vs regulatory questions.** The fixed medical reply is used only when the
message asks something clinical (should I take or stop, diagnose, dose, safe or dangerous, ...)
about a body or a patient (I, me, my, kids, pacemaker, MRI, rash, ...) and names no product code
and no regulatory word (CAPA, recall, report, MAUDE, MDR, signal, complaint, spike, 510(k), ...).
"Should we start a CAPA for LLZ?" or "Should I worry about the LLZ spike?" go to Muse Spark;
"Is it safe for me to get an MRI with my pacemaker?" gets the medical reply. "Is X safe" with a
regulatory word ("is it safe to close the CAPA") also goes to Muse Spark.

The privacy reply says that greetings and simple lookups use no model, that when live answers
are on an open question is sent to Meta's Muse Spark, and that MaudeSignal keeps only a hash of
the question (the same as /privacy).

## Tier 2: direct lookups through the claim gate

The router finds one intent and at most one product code, report id or K-number. The answer is
a fixed template filled from the existing read-only tools (`copilot.tools.report_sources`,
`device_510k`, `my_device_types`, the stored digest, the stored recalls and reports, the stored
AI-device sweep). Each template sentence carries the gate claims for what it states, and the
same claim gate that checks Muse Spark (`gate.verify_sentence`) checks it against the stored
records: a count, recall count, report id, recall number or K-number that does not recompute,
or a number with no claim, holds the sentence back. The LLZ sentence carries its weekly average
together with the baseline count it comes from ("8.75 ... (35 reports)"), so the average is
checked too. The quoted LLZ figures (33 reports, weekly average 8.75) are the stored ones,
unchanged.

A question with a qualifier the templates do not apply goes to Muse Spark instead of getting
a template that answers something else: a year or month, since / before / after / between /
from, last or past year / quarter / month / week / N days, class I / II / III, per or by
manufacturer / firm / year / status, a break-down, open or terminated recalls, most / top /
only / except, compare / vs, and "how many ... are / were ...". "How many LLZ recalls are class
I?", "LLZ recalls in 2019" and "what changed for LLZ last year" are tier 4.

What tier 2 never does: state live openFDA numbers (they cannot be recomputed from stored
records). A product code outside the stored snapshot gets "not in the stored snapshot" and a
button that opens Check any device type. An unknown code one letter away from a known one gets
"Did you mean …?" (the connector's distance-1 helper, `guidance.suggest_codes`); the suggestion
is a chip, never applied. A follow-up with no subject after earlier turns ("which were not filed
by the manufacturer?") goes to tier 4, which has the context.

## Tier 3: six-hour cache

Only live Muse Spark answers with at least one gate-passed, linked sentence are kept (recorded,
free and fully held-back answers are not). The key is a SHA-256 of the data version (snapshot
dates, digest week and sweep run, `ConnectorData.version`), the normalised question (lower
case, punctuation and extra spaces removed) and the chosen product code; the question text is
never stored. The connector's public demo key never receives a cached live answer. Storage is the connector's
existing cache: Upstash Redis when configured, this instance's memory otherwise. Any read,
parse or write error is a miss. A question that points back to earlier turns ("why did that
happen?") is not looked up or stored when history is sent.

## Tier 4: Muse Spark, cheaper

* **Shorter system prompt**: the block between the `live-compact-prompt` markers in
  `skills/safety-copilot/SKILL.md` (Skill 1.3.2), about 1.7 KB instead of about 9 KB. Other
  callers (recordings, Streamlit) keep the full prompt; the block is removed from it.
* **Reasoning effort** `low`; `medium` only for comparisons (compare, versus, vs, difference,
  between, side by side).
* **Output cap** `max_tokens` 3,000 (5,000 for comparisons), down from 8,000. Reasoning tokens
  count toward it; with the old default effort a 4,000 cap cut answers off (BUDGET.md), so
  `length_stops` should be watched in the first live runs. Not measured here (no paid calls).
* **At most 2 tool rounds**; each tool result sent back to the model is cut to 6,000 characters.
* **Repair turn only when the gate blocked something** (unchanged), and it now asks for the
  corrected JSON directly, without another tool round.
* **Prompt caching: not used.** The Meta Model API notes in this repository
  (`copilot/meta_provider.py`, `BUDGET.md`, `VOICE_API_NOTES.md`, `VISION_API_NOTES.md`)
  document no prompt-caching parameter and no cached-token price, and Meta's documentation was
  not reachable from this build environment to check. Nothing is enabled or assumed.
* **The real cost of each answer** is shown under it ("Cost of this answer: $…", $0.0000 with
  "no model call" for tiers 1 to 3).

The $3/day global cap and the per-call reservation ledger (`callcap.py`) are unchanged and apply
to every tier-4 model call exactly as before. Tiers 1 to 3 never call it (tests check that no
ledger entry is written).

## Gate presentation

A sentence that passed the gate with no claims and states no fact (a greeting, "Here is what I
found.", "A named human must review this.") is no longer listed as "held back"; it is simply not
shown (`ask.is_connective`). Anything with a digit, longer than a short transition, or naming FDA data
(a device, recall, report, problem, failure, product code ...) is not connective, so "Based on
the records, the device was recalled for software failure." is still listed as held back. When the model wrote no factual
sentence at all, the answer says "I have nothing checked to add to that …" instead of "I could
not verify an answer". Numbers and FDA facts go through the claim gate unchanged.

## Cost per tier: before and after

Method: `scripts/chat_tier_costs.py` routes a fixed, hand-picked sample of 20 questions with
the real router over the stored demo data (no model, no network). Before: every question is
priced at the recorded average typed-ask cost, **$0.048**. After: tiers 1 to 3 are $0, and each
tier-4 question is still priced at $0.048, which is an upper bound because the cheaper tier-4
settings above were not measured (that needs paid calls). No other cost number is used. The
sample is not measured traffic, and it has no qualified ("in 2019", "class I") or regulatory
"should we" questions, which now go to tier 4; with a different mix the after-average is
$0.048 × (share of questions that reach tier 4).

<!-- cost-table:start -->
Sample: 20 questions (`scripts/chat_tier_costs.py`). Before: every question goes to Muse Spark at the recorded average typed-ask cost of $0.048. After: tiers 1 to 3 cost $0; a tier-4 question is still priced at $0.048 (upper bound: the cheaper tier-4 settings are not measured, which would need paid calls).

| # | Question | Tier | Why | Before | After |
|---|---|---|---|---|---|
| 1 | hi | canned | greeting | $0.048 | $0.000 |
| 2 | namaste | canned | greeting | $0.048 | $0.000 |
| 3 | What can you do? | canned | capabilities | $0.048 | $0.000 |
| 4 | What changed this week? | direct | what_changed | $0.048 | $0.000 |
| 5 | What changed this week for LLZ? | direct | what_changed | $0.048 | $0.000 |
| 6 | Check product code QIH | direct | check_code | $0.048 | $0.000 |
| 7 | Recalls for LLZ | direct | recalls | $0.048 | $0.000 |
| 8 | Who filed MYN reports? | direct | who_filed | $0.048 | $0.000 |
| 9 | show report 19864749 | direct | report | $0.048 | $0.000 |
| 10 | 510(k) for K261677 | direct | k510 | $0.048 | $0.000 |
| 11 | Show the AI device sweep | direct | ai_sweep | $0.048 | $0.000 |
| 12 | Is this medical advice? | canned | is_medical_advice | $0.048 | $0.000 |
| 13 | thanks | canned | thanks | $0.048 | $0.000 |
| 14 | Why did LLZ reports increase this week? | live | open_question | $0.048 | $0.048 |
| 15 | Compare LLZ and QIH | live | open_question | $0.048 | $0.048 |
| 16 | What kinds of problems do the LLZ reports describe? | live | open_question | $0.048 | $0.048 |
| 17 | Which recalls are related to the LLZ increase? | live | open_question | $0.048 | $0.048 |
| 18 | why did LLZ reports increase this week | cache | same question earlier | $0.048 | $0.000 |
| 19 | Are there PubMed papers on AI triage failures? | live | open_question | $0.048 | $0.048 |
| 20 | what changed for LLX | direct | did_you_mean | $0.048 | $0.000 |

| Tier | Questions | Before | After |
|---|---|---|---|
| canned | 5 | $0.240 | $0.000 |
| direct | 9 | $0.432 | $0.000 |
| cache | 1 | $0.048 | $0.000 |
| live | 5 | $0.240 | $0.240 |
| **total** | **20** | **$0.960** | **$0.240** |

Average per question: before **$0.0480**, after **$0.0120** (upper bound; target $0.02).
<!-- cost-table:end -->

## Tests (all offline)

* `tests/unit/test_chat_tiers_router.py`: 90+ phrasings (greetings with typos, Hindi and Telugu
  in Latin and native script, thanks, help, medical advice, off-topic, every direct intent, and
  open questions that must reach tier 4), did-you-mean, follow-ups, normalisation.
* `tests/unit/test_chat_tiers_direct.py`: every direct answer passes the gate and links every
  number; a changed digest number or a wrong average is held back; unstored ids are never
  stated.
* `tests/unit/test_chat_tiers_cache.py`: hit within 6 h, miss after, normalisation, product
  code in the key, no question text stored, every store error is a miss.
* `tests/unit/test_chat_tiers_routes.py`: the live route, REST and MCP: tier and cost per
  answer, tiers 1 to 3 use no daily limit and write no ledger entry, tier 4 uses the compact
  prompt, low effort and two tool rounds, the cache hit is free.
* `tests/unit/test_chat_tier_costs.py`: the table above is what the script prints.
* `tests/unit/test_chat_tiers_review.py`: regulatory "should" questions are not medical,
  first-person medical questions are, qualified questions reach tier 4, factual sentences stay
  held back, the cache key carries the data version, held-back answers are not cached, the demo
  key gets no cached live answer, the privacy reply.
* Web: `web/src/live/*.test.ts(x)` (badge, chips, cost line); Playwright scenarios in
  `scripts/release/e2e_web.py` (greeting, direct lookup, live question with a mocked route).
