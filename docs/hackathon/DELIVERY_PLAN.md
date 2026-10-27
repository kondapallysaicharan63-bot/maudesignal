# DELIVERY PLAN — MaudeSignal Safety Operator (Meta AI Developer Hackathon)

One complete end-to-end plan: start → submission. This is the SPINE.
Daily workflows (plan → design → code → dependencies → verify → retro)
are written each morning from this spine — they do not replace it.

## Goal + deadline

- **Goal:** 1st place, Indie Developer track ($150K). Solo + agent team.
- **Hard deadline:** Nov 4, 9:00 PM ET (submission portal).
- **Internal target:** Nov 4, 6:00 PM PT — 3-hour buffer. Never plan to
  submit in the last hour (kickoff's explicit warning).
- **Primary artifact:** 3-minute demo video (voiceover, live clicks,
  Monday-morning story, ends on an action). Plus public repo + live link.

## Phases

### Phase 0 — Investigation + scaffold (Day 1, Oct 26) — DONE
- Audits (maudesignal pipeline real + wired; Aethel ports identified),
  workflow + checklist + skills worksheet, Discord scan, independent
  adversarial review (adopted), Meta models page verified, branch
  `hackathon-copilot` pushed to GitHub (commit 61c5813, no keys).
- Remaining from Day 1: Meta API key handoff → live smoke test +
  models list check. NOT done until the smoke test passes.

### Phase 1 — Foundation (Days 2–3, Oct 27–28)
- Day 2: Groq-seed demo dataset (≤100 records) → Meta subset comparison
  (schema-valid rates side by side) → switch default to Meta only with
  evidence. One-page claim-level gate spec. Deploy spike (Streamlit Cloud
  incl. WeasyPrint check). Written $150 budget (batched extraction, every
  call cost-logged). Agents 101 session, 12 PM ET.
- Day 3: Claim-level citation gate as code (recompute numbers, verbatim
  quote match, block/redact) + adversarial test set (30–50 cases) +
  rank-explainer + copilot retrieval. Agents 102 session, 12 PM ET.
- Phase gate: gate blocks every adversarial case and passes every valid
  case; demo dataset exists; deploy spike answered (WeasyPrint go/no-go);
  budget written. If any fails, it is fixed here — not carried into
  video week.

### Phase 2 — Agentic + surveillance (Days 4–6, Oct 29–31)
- Day 4: Tools (signal-query, deadline-check) + CAPA action + audit-first
  pattern module + conversation-memory + signal-compare. Voice-query
  starts (billing verified first). CUT: complaint-action.
- Day 5 (Oct 30) — LIGHT: Stanford/DEL meeting + college presentation.
  Background tests only; Fireworks session if free. No build commitments.
- Day 6: MHRA adapter ONLY (RSS + Warning Letters deferred) +
  deterioration-detector (new / spike / escalation) + overnight-digest +
  monitor as capped GitHub Actions cron (20 records/day) + copilot UI
  panel + Overnight page.
- Phase gate: copilot answers a question end-to-end with gate + one
  action + audit row; monitor writes a real digest; dashboard shows it.

### Phase 3 — Demo + polish (Days 7–8, Nov 1–2)
- Day 7: Video script (~2:45, captions, two takes — primary on
  stored-first path) + video draft + accuracy-sample (20 extractions
  hand-checked, one honest number) + end-to-end rehearsal.
  TreeHacks deadline tonight — applications chat owns it, NOT build time.
- Day 8: Polish + Spark Open ONLY if a grant landed (stretch —
  voice-query is already the second touchpoint) + README/HACKATHON.md.
- Phase gate: video draft exists and rehearses clean; accuracy number
  published; repo labels old vs. new correctly.

### Phase 4 — Dry run + submit (Days 9–10, Nov 3–4)
- Day 9: FULL dry run (repo link, video link, live link, submission
  form draft). Last day for submission questions.
- Day 10: Submit by 6 PM PT. X post of demo for Most Viral ($20K).
- Phase gate: submission confirmed in portal, not just "sent."

## Critical path (the chain that decides the deadline)

```
Meta key → smoke test → Groq seed → Meta subset → gate spec →
claim-level gate → tools + CAPA → deterioration + digest →
video draft → rehearsal → dry run → SUBMIT
```
Any link slipping moves everything after it. The two links with no slack
are the gate (Day 3) and the video (Day 7). Everything else has a fallback.

## Dependencies (what must exist before each phase)

| Dependency | Needed by | Status |
|---|---|---|
| Meta API key (secure handoff) | Day 1 close + Day 2 subset | PENDING from Charan |
| openFDA key (new) | Already used for data | DONE, verified live |
| GitHub branch pushed | Day 6 Actions monitor | DONE (Oct 26 evening) |
| Streamlit Cloud account | Day 2 deploy spike | Needed Day 2 |
| Voice-transcribe billing check | Day 4 voice-query | Needed Day 4 |
| Partner grants (Baseten/Modal/Fireworks) | Day 8 Spark Open ONLY | PENDING, never load-bearing |
| Baseten form confirmation | — | UNCONFIRMED (Modal + Fireworks confirmed) |

## Verification standard: prerequisites complete, everything e2e-tested, agentic

A plan counts as VERIFIED only when every prerequisite is listed with a
status AND every path that will be demoed has been tested end-to-end by
an agent — not by assertion. No exceptions.

### Prerequisites (complete list)

| # | Prerequisite | Status |
|---|---|---|
| 1 | Python 3.12 venv, repo imports, 321 tests collect | DONE Day 1 |
| 2 | GitHub branch + auth (`gh` device login + `setup-git`) | DONE Oct 26 |
| 3 | openFDA key, new, verified live (120,000/day) | DONE Oct 26 |
| 4 | Meta API key + $150 credit in account | PENDING from Charan (secure handoff) |
| 5 | Meta pricing + rate limits read (budget input) | PENDING, Day 2 |
| 6 | Streamlit Cloud account (GitHub-connected) | NEEDED Day 2 |
| 7 | MHRA official feed access (public, no key expected) | VERIFY Day 6 morning |
| 8 | Voice-transcribe billing/pricing confirmation | NEEDED Day 4 |
| 9 | Partner grants | PENDING, never load-bearing |
| 10 | Submission portal access (Cerebral Valley, approved Oct 25) | DONE |
| 11 | X account access for Day 10 demo post | NEEDED Day 10 (Charan posts) |
| 12 | Baseten $100 form confirmation | UNCONFIRMED |

### E2E layers (QA agent owns all seven; nothing demoed untested)

1. Unit/integration — pytest: 321 existing + new gate/tool/monitor
   tests. Run after EVERY code change, not just daily.
2. Gate adversarial set — 30–50 cases (Day 3). Copilot builds the gate,
   QA breaks it. Builder and breaker stay separate, deliberately.
3. Copilot loop e2e — scripted scenario: question → tool → gate →
   action → audit row exists (Day 4).
4. Monitor e2e — cron trigger → ingest → deterioration → digest →
   Overnight page shows it (Day 6).
5. Dashboard e2e — Playwright: every button clicked, every page loads.
   This is Charan's bar: everything works, everything tested (Days 6–8).
6. Deployed app e2e — public link, stored-first, NO live key, no live
   calls from the deployed app (Day 8).
7. Submission e2e — full dry run Day 9 (repo link, video link, live
   link, form draft) + Day 10 confirmation inside the portal, not just
   "sent."

### Agentic execution

- QA agent runs layers 1–7; evening automated verification posts
  results to the build chat (tests + demo path + claims cited).
- A failure loops the SAME day with the owning agent; it is never
  carried silently to the next day.
- The demo video's primary take is the stored-first path — a path that
  has already passed layers 1–6. The live fresh-check take is second,
  never the only take.

## Fallbacks (decided in advance, not improvised under pressure)

- Meta underperforms on subset → Groq stays default, with evidence;
  demo dataset already exists, no day lost.
- No partner grant lands → voice-query is the second Meta touchpoint;
  Spark Open stays a stretch goal, nothing depends on it.
- Streamlit deploy fails (WeasyPrint) → PSUR PDF generated from the
  local run for the video; dashboard shows the artifact; decided Day 2.
- Credit runs low → deployed app still works stored-first; video is
  already recorded; spend cap enforced from Day 2.
- Live call fails during recording → primary take is stored-first;
  second take attempts the live fresh-check. Never one take against a
  live API.

## Submission package (Nov 4)

- [ ] Public repo, `hackathon-copilot` work visible, HACKATHON.md current
      (old vs. new labeled; demo shows Oct 26–Nov 4 work only)
- [ ] 3-min video: Monday-morning story, ends on an action, captions
- [ ] Live product link: Streamlit Cloud, stored-first, NO live key
- [ ] Framing line present: "B2B regulatory tool, not medical advice"
- [ ] Tests green, demo path rehearsed twice, no keys anywhere in repo
- [ ] X post of demo submitted for Most Viral consideration

## Top 3 risks (from the independent review)

1. Demo-day failure (dead link, failed live call) → recorded video +
   stored-first primary path + deploy spike Day 2 + two rehearsals.
2. Trust story fails scrutiny → claim-level gate + adversarial test set
   + hand-verified accuracy number (all inside Days 3 and 7).
3. Credit burn / Meta underperformance → written Day 2 budget +
   Groq-seeded safety net + Meta proven on a subset before default.

## How this plan relates to the other docs

- WORKFLOW.md: product, stack, rules, partner usage (the reference).
- DEV_WORKFLOW.md: agent team, daily loop, owner map, requirements vs.
  flow vs. components (the machine).
- CHECKLIST.md: live status — done / in-progress / blocked / pending.
- SKILLS_WORKSHEET.md: skills inventory + adopted items.
- This plan: the spine — phases, critical path, gates, fallbacks,
  submission package. If this plan and a daily workflow disagree, this
  plan wins unless Charan decides otherwise.
