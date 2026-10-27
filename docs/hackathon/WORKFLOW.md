# META HACKATHON BUILD — WORKFLOW & TEAM OPERATING SYSTEM

**Event:** Meta Global AI Developer Hackathon, Oct 26 – Nov 4, 2026
**Track:** Indie Developer, solo (user) + Muse as the team
**Target:** 1st place Indie ($150K) — out of ~20,000 applications
**Build chat:** "Meta Hackathon Build" (separate from Main chat and Hackathon Applications chat)
**Workspace:** `~/workspace/hackathon-meta-ai/` — repo clone at `maudesignal/` on branch `hackathon-copilot` (UNPUSHED — nothing goes to GitHub without the user's approval)

## 1. What we are building (and what we are NOT)

**Product:** MaudeSignal Safety Operator — a conversational + agentic postmarket
surveillance tool for quality/regulatory professionals working on FDA-cleared
AI/ML medical devices.

- Ask in plain English → grounded answers over live FDA MAUDE signals.
- Agentic actions, not just answers: investigate a signal → open a CAPA →
  draft a PSUR section → file an alert. Every action leaves a tamper-evident
  audit trail.
- Citation hard-gate BUILT AS CODE: every factual claim verified against a
  primary source (openFDA lookups) or blocked/redacted. (The old README
  promised this; no code enforced it. The hackathon builds it for real.)
- B2B regulatory tool. NEVER medical advice, never diagnoses, never
  treatment recommendations. It refuses patient-medical-advice requests.

**We are NOT building:** a generic AI chatbot, a basic RAG app, a simple
analyzer. Those are on the official anti-projects list and would be flagged.

## 2. Tech stack (full)

| Layer | Choice | Why |
|---|---|---|
| Language | Python 3.12 | maudesignal is Python; team knows it |
| Base product | maudesignal (MIT, public) | Real 8-phase pipeline, 321 tests, real pilot numbers |
| Chat/reasoning model | `muse-spark-1.3` via Meta Model API | Latest, docs-recommended; Standard tier ONLY (never Contributor — it trains on your data) |
| API style | OpenAI-compatible client, `base_url=https://api.meta.ai/v1`, `stream=True` | Matches repo's provider pattern; streaming dodges long-call timeouts |
| Second Meta touchpoint | Muse Voice Transcribe (voice-query) — grant-free | Second Meta model in the demo, needs no grant; verify billing vs. $150 before building |
| Open-weight stretch | Muse Spark Open via partner inference (Baseten / Modal / Fireworks) | $10K Best Open Weight bonus ONLY if a grant lands; never load-bearing (adopted review change Oct 26) |
| Data (live) | openFDA device events + 510k, PubMed E-utilities, ClinicalTrials.gov v2 | Real data, current (26.5M device events, updated Oct 13, 2026) |
| Storage | SQLite via SQLAlchemy (existing 12 tables) | No new infra; demo runs on one machine |
| Dashboard | Streamlit 7-page app (existing, triggers live actions) | Demo surface; copilot panel added as new page |
| Reports | Jinja2 → WeasyPrint PDF (existing PSUR flow) | Agentic "draft a section" output |
| Tests | pytest (321 existing tests must stay green) | QA gate: nothing ships with red tests |
| Env/keys | `.env` file, gitignored, env vars only | NEVER a key in chat, code, or git |

## 3. The Meta swap (existing → Meta)

Judges score "Use of Meta AI Tooling" — so Meta must be the highlighted
provider, not a side option:

1. **Copilot (NEW):** Muse Spark 1.3 — done as scaffold (`src/maudesignal/copilot/`).
2. **Extraction pipeline (EXISTING, Groq default):** add Meta as a first-class
   provider option (`meta` in `get_provider`), keep Groq as fallback. Do NOT
   delete Groq — fallback proves engineering judgment; Meta is the default
   for the demo.
3. **Agentic tools (NEW):** tool-calling flows run on Muse Spark 1.3.
4. **Voice-query (NEW, adopted review change Oct 26):** Muse Voice
   Transcribe — speak a question → copilot answers. Grant-free second
   Meta touchpoint; verify billing against the $150 before building.
5. **Open-weight path (STRETCH, demoted Oct 26):** Spark Open via
   Baseten/Modal for the $10K bonus ONLY if partner credits land; the
   build never depends on it. Meta $150 credit is the primary fuel.
6. **What stays non-Meta:** openFDA/PubMed/ClinicalTrials data, SQLite,
   Streamlit, WeasyPrint — data and plumbing, not AI tooling. Judges care
   about the AI layer being Meta.

## 4. openFDA key update (old → new)

- Current code: key is OPTIONAL (`openfda_client.py` — no key = 240 req/min,
  1,000/day; with key = 120,000/day).
- No openFDA key email found in the 63 mailbox (checked Oct 26). The "new
  key" the user mentions is NOT in email.
- Action: user confirms whether the new key already exists (laptop `.env`?)
  or we create one (free signup at open.fda.gov, key emailed to him). Then
  update `.env` (`OPENFDA_API_KEY=...`) in the workspace copy AND his local
  copy. Old key is replaced, never committed.
- This is a Day 1/2 task: the fresh live pipeline run needs the higher limit.

## 5. Agent team — "team of four" means as many as needed

Not literally four people. Parallel agents, each owning ONE separate task,
coordinated by the main build agent (me, in the build chat):

| Agent | Owns | Runs when |
|---|---|---|
| Build lead (main) | Architecture, integration, user decisions | Always |
| Pipeline agent | Fresh end-to-end run, demo data seed, pipeline fixes | Day 1–2 |
| Copilot agent | Copilot tools, citation gate code, agentic actions | Day 2–5 |
| Aethel-port agent | Port tool-use pattern, state machines, audit-first | Day 2–4 |
| QA agent | Test suite green, verification of every claim, demo dry-runs | Daily, esp. Day 6–9 |
| Demo agent | 3-min video script, recording, submission page | Day 6–10 |

Rules: one agent per task, no two agents editing the same file at once,
every agent reports evidence (file paths, test output), never claims.
The user is the founder/decision-maker: agents propose, user approves
anything outward (push, submit, purchase, email).

## 6. Day-by-day plan (Oct 26 – Nov 4)

- **Day 1 (Oct 26, DONE in part):** env + repo + scaffold + Meta docs
  confirmed + partner accounts + credit requests. Remaining: Meta API key
  handoff (safe channel) + live smoke test + openFDA key (new key creation
  approved by user; old key not found in either mailbox).
- **Day 2 (Oct 27, REVISED by adopted review Oct 26):** seed demo
  dataset on Groq FIRST (known-good provider); run a SUBSET on Meta and
  compare schema-valid rates side by side — switch default to Meta only
  with evidence. Write the one-page citation-gate spec (claim-level:
  recompute numbers + verbatim quote match) BEFORE Day 3 builds it.
  Deploy spike: minimal app on Streamlit Cloud, including the WeasyPrint
  question (decide early, not video week). Written $150 budget: demo
  dataset capped at ≤100 records, extraction batched, every call logged
  with tokens + cost. Agents 101 session 12 PM ET — attend.
- **Day 3 (Oct 28, REVISED):** citation gate as CODE at CLAIM level —
  recompute every number from stored records, verbatim-match every quote
  to a record ID, block/redact on mismatch (not just citation-existence
  checking) + adversarial test set (30–50 cases: fake K-number, right
  K-number wrong device, hallucinated CFR, drifted quote, stale number)
  + rank-explainer inside signal-query (severity × count × recency) +
  copilot retrieval (signal store → grounded context). Agents 102
  session 12 PM ET — attend.
- **Day 4 (Oct 29, REVISED):** agentic tools (signal_query,
  deadline_check) + CAPA action + audit-first (one pattern module:
  forward-only transitions + audit-first write, applied to CAPA and
  alerts — not two full state machines) + conversation-memory
  (Streamlit session state) + signal-compare (device vs. predicate from
  existing 510k + stored signals). Voice-query STARTS (billing verified
  first). CUT per review: complaint-action — maudesignal has no
  complaint entity to attach it to.
- **Day 5 (Oct 30) — LIGHT DAY:** user has Stanford/DEL meeting with Dr.
  Razavi + a college presentation. No build commitments. Only: Fireworks
  session 12 PM ET if free, plus review. Agents run background tests only.
- **Day 6 (Oct 31, REVISED):** UK MHRA adapter ONLY (RSS + Warning
  Letters deferred — three adapters the day before video week is how
  Day 7 dies) + deterioration-detector (new-signal / spike vs. trailing
  4-week baseline / severity escalation → "3 new, 1 worsening" digest)
  + overnight-digest artifact + monitor as a GitHub Actions cron on the
  public repo (capped: max 20 new records/day; digest committed as
  artifact) + copilot UI panel in dashboard. Honesty rule: if Actions
  isn't ready, HACKATHON.md says monitor = CLI + documented schedule —
  never imply an always-on hosted service that doesn't exist.
- **Day 7 (Nov 1):** demo script + 3-min video draft; end-to-end demo path
  rehearsed. Accuracy-sample: hand-check 20 extractions field-by-field,
  report one honest number. Video story (adopted review change): one
  analyst's Monday morning — overnight digest → worst signal → why it
  ranks #1 → CAPA opened → PSUR paragraph drafted → citations verified —
  END ON AN ACTION, not the old drift chart. Script timed ~2:45, captions
  burned in, two takes (primary on stored-first path). TreeHacks deadline
  tonight — applications chat owns it, NOT build time.
- **Day 8 (Nov 2):** polish + Spark Open wired ONLY if a grant landed
  (stretch — voice-query is already the second touchpoint) +
  README/HACKATHON.md updated.
- **Day 9 (Nov 3):** full dry run, last day for submission questions;
  submission page drafted (video link, repo link, team list).
- **Day 10 (Nov 4):** submit by 6 PM PT (buffer before 9 PM ET deadline);
  final office hours; post demo on X for Most Viral ($20K) consideration.

## 6b. How the user + team work together (async model)

- The user does NOT have to stay in chat. Agents work in the background
  while he is in class, meetings, or away. He checks in when free (phone
  or desktop), reviews results, and decides. That is the whole point of
  the team: progress continues on his busy days (including Oct 30).
- Three ways to SEE the work: (1) chat summaries + files sent as
  attachments; (2) GitHub, after an approved push; (3) the live Streamlit
  dashboard — the assistant runs it and shares screenshots/recordings,
  or the user runs it locally with `./run.sh`.
- Exports on request: code files, docs, charts/screenshots, the demo
  video, the workflow itself. Anything built can be handed over as a file.
- Automation already in the loop: tests auto-run after every code change;
  every evening an automated verification (tests + demo path) posts
  results to the build chat; the daily retro is written, not remembered.

## 6c. Live extraction flow (how "press Extract → FDA → answer" works)

- Current (already built): Dashboard Ingest page → openFDA
  `device/event.json` → raw reports saved in SQLite → Extract page →
  3-Skill chain (narrative → triage → classifier) via LLM → JSON schema
  validated → audit row written → stored as extractions.
- Pilot numbers (user's "300 or 20 something"): 290 records ingested,
  43 extractions, 32.6% AI-signal rate, $0.00 LLM cost.
- Copilot design (two modes, user chooses): (a) STORED-FIRST — answers
  read from stored signals (fast, auditable, demo-safe); (b) FRESH CHECK
  — user asks about something new → live openFDA fetch for that product
  code → on-demand extraction via Meta model → answer grounded in the
  fresh records. The demo shows the fresh path live.
- Skills inventory (all 8, in `skills/`): maude-narrative-extractor
  (Active), severity-triage (Active), ai-failure-mode-classifier (Active),
  root-cause-analyzer (Active), drift-analysis-interpreter (wired via CLI
  despite its doc saying "skeleton"), trend-interpreter (Active),
  psur-report-drafter (v1.1.0, Active), regulatory-citation-verifier
  (CRITICAL, Active as a doc — NOT wired in code; the hackathon wires it
  for real). Missing, to build: fda-guidance-retriever. NEW copilot
  skills to add (ADOPTED review changes Oct 26): signal-query,
  capa-action, alert-action, deadline-check, voice-query, signal-compare,
  conversation-memory, rank-explainer (inside signal-query),
  deterioration-detector, overnight-digest (monitor output),
  claim-verifier (gate upgrade, not separate), gate-adversarial-test-set.
  CUT: complaint-action (no complaint entity exists). Every existing
  skill depends on the citation verifier — which is why building the
  gate as code unlocks the whole set.

## 6d. Daily background monitor (NEW — does not exist yet, we build it)

Verified Oct 26: maudesignal has NO scheduler — no cron, no Prefect, no
background job anywhere in `src/`. Ingest/extract/alert are manual
(CLI commands or dashboard buttons) only. Aethel had a 4-hour Prefect
cadence; maudesignal never did.

Build: a `monitor` command + scheduled daily run as a GitHub Actions
cron on the public repo (capped: max 20 new records/day so it can't eat
the credit budget): ingest new MAUDE records → extract → triage/classify
→ deterioration-detector → alert check → trend snapshot → store, writing
a dated overnight-digest artifact (new signals, worsening signals, top
alert, PSUR link) that the dashboard's new "Overnight" page shows. Demo
story: "surveillance that never sleeps — Monday morning: 1 device got
worse overnight." Fresh questions still work on demand (fresh-check
mode) alongside the daily monitor. Honesty rule: runs are public in the
repo's Actions tab; if Actions isn't ready, HACKATHON.md says monitor =
CLI + documented schedule.

## 6e. Sources: FDA-only today → multi-source (rules-clean only)

Have: FDA MAUDE events, FDA 510k catalog, PubMed, ClinicalTrials.gov.
Add (Day 6, REVISED Oct 26): UK MHRA adapter ONLY — news RSS feeds
and FDA Warning Letters deferred (three adapters the day before video
week is how Day 7 dies; MHRA alone is the defensible multi-source
bullet). All via official public feeds/APIs, with attribution.
Skip: X/Twitter monitoring — verified Oct 26: X free tier is
WRITE-ONLY (no read/search); read access starts ~$200/mo Basic. Scraping
X against its ToS would also break Meta's "violate platform policies"
ban. Skip full Reddit/Twitter sentiment pipeline (too big for 10 days;
Reddit API possible later, not now). Never scrape a site against its
ToS or robots.txt — feeds and official APIs only.

## 6f. Rules + government-guideline compliance (checked Oct 26)

- Meta bans: AI medical-advice projects; anything violating legal,
  ethical, or platform policies; code/data/assets without rights. We
  comply: B2B regulatory tool, advisory-only, official public data only.
- openFDA's own terms: data is UNVALIDATED — "Do not rely on openFDA to
  make decisions regarding medical care." Our framing matches: analysis
  aid for professionals, never a medical decision.
- Government-guideline alignment: the tool SUPPORTS vigilance workflows
  (FDA 21 CFR Part 803 MDR awareness, EU MDR vigilance concepts) but
  never makes a reportability decision and never submits a report.
  Every generated report stays stamped DRAFT — REQUIRES HUMAN REVIEW.
  No PII is displayed or stored beyond what FDA publishes; signals are
  aggregated, never individual-patient advice.
- The one thing that WOULD break the rules: ToS-violating scraping or
  presenting unverified citations as verified. Both are explicitly out.

## 7. Daily loop (every day, non-negotiable)

1. **Morning:** plan in the build chat — today's tasks, owners, done criteria.
2. **Build:** agents work in parallel; user reviews anything outward.
3. **Evening verify:** tests green? demo path still works? claims cited?
   Accuracy tracked every day: extraction schema-valid rate, citation
   verification rate, test pass rate, confidence distribution.
4. **Retro (this is the improvement loop):** what we did today, what
   slowed us down, what we automate or fix tomorrow, what the user missed
   or should know. Written into the build chat + WORKFLOW log below.
5. **Learnings (for presenting):** every retro includes "What Charan
   learned today, in presenting words" — so that by video day he can say,
   in his own words, what the AI does, how accurate it is, and what he
   built and learned. A presenter-notes doc grows from these entries.
6. **Carry-forward:** open items move to tomorrow's plan explicitly — nothing
   silently drops.

## 8. Coaching rules (how the "100 hackathons won" coach acts)

- If the user is about to do something that loses points (generic chatbot
  framing, unverified claim, medical-advice framing, demoing pre-existing
  work as new, committing a key), STOP and say so plainly, with the fix.
- If a decision is made, it stands — one advisory airing, then commit.
- Every claim in the submission must be verifiable: a test, a file, a
  live API response, or it doesn't go in.
- Demo is the primary artifact: judges watch the video first. Build the
  video's story from Day 6, not Day 10.
- Solo ≠ small. The product story is "one founder, full pipeline, real
  data, auditable actions" — that beats a 4-person chatbot every time.

## 9. Partner resources — how each is used here

- **Meta $150 credit (IN ACCOUNT):** primary fuel — Muse Spark 1.3 for
  copilot + extraction + agents. Spend-limit notification set on Billing.
- **Baseten (account + signup credit; $100 hackathon grant REQUESTED):**
  Spark Open inference (`meta-models/muse-spark-open-1026`) for the $10K
  open-weight bonus. Grant is reviewed, not guaranteed.
- **Modal (account created, workspace `kondapallysaicharan63`; $100 grant
  REQUESTED):** same open-weight path, alternative to Baseten. Selection
  pending — no grant email yet.
- **Fireworks (account created; $25 grant REQUESTED):** same open-weight
  path, smallest grant. Selection pending — no grant email yet.
- Rule: partner credits are BACKUP for the open-weight story. The build
  never depends on a grant that hasn't landed. (Adopted Oct 26: Spark
  Open is a stretch goal; voice-query is the grant-free second Meta
  touchpoint.)

## 10. Workspace mechanics — how the user works with this

- There is NO virtual desktop the user logs into. The "environment" is
  the assistant's workspace computer: repo, venv, code, tests, docs.
- The user works THROUGH CHAT: asks, decides, reviews, approves. The
  assistant shows results, file paths, and (when asked) file contents.
- If the user wants to run code on his own Mac, he clones the same repo
  and checks out the same branch — but NOTHING is pushed to GitHub until
  he explicitly approves a push.
- Outward actions (push, submit, purchase, email, registration) always
  need his explicit word. Everything else, the team just does.

## 11. Submission checklist (Nov 4)

- [ ] Public repo, `hackathon-copilot` work merged/visible, HACKATHON.md current
- [ ] 3-min demo video: ONLY Oct 26–Nov 4 work highlighted, pre-existing base labeled
- [ ] Submission page: video link works, repo link works, all contributors listed (solo)
- [ ] Framing line present: "B2B regulatory tool, not medical advice"
- [ ] Tests green, demo path rehearsed twice, no keys anywhere in repo
- [ ] Deployed public app runs stored-first with NO live key (live Meta
      calls only in the recorded video and the local run)
- [ ] Video tells the Monday-morning story and ends on an action, not
      the old drift chart; only Oct 26–Nov 4 work highlighted
- [ ] X post of demo submitted for Most Viral consideration

## Retro log (append daily)

- **Oct 26:** env + scaffold + docs + partner accounts/requests done. Audits
  (maudesignal + Aethel) done. Workflow + build chat created. Friday Oct 30
  marked LIGHT (Razavi meeting + college presentation). Async model agreed:
  user need not stay in chat; agents work in background. Skills inventoried
  (8 + 2 to build). Still open: Meta API key handoff, live smoke test,
  openFDA new-key creation (approved; old key in neither mailbox),
  Discord sign-in for kickoff video summary.
- **Oct 26 (evening):** independent adversarial review adopted by
  Charan. Claim-level gate + adversarial test set + accuracy-sample;
  deterioration-detector + overnight-digest; voice-query as grant-free
  second Meta touchpoint; Spark Open → stretch; complaint-action cut;
  Day 6 sources → MHRA only; Day 2 reordered (Groq-seed first, gate
  spec, deploy spike, $150 budget); monitor → GitHub Actions cron
  (capped); video = Monday-morning story ending on an action; deployed
  app stored-first, no key. Recorded in SKILLS_WORKSHEET §F + CHECKLIST
  (now ADOPTED).
