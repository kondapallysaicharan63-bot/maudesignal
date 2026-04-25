# Document 6: Risk Register

**Project Name:** SafeSignal
**Owner:** [Your Name]
**Version:** 1.0 (Draft)
**Date:** [Today's Date]
**References:** Documents 1–5
**Review Cadence:** Weekly (Sunday, 30 min)

---

## 1. Purpose of This Document

This document enumerates everything that could kill or derail the project. Each risk has a likelihood, an impact, a mitigation, and an owner (you). Every Sunday, you review this document, update probabilities, and add any new risks you've discovered.

**Without this document, risks manifest as surprises in Week 6. With it, they manifest as decisions you made in Week 1.**

---

## 2. Risk Rating Scale

### 2.1 Likelihood
- **Low (L):** <20% probability over the project duration
- **Medium (M):** 20–60%
- **High (H):** >60%

### 2.2 Impact
- **Low:** Minor delay or quality hit (<1 week recoverable)
- **Medium:** Meaningful setback (1–2 weeks, scope adjustment)
- **High:** Threatens project viability (requires restructure)
- **Critical:** Project fails or ships unusable

### 2.3 Priority (= Likelihood × Impact)
- **P1 — Critical:** Immediate mitigation required
- **P2 — High:** Mitigation plan in place, monitored weekly
- **P3 — Medium:** Aware, reviewed monthly
- **P4 — Low:** Logged, no active action

---

## 3. Risk Register

### 3.1 Scope & Execution Risks

| ID | Risk | L | I | P | Mitigation | Owner |
|---|---|---|---|---|---|---|
| R-01 | **Scope creep** — I keep adding features past the 7 in Charter §4 | H | H | **P1** | Hard cap enforced via Document 2; weekly review; any new feature requires removing an existing one | Self |
| R-02 | **Gold standard labeling skipped** — I don't actually hand-label 100 records | M | H | **P2** | Budget 4 hrs in Week 2; treat as a gate; no extraction quality claims without this | Self |
| R-03 | **Week 4–5 motivation dip** — classic mid-project collapse | H | H | **P1** | Buffer week; rest day scheduled; social accountability (share weekly update publicly) | Self |
| R-04 | **Over-engineering early** — spending Week 1 on perfect architecture instead of shipping | M | M | **P3** | Working product end of every week; no refactor without user-facing benefit | Self |
| R-05 | **Documentation drift** — code diverges from Documents 1–5 silently | M | M | **P3** | Architecture review checkpoint end of Week 2 (Doc 5 §16); doc updates included in "definition of done" | Self |
| R-06 | **Timeline slip** — 8 weeks becomes 12 | M | H | **P2** | Hard stop Week 10 per Charter §16; cut scope before extending time | Self |

### 3.2 Technical Risks

| ID | Risk | L | I | P | Mitigation | Owner |
|---|---|---|---|---|---|---|
| R-07 | **Claude extraction accuracy stalls <80%** | M | H | **P2** | Iterate Skills (not models); add few-shot examples; split into simpler sub-skills; if stuck after 3 iterations → escalate or scope down | Self |
| R-08 | **openFDA API rate limits block development** | M | M | **P3** | Cache aggressively in Week 1; request API key for higher limits; batch requests | Self |
| R-09 | **openFDA API change or outage mid-project** | L | H | **P3** | Pre-download 12 months of MAUDE data by end of Week 1 (local cache); verify offline operation | Self |
| R-10 | **MAUDE data sparsity for AI-enabled codes** | M | **Critical** | **P1** | Pilot query in Week 1 Day 1; if <500 records per target code over 12 months, pivot product code selection or expand window | Self |
| R-11 | **Hallucinated regulatory citations slip through** | M | **Critical** | **P1** | Mandatory verifier pre-output (FR-24); test set of 200 outputs checked; zero tolerance | Self |
| R-12 | **Claude API pricing change** | L | M | **P4** | Monitor pricing; pin models; $150 budget has 2x safety margin | Self |
| R-13 | **LLM non-determinism breaks reproducibility tests** | H | M | **P2** | Accept NFR-14 ceiling (95% agreement on structured fields); use temperature=0 where possible; don't test exact string match | Self |
| R-14 | **Drift detection produces false positives/negatives** | M | M | **P3** | Use well-established statistical tests (KS, PSI); tune thresholds on synthetic data; document known limitations | Self |
| R-15 | **Streamlit performance degrades on 10K+ records** | L | M | **P4** | Paginate tables; memoize expensive queries; defer real optimization unless NFR-03 fails | Self |
| R-16 | **Subtle data quality bug corrupts extractions** | M | H | **P2** | Gold-set evaluation catches drift; integration tests; code review (at minimum via Git diff self-review) | Self |
| R-17 | **Local SQLite DB corruption on crash** | L | L | **P4** | Use SQLite WAL mode; raw data immutable and re-fetchable | Self |

### 3.3 Customer Discovery & Validation Risks

| ID | Risk | L | I | P | Mitigation | Owner |
|---|---|---|---|---|---|---|
| R-18 | **Nobody responds to LinkedIn outreach** | M | **Critical** | **P1** | Send 20, not 5; personalize each; offer value (share a finding) instead of asking; iterate message weekly | Self |
| R-19 | **Customer discovery confirms the problem isn't real** | L | **Critical** | **P2** | Gate 0 → 1 forces this check early; if confirmed, pivot or stop; cheaper to learn in Week 1 than Week 8 | Self |
| R-20 | **Discovery calls give generic positive feedback** (you don't learn anything real) | M | H | **P2** | Use "Mom Test" questions — ask about past behavior, not future intent; ask about problems, not solutions | Self |
| R-21 | **I skip customer discovery because coding is more fun** | H | H | **P1** | Hard gate in Charter §7; no production code until Gate 0 passes; social accountability | Self |

### 3.4 Career / Outcome Risks

| ID | Risk | L | I | P | Mitigation | Owner |
|---|---|---|---|---|---|---|
| R-22 | **Project ships but recruiters don't notice** | M | H | **P2** | Visibility plan (§5.3 of Doc 1): LinkedIn post, Medium writeup, Hacker News, community submissions; ≥5 cold applications using project | Self |
| R-23 | **Employer sees the project as too niche** | M | M | **P3** | Narrative framing: "AI + regulatory + engineering" not "MAUDE surveillance"; broaden applicable roles (RA, QA, AI safety, ML engineer in medtech) | Self |
| R-24 | **Open-source license issues with a future employer** | L | M | **P4** | MIT license is universally employer-safe; no NDA constraints as a student | Self |
| R-25 | **Someone builds the same thing and ships it first** | L | M | **P4** | Low probability in 8 weeks; announce a beta by Week 6 to plant flag; differentiate via taxonomy + docs | Self |
| R-26 | **The project lands a job that's not actually a good fit** | M | M | **P3** | Be clear on target roles (RA, post-market quality, AI safety in medtech) before applying; use project as filter, not just bait | Self |

### 3.5 Personal & Time Risks

| ID | Risk | L | I | P | Mitigation | Owner |
|---|---|---|---|---|---|---|
| R-27 | **Coursework crunch consumes project hours** | H | H | **P1** | Calendar blocks protected; sacrifice depth on one Skill rather than skip outreach; stop-date Week 10 is firm | Self |
| R-28 | **Burnout / health issue** | M | H | **P2** | 1 day/week off is mandatory, not optional; cap at 40 hrs/week even if motivated; talk to someone if >2 bad days in a row | Self |
| R-29 | **Family / life emergency** | L | H | **P3** | Buffer week; project can pause for a week without dying; scope was chosen to be pause-resilient | Self |
| R-30 | **Loneliness / no peer feedback** | M | M | **P3** | Find 1 technical peer for weekly check-in; engage with maintainers of similar open-source repos; join 1 Discord/Slack community | Self |

### 3.6 Regulatory & External Risks

| ID | Risk | L | I | P | Mitigation | Owner |
|---|---|---|---|---|---|---|
| R-31 | **FDA issues new AI/ML guidance that invalidates approach** | L | H | **P3** | Low probability in 8 weeks; monitor FDA press releases; document assumption in Charter §12 | Self |
| R-32 | **Someone interprets my tool as regulatory advice** | L | H | **P3** | Prominent disclaimers in README, every report, every dashboard (FR-33); human-in-the-loop language everywhere | Self |
| R-33 | **MAUDE data used incorrectly — defamation or liability risk** | L | M | **P4** | Only summarize/reframe public data; never name manufacturers in a negative statement without the MDR ID cited; cite sources in every claim | Self |
| R-34 | **Anthropic changes TOS or model availability** | L | M | **P4** | Keep prompts portable to other providers; monitor Anthropic announcements | Self |

---

## 4. Top 5 Risks to Actively Mitigate Starting Week 1

These are the P1 risks that deserve the most attention. Revisit weekly:

1. **R-01 — Scope creep.** Checked every Sunday against Charter §4.
2. **R-10 — MAUDE data sparsity.** Validated by Monday of Week 1 via pilot query.
3. **R-11 — Hallucinated citations.** Verifier built first; zero-tolerance test on every sample.
4. **R-18 / R-21 — Discovery failure.** 20 outreaches in Week 1 is non-negotiable.
5. **R-27 — Coursework crunch.** Calendar blocks protected from Day 1.

---

## 5. Risk Review Process

### 5.1 Weekly Review (every Sunday, 30 min)

For each active P1 and P2 risk:
- Has likelihood changed (up or down)?
- Has impact changed?
- Is mitigation still working?
- Are there new risks discovered this week?

Update version bump: `1.0 → 1.1, 1.2, ...`

### 5.2 When to Escalate a Risk to P1

- It actually happens → emergency response triggered
- Likelihood moves from L to M on a High-impact risk
- Multiple related risks compound (e.g., R-07 + R-11 together = extraction pipeline is the bottleneck)

### 5.3 When to Retire a Risk

- Mitigation is proven effective for 3+ weeks
- Risk window has closed (e.g., R-10 retired after Week 1 data pilot passes)

---

## 6. Contingency Plans (For P1 Risks Only)

### 6.1 If R-10 triggers (MAUDE data too sparse)
- Switch from radiology product codes to cardiovascular (QDI, DQK) — second-highest AI/ML clearance category
- Extend time window from 12 months to 36 months
- If still sparse: pivot the project from postmarket to pre-market (510(k) summary analysis) and update Doc 1 accordingly

### 6.2 If R-11 triggers (citations hallucinate)
- Disable all regulatory citation output until verifier is fixed
- Every public claim in README includes a source link
- Do not ship a version that might cite fake CFR sections — reputational damage too high

### 6.3 If R-18 triggers (no LinkedIn responses)
- Rewrite outreach template (3 variants, A/B test)
- Offer a clear value exchange: "I'll share my findings on AI device recalls in exchange for 20 min"
- Expand target list from RA professionals to QA, clinical affairs, and medtech product managers
- Ask SJSU alumni via the career center

### 6.4 If R-21 triggers (I skip discovery because coding is fun)
- Close the laptop. Do not open the IDE.
- Re-read Charter §9 and §15 (commitment contract)
- Send 5 outreach messages before any more code
- Text an accountability partner (pre-arranged)

### 6.5 If R-27 triggers (coursework crunch)
- Cut Feature F7 (PSUR report) first — lowest visibility impact
- Then cut Feature F6 polish (keep dashboard minimal)
- Maintain F1–F5 (the core pipeline) at all costs

---

## 7. Risk Log (Things That Actually Happened)

This section is filled in as the project progresses. Each entry:

```
Date: YYYY-MM-DD
Risk ID: R-XX
What happened:
Mitigation taken:
Outcome:
Lesson learned:
```

(Empty at project start.)

---

## 8. What This Document Is and Is Not

**IS:**
- Weekly check-in tool
- Contingency plan for P1 risks
- Evidence of serious project thinking (recruiters who read this will notice)

**IS NOT:**
- Comprehensive (new risks get added weekly — this is a living doc)
- A substitute for good judgment
- A reason to procrastinate (risk documentation is not project execution)

---

**End of Document 6.**
