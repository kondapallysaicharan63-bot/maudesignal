# Document 4: Skills Matrix & Learning Plan

**Project Name:** MaudeSignal
**Owner:** [Your Name]
**Version:** 1.0 (Draft)
**Date:** [Today's Date]
**References:** Documents 1–3

---

## 1. Purpose of This Document

This is an honest inventory of every skill required to execute this project, your current level in each, the gap, and how you will close it. It serves three purposes:

1. **Diagnostic:** You cannot plan time if you don't know what you need to learn.
2. **Evidence:** For job applications, this document maps to concrete capabilities you now have.
3. **Anti-overestimation:** Students commonly assume they'll "figure it out." This document forces you to schedule learning time the same way you schedule coding time.

**Rule:** Fill in your current level honestly. Nobody sees this but you. Lying here costs you weeks later.

---

## 2. Skill Level Definitions

| Level | Definition |
|---|---|
| **0 — None** | Never touched it. Can't define the core concepts. |
| **1 — Aware** | Heard of it. Can explain what it is but can't use it. |
| **2 — Beginner** | Can follow tutorials. Needs constant reference. |
| **3 — Working** | Can use it for real tasks with occasional lookup. |
| **4 — Proficient** | Can teach it. Recognized in a professional context. |
| **5 — Expert** | Industry reference level. |

**For this project, Level 3 is the floor for core skills.** Level 2 is okay for supporting skills.

---

## 3. Skills Matrix

### 3.1 Core Technical Skills

| # | Skill | Required | Current | Gap | How to Close | Time Budget | Deadline |
|---|---|---|---|---|---|---|---|
| 1 | **Python (core)** | 3 | ? | ? | Write daily; lean on Claude for review | Ongoing | Week 1 |
| 2 | **Python typing (`typing`, `mypy`)** | 3 | ? | ? | mypy docs + real PRs | 4 hrs | Week 2 |
| 3 | **REST API integration (`requests`)** | 3 | ? | ? | Real Python tutorial | 3 hrs | Week 1 |
| 4 | **Pandas / data wrangling** | 3 | ? | ? | Kaggle "Pandas" micro-course | 6 hrs | Week 1 |
| 5 | **SQLite / SQL basics** | 2 | ? | ? | SQLBolt + sqlite3 tutorial | 4 hrs | Week 2 |
| 6 | **Claude API (Anthropic SDK)** | 3 | ? | ? | Official docs; prompt lab | 6 hrs | Week 1 |
| 7 | **Prompt engineering (structured outputs)** | 3 | ? | ? | Anthropic prompt guide | 5 hrs | Week 1 |
| 8 | **Streamlit** | 2 | ? | ? | Streamlit official tutorial | 4 hrs | Week 5 |
| 9 | **Git & GitHub workflow** | 3 | ? | ? | Already doing daily | Ongoing | Week 1 |
| 10 | **pytest** | 2 | ? | ? | pytest docs + write first test | 3 hrs | Week 2 |
| 11 | **GitHub Actions (CI/CD)** | 2 | ? | ? | Copy a template workflow | 3 hrs | Week 6 |

### 3.2 Data & ML Skills

| # | Skill | Required | Current | Gap | How to Close | Time Budget | Deadline |
|---|---|---|---|---|---|---|---|
| 12 | **Statistics for drift (KS test, PSI)** | 2 | ? | ? | Khan Academy stats + Evidently docs | 5 hrs | Week 4 |
| 13 | **`evidently.ai` library** | 2 | ? | ? | Official tutorial | 3 hrs | Week 4 |
| 14 | **Schema design (JSON Schema)** | 2 | ? | ? | json-schema.org tutorial | 2 hrs | Week 2 |
| 15 | **Time-series basics** | 2 | ? | ? | pandas time-series docs | 2 hrs | Week 4 |

### 3.3 Domain (FDA Regulatory) Skills

| # | Skill | Required | Current | Gap | How to Close | Time Budget | Deadline |
|---|---|---|---|---|---|---|---|
| 16 | **510(k) pathway fundamentals** | 3 | ? | ? | FDA CDRH Learn modules | 4 hrs | Week 1 |
| 17 | **MAUDE database structure & fields** | 3 | ? | ? | MAUDE data dictionary + openFDA docs | 3 hrs | Week 1 |
| 18 | **FDA AI/ML device guidance (2025)** | 3 | ? | ? | Read guidance doc (cover-to-cover) | 4 hrs | Week 1 |
| 19 | **GMLP (Good Machine Learning Practice)** | 2 | ? | ? | FDA GMLP guiding principles | 2 hrs | Week 2 |
| 20 | **QMSR / ISO 13485 basics** | 2 | ? | ? | FDA QMSR summary + blog overviews | 3 hrs | Week 3 |
| 21 | **21 CFR Part 803 (MDR reporting)** | 2 | ? | ? | eCFR full read of Part 803 | 3 hrs | Week 2 |
| 22 | **PCCP (Predetermined Change Control Plan)** | 1 | ? | ? | FDA PCCP guidance — skim | 1 hr | Week 3 |
| 23 | **PSUR structure (EU MDR-style)** | 2 | ? | ? | Example PSURs online; template | 2 hrs | Week 6 |

### 3.4 Professional / Soft Skills

| # | Skill | Required | Current | Gap | How to Close | Time Budget | Deadline |
|---|---|---|---|---|---|---|---|
| 24 | **Cold outreach (LinkedIn)** | 3 | ? | ? | Send 20 in Week 1, learn by doing | 3 hrs | Week 1 |
| 25 | **Customer discovery interviews** | 2 | ? | ? | Read "The Mom Test" (book) | 4 hrs | Week 1 |
| 26 | **Technical writing** | 3 | ? | ? | Practice via these docs themselves | Ongoing | — |
| 27 | **Demo video production** | 2 | ? | ? | Loom or OBS + script | 3 hrs | Week 7 |
| 28 | **Pitch/narrative for interviews** | 3 | ? | ? | Practice 3-min and 10-min versions | 2 hrs | Week 8 |
| 29 | **Open-source repo hygiene** | 2 | ? | ? | Study 3 high-quality repos | 2 hrs | Week 6 |

### 3.5 Already Strong (Your BME Background)

| # | Skill | Level | Relevance |
|---|---|---|---|
| A | Biomedical engineering fundamentals | 3–4 | Framing clinical context |
| B | Clinical domain knowledge | 3 | Understanding MAUDE narratives |
| C | Research paper literacy | 3 | Reading Babic et al. and FDA guidance |
| D | Academic writing | 3 | The docs themselves |

**Don't underestimate these.** They are your moat against pure CS candidates applying for the same medtech roles.

---

## 4. Total Learning Time Budget

Summing the "Time Budget" column for all gaps you have: roughly **40–80 hours** of focused learning over 8 weeks, depending on starting levels. This is budgeted **within** your 20–40 hrs/week commitment — not on top of it.

**Recommended allocation:**
- Week 1: ~10 hrs learning (heavy front-load — FDA docs, Claude API, MAUDE)
- Weeks 2–3: ~5 hrs/week (Python typing, SQL, pytest)
- Weeks 4–5: ~4 hrs/week (stats, drift detection)
- Weeks 6–7: ~3 hrs/week (Streamlit polish, demo production)
- Week 8: ~2 hrs (interview prep)

---

## 5. Prioritized Learning Resources

### 5.1 Non-Negotiable (Week 1, in this order)
1. **FDA CDRH Learn — 510(k) Overview** (free, ~90 min) — `https://www.fda.gov/training-and-continuing-education/cdrh-learn`
2. **FDA Final Guidance: "AI-Enabled Device Software Functions" (2025)** — download PDF, read cover-to-cover, 3–4 hours
3. **MAUDE data dictionary** — `https://open.fda.gov/apis/device/event/`
4. **Anthropic Claude API docs + prompt engineering guide** — `https://docs.claude.com`
5. **Babic et al. paper** — *npj Digital Medicine*, 2025 — your anchor citation

### 5.2 High-Value (Weeks 2–3)
6. Rob Fitzpatrick, *The Mom Test* (book, 150 pages, 4 hrs) — customer discovery
7. FDA GMLP Guiding Principles (10 principles, short read)
8. 21 CFR Part 803 full text (eCFR)
9. Real Python — Pandas and requests tutorials

### 5.3 Tactical (Just-in-Time)
- Streamlit — wait until Week 5
- GitHub Actions — copy a template in Week 6
- Evidently.ai — Week 4 only, don't front-load

### 5.4 Avoid for Now (Not in Scope)
- Full ML / deep learning courses (you're using Claude, not training models)
- React / full-stack web dev (not needed)
- AWS / cloud certifications (not needed)
- FDA PMA process (you're not submitting one)

---

## 6. Daily & Weekly Rhythm (to protect learning time)

**Daily (suggested 5-hr block):**
- 30 min — reading / learning (FDA docs, papers)
- 3 hrs — building (code + Skills)
- 1 hr — documentation / writing
- 30 min — outreach / admin (LinkedIn, email, Git commits)

**Weekly (Sunday 1-hr review):**
- Check skills matrix — update any gaps closed
- Log hours per category
- Set 3 specific goals for the week
- Revisit Document 2 commitment contract

---

## 7. Claude Skills vs Human Skills — Important Distinction

**Human skills (this document):** Things *you* need to know to build the project.

**Claude Skills (`SKILL.md` files — see Document 5):** Instructions *Claude* follows when performing specific tasks in the system.

These are two different things. This document is only about you.

---

## 8. How to Fill In the "?" Cells

You have two choices:

**Option A — Honest self-assessment right now:**
- For each skill, rate yourself 0–5 using the definitions in §2
- Don't look things up; go by gut
- If unsure between two levels, pick the lower one

**Option B — Evidence-based assessment (better):**
- For each skill, find a concrete piece of evidence
- Python 3? "I can write a Pandas group-by without Googling."
- FDA AI guidance 3? "I've read the full document and can explain the TPLC approach."
- No evidence → Level ≤1

**Do this today. Not later. The gaps only close if you see them.**

---

## 9. Skills You Will Acquire From This Project (Keep This List)

By the time v1.0 ships, you will have demonstrated:

- ✅ End-to-end Python engineering (ingestion → storage → processing → UI)
- ✅ LLM application development with Claude API
- ✅ Prompt/Skill engineering for regulated domains
- ✅ FDA regulatory domain fluency (510(k), MAUDE, AI/ML guidance, QMSR)
- ✅ Statistical drift detection
- ✅ Data pipeline design
- ✅ Open-source project hygiene (tests, CI, docs, licensing)
- ✅ Technical writing (~25 pages of docs)
- ✅ Customer discovery / professional interviewing
- ✅ Product thinking (scope, gates, tradeoffs)

**This combination of skills is what top medtech employers are looking for in 2026.** Write them into your resume's Skills section verbatim, with evidence links (GitHub, docs, writeup).

---

## 10. Change Control

Update this document weekly during your Sunday review. Strikethrough skills as you level up. Add new skills you discover you need. Version bump if major changes.

---

**End of Document 4.**
