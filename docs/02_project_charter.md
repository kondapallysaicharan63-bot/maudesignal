# Document 2: Project Charter & Scope

**Project Name:** SafeSignal — Open-Source AI Postmarket Surveillance Toolkit
**Owner:** [Your Name] (solo)
**Version:** 1.0 (Draft)
**Date:** [Today's Date]
**References:** Document 1 (Vision & Mission), v1.0
**Status:** Draft — Pending Self-Commitment

---

## 1. Purpose of This Document

Document 1 defined **what** we're building and **why**. This document defines **exactly what's in and out of scope**, **by when**, and **under what conditions we stop**. It is a commitment contract between you now (motivated, excited) and you in Week 4 (tired, tempted to add features, tempted to give up).

When those two versions of you disagree, **this document wins.**

---

## 2. Project Identification

| Field | Value |
|---|---|
| Project Name | SafeSignal |
| Public Repo | `github.com/[your-username]/safesignal` |
| Owner / Lead | [Your Name] |
| Role | Solo builder (designer, engineer, writer, marketer) |
| Project Type | Open-source portfolio project |
| Primary Goal | Land a top medtech / health-AI job within 6 months of completion |
| Start Date | [YYYY-MM-DD] |
| Target MVP Date | Start + 8 weeks = [YYYY-MM-DD] |
| Hard Stop Date | Start + 10 weeks (2-week buffer only) |
| License | MIT |
| Language | Python 3.11+ |

---

## 3. Objectives (Translated from Vision Doc)

These are the concrete, measurable objectives. Each maps back to a section of Document 1.

| # | Objective | Tied to Doc 1 Section | How Measured |
|---|---|---|---|
| O1 | Ship a working MAUDE ingestion + AI extraction pipeline for 3 product codes | §5.1 Technical | End-to-end pipeline runs unattended |
| O2 | Publish a production-quality open-source repo | §5.2 Engineering | Passes linting, typing, tests, CI |
| O3 | Generate real-world visibility and conversation | §5.3 Visibility | ≥20 GitHub stars, ≥100 LinkedIn reactions, 1 writeup |
| O4 | Build a network of real RA/QA professionals around the project | §5.4 Network | ≥5 informational interviews, ≥10 LinkedIn connections |
| O5 | Validate the problem is real before over-building | §9 Validation Gate | ≥3 customer discovery calls by end of Week 1 |

If any of O1–O5 fail at Week 8, the project has not succeeded as a portfolio asset.

---

## 4. In-Scope Features (Hard Cap: 7)

These are the **only** features that will be built in v1.0. Anything not on this list is out of scope, regardless of how small or tempting it looks.

### F1 — MAUDE Data Ingestion Module
- Pulls adverse event reports from openFDA API for configurable product codes
- Handles pagination, rate limits, retries, caching
- Stores raw JSON + normalized tables in local SQLite
- Supports 3 product codes at MVP: **QIH, QAS, QFM** (all AI radiology)

### F2 — Claude-Powered Narrative Extraction
- Reads free-text MAUDE narratives
- Extracts structured fields via versioned `SKILL.md`: failure_mode, severity, patient_outcome, ai_related_flag, confidence
- ≥90% accuracy on 100-record hand-labeled gold set

### F3 — AI-Specific Failure Taxonomy & Classifier
- Proprietary failure-mode taxonomy (5+ categories) that MAUDE does not capture
- Categories at minimum: concept drift, covariate shift, subgroup degradation, false positive / false negative pattern, automation bias
- Classifier assigns each extracted event to 0–N categories

### F4 — Drift Simulation Harness
- Synthetic deployed-model simulator that generates time-series performance data with injectable drift patterns
- Used to demonstrate the tool's drift-detection capability in the demo (MAUDE alone cannot demonstrate this)
- Drift detection using `evidently` or equivalent (KS test, PSI score)

### F5 — Regulatory Citation Verifier
- Every LLM-generated regulatory reference (510(k) numbers, guidance titles, CFR citations) is verified against primary sources
- Unverifiable claims are flagged `[CITATION NEEDED]`, never fabricated
- Non-negotiable: zero hallucination tolerance in test set

### F6 — Streamlit Dashboard
- Single-page Streamlit app with 5 views: volume trend, severity breakdown, AI failure categories, anomaly alerts, data export
- Runs locally: `streamlit run app.py`
- No auth, no users, no deployment to cloud

### F7 — PSUR-Style Periodic Report Generator
- Generates a Markdown/PDF report summarizing findings over a configurable time window
- Structured like a simplified Periodic Safety Update Report
- Every factual claim links back to a MAUDE report ID or primary source

**That's 7. No #8. If you catch yourself wanting an #8, you're scope-creeping.**

---

## 5. Out-of-Scope (Explicit Exclusions)

Items that will almost certainly come up during the build as "it would only take a day." Written down here so future-you can be reminded that they are **not in scope**.

| Category | Excluded Feature | Why |
|---|---|---|
| Regulators | EU MDR / Eudamed data, Health Canada, PMDA | v1 is U.S. only |
| Data sources | FDA 510(k) database integration, Recalls DB, FAERS, literature | Adds complexity, dilutes focus |
| Users | Authentication, multi-user accounts, roles, teams | Not a SaaS |
| Deployment | Docker, AWS/GCP/Azure, Kubernetes, production infra | Laptop-only MVP |
| Billing | Stripe, subscriptions, paywalls | Open-source, no revenue |
| Architecture | Microservices, message queues, distributed anything | Monolith on SQLite is fine |
| Integrations | Slack, Teams, email digests, webhooks | Nice-to-have, not needed for demo |
| UI | Custom React frontend, design system, branding | Streamlit defaults only |
| AI/ML | Fine-tuning custom models, RLHF, training pipelines | Claude + good prompts is enough |
| Regulatory | 510(k) submission features, PCCP authoring, predicate search | Different gap, different project |
| Data formats | Excel integration, HL7/FHIR, DICOM, custom parsers | Not needed for MAUDE |
| Chat | Chatbot interface, conversational UI | Structured pipelines only |
| Compliance | SOC 2, HIPAA certification, 21 CFR Part 11 validation package | Open-source research tool, not regulated |
| Language | Translation, localization, non-English support | English only |
| Mobile | iOS/Android apps, mobile-responsive dashboard | Desktop only |

---

## 6. Deliverables at Project End

Concrete, shippable artifacts that must exist on the target completion date. Use this as your final checklist.

### 6.1 Code Deliverables
- [ ] Public GitHub repo at `github.com/[username]/safesignal`
- [ ] MIT license, contribution guide, code of conduct
- [ ] Python package installable via `pip install -e .`
- [ ] CLI entry point: `safesignal ingest --product-code QIH --months 12`
- [ ] Streamlit app entry point: `safesignal dashboard`
- [ ] Tests passing, CI green (GitHub Actions)
- [ ] Type checking passing (`mypy`)
- [ ] Linting passing (`ruff`, `black`)

### 6.2 Documentation Deliverables
- [ ] `README.md` — project overview, setup, usage, screenshots
- [ ] `docs/01–08` — all 8 project documents
- [ ] `skills/` — all 7 SKILL.md files versioned
- [ ] `docs/09_whitepaper.md` — longer-form technical writeup (3–5 pages)
- [ ] Architecture diagram (Excalidraw or draw.io, embedded in README)
- [ ] Demo GIF in README (≤30 seconds)

### 6.3 Visibility Deliverables
- [ ] Demo video on YouTube, ≤5 minutes, embedded in README
- [ ] LinkedIn post announcing launch, tagged appropriately
- [ ] Medium or Substack longer-form writeup
- [ ] Submitted to at least one community (Hacker News, r/medicaldevices, RAPS group)

### 6.4 Evidence Deliverables (Proof of Real-World Use)
- [ ] `docs/00_customer_discovery.md` — notes from ≥5 RA/QA conversations
- [ ] `docs/feedback.md` — written feedback from ≥3 professionals who reviewed the tool
- [ ] Links / screenshots of online engagement

### 6.5 Career Deliverables
- [ ] Resume updated with project link and measurable outcomes
- [ ] Interview narrative prepared: "walk me through a project you're proud of" — 3-minute and 10-minute versions
- [ ] ≥5 job/internship applications submitted using this as lead portfolio piece

---

## 7. Phase Structure & Milestones

The 8 weeks are structured into 4 phases. Each phase ends with a **go/no-go gate** — a binary checkpoint that must pass before the next phase begins.

### Phase 0 — Documentation & Discovery (Week 1)
**Duration:** 7 days
**Time budget:** 30–40 hours
**Goal:** Prove the problem is real before committing to the build.

**Deliverables:**
- All 8 project documents drafted and versioned in Git
- All 7 SKILL.md files drafted (behavior defined before implementation)
- 20 LinkedIn outreach messages sent
- ≥3 informational interviews completed and documented

**Gate 0 → 1 (MUST PASS to proceed):**
- [ ] Docs 1, 2, 3, 5, 7 complete (Vision, Charter, Requirements, Architecture, Roadmap)
- [ ] At least 3 customer discovery conversations completed
- [ ] Of those 3: at least 2 confirm the pain is real OR suggest a clearer variant of the problem
- [ ] If <2 confirm: PAUSE. Re-scope or pick a different project. Do not proceed to build.

---

### Phase 1 — Core Ingestion & Extraction (Weeks 2–3)
**Duration:** 14 days
**Time budget:** 40–80 hours
**Goal:** End-to-end: raw MAUDE → structured data in SQLite.

**Deliverables:**
- F1 (MAUDE ingestion) fully working
- F2 (Claude extraction) v1 working on test set
- F5 (Citation verifier) wired into every LLM call
- Gold standard test set of 100 hand-labeled records

**Gate 1 → 2 (MUST PASS to proceed):**
- [ ] Can run `safesignal ingest --product-code QIH --months 12` end-to-end
- [ ] Extraction hits ≥80% accuracy on gold set (90% by end of Phase 2)
- [ ] Zero hallucinated citations in 50 sampled outputs
- [ ] 3 additional outreach messages sent; 1 more interview completed

---

### Phase 2 — AI Signal Detection (Weeks 4–5)
**Duration:** 14 days
**Time budget:** 40–80 hours
**Goal:** The differentiator — AI-specific signals MAUDE can't show.

**Deliverables:**
- F3 (AI failure taxonomy & classifier) implemented and validated
- F4 (Drift simulation + detection harness) working end-to-end
- Refined extraction accuracy: ≥90% on gold set

**Gate 2 → 3 (MUST PASS to proceed):**
- [ ] Classifier produces defensible output on 20 hand-reviewed records
- [ ] Drift simulator demonstrates detection on injected drift patterns
- [ ] Feedback from at least 1 RA professional on the taxonomy itself
- [ ] All Skills versioned, reviewed, tested

---

### Phase 3 — Dashboard, Reports & Launch (Weeks 6–7)
**Duration:** 14 days
**Time budget:** 40–80 hours
**Goal:** Make it presentable. Ship it publicly.

**Deliverables:**
- F6 (Streamlit dashboard) with 5 views
- F7 (PSUR-style report generator)
- README, architecture diagram, demo GIF
- Demo video recorded and uploaded
- LinkedIn post + Medium writeup drafted

**Gate 3 → 4 (MUST PASS to proceed):**
- [ ] A stranger can clone the repo and run the full demo in <15 minutes
- [ ] Demo video exists and is watchable (not pretty, just watchable)
- [ ] At least 3 professionals have reviewed the tool and given feedback

---

### Phase 4 — Launch, Outreach & Buffer (Week 8 + buffer)
**Duration:** 7–14 days
**Time budget:** 20–40 hours
**Goal:** Convert the build into job interviews.

**Deliverables:**
- Public launch: LinkedIn, Medium, Hacker News, RAPS, r/medicaldevices
- ≥5 job/internship applications using this as lead project
- Resume + interview narratives finalized
- Final whitepaper polished

**Exit Gate (success):**
- [ ] All success criteria in Document 1 §5 met
- [ ] Recruiter email (Doc 1 §4) can be sent with confidence
- [ ] Hard stop: Project goes into maintenance mode after week 10 regardless

---

## 8. Time Allocation (Recommended Weekly Breakdown)

For a 30-hr/week target (middle of your 20–40 range):

| Activity | Hours/week | % |
|---|---|---|
| Building (code, Skills, testing) | 18 hrs | 60% |
| Documentation & writing | 4 hrs | 13% |
| Customer discovery / outreach | 4 hrs | 13% |
| Learning (FDA docs, ML, regulatory reading) | 3 hrs | 10% |
| Admin / Git / misc | 1 hr | 4% |

**Rule:** Outreach hours cannot be sacrificed to building hours. If you skip customer discovery, you build the wrong thing and the project fails at §5.4.

---

## 9. Stakeholders (Who Cares About This Project)

Even solo open-source projects have stakeholders. Identifying them helps you know who to pull into reviews.

| Stakeholder | Role | Engagement Frequency |
|---|---|---|
| You | Owner, builder, decision-maker | Daily |
| SJSU faculty advisor (optional) | Sanity check, academic angle | Monthly |
| RA/QA mentor (target: find 1 by Week 2) | Regulatory reality check | Bi-weekly |
| Customer discovery interviewees (5+) | Problem validation + tool feedback | Once each |
| Beta testers (2–3) | Try the tool, give feedback | Week 6–7 |
| Recruiters / hiring managers | Eventual audience | Week 8+ |
| Open-source community | Fork, star, file issues | Week 8+ |

---

## 10. Constraints

### 10.1 Hard Constraints (Cannot Be Violated)
- **Time:** 8 weeks to MVP, 10 weeks absolute hard stop
- **Budget:** <$200 in API costs + hosting
- **Legal:** No PHI, no regulatory advice output, no liability claims
- **Solo:** No co-founders, no employees, no paid contractors

### 10.2 Soft Constraints (Strong Defaults)
- **Stack:** Python + Claude API + SQLite + Streamlit (change only with written justification)
- **License:** MIT (change only with written justification)
- **Platform:** macOS/Linux development, Windows untested
- **Regulator:** FDA only (no EU MDR even if tempting)

---

## 11. Dependencies

Things outside your control that this project depends on. If any break, the project is at risk.

| Dependency | Risk if Broken | Contingency |
|---|---|---|
| openFDA API availability | High — no data, no product | Pre-cache 12 months of MAUDE data in Week 1 |
| Anthropic Claude API | High — no AI, no product | Keep prompts portable to Claude/GPT/Gemini |
| Python 3.11+ stability | Low | Pin versions in `pyproject.toml` |
| `evidently` or `alibi-detect` library | Medium | Can roll own KS test if needed |
| Your health & time | High | Protected calendar blocks; buffer week; no Week 5 crunch |

---

## 12. Assumptions (If These Are Wrong, Scope Changes)

1. MAUDE data for product codes QIH/QAS/QFM is sufficient in volume to demonstrate patterns (validated Week 2)
2. Claude Sonnet is sufficient for extraction quality at 90%+ (if not, upgrade to Opus for bulk)
3. At least 3 RA/QA professionals on LinkedIn will respond to cold outreach (validated Week 1)
4. Open-source MIT is acceptable to all future employers (it is — no-compete issues at this scope)
5. No FDA policy change invalidates the approach within 8 weeks (low probability)

---

## 13. Risks (Summary — Full Register in Document 6)

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Scope creep eats timeline | **Very High** | High | This document; weekly review against §4 |
| No customer validation (ghosted outreach) | Medium | **Critical** | 20 messages, not 5; follow up; offer value first |
| Claude extraction accuracy stalls <80% | Medium | High | Iterate Skills, not models; manual review loop |
| Burnout mid-project (Week 4–5 dip) | **High** | High | Buffer week; rest day scheduled; social accountability |
| Someone else ships similar open-source tool first | Low | Medium | Launch early (Week 6 beta announce) |
| Employer sees project as "too niche" | Low | Medium | Narrative frames it as AI + regulatory + engineering |

---

## 14. Change Control Process

Any change to this Charter must follow this process. Without it, scope creeps silently.

1. **Propose in writing.** Open an issue in the GitHub repo tagged `scope-change`.
2. **Justify against the goal.** Answer: "Does this change make it more or less likely I land a top medtech job in 6 months?"
3. **Evaluate tradeoff.** If adding something in-scope, what comes OUT? (Features 1–7 is a hard cap.)
4. **Commit the change.** Version bump (1.0 → 1.1 minor, → 2.0 major). Commit message explains.
5. **If unsure, default to NO.** The bias is against changes, not toward them.

**Changes that do NOT require this process:**
- Typos and formatting
- Clarifications that don't alter scope
- Within-feature implementation decisions

---

## 15. Commitment Contract (Sign With Yourself)

This section is unusual for a charter but critical for solo founders. You sign this with yourself, in writing, and revisit weekly.

### I, [Your Name], commit to the following:

**Time commitments:**
- [ ] I will protect [N] hours per week on my calendar for this project, and treat those blocks as non-negotiable.
- [ ] I will work in phase-gated sprints and will not skip gates because I "feel" ready.

**Scope commitments:**
- [ ] I will not add an 8th feature to §4 without removing one of the existing 7.
- [ ] I will not work on excluded items in §5, even if they take "only a day."

**Quality commitments:**
- [ ] I will not merge code without tests for the core extraction logic.
- [ ] I will not ship hallucinated citations — ever.
- [ ] I will document before coding, not after.

**Discovery commitments:**
- [ ] I will send 20 outreach messages in Week 1 before writing a single line of production code.
- [ ] I will not treat customer discovery as optional.

**Stop commitments:**
- [ ] If Gate 0 → 1 fails, I will pause or pivot. I will not "push through" without validation.
- [ ] If Week 10 arrives, I will ship what I have, launch it, and move on.
- [ ] I will not let this project consume Week 11 and beyond without a written new charter.

**Recovery commitments:**
- [ ] If I fall behind by >1 week, I will cut scope from §4, not add hours or skip sleep.
- [ ] If I burn out, I will take 3 days off without guilt and come back.

| Signed | Date |
|---|---|
| [Your Name] | [YYYY-MM-DD] |

---

## 16. Exit Criteria (How the Project Officially Ends)

The project is considered **complete** (not "done forever" — just the v1.0 build phase) when:

1. All Phase 4 deliverables (§6) are shipped.
2. Exit Gate (§7) passes.
3. You have sent the recruiter email (Doc 1 §4) to at least 5 recipients.
4. A final retrospective is written at `docs/10_retrospective.md`.

After exit, the repo continues to exist. Maintenance is optional. Extensions become new projects with their own charters.

---

## 17. What This Document Is and Is Not

**IS:**
- A contract that wins against future tired-you
- The source of truth for "is this in scope?"
- The basis of weekly self-review

**IS NOT:**
- Requirements specification (→ Document 3)
- Technical design (→ Document 5)
- Risk register detail (→ Document 6)
- Weekly work breakdown (→ Document 7)

---

**End of Document 2.**
