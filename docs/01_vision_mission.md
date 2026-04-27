# Document 1: Vision & Mission

**Project Name:** MaudeSignal — Open-Source AI Postmarket Surveillance Toolkit
**Owner:** [Your Name]
**Version:** 1.0 (Draft)
**Date:** [Today's Date]
**Project Type:** Open-source portfolio project, career-leverage asset
**Target Completion:** 6–8 weeks from start date

---

## 1. Problem Statement

The FDA has cleared over 1,000 AI/ML-enabled medical devices (295 in 2025 alone), deployed across hospitals to read imaging, flag strokes, and triage radiology studies. These devices are monitored through the FDA's MAUDE database — a reporting system built in the 1990s for mechanical device failures. **MAUDE has no data fields** to capture AI-specific failures: concept drift, covariate shift, subgroup performance degradation, or automation bias.

A deployed imaging AI whose sensitivity silently drops from 85% to 72% over 18 months will generate **zero** adverse event reports, because no individual case looks like a "malfunction." Research (Babic et al., npj Digital Medicine, 2025) on ~950 FDA-cleared AI/ML devices found that the majority of adverse event reports came from just two devices — meaning AI failures across the other ~948 are **invisible to regulators and manufacturers alike**.

The Quality Management System Regulation (QMSR), effective February 2, 2026, mandates real-world performance monitoring for every medical device manufacturer. This turns a research curiosity into a regulatory compliance gap — and the tooling to address it does not yet exist in open-source form.

---

## 2. What This Project Is

An **open-source toolkit** that ingests FDA MAUDE adverse event data for AI/ML-enabled medical devices, uses Claude (Anthropic API) with structured Skills to extract AI-specific failure signals that MAUDE's native schema cannot capture, and produces regulator-style reports and dashboards.

Built as a **public GitHub repository with production-quality engineering**, regulatory rigor, and a written whitepaper — designed to function simultaneously as:

- A working tool that regulatory affairs teams can actually use
- A portfolio centerpiece for landing roles at top medtech and health-AI companies
- A foundation for future commercial or research extensions if desired

---

## 3. Why This Project (Strategic Rationale)

### Why this topic specifically will land a medtech job:

1. **It sits at the exact intersection top employers are hiring for right now:** AI/ML + regulatory + postmarket quality. This combination is rare in candidates.
2. **It proves three skills at once:** domain expertise (FDA regulatory), applied AI engineering (Claude, RAG, prompts), and software rigor (clean code, tests, documentation).
3. **It's timely.** QMSR takes effect Feb 2026. Every medtech RA/QA team is actively thinking about this problem.
4. **It's defensible in interviews.** You can walk through design tradeoffs, cite FDA guidance, and explain regulatory constraints. Other candidates can't.
5. **It's shareable.** Open-source on GitHub means recruiters can read it. A hiring manager at Medtronic can see your code. This is leverage other BME candidates don't have.

### Why open-source (not commercial) is the right choice for you right now:

- Maximum visibility — anyone can find it, fork it, share it
- Zero legal overhead — no company formation, no IP disputes with employers
- Credibility through public code — recruiters and hiring managers can audit the work
- Keeps options open — can commercialize later if traction emerges
- Aligned with the community — FDA, academia, and medtech increasingly value open tooling

---

## 4. Target Outcome: What "Success" Looks Like

This project succeeds when, 8 weeks from start, you can send this email to any medtech recruiter:

> *"Hi — I'm a BME M.S. candidate at SJSU. I built and open-sourced a tool that detects AI-specific failure signals in FDA postmarket surveillance data, which MAUDE's native schema can't capture. It's used by [N] people on GitHub, cited in [X] LinkedIn post(s), and I've had informational interviews with RA professionals at [companies]. Here's the repo and a 5-minute demo: [links]. I'd love to discuss roles in your regulatory affairs or post-market AI quality team."*

**If you can send that email with confidence — the project succeeded.** If you can't, it didn't.

---

## 5. Concrete Success Criteria (Measurable, Binary Pass/Fail)

### 5.1 Technical — the product must actually work
- [ ] Ingests ≥12 months of MAUDE data for ≥3 AI-enabled device product codes (e.g., QIH, QAS, QFM)
- [ ] Claude-powered extraction achieves ≥90% accuracy on a hand-labeled 100-record gold standard
- [ ] Detects and categorizes at least 5 AI-specific failure types not surfaced by MAUDE's native fields
- [ ] Every regulatory citation in every output is verifiable against a primary source — zero hallucinations on test set
- [ ] Full pipeline runs end-to-end, unattended, in under 30 minutes per product code
- [ ] Streamlit dashboard displays: volume trends, severity breakdown, AI failure categories, anomaly alerts, exportable report

### 5.2 Engineering Quality — the repo must look senior-level
- [ ] Clean, typed Python (passes `mypy`, `ruff`, `black`)
- [ ] Unit tests with ≥70% coverage on core extraction logic
- [ ] All 8 project documents + all SKILL.md files versioned in the repo
- [ ] README with architecture diagram, setup instructions, and demo GIF
- [ ] CI/CD configured (GitHub Actions — at minimum tests run on PR)
- [ ] MIT or Apache 2.0 license, clean commit history

### 5.3 Visibility — the project must be discoverable
- [ ] Public GitHub repo with ≥20 stars (realistic for 8 weeks with outreach)
- [ ] One LinkedIn post with technical writeup, ≥100 reactions
- [ ] One longer-form writeup on Medium, Substack, or personal blog
- [ ] Demo video (≤5 min) on YouTube, embedded in README
- [ ] Submitted to at least one community: Hacker News, r/medicaldevices, or RAPS LinkedIn group

### 5.4 Network — the job-landing fuel
- [ ] ≥5 informational interviews completed with real RA / post-market professionals
- [ ] ≥3 of them give direct feedback on the tool (written or verbal)
- [ ] ≥10 LinkedIn connections at target medtech companies (Medtronic, Abbott, Stryker, Edwards, Intuitive, GE Healthcare, Philips, plus AI medtech: Aidoc, Viz.ai, Rad AI, Cleerly)
- [ ] Used as the lead portfolio piece in ≥5 internship or job applications

### 5.5 Failure Criteria (When to Stop or Pivot)
Abandon or restructure the project if, by **end of Week 3:**
- Claude extraction accuracy cannot exceed 70% despite iteration
- openFDA MAUDE data turns out to be too sparse for AI-enabled codes to show signal
- You cannot get a single informational interview scheduled after 15 outreach attempts (signals the problem isn't as real as the research suggests, or your outreach needs work)

---

## 6. Non-Goals (Explicit Out-of-Scope)

These items are tempting but excluded. They do not serve the job-landing goal and would blow up the 8-week timeline.

- ❌ **Not a company.** No LLC, no incorporation, no cofounders, no fundraising.
- ❌ **Not an FDA-cleared device.** This tool does not require its own 510(k).
- ❌ **Not a thesis or academic publication.** (Can happen later, but is not the goal.)
- ❌ **Not a full eQMS replacement.** Not competing with Greenlight Guru, MasterControl, Veeva.
- ❌ **Not a 510(k) submission consistency tool.** That's a separate gap (i-GENTIC territory).
- ❌ **Not a predicate device search tool.** Complizen handles that.
- ❌ **Not a clinical decision support tool.** Does not advise patient care.
- ❌ **Not handling PHI.** MAUDE is already de-identified and public.
- ❌ **Not multi-cloud or production-scale.** Runs on a laptop + Claude API.
- ❌ **Not multi-regulator.** U.S. FDA / MAUDE only. No EU MDR, no Health Canada, no PMDA.
- ❌ **Not a SaaS with user accounts, auth, billing, teams.** Pure open-source CLI + dashboard.
- ❌ **Not beautiful UI.** Streamlit defaults are fine. Function over form.
- ❌ **Not a chatbot or general Q&A tool.** Structured pipelines only.

---

## 7. Guiding Principles (Non-Negotiable)

1. **Regulatory integrity over speed.** No hallucinated citations. No fabricated 510(k) numbers. Every fact traceable.
2. **Human-in-the-loop by default.** The tool surfaces signals; humans decide actions. This is stated explicitly in README, code comments, and outputs.
3. **Reproducibility first.** Same input → same output. Deterministic prompt templates, versioned Skills, seed-fixed where possible.
4. **Ship working weekly.** Every week ends with something runnable end-to-end, even if minimal. No "it'll work once I finish integrating."
5. **Public by default.** Code, docs, Skills, prompts, and examples are all public. Private only if PHI-risk (none expected).
6. **Skills-driven, not prompt-spaghetti.** All LLM behavior lives in versioned `SKILL.md` files, not inline strings.
7. **Document before you code.** No function gets written before its behavior is specified in the relevant doc or SKILL.
8. **Depth over breadth.** One product code done excellently > five done poorly.
9. **Recruiter's-eye view.** Every artifact — code, README, commits, issues — should look good to a senior medtech hiring manager reading it on a Tuesday afternoon.

---

## 8. Users — Who This Tool Is Built For

Even though the primary goal is a job, the product must be **genuinely useful** to real users or it's worthless as a portfolio. Genuine utility is what makes recruiters take it seriously.

### 8.1 Primary User: Regulatory Affairs / Post-Market Surveillance Analyst
- Works at a medical device company (any size, but AI/ML device manufacturers most acute)
- Responsible for MAUDE monitoring under 21 CFR Part 803
- Currently spends 8–15 hrs/week on manual MAUDE searches
- Anxiety: missing a signal, failing an audit, compliance gap with QMSR 2026

### 8.2 Secondary User: Quality Engineer / CAPA Owner
- Initiates corrective actions based on postmarket signals
- Needs comparative data: our device vs. competitor devices in same product code

### 8.3 Tertiary User: Fellow Student / Researcher
- Studying AI medical device safety
- Will fork, extend, cite — generating GitHub stars and credibility

---

## 9. Critical Assumption to Validate Immediately

**You have not yet talked to any real RA/post-market professional.** This is the single largest risk to the entire project. Before committing to 8 weeks of build, you must validate:

1. Is manual MAUDE monitoring actually the pain I think it is?
2. Are AI-specific failures a real concern or theoretical?
3. Would a tool like this be useful, or is it a solution looking for a problem?

### Validation Gate (Week 1 — Non-Negotiable)

- [ ] Identify 20 target RA/post-market professionals on LinkedIn
- [ ] Send 20 cold outreach messages requesting 20-minute informational calls
- [ ] Complete at least 3 calls before end of Week 1
- [ ] Write up findings in `docs/00_customer_discovery.md`

**If all 3 calls confirm the pain is real → proceed with build.**
**If 2+ calls say "this isn't really a problem" → pause, re-scope, or pick a different project.**

This is the most important gate in the whole plan. Skipping it is how students build impressive tools nobody wants.

---

## 10. Competitive Landscape (What Already Exists)

- **DeviceWatch** — Closest competitor. Commercial, MAUDE-focused, uses Claude. Not open-source. Generic surveillance, not AI-specific.
- **i-GENTIC AI** — Submission consistency, not postmarket. Different gap.
- **Complizen** — Predicate research / guidance retrieval. Different gap.
- **Legacy eQMS (Greenlight, MasterControl, Veeva)** — Document management; do not solve signal detection.
- **FDA Elsa** — Internal FDA tool, does not train on industry data, not accessible externally.

**Your differentiator:** Open-source + AI-specific failure taxonomy + reproducible methodology + student-accessible. No one occupies this space publicly.

---

## 11. Constraints & Commitments

### 11.1 Time
- 20–40 hours/week for 6–8 weeks
- Protected weekly blocks on calendar — non-negotiable
- Clear stop date — don't let it sprawl past 8 weeks without honest re-scoping

### 11.2 Budget
- Claude API: ~$50–150 total (Sonnet for bulk extraction, Opus for reasoning)
- Domain / hosting (optional): <$30
- No cloud infra costs — laptop only

### 11.3 External Dependencies
- openFDA API remains free and accessible
- Anthropic Claude API remains available and pricing stable
- FDA guidance on AI/ML devices remains current within project window

---

## 12. What This Document Is and Is Not

**IS:**
- The standard every decision is checked against weekly
- The scope shield when you're tempted to add features
- The narrative backbone for README, LinkedIn post, and interview stories

**IS NOT:**
- Technical design (→ Document 5)
- Week-by-week plan (→ Document 7)
- Requirements specification (→ Document 3)

---

## 13. Change Control

Any change to this document must be:
1. Committed to Git with an explanation in the commit message
2. Reflected in a version bump (1.0 → 1.1 minor, → 2.0 major)
3. Justified against the core goal: "does this still serve landing a top medtech job?"

---

**End of Document 1.**
