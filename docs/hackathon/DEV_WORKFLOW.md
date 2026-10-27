# DEVELOPMENT AGENTIC WORKFLOW — how this app gets delivered (Oct 26 – Nov 4)

This is the THIRD workflow. The other two describe the APP (product pipeline
+ copilot agent loop). This one describes the TEAM that builds it: who does
what, in what order, through which gates, to submission.

## The loop (every day)

```
FOUNDER (Charan) — decides. Reviews when free.
   Approves ONLY outward actions: push, submit, purchase, email.
        |
        v
BUILD LEAD (main agent, build chat) — architecture, integration, plan.
   Splits each day into ONE-task agents. No agent shares a file
   with another agent on the same day.
        |
   +----+----------+-----------+----------+-----------+
   |    |          |           |          |           |
   v    v          v           v          v           v
Pipeline Copilot  Aethel-port QA         Demo
agent   agent     agent      agent       agent
   |    |          |           |          |
   +----+----------+-----------+----------+-----------+
        |
        v
EVIDENCE GATE — every agent reports: files changed, test output,
   proof for every claim. No claims without evidence.
   - tests green? (321 existing + new tests)
   - demo path still works?
   - every claim cited?
   FAIL -> fix loop (same agent, same day)
   PASS -> build lead integrates
        |
        v
EVENING VERIFY + RETRO (build lead, written, not remembered):
   what shipped, what slowed us down, what automates tomorrow,
   "what Charan learned today, in presenting words",
   missed items -> tomorrow's plan EXPLICITLY (nothing silently drops)
        |
        v
DELIVERY PIPELINE:
   commit -> push (ONLY on Charan's word) -> deploy spike ->
   video -> submission (target Nov 4, 6 PM PT; hard deadline 9 PM ET)
```

## Day-by-day owner map

| Day | Pipeline agent | Copilot agent | Aethel-port | QA agent | Demo agent |
|---|---|---|---|---|---|
| Day 2 (Oct 27) | Groq-seed demo data, Meta subset compare, deploy spike, $150 budget | One-page gate spec | — | Tests green | — |
| Day 3 (Oct 28) | — | Claim-level gate + adversarial test set + rank-explainer + retrieval | — | Gate tests | — |
| Day 4 (Oct 29) | — | Tools (signal-query, deadline-check), CAPA action, memory, compare, voice start | Pattern module (forward-only + audit-first) | Tool tests | — |
| Day 5 (Oct 30) LIGHT | Background tests only | Background tests only | — | Background tests only | Fireworks session if free |
| Day 6 (Oct 31) | MHRA adapter only | Deterioration-detector, overnight-digest, Actions monitor | — | Monitor tests | Copilot UI panel |
| Day 7 (Nov 1) | — | — | — | Rehearsal | Script + video draft + accuracy-sample |
| Day 8 (Nov 2) | — | Spark Open ONLY if grant landed | — | Polish tests | README/HACKATHON.md |
| Day 9 (Nov 3) | — | — | — | FULL DRY RUN | Submission draft |
| Day 10 (Nov 4) | — | — | — | Final check | Submit by 6 PM PT + X post |

## Hard gates (dates that cannot slip quietly)

- Day 2: gate spec + budget + deploy spike done — else Day 3 and Day 8 slip.
- Day 7: video draft + rehearsal — else video week collapses.
- Day 9: full dry run — last day for submission questions.
- Day 10: submit by 6 PM PT (3-hour buffer before the 9 PM ET deadline).

## Async rules (how Charan works with the team)

- Charan does NOT stay in chat. Agents work while he is in class or
  meetings; he reviews and decides when free (phone or desktop).
- Coordination surface: the "Meta Hackathon Build" chat + these files
  (WORKFLOW.md, CHECKLIST.md, SKILLS_WORKSHEET.md) as source of truth.
- Coach rule: if a move loses points (generic framing, unverified claim,
  medical-advice framing, demoing old work as new, committing a key),
  the build lead STOPS and says so plainly, with the fix.
- A decision, once made, stands — one advisory airing, then commit.
  (Adopted review changes, Oct 26, are an example: decided once, now
  in the day plan.)

## Requirements vs. flow vs. components (three different lenses — do not mix)

The same copilot loop looks different through each lens. Requirements say
what must be TRUE. Flow says WHEN it runs. Components say what CODE gets
written. Each dev agent owns different items in all three.

### 1. REQUIREMENTS — what "done" means per agent

- Pipeline: demo signals exist in the store, schema-valid; fresh-check
  works live against openFDA; Streamlit Cloud deploy proven (incl.
  WeasyPrint); $150 budget written and enforced; MHRA ingests, normalizes,
  dedupes.
- Copilot: Spark 1.3 can call every tool; retrieval returns ranked signals
  with reasons; gate blocks ALL adversarial cases and passes ALL valid
  ones; voice transcribes then answers; memory holds context across turns.
- Aethel-port: one pattern module; CAPA/alert transitions forward-only
  (illegal moves rejected); audit row written BEFORE the state change;
  audit log tamper-evident.
- QA: full suite green; gate adversarial set green; accuracy-sample
  number published (20 hand-checked); demo path rehearsed; dry run passed.
- Demo: video ~2:45, Monday-morning story, captions, two takes;
  submission links work; HACKATHON.md labels old vs. new correctly.

### 2. FLOW — where each agent's work runs in the copilot loop

- Pipeline: BEFORE the loop — inputs. Data in the store, fresh-check
  fetch, and the daily monitor's ingest side.
- Copilot: THE loop — ask → tools → grounded answer → gate.
- Aethel-port: the loop's CONSTRAINT layer — after gate pass: actions
  (CAPA, alert, PSUR) + audit trail.
- QA: ACROSS the loop — not a runtime stage; verifies every stage.
- Demo: AFTER the loop — presentation of the loop working end-to-end.

### 3. COMPONENTS — the code each agent writes (no overlaps)

- Pipeline: ingest adapters (MHRA), seed scripts, demo dataset (SQLite
  rows), deploy config (Streamlit Cloud + WeasyPrint deps), budget ledger.
- Copilot: src/maudesignal/copilot/ (meta_provider, copilot.py, tools:
  signal_query, signal_compare, deadline_check, conversation-memory,
  voice_query), claim-verifier gate module, rank-explainer,
  gate-adversarial-test-set file, deterioration-detector,
  overnight-digest generator.
- Aethel-port: state-machine pattern module (transitions + audit-first
  write), audit trail store/writer.
- QA: pytest additions (gate tests, tool tests, monitor tests),
  accuracy-sample script + report, rehearsal checklist, dry-run report.
- Demo: video script + recording + captions, submission page draft,
  README/HACKATHON.md updates, dashboard copilot panel + Overnight page.

Rule that keeps the lenses clean: Pipeline never writes gate code,
Copilot never writes deploy config, QA never writes features (only tests
and verification), Demo never writes loop logic (only shows it). Builder
and breaker stay separate: Copilot builds the gate, QA breaks it with the
adversarial set.
