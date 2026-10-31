# Validation evidence

Facts only, with where each one comes from. This page does **not** claim that
MaudeSignal is validated, 21 CFR Part 11 compliant or fit for any particular
quality system: that is the manufacturer's call, made in its own environment.

## Intended use

MaudeSignal helps postmarket-surveillance (PMS) and regulatory-affairs teams at
medical-device makers watch public FDA data for the device types (FDA product
codes) they choose. It shows what got worse, who filed the reports, and
evidence a person can review: report counts, verbatim quotes, recalls, 510(k)
records and papers, each tied to the stored FDA record.

**Out of scope:**

- Medical advice, diagnosis or treatment. It is not clinical decision support
  and not an FDA-cleared device.
- **Decisions.** It never decides whether an event is reportable or whether a
  CAPA is needed, and it does not define similar devices: it works on the
  device types the user chooses. Whether a CAPA is required is
  decided by the company's own CAPA-need form; the CAPA-need evidence pack is evidence
  only. A named person accepts or rejects every record.
- **Data beyond public FDA records.** Only public openFDA data (MAUDE, recalls,
  510(k)) and PubMed abstracts. No PHI, no complaint files, no private data.
- Filing anything with FDA.

## What is deterministic and what a model writes

| Part | Deterministic (no model) | Model-generated |
|---|---|---|
| What-changed monitor: reports suddenly increased / more serious than usual / new kind of problem rules, ranking and its reason | yes (`src/maudesignal/monitor/`) | — |
| Report-source counts and the "not filed by a manufacturer" list | yes (`src/maudesignal/monitor/sources.py`, stored openFDA `report_source_code`) | — |
| Citation gate: recomputes every count and share, matches every quote word for word, checks every report id, 510(k), recall, PMID and CFR section | yes (`src/maudesignal/gate/`) | — |
| Copilot answer text | — | Muse Spark 1.3; shown only sentence by sentence after the gate passes it |
| Numbers printed in the evidence-pack PDF | yes, each re-verified by the gate | — |
| PDF narrative summary | — | Muse Spark 1.3, gated the same way; withheld sentences shown with reasons |
| PDF review findings | — | Muse Wonder 1.0; findings only, never edits the record |
| 510(k) / label reading | field check is deterministic (two reads must agree, then openFDA and the PDF text layer) | Muse Spark 1.3 reads; SAM 3.1 finds the label |
| MDR clock | yes (calendar arithmetic, advisory) | — |
| Audit trail | yes (SHA-256 hash chain, re-verified on display) | — |

## Evidence

| Check | Result | Source |
|---|---|---|
| Unit tests | 1147 pass; 78% line + branch coverage (run 2026-10-30) | `pytest tests/unit --cov=src/maudesignal --cov-branch` |
| CI | ruff, black, `mypy --strict`, tests on Python 3.11 and 3.12 | `.github/workflows/ci.yml` |
| Adversarial gate set | 130 cases (84 must be withheld, 46 must pass): 0 false passes, 0 false blocks | `tests/fixtures/gate/adversarial.jsonl`, `tests/unit/test_gate.py` |
| Gate on real model output | fifth 2026-10-28 recording (run 40764365995), 28 answers (22 typed, 6 text-to-speech): 63/65 sentences passed first time (96.9%), 64/65 after repair; the one withheld sentence was true (a false block: a year read as a count, fixed with cases dt03–dt05); 0 unparsed, 0 token-cap stops. Earlier runs that day: 49/50 (fourth), 52/53 (third, 1 unparsed), 45/48 (second), and the first exposed unparsed replies counted as passed (fixed) | `docs/hackathon/HAND_CHECK.md` |
| Hand-check of the recorded answers | 27 of 28 answers fully correct (typed 21 of 22, text-to-speech 6 of 6; Oct-29 voice run 40965201781, Charan's takes 1/4/6: 3 of 3 answers, 8 of 8 sentences correct and gate 8/8); of 65 sentences 64 correct, 1 incomplete (wrongly withheld), 0 wrong; checked against the demo database by Claude; independent check by Charan pending. Fourth run: 24 of 24; third: 21 of 24; second: 19 of 21; first: 6 of 21 | `docs/hackathon/HAND_CHECK.md` |
| Independent review of the evidence PDF | Muse Wonder 1.0: 0 findings on the current pack's PDF (SER-LLZ-20260831-001, recorded 2026-10-31; Muse Spark summary 5 sentences shown, 0 withheld). The previous recording had 2 findings (a high one on section 4.1 citing a report that does not mention error 500, a medium one on the section 4 title), both fixed by the reword. Earlier: 0 findings on the third, fourth and fifth recordings' PDFs (the second recording's 4 findings were fixed in code first) | `demo/dossier/*-review.json` |
| 510(k) reading | 5 of 5 summaries read; agreement between the two reads 100% / 90% / 90% / 90% / 80% (fifth recording; 100/100/100/100/80 in the fourth); every disagreement, and every field that conflicts with openFDA, left for a person | `demo/vision/510k-*.json` |
| Label camera | 7 of 7 photos read (run 40792998780): CareSens N, both HoMedics thermometers and Welch Allyn 802 LTR read correctly; thermometers matched to product code FLL; NOMAD Pro 2 left for a person to pick (device name only partly legible); Spot Vital Signs (label rotated 90°) returned nothing; the Welch module was misread ("AEROSOL, VASCULAR AND PULMONARY EQUIPMENT" for "MEDICAL-CARDIO VASCULAR AND PULMONARY EQUIPMENT"), every field marked only partly legible and no product code assigned. No lot or serial stored; checked against each photo by Claude | `demo/vision/label-*.json`, `demo/vision/labels/` |
| Audit-chain tamper test | editing any stored entry breaks the chain at that entry; detected in the database and in exported trails | `tests/unit/test_copilot_agent.py::test_audit_chain_detects_tampering`, `tests/unit/test_voice.py::test_audit_export_roundtrip_and_tamper_detection` |
| Spend caps on live calls | $1 and 20 Meta calls per browser session, $10 per day; no call starts once a cap is reached; checked in the running app with the call cap at 0 | `tests/unit/test_spend.py`, `src/maudesignal/copilot/spend.py` |
| Browser tests | Playwright tests of the product pages (Signals, Copilot, Vision, Audit) against the keyless demo app; expected values computed from the demo database | `tests/e2e/test_08_hackathon_pages.py` |
| Report-source counts vs openFDA | stored counts compared with openFDA `count=report_source_code.exact` over the stored window, each run of the record workflow | `scripts/check_source_counts.py` → `docs/hackathon/SOURCE_COUNTS.md` |

## Agentic workflows (status)

| Workflow | State | Source |
|---|---|---|
| Weekly investigator | Built; tested with mocked model calls, plus one real recording: `demo/investigations/20261030T010942Z-weekly-llz.json` (LLZ, window 2026-08-25 to 2026-08-31, Muse Spark 1.3). 7 of 7 sentences and 9 of 9 claims passed the gate on the first pass, no repair, $0.224989. One run only, not a statistical estimate. | `src/maudesignal/copilot/investigator.py`, `tests/unit/test_weekly_investigator.py` |
| Recall-triggered sweep | Built; tested with mocked model calls only. No real recording yet. | `src/maudesignal/copilot/recall_sweep.py`, `tests/unit/test_recall_sweep.py` |
| Search protocol (methodology appendix) | Built; tested. Derived from the stored tool-call log, so it contains no model-written text. | `src/maudesignal/copilot/protocol.py`, `tests/unit/test_search_protocol.py` |

## Known limits

- The copilot's answers are only as complete as the stored records; the demo
  database holds 137 reports (LLZ complete for Jul–Aug 2026; all QIH, MYN and
  POK reports at fetch time). openFDA re-publishes weekly.
- MAUDE is a passive reporting system: a report shows an event associated with
  a device, not that the device caused it, and counts are not rates.
- The gate checks that a statement matches a stored record. It does not judge
  whether an answer is complete or the most relevant one: the hand-check above
  found correct-but-misleading answers that the gate passed.
- **Negative answers are not gated.** A sentence that says something is *absent*
  ("no relevant papers are on file") carries no claim to check. In the second
  and third recordings one such sentence was wrong: relevant abstracts were
  stored. The literature tool was fixed; the fourth recording's two negative
  sentences (14, 23) were checked by hand and are correct, but the gate still
  cannot check a negative.
- 510(k) reading: every summary was read in the third and fourth recordings,
  but two reads agree on only 80–100% of the fields; the rest are shown as conflicts for a
  person to settle, never auto-resolved.
- Completeness: the gate checks what is said, not what is left out. In the
  third recording a recall answer missed three stored recalls for the device
  it was asked about (the fourth names one of them as an example).
- The gate can also withhold a true sentence (a false block): in the fifth
  recording it read the year in "August 31, 2026" as a count. Fixed and added
  to the adversarial set; others may remain.
- Label camera: a rotated or small label can return nothing (Spot Vital Signs);
  the model can mis-read a partly legible field (the Welch module is read with the
  wrong text on most runs, always marked partly legible). A product code is inferred only from a
  clearly read name, and a person confirms every match.
- The hand-check sample is 31 recorded answers to fixed demo questions (28 from the fifth recording, 3 voice takes), checked by
  Claude against the database. It is not an independent or statistical
  accuracy estimate.
- The approval step records a typed name with a timestamp in a hash-chained
  log. It is not an authenticated electronic signature.

## What a manufacturer would still need for its own CSV / CSA

- **Intended use in its quality system** and a risk-based assessment of how
  much assurance this use needs.
- **Requirements trace:** its own requirements mapped to tests (the tests above
  are a starting point, not its trace).
- **IQ / OQ / PQ (or CSA-style assurance) in its own environment**, on its own
  product codes and data, including a hand-check sample of its own.
- **Authenticated electronic signatures** and access control if records are
  signed in the tool; today an approval is a typed name in a hash-chained log.
- **Change control** for model versions, Skill versions and the gate's CFR
  list, and periodic re-checks of the hand-check rate.
