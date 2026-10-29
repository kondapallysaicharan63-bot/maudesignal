# Signal Evaluation & CAPA Dossier — regulatory sources

HACKATHON-BUILT — Meta Global AI Developer Hackathon (Oct 26 – Nov 4, 2026).

The layout of the dossier PDF (`src/maudesignal/dossier/`) was modeled on the
primary sources below, read on 2026-10-27. MaudeSignal does not claim
compliance with any of them. The dossier is a draft working record for a
human QA/RA reviewer; nothing in it is filed with FDA.

| Topic | What the dossier takes from it | Source |
|---|---|---|
| FDA Form 3500A (MedWatch, mandatory) | Section letters and item numbers of the MDR worksheet table: A Patient, B Adverse event or product problem (B1–B7), C Suspect products, D Suspect medical device (D1 brand name, D2a procode, D2b common device name, D3 manufacturer, D4 model/lot/catalog/UDI, D5–D10), E Initial reporter, F User facility/importer, G All manufacturers (G1 contact office, G2 report source, G3 date received by manufacturer, G4 PMA/510(k) number, G6 type of report, G7 adverse event terms, G8 manufacturer report number), H Device manufacturers only (H1 type of reportable event … H11 additional manufacturer narrative) | https://www.fda.gov/about-fda/forms/medwatch-fda-safety-information-and-adverse-event-reporting-program-mandatory-instructions |
| 21 CFR 803.52 | Which information categories a manufacturer must supply "if known or reasonably known": (a) patient, (b) event/problem, (c) device, (d) initial reporter, (e) reporting information for all manufacturers, (f) device-manufacturer information. Used to label each worksheet row with its 803.52 paragraph | https://www.law.cornell.edu/cfr/text/21/803.52 (eCFR: https://www.ecfr.gov/current/title-21/chapter-I/subchapter-H/part-803/subpart-E/section-803.52) |
| 21 CFR 803.50(a) | 30-calendar-day clock from the day the manufacturer becomes aware of information reasonably suggesting (1) death/serious injury causation or (2) a malfunction likely to cause/contribute if it recurred. Reportability checkboxes on the worksheet | https://www.law.cornell.edu/cfr/text/21/803.50 |
| 21 CFR 803.53 | 5-work-day report: (a) event necessitating remedial action to prevent an unreasonable risk of substantial harm (awareness may come from trend analysis); (b) FDA written request | https://www.law.cornell.edu/cfr/text/21/803.53 |
| 21 CFR 803.17 | Written MDR procedures: internal identification/evaluation, standardized review for reportability, timely submission; documentation and record keeping | https://www.law.cornell.edu/cfr/text/21/803.17 |
| 21 CFR 803.18 | MDR event files must hold the information evaluated and the deliberations/decision-making used to decide reportability; manufacturer retention: longer of 2 years or expected device life | https://www.law.cornell.edu/cfr/text/21/803.18 |
| QMSR (21 CFR Part 820 as amended) | Effective 2026-02-02; incorporates ISO 13485:2016 by reference. CAPA is therefore mapped to ISO 13485 §8.5.2 / §8.5.3, not to the superseded 21 CFR 820.100 | https://www.fda.gov/medical-devices/quality-management-system-regulation-qmsr/quality-management-system-regulation-frequently-asked-questions ; Federal Register final rule: https://www.govinfo.gov/content/pkg/FR-2024-02-02/html/2024-01709.htm |
| 21 CFR 820.35 | Complaint records (in addition to ISO 13485 §8.2.2) for complaints reportable under Part 803: device name, date received, UDI/other identifiers, nature and details, correction/corrective action, reply | https://www.law.cornell.edu/cfr/text/21/820.35 |
| ISO 13485:2016 §8.5.2 | Corrective action elements (a) review nonconformities incl. complaints, (b) determine causes, (c) evaluate need for action, (d) plan, document and implement action incl. updating documentation, (e) verify the action does not adversely affect the ability to meet regulatory requirements or device safety and performance, (f) review effectiveness; records of results | Paraphrase used (the standard itself is paywalled): https://presencis.com/regulations/iso-13485/article-8.5/ |
| ISO 13485:2016 §8.5.3 | Preventive action: potential nonconformities and causes, need for action, plan/document/implement, verify no adverse effect, review effectiveness | same as above |
| ISO 13485:2016 §8.2.2 | Complaint handling incl. determining whether information is reportable to regulatory authorities | (named in the QMSR FAQ and 820.35; clause text not freely available) |
| 21 CFR 11.10(e) | "secure, computer-generated, time-stamped audit trails" — the audit-trail appendix is modeled on it | https://www.law.cornell.edu/cfr/text/21/11.10 |
| 21 CFR 11.50 | Signature manifestation: printed name, date and time of signing, meaning (review, approval, …), shown in any human-readable form | https://www.law.cornell.edu/cfr/text/21/11.50 |

## Meta Model API (for F9 reviewer and the optional illustration)

| Topic | What we use | Source |
|---|---|---|
| PDF input | Chat Completions accepts a `{"type":"file","file":{"filename","file_data":"data:application/pdf;base64,…"}}` content part (≤ 50 MB inline; text from first 100 pages). The reviewer sends the PDF this way **and** the evidence narratives as text; a text-only mode exists as a fallback | https://dev.meta.ai/docs/file-handling |
| `muse-wonder-1.0` | 1,048,576-token context, text/image/video/audio/PDF input, Standard mode only on the Model API (Preview) | https://dev.meta.ai/docs/models |
| Pricing | Wonder $4.00 / $20.00 per 1M input/output tokens; Spark 1.3 $1.25 / $4.25; Muse Image $0.01 per returned image | https://dev.meta.ai/docs/pricing-rate-limits |
| `muse-image-1.0` | `POST /v1/images/generations` `{"model","prompt","n","output_format":"png"}` → `data[0].b64_json` | https://dev.meta.ai/docs/image-generation |

## What the dossier does NOT claim

- **Not Part 11 compliant.** There are no authenticated electronic signatures
  (no 11.100/11.200/11.300 identity controls, no 11.70 signature/record
  linking). The signature block is *modeled on* 11.50 and the audit appendix on
  11.10(e); the gap is printed on the approval page and in the appendix.
- **No reportability decision.** The MDR worksheet is stamped "DRAFT WORKSHEET —
  NOT FOR SUBMISSION"; reportability is a human regulatory decision.
- **No root cause, no effectiveness check.** Those §8.5.2 fields are printed as
  "To be completed by CAPA owner".

## Points we were unsure of

- ISO 13485:2016 is paywalled; the §8.5.2 (a)–(f) lettering follows the
  standard's structure as paraphrased by secondary sources, not the licensed text.
- 3500A item titles were taken from the current mandatory-reporting
  instructions page (form revision current on 2026-10-27); older form revisions
  number some G/H items differently.
- Awareness date is never inferred by the software: it is an input (the demo
  script uses the CAPA-need evidence pack's creation date and labels it as such).
