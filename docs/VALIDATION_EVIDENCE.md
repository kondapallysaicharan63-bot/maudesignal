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
- **Decisions.** It never decides whether an event is reportable, which devices
  are similar, or whether a CAPA is needed. Whether a CAPA is required is
  decided by the company's own CAPA-need form; the evidence pack is evidence
  only. A named person accepts or rejects every record.
- **Data beyond public FDA records.** Only public openFDA data (MAUDE, recalls,
  510(k)) and PubMed abstracts. No PHI, no complaint files, no private data.
- Filing anything with FDA.

## What is deterministic and what a model writes

| Part | Deterministic (no model) | Model-generated |
|---|---|---|
| Overnight monitor: new / spike / severity rules, ranking and its reason | yes (`src/maudesignal/monitor/`) | — |
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
| Unit tests | 540 pass; 76% line + branch coverage (run 2026-10-28) | `pytest tests/unit --cov=src/maudesignal --cov-branch` |
| CI | ruff, black, `mypy --strict`, tests on Python 3.11 and 3.12 | `.github/workflows/ci.yml` |
| Adversarial gate set | 101 cases (62 must be withheld, 39 must pass): 0 false passes, 0 false blocks | `tests/fixtures/gate/adversarial.jsonl`, `tests/unit/test_gate.py` |
| Gate on real model output | second 2026-10-28 recording (run 40638240641), 21 answers: 0 replies failed to parse; 45/48 sentences passed first time (93.8%), 49/50 after at most one repair turn (98.0%). The first recording that day exposed unparsed replies counted as passed; fixed before this run | `docs/hackathon/HAND_CHECK.md` |
| Hand-check of the recorded answers | 19 of 21 answers fully correct (90.5%); of 50 sentences 48 correct, 1 incomplete (a gate false block, fixed since with adversarial cases d01/d02), 1 wrong (see Known limits). First recording: 6 of 21 | `docs/hackathon/HAND_CHECK.md` |
| Independent review of the evidence PDF | Muse Wonder 1.0 raised 4 findings on the recorded PDF (empty narrative shown as passed; date of event wording; revision history reference; brand capitalization); all four addressed in code, not yet re-recorded | `demo/dossier/*-review.json` |
| Audit-chain tamper test | editing any stored entry breaks the chain at that entry; detected in the database and in exported trails | `tests/unit/test_copilot_agent.py::test_audit_chain_detects_tampering`, `tests/unit/test_voice.py::test_audit_export_roundtrip_and_tamper_detection` |
| Spend caps on live calls | $1 and 20 Meta calls per browser session, $10 per day; no call starts once a cap is reached; checked in the running app with the call cap at 0 | `tests/unit/test_spend.py`, `src/maudesignal/copilot/spend.py` |
| Browser tests | Playwright tests of the five new pages against the keyless demo app; expected values computed from the demo database | `tests/e2e/test_08_hackathon_pages.py` |
| Report-source counts vs openFDA | stored counts compared with openFDA `count=report_source_code.exact` over the stored window, each run of the record workflow | `scripts/check_source_counts.py` → `docs/hackathon/SOURCE_COUNTS.md` |

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
  recording one such sentence was wrong: relevant abstracts were stored.
- 510(k) reading: in the second 2026-10-28 recording, 2 of 5 summaries were read
  (K031779: both reads agreed on all 10 fields, all verified; K261677: 80%
  agreement, 2 conflicts left for a person). The other 3 stopped at the reader's
  own 4096-token default, which has since been raised to 16000.
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
