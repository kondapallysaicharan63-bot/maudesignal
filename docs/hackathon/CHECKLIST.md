# BUILD CHECKLIST — Meta Hackathon (updated daily; missed items roll forward)

**Overall status (Oct 26, Day 1): ON TRACK.** Everything in our control is
done. Two items wait on the user (see Blocked). Nothing is late — Day 1
ends tonight; Day 2 starts Oct 27.

**How old vs new work is differentiated (judges' rule):**
- OLD (pre-existing, NOT claimed as hackathon work): the maudesignal
  pipeline, Skills, dashboard, tests, PRD suite in `docs/`, pilot numbers.
- NEW (Oct 26–Nov 4 only, the submission): everything under
  `src/maudesignal/copilot/` + `HACKATHON.md` + demo video + submission
  write-up, all on branch `hackathon-copilot`. Git history proves dates.
- Rule: new code lives in NEW files. Old files are edited only when
  unavoidable (e.g. registering the Meta provider), and every such edit
  is listed in HACKATHON.md. Old providers (Groq, Gemini) are KEPT as
  fallbacks, not deleted — deleting working code adds risk, not points.
  Meta is the DEFAULT and the demo's featured provider.

## DONE (with evidence)

- [x] Repo cloned, branch `hackathon-copilot` (unpushed — no GitHub push yet)
- [x] Python venv installed; maudesignal + copilot import; 321 tests collect
- [x] Copilot scaffold: `meta_provider.py` (Meta API + streaming),
      `copilot.py` (SafetyCopilot), `test_meta_connection.py`, `.env.example`
- [x] Meta docs confirmed: base `https://api.meta.ai/v1`, model
      `muse-spark-1.3`, Standard tier only (never Contributor)
- [x] Meta $150 credit IN ACCOUNT (green banner, Oct 26)
- [x] Partner accounts: Baseten, Modal (`kondapallysaicharan63`),
      Fireworks — all created; $100/$100/$25 grants REQUESTED, pending
- [x] Audits: maudesignal layer-by-layer + Aethel port audit (both filed)
- [x] openFDA NEW key: signup done, newest key wired into gitignored
      `.env`, verified live (HTTP 200, 26.5M events, updated Oct 13, 2026)
- [x] Workflow + build chat created; Friday Oct 30 marked LIGHT
      (Razavi meeting + college presentation)
- [x] Rules checked: Meta bans, openFDA disclaimer, advisory-only +
      human-review framing; X/Twitter skipped (free tier write-only)
- [x] Skills inventoried: 8 existing + fda-guidance-retriever missing +
      4 new copilot skills to add
- [x] Daily monitor gap confirmed: NO scheduler exists in maudesignal
      today — building it is a headline feature
- [x] PRD alignment checked: workflow follows the hackathon PRD
      (copilot + citation gate + two Meta models + 4-step demo); additions
      since the PRD (daily monitor, MHRA, RSS/Warning Letters, Aethel
      ports) fit the PRD's vision and are listed as extensions
- [x] Kickoff recording found + summarized (Vimeo, 23 min, Oct 26);
      livestream page still has no replay embedded
- [x] Competitive scan done: agents dominate (sales, voice, shopping,
      physical MCP, home design, lending, health privacy); judging
      emphasis = impact first, then Meta tooling, depth, demo

## IN PROGRESS

- [ ] Baseten $100 grant form — submission UNCONFIRMED (Modal +
      Fireworks confirmed; Baseten account created but form status
      unknown — verify before evening)
- [ ] Meta API key handoff → live smoke test (see Blocked)

## PENDING DECISIONS (need Charan's yes/no)

- [x] Push branch `hackathon-copilot` to GitHub → mirrors all work to
      Charan's laptop — PUSHED evening Oct 26 (commit 61c5813, 6 files,
      361 lines); GitHub device login completed, workspace now authed
      for future pushes

- [ ] Build order: pipeline-first, then copilot tools (recommended: yes)
- [ ] Top-3 Aethel ports: tool-use, state machines, audit-first
      (recommended: yes)
- [ ] MHRA adapter + news RSS + Warning Letters on Day 6 (recommended: yes)
- [ ] Second Meta model: Spark Open via partner inference for $10K
      bonus (recommended: yes, if credits land)
- [ ] Deployment: Streamlit Community Cloud (free) or Hugging Face
      Spaces (free) for a live demo link — decide Day 8–9
- [ ] Video style: 3-min screencast with live clicks + voiceover
      (recommended: yes)

## REVIEW FINDINGS (independent review 2026-10-26 — ADOPTED 2026-10-26, in the day plan now; unchecked = not built yet)

- [ ] Adopt claim-level citation gate (recompute numbers + verbatim
      quote match) + adversarial test set + hand-verified accuracy number
- [ ] Adopt deterioration-detector (new / spike / escalation) on Day 6
      as the monitor's real output
- [ ] Adopt voice-query (Muse Voice Transcribe) as the grant-free second
      Meta touchpoint — verify billing vs. $150 first
- [ ] Adopt signal-compare, overnight-digest, conversation-memory,
      rank-explainer, GitHub Actions monitor (capped)
- [ ] Cut complaint-action (no complaint entity in maudesignal);
      Day 6 sources cut to MHRA only; Spark Open → stretch goal
- [ ] Reorder Day 2: seed demo data on Groq first, prove Meta on a
      subset; write one-page gate spec Day 2; deploy spike Day 2–3;
      video = Monday-morning story ending on an action

## BLOCKED ON USER (nothing else can unblock these)

- [ ] Meta API key handoff via a safe channel (NEVER in chat) → then
      live smoke test (`test_meta_connection.py`)

## PENDING BY DAY

- Day 2 (Oct 27): fresh pipeline run end-to-end on live data; seed demo
  dataset; fix breakages; attend Agents 101 (12 PM ET)
- Day 3 (Oct 28): citation gate as CODE + copilot retrieval; Agents 102
- Day 4 (Oct 29): agentic tools + CAPA/complaint actions + audit-first
- Day 5 (Oct 30, LIGHT): review only; Fireworks session if free
- Day 6 (Oct 31): MHRA adapter + news RSS + Warning Letters + copilot
  UI panel + daily `monitor` command
- Day 7 (Nov 1): demo script + 3-min video draft + demo path rehearsed
- Day 8 (Nov 2): polish + Spark Open if partner credits landed +
  README/HACKATHON.md updated
- Day 9 (Nov 3): full dry run + submission page drafted
- Day 10 (Nov 4): SUBMIT by 6 PM PT + X post for Most Viral

## CURRENT ROLES

- Founder/decision-maker: Charan (approves all outward actions)
- Build lead + coach: main agent in build chat (architecture, decisions,
  daily retro, flagging losing moves)
- Pipeline agent: Day 2 run + demo data (spawns Day 2)
- Copilot agent: Day 3–4 tools + citation gate (spawns Day 3)
- Aethel-port agent: Day 4 state machines + audit-first (spawns Day 4)
- QA agent: daily — tests green, claims verified, demo path works
- Demo agent: Day 7–10 video + submission

## DAILY RULE (roll-forward)

Every evening: mark done, move every missed/pending item to the next
day's list explicitly, write the retro (what we did, what slowed us,
what we automate tomorrow, what Charan learned in presenting words,
accuracy numbers). Nothing silently drops. This file is updated daily.
