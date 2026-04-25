# Document 8: Glossary

**Project Name:** SafeSignal
**Owner:** [Your Name]
**Version:** 1.0 (Draft)
**Date:** [Today's Date]
**References:** All preceding documents

---

## 1. Purpose of This Document

Regulated industries live and die by precise terminology. Using "approval" when you mean "clearance," or confusing "510(k)" with "PMA," signals amateur in any conversation with RA professionals. This glossary defines every domain, technical, and project-specific term used anywhere in SafeSignal's documentation, code, or outputs.

**Use this document three ways:**
1. As study material — read it once in Week 1
2. As a reference when writing docs, code, or outreach messages
3. As the authoritative source when terms disagree elsewhere

---

## 2. FDA Regulatory Terms

### **510(k)**
Premarket notification submitted under Section 510(k) of the Federal Food, Drug, and Cosmetic Act. Used for Class II medical devices (and some Class I). Demonstrates that the new device is **substantially equivalent** to a legally marketed predicate device. Results in FDA **clearance** (not approval).

### **AE (Adverse Event)**
Any undesirable experience associated with use of a medical device. In FDA terminology, an AE can involve death, serious injury, or device malfunction. Reported via MDR into MAUDE.

### **ALCOA+**
Data integrity principles required in FDA-regulated environments. Stands for **A**ttributable, **L**egible, **C**ontemporaneous, **O**riginal, **A**ccurate — plus **C**omplete, **C**onsistent, **E**nduring, and **A**vailable. Applies to all electronic records, including LLM-generated outputs.

### **CAPA (Corrective and Preventive Action)**
Systematic process for investigating, correcting, and preventing the recurrence of quality problems. Required under FDA QSR / QMSR and ISO 13485.

### **CDRH**
Center for Devices and Radiological Health — the FDA division responsible for medical devices. (Distinct from CDER for drugs, CBER for biologics.)

### **CFR (Code of Federal Regulations)**
Codified U.S. federal regulations. Medical device regulations live in Title 21, primarily Parts 800–899. Key parts for this project:
- **21 CFR Part 803** — Medical Device Reporting (MDR)
- **21 CFR Part 807** — Establishment Registration, Device Listing, 510(k)
- **21 CFR Part 820** — Quality System Regulation (being replaced by QMSR)

### **Clearance vs. Approval**
**Clearance** = FDA's decision on a 510(k) — the device can be legally marketed because it's substantially equivalent to a predicate. **Approval** = FDA's decision on a PMA (higher-risk Class III devices) — the device has independently demonstrated safety and effectiveness. These are not interchangeable.

### **De Novo Classification**
Pathway for **novel low-to-moderate-risk devices** that have no valid predicate. Creates a new device type and classification.

### **eSTAR**
FDA's mandatory electronic submission template for 510(k) applications (and increasingly other submission types).

### **FDA Elsa**
"Electronic Language System Assistant" — FDA's internal AI copilot (deployed 2025) that helps reviewers summarize submissions, flag gaps, and organize documents. Runs on AWS GovCloud. **Does not train on industry submissions.**

### **GMLP (Good Machine Learning Practice)**
FDA's 10 guiding principles for ML-enabled medical device development. Joint principles with Health Canada and UK MHRA.

### **IDE (Investigational Device Exemption)**
Permission to conduct a clinical investigation of an unapproved device.

### **IFU (Instructions for Use)**
Labeling component — how the device is intended to be used.

### **Indications for Use**
Specific clinical conditions, populations, and settings in which the device is intended to be used. A narrower concept than Intended Use.

### **Intended Use**
The general purpose or function of the device. Broader than indications for use.

### **MAUDE (Manufacturer and User Facility Device Experience)**
FDA's publicly searchable database of medical device adverse event reports from 1991 onward. Updated monthly. Does not currently support AI-specific failure fields. The central data source for SafeSignal.

### **MDR (Medical Device Report)**
The individual adverse event report filed under 21 CFR Part 803 that populates MAUDE.

### **MDR-Reportable Event**
An event that, under 21 CFR 803, must be reported by a manufacturer, importer, or user facility. Examples: device-associated death, serious injury, malfunction that could cause death/injury if it recurred.

### **MedSun (Medical Product Safety Network)**
FDA's enhanced adverse event reporting program launched in 2002, focused on collaboration with hospital-based reporters. Different from MAUDE (broader reporter base).

### **PCCP (Predetermined Change Control Plan)**
FDA mechanism (introduced 2019, formalized in guidance 2023+) allowing manufacturers to specify in advance which AI/ML model updates are permitted without requiring a new 510(k) submission. Scope must be defined; within-scope changes can be implemented post-market without new review.

### **PMA (Premarket Approval)**
Most stringent FDA review pathway — applies to Class III (high-risk, life-sustaining) devices. Requires independent demonstration of safety and effectiveness through clinical trials.

### **Postmarket Surveillance**
Monitoring of medical devices after they enter the market. Includes MDR reporting, registries, literature monitoring, and real-world performance assessment. Focus of SafeSignal.

### **Predicate Device**
A legally marketed device used to establish substantial equivalence in a 510(k) submission.

### **PSUR (Periodic Safety Update Report)**
Structured periodic safety report. The term originates in EU MDR and pharma; FDA uses similar "Periodic Safety" concepts under Section 522 and the Quality System. SafeSignal produces PSUR-style reports from MAUDE data.

### **QMSR (Quality Management System Regulation)**
FDA rule (effective February 2, 2026) that replaces 21 CFR Part 820 by incorporating ISO 13485:2016 by reference. Aligns U.S. medical device quality system requirements with international standards. **Key driver for SafeSignal's timing.**

### **QSR (Quality System Regulation)**
The existing U.S. medical device quality system rule (21 CFR Part 820). Being superseded by QMSR.

### **Recall**
Mandatory or voluntary removal or correction of a marketed medical device. FDA Recall Database tracks these separately from MAUDE.

### **RTA (Refuse to Accept)**
FDA's early screening decision on a 510(k) submission — if the submission fails preliminary completeness checks, it is refused without substantive review. Inconsistencies between documents are a leading RTA cause.

### **RWD (Real-World Data) / RWE (Real-World Evidence)**
Data collected outside of traditional clinical trials (registries, EHRs, claims, device telemetry) and the evidence derived from it. FDA increasingly accepts RWE in regulatory decisions.

### **SaMD (Software as a Medical Device)**
Software that, by itself, constitutes a medical device (e.g., an AI that reads CT scans). Distinct from software in a medical device (firmware on a pacemaker).

### **Substantial Equivalence (SE)**
The legal standard for 510(k) clearance — the new device has the same intended use and the same technological characteristics as a predicate (or different characteristics that do not raise new safety/effectiveness questions).

### **TPLC (Total Product Life Cycle)**
FDA's framework for continuous oversight across design, clearance, deployment, updates, and retirement. Especially relevant for AI/ML devices that learn or update.

### **UDI (Unique Device Identifier)**
A system for identifying each medical device through distribution and use. Comprises Device Identifier (DI) and Production Identifier (PI).

### **Warning Letter**
FDA's formal written notification to a manufacturer of a significant regulatory violation. Public document. Strong career-ending event for those involved.

---

## 3. AI / Machine Learning Terms

### **Automation Bias**
Tendency of human users to over-rely on AI outputs and under-check their own judgment. A recognized risk for AI-enabled medical devices.

### **Concept Drift**
Change in the statistical properties of the target variable (y) over time — i.e., the relationship between inputs and outputs shifts. Example: an AI trained to detect pneumonia from chest X-rays may degrade as radiographic techniques or patient populations shift.

### **Covariate Shift**
Change in the distribution of input features (X) while the mapping from X to y is assumed stable. Example: hospital acquires a new CT scanner whose images look different.

### **Distribution Shift**
Umbrella term covering both concept drift and covariate shift.

### **Drift Detection**
Statistical techniques for identifying when model inputs or outputs diverge from expected/training distribution. SafeSignal uses Kolmogorov-Smirnov (KS) test and Population Stability Index (PSI).

### **False Negative / False Positive**
- **False Negative:** Model says "negative" when ground truth is "positive" (missed detection — potentially deadly in medical AI)
- **False Positive:** Model says "positive" when ground truth is "negative" (false alarm — causes unnecessary workup)

### **GMLP** — see FDA Regulatory Terms.

### **Ground Truth**
The reference standard against which model predictions are evaluated. In medical AI, typically expert-annotated or derived from pathology/follow-up.

### **Hallucination**
LLM output that is confident but unsupported by source data or reality. In regulated contexts, includes fabricated 510(k) numbers, fake CFR citations, or invented guidance document titles. **Zero-tolerance in SafeSignal** (FR-24).

### **KS Test (Kolmogorov-Smirnov Test)**
Non-parametric statistical test for whether two samples come from the same distribution. Used in SafeSignal to detect covariate shift.

### **LLM (Large Language Model)**
Foundation model trained on large text corpora. Claude is an LLM. Used in SafeSignal for structured extraction and classification of MAUDE narratives.

### **Model Card**
Structured document (per Mitchell et al. 2019; adopted by FDA in 2024–25 AI/ML guidance, Appendix F) describing an AI model: intended use, performance, limitations, training data, evaluation data, bias considerations.

### **PSI (Population Stability Index)**
Metric for measuring how much a distribution has shifted between two time periods. Used for drift monitoring.

### **RAG (Retrieval-Augmented Generation)**
LLM architecture pattern that retrieves relevant documents before generating output, grounding responses in verifiable sources. SafeSignal's `fda-guidance-retriever` Skill uses RAG.

### **Subgroup Degradation**
Performance drop for a specific demographic subgroup (sex, age, race, equipment type) while overall aggregate performance appears stable. Classic case of Simpson's Paradox in medical AI.

### **Substantial Equivalence** — see FDA Regulatory Terms.

---

## 4. SafeSignal Project-Specific Terms

### **AI Failure Taxonomy**
SafeSignal's classification of AI-specific failure modes not captured by MAUDE's native schema. Minimum 5 categories: `concept_drift`, `covariate_shift`, `subgroup_degradation`, `false_negative_pattern`, `false_positive_pattern`, `automation_bias`, `not_ai_related`.

### **Citation Verifier**
SafeSignal's module (`verifier/`) and Skill (`regulatory-citation-verifier`) that validates every regulatory citation in every output against primary sources. Mandatory pre-output gate.

### **Drift Simulator**
SafeSignal's synthetic performance-data generator that injects known drift patterns to validate the drift detector.

### **Extraction**
SafeSignal's process of converting unstructured MAUDE narratives into structured JSON records via Claude + Skill.

### **Gate (Go / No-Go Gate)**
A binary checkpoint at the end of each project phase. Gates cannot be skipped. Failing a gate triggers re-scope or pause.

### **Gold Set / Gold Standard Test Set**
100 hand-labeled MAUDE records used to measure extraction and classification accuracy (FR-08, §5 of Doc 3).

### **Phase 0–4**
SafeSignal's 4 execution phases:
- **Phase 0** — Documentation + Discovery (Week 1)
- **Phase 1** — Ingestion + Extraction (Weeks 2–3)
- **Phase 2** — Classification + Drift (Weeks 4–5)
- **Phase 3** — Dashboard + Report (Weeks 6–7)
- **Phase 4** — Launch + Outreach (Week 8+)

### **SKILL.md**
Versioned Markdown file defining a Claude Skill — the prompt, procedure, inputs, outputs, examples, and rules for one specific LLM task. SafeSignal has 7 Skills.

### **Skill (Claude Skill)**
A structured, versioned behavior contract that Claude follows for a specific task. Stored as `SKILL.md` files in `skills/<name>/`. Distinct from human skills (Document 4).

### **v1.0**
The target MVP release, due end of Week 8. No features will be added post-v1.0 during the current project phase.

---

## 5. Tech Stack Terms (Quick Reference)

### **Anthropic Claude API**
Anthropic's LLM inference service. SafeSignal uses Claude Sonnet (bulk extraction) and Claude Opus (complex reasoning).

### **Evidently**
Open-source Python library for ML monitoring and drift detection. Used for KS test and PSI computation.

### **openFDA**
FDA's public API platform exposing device adverse events, recalls, 510(k)s, and drug data. `https://open.fda.gov`.

### **Pydantic**
Python library for data validation using type hints. Used for validating Claude's JSON outputs against schemas.

### **SQLAlchemy (Core)**
Explicit, SQL-first Python database toolkit. Used for SafeSignal's storage layer (not the ORM mode — Core only).

### **SQLite**
File-based relational database built into Python's standard library. SafeSignal's v1 database.

### **Streamlit**
Python framework for building data dashboards with minimal frontend code. SafeSignal's dashboard UI.

### **Typer**
Python library for building typed CLIs from regular functions. SafeSignal's CLI entry points.

---

## 6. Organizations & Resources

### **CDRH** — see FDA Regulatory Terms.

### **CDRH Learn**
FDA's free online training platform for medical device professionals.

### **FDA (U.S. Food and Drug Administration)**
U.S. federal agency responsible for regulating medical devices, drugs, biologics, food, cosmetics, and tobacco.

### **IMDRF (International Medical Device Regulators Forum)**
International body harmonizing medical device regulation. Source of many common codes and taxonomies.

### **ISO 13485**
International standard for quality management systems for medical devices. Being incorporated by reference into U.S. QMSR (effective Feb 2026).

### **RAPS (Regulatory Affairs Professionals Society)**
Global professional organization for regulatory affairs. Source of RAC certification.

---

## 7. Non-Obvious Usage Notes

### "The device was cleared"
Correct for 510(k). Use "approved" only for PMA devices.

### "FDA-approved AI"
Usually incorrect. Most AI medical devices are FDA-**cleared** (510(k)) or authorized (De Novo), not approved.

### "Substantial equivalence"
A legal standard, not a technical one. Saying "our AI is substantially equivalent" in casual conversation is a red flag to RA professionals.

### "AI/ML-based device"
FDA's preferred phrasing. "AI device" is fine in casual writing, but "AI/ML-enabled device" or "AI/ML-based device" is more precise.

### "Postmarket surveillance" vs. "Post-market surveillance"
Both are used. FDA uses "postmarket" (one word). Stick to the same convention within a single document.

### "Adverse event" vs. "MDR"
An AE is the clinical event. An MDR is the regulatory report about the AE. They are related but not identical.

---

## 8. Terms to Add as You Learn Them

Keep this list open during customer discovery calls and FDA document reading. Every unfamiliar term goes here. Version bump monthly.

- [ ] _Add new terms here as encountered_

---

## 9. What This Document Is and Is Not

**IS:**
- The authoritative term reference for all SafeSignal artifacts
- Training material for the builder
- A credibility signal for readers who audit the docs

**IS NOT:**
- A complete FDA regulatory textbook (go read the real ones)
- Legal advice
- A substitute for reading primary sources

---

**End of Document 8.**
