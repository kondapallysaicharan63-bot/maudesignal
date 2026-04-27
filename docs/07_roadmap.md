# Document 7: Roadmap & Milestone Plan

**Project Name:** MaudeSignal
**Owner:** [Your Name]
**Version:** 1.0 (Draft)
**Date:** [Today's Date]
**References:** Documents 1–6
**Status:** Draft — pending start date commitment

---

## 1. Purpose of This Document

This document turns the 4-phase plan from Document 2 into a **week-by-week, day-by-day** execution schedule. It answers: "What am I doing this Monday morning?"

It is strict but not rigid. Each week has:
- A goal
- Deliverables
- Time allocation (by category)
- A Go/No-Go gate at the end

Every Sunday, you check the week's gate. If it didn't pass, you adjust next week — you do not proceed on hope.

---

## 2. Master Schedule Overview

```
Week 0   — Prep (before official Week 1 starts)
Week 1   — Phase 0: Documentation + Discovery (GATE 0)
Week 2   — Phase 1: Ingestion + Gold Set
Week 3   — Phase 1: Extraction + Verifier   (GATE 1)
Week 4   — Phase 2: Classification + Taxonomy
Week 5   — Phase 2: Drift Simulation + Detection  (GATE 2)
Week 6   — Phase 3: Dashboard + Report Generator
Week 7   — Phase 3: Polish + Docs + Demo Video  (GATE 3)
Week 8   — Phase 4: Launch + Outreach  (EXIT GATE)
Week 9–10 — Buffer (do not plan into this)
```

**Hard stop: End of Week 10.** After that, the project transitions to maintenance mode regardless of completion status. See Charter §16.

---

## 3. Week 0 — Preparation (1–3 Days)

**Goal:** Start Week 1 without setup friction.

### Checklist
- [ ] Pick start date (write it in the Charter)
- [ ] Put 20–40 hrs/week blocks on calendar through Week 10
- [ ] Finalize all 8 documents (1 through 8) in a Git repo
- [ ] Create GitHub repo: `github.com/[username]/maudesignal` (public, MIT license)
- [ ] Install: Python 3.11+, VS Code/Cursor, Git, Docker (optional)
- [ ] Create Anthropic account, get API key, add $20 credit
- [ ] Create `.env` file with keys (gitignored)
- [ ] Tell one friend or mentor the start date (social accountability)

**Output:** An empty-but-ready repo with complete docs, the environment works, calendar is blocked.

---

## 4. Week 1 — Phase 0: Documentation Freeze + Customer Discovery

**Goal:** Validate the problem is real; freeze docs; no production code yet.

### Time Allocation (30 hrs target)

| Activity | Hours |
|---|---|
| Customer discovery outreach + calls | 10 |
| Learning (FDA docs, Claude API, MAUDE) | 10 |
| Document finalization + Skill stubs | 6 |
| Data pilot query (validate MAUDE sparsity — R-10) | 3 |
| Admin / Git / calendar | 1 |

### Monday — "Set the Foundation"
- [ ] Commit Documents 1–8 to repo, tag as `v1.0-docs`
- [ ] Read FDA AI-enabled SaMD guidance (half)
- [ ] Draft LinkedIn outreach template; identify 20 target people
- [ ] Send first 5 outreach messages

### Tuesday — "Learn the Domain"
- [ ] Finish FDA AI guidance reading
- [ ] Read MAUDE data dictionary (open.fda.gov)
- [ ] Read Babic et al. paper
- [ ] Send 5 more outreach messages
- [ ] Pilot query: openFDA MAUDE count for product codes QIH, QAS, QFM over 12 months — **record actual counts in `docs/00_customer_discovery.md`**

### Wednesday — "Build Skill Stubs"
- [ ] Read Anthropic Claude API docs + prompt engineering guide
- [ ] Draft `skills/regulatory-citation-verifier/SKILL.md` (v0.1 — just structure, rules, 2 examples)
- [ ] Draft `skills/maude-narrative-extractor/SKILL.md` (v0.1)
- [ ] Send 5 more outreach messages (total: 15)

### Thursday — "First Customer Call"
- [ ] Review "The Mom Test" chapters 1–3
- [ ] Conduct first customer discovery call (if scheduled)
- [ ] Document findings in `docs/00_customer_discovery.md`
- [ ] Refine outreach template based on what worked/didn't

### Friday — "Close the Discovery Loop"
- [ ] Follow up with non-responders (short nudge)
- [ ] Conduct second customer call if scheduled
- [ ] Send 5 more outreach messages if response rate low (total: 20)
- [ ] Review Skills drafts with fresh eyes

### Saturday — "Rest / Catch-up"
- Rest day OR catch up on anything slipped
- Do NOT start coding features early — Gate 0 is not passed yet

### Sunday — "Week 1 Review + Gate 0 Check"
- [ ] **Gate 0 → 1 Check:**
  - Docs 1, 2, 3, 5, 7 complete? ✅ / ❌
  - ≥3 customer discovery calls completed? ✅ / ❌
  - Of those, ≥2 confirm the pain is real OR suggest a clearer variant? ✅ / ❌
  - MAUDE data pilot shows ≥500 records per target code over 12 months? ✅ / ❌
- [ ] If all pass → proceed to Week 2
- [ ] If fail → PAUSE. Re-scope per Charter §7. Update Documents 1 and 2. Do not proceed to build.

---

## 5. Week 2 — Phase 1: Ingestion + Gold Set

**Goal:** Working MAUDE ingestion; hand-labeled gold set ready.

### Time Allocation (30 hrs target)

| Activity | Hours |
|---|---|
| Build F1 (ingestion) | 12 |
| Hand-label gold set (100 records) | 6 |
| Learn pytest + write first tests | 3 |
| Draft storage schema + SQLAlchemy | 5 |
| Customer discovery continued (3 more messages, 1 follow-up call) | 3 |
| Documentation updates | 1 |

### Milestones
- [ ] `maudesignal ingest --product-code QIH --months 12` works end-to-end
- [ ] SQLite DB has `raw_reports` and `normalized_events` tables populated
- [ ] Pagination, retry, caching all implemented (FR-03, FR-04, FR-05)
- [ ] Unit tests for ingestion at ≥50% coverage
- [ ] Gold set: 100 MAUDE records hand-labeled in `tests/gold_set/gold_100.jsonl`
- [ ] Architecture review checkpoint (Doc 5 §16) — does the code match the design?

### Daily Focus
- **Mon–Tue:** Ingestion module + storage schema
- **Wed:** First integration test + error handling
- **Thu–Fri:** Hand-labeling gold set (2–3 hrs/day) + unit tests
- **Sat:** Buffer / rest
- **Sun:** Weekly review, risk register update

---

## 6. Week 3 — Phase 1: Extraction + Verifier (GATE 1)

**Goal:** Structured extraction working at ≥80% accuracy; verifier blocks hallucinations.

### Time Allocation (30 hrs target)

| Activity | Hours |
|---|---|
| Build F2 (extraction) | 10 |
| Build F5 (citation verifier) — FIRST | 8 |
| Refine SKILL.md v1.0 for extractor + verifier | 5 |
| Run gold set evaluation; iterate | 5 |
| Outreach + 1 call | 2 |

### Milestones
- [ ] `skills/regulatory-citation-verifier/SKILL.md` v1.0 final, with 3 good + 2 bad examples
- [ ] `skills/maude-narrative-extractor/SKILL.md` v1.0 final
- [ ] Extractor runs on full ingested dataset
- [ ] Extraction accuracy on gold set ≥80% (target 90% by end of Phase 2)
- [ ] Verifier rejects 100% of fake K-numbers on 50-record test
- [ ] Zero hallucinated citations in 50 sampled outputs
- [ ] LLM audit log populated (FR-12)

### Gate 1 → 2 Check (Sunday)
- [ ] Can run `maudesignal ingest` + `maudesignal process` end-to-end? ✅ / ❌
- [ ] Extraction hits ≥80% on gold set? ✅ / ❌
- [ ] Zero hallucinated citations in 50-sample audit? ✅ / ❌
- [ ] ≥1 more customer discovery call this week? ✅ / ❌

If fail → iterate on Skills before moving to classification.

---

## 7. Week 4 — Phase 2: Classification + Taxonomy

**Goal:** AI failure-mode classifier operational.

### Time Allocation (30 hrs target)

| Activity | Hours |
|---|---|
| Build F3 (classifier) | 12 |
| Finalize AI failure taxonomy in Glossary (Doc 8) | 3 |
| Draft `ai-failure-mode-classifier` SKILL.md | 5 |
| Extraction accuracy refinement → 90% | 5 |
| Begin F4 (drift simulator skeleton) | 3 |
| Outreach / feedback collection | 2 |

### Milestones
- [ ] `skills/ai-failure-mode-classifier/SKILL.md` v1.0
- [ ] Classifier outputs multi-label taxonomy on 100-record sample
- [ ] Hand-review of 20 classifications for plausibility
- [ ] Extraction accuracy ≥90% on gold set
- [ ] First draft of drift simulator generates synthetic performance data

### Key Risk Watch
- R-07 (extraction stalls <80%): if still an issue, escalate — spend max 1 day on this before moving on
- R-13 (LLM non-determinism): accept NFR-14 ceiling

---

## 8. Week 5 — Phase 2: Drift Simulation + Detection (GATE 2)

**Goal:** Drift detection demonstrable on synthetic data.

### Time Allocation (30 hrs target)

| Activity | Hours |
|---|---|
| Build F4 (drift simulator + detector) | 15 |
| Learn `evidently` + KS test + PSI | 5 |
| Draft `drift-analysis-interpreter` SKILL.md | 3 |
| Get feedback from 1 RA professional on taxonomy + drift approach | 3 |
| Refactor / clean-up (typing, tests) | 3 |
| Documentation sync | 1 |

### Milestones
- [ ] Drift simulator generates gradual, sudden, and subgroup-specific drift patterns (FR-18)
- [ ] KS test and PSI implemented and tested
- [ ] Drift detector identifies ≥80% of injected drift events (FR-19)
- [ ] Drift alert schema populated in DB (DR-05)
- [ ] All Skills versioned (v1.x) and have 3+ good examples

### Gate 2 → 3 Check (Sunday)
- [ ] Classifier + drift + verifier all produce defensible output? ✅ / ❌
- [ ] At least 1 RA professional has reviewed the taxonomy? ✅ / ❌
- [ ] Extraction still ≥90% on gold set? ✅ / ❌
- [ ] Total customer discovery calls ≥4? ✅ / ❌

---

## 9. Week 6 — Phase 3: Dashboard + Report Generator

**Goal:** User-facing surfaces complete.

### Time Allocation (30 hrs target)

| Activity | Hours |
|---|---|
| Build F6 (Streamlit dashboard, 5 views) | 12 |
| Build F7 (PSUR-style report generator) | 8 |
| Draft `psur-report-drafter` SKILL.md | 3 |
| Learn Streamlit (tactical) | 3 |
| CI setup (GitHub Actions) | 2 |
| Outreach / schedule beta-reviewer calls | 2 |

### Milestones
- [ ] Dashboard accessible at `localhost:8501`
- [ ] All 5 required views (FR-26) render without error
- [ ] Filters work (FR-27)
- [ ] CSV/JSON export works (FR-28)
- [ ] Report generator produces Markdown + PDF (FR-30)
- [ ] Report includes all 9 required sections (FR-31)
- [ ] CI pipeline green (tests + lint + typecheck)

---

## 10. Week 7 — Phase 3: Polish + Docs + Demo Video (GATE 3)

**Goal:** Repo is presentable to a senior medtech hiring manager.

### Time Allocation (30 hrs target)

| Activity | Hours |
|---|---|
| README write (overview, install, usage, screenshots, demo GIF) | 6 |
| Architecture diagram (Excalidraw) | 2 |
| Write whitepaper (`docs/09_whitepaper.md`, 3–5 pages) | 6 |
| Demo video (script + record + edit) | 5 |
| Bug fixes, edge cases, final testing | 6 |
| Ask 3 professionals to test the tool | 3 |
| Outreach continuation | 2 |

### Milestones
- [ ] README complete with all sections (NFR-16)
- [ ] Architecture diagram embedded
- [ ] Demo GIF in README (≤30 sec)
- [ ] Demo video on YouTube (≤5 min)
- [ ] Whitepaper published
- [ ] All 8 project documents final (v1.0+)
- [ ] All 7 SKILL.md files at v1.0+, versioned in repo
- [ ] ≥3 beta testers have used the tool and given feedback

### Gate 3 → 4 Check (Sunday)
- [ ] Stranger can go `git clone` → working demo in <15 min? (Test it!) ✅ / ❌
- [ ] Demo video exists? ✅ / ❌
- [ ] ≥3 professionals have reviewed the tool? ✅ / ❌
- [ ] All Must FRs from Document 3 pass acceptance tests? ✅ / ❌
- [ ] CI green? ✅ / ❌

---

## 11. Week 8 — Phase 4: Launch + Outreach (EXIT GATE)

**Goal:** Convert the build into interviews and applications.

### Time Allocation (25 hrs target — lighter week, high-leverage)

| Activity | Hours |
|---|---|
| LinkedIn launch post (draft + post) | 3 |
| Medium/Substack writeup | 4 |
| Submit to Hacker News, r/medicaldevices, RAPS LinkedIn group | 2 |
| Resume update with project link + measurable outcomes | 3 |
| Interview narratives (3-min and 10-min versions, rehearsed) | 4 |
| ≥5 job/internship applications using this as lead piece | 5 |
| Final whitepaper polish | 2 |
| Retrospective doc `docs/10_retrospective.md` | 2 |

### Exit Gate (Saturday of Week 8)
- [ ] All Document 1 §5 success criteria met (or consciously waived)? ✅ / ❌
- [ ] Recruiter email (Doc 1 §4) sendable with confidence? ✅ / ❌
- [ ] ≥5 applications submitted? ✅ / ❌
- [ ] Retrospective written? ✅ / ❌

### If Not Exiting This Week — Use Buffer
- Weeks 9–10 are for fixing what's broken, not adding scope
- By end of Week 10, ship what you have and move on

---

## 12. Daily Rhythm (Recommended)

For a typical 5-hour day:

```
08:00 – 08:30   Quick plan: review yesterday, set 3 goals for today, check risk register
08:30 – 11:30   Deep work: code, Skills, or primary feature work (no notifications)
11:30 – 12:00   Break / stand up / walk
12:00 – 13:00   Lunch
13:00 – 14:00   Customer discovery / outreach / replies
14:00 – 15:30   Documentation, tests, or learning
15:30 – 15:45   Git commit, push, end-of-day notes
```

**Non-negotiable daily habits:**
- 1 Git commit per working day (even if small)
- Outreach hour is sacrosanct — always the same time
- Weekly review Sunday, 30 min minimum

---

## 13. Weekly Review Template (Sunday, 30 min)

Copy this template to `docs/weekly_reviews/week_XX.md` every Sunday.

```markdown
# Week [XX] Review — [YYYY-MM-DD]

## What I completed this week
- ...

## What slipped and why
- ...

## Hours worked (vs. target)
- Planned: 30 hrs
- Actual:  [X] hrs
- Breakdown: Build [X], Discovery [X], Learning [X], Docs [X], Admin [X]

## Gate status
- This week's gate: [PASS / FAIL / N/A]
- If fail, plan to close gap:

## Risk register updates
- New risks:
- Risks changed priority:
- Risks retired:

## Skills matrix updates
- Skills leveled up:
- New skills needed:

## Next week's top 3 goals
1.
2.
3.

## Discovery progress
- Outreach sent this week:
- Calls completed:
- Key insights:

## Energy check (1–10)
- How am I doing?
- What do I need?
```

---

## 14. If Things Go Wrong — Recovery Playbook

### 14.1 If you miss a week entirely
- Don't try to catch up in 1 week
- Move all subsequent deliverables back 1 week
- Cut scope from the END (Week 8 launch items) not the MIDDLE (core pipeline)
- If this happens twice, scope cut is mandatory — use contingencies in Doc 6 §6

### 14.2 If a gate fails
- Stop. Do not proceed.
- Write a recovery plan (1 page max) for closing the gap
- Time-box recovery to 3 days; if still blocked, escalate (talk to mentor, reconsider scope)

### 14.3 If you hit burnout
- Take 3 full days off. No guilt.
- When you return, re-read Document 1 (Vision) before any other doc
- Reduce weekly hours target by 5 for 2 weeks
- If burnout recurs, consider if the project is still the right use of your time

---

## 15. What Shipping Looks Like

By end of Week 8, these things exist in the world:

- A public GitHub repo (`github.com/[username]/maudesignal`)
- A README that makes sense to a stranger
- A 5-minute demo video on YouTube
- A LinkedIn post with the project announcement
- A Medium/Substack writeup
- At least 5 job/internship applications submitted
- At least 5 conversations with RA/QA professionals in your network

You can then tell someone truthfully: "I built a tool. It works. People used it. Here's what I learned."

**That story lands jobs. Everything in this document serves that story.**

---

## 16. What This Document Is and Is Not

**IS:**
- Your daily and weekly operating system for 8 weeks
- The plan against which every Sunday's review happens
- The evidence trail of consistent execution

**IS NOT:**
- Immutable (update as you learn, version-bump the doc)
- An excuse for rigidity (it's a plan, not a cage)
- A substitute for judgment

---

**End of Document 7.**
