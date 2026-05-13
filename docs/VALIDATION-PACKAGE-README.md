# Tool Validation Package

This directory (`validation_package/`) contains everything a MedTech company needs to
formally validate MaudeSignal within their Quality Management System (QMS).

---

## Contents

| Document | File | Purpose |
|---|---|---|
| Installation Qualification | `IQ-MaudeSignal.docx` | Verifies correct installation and configuration |
| Operational Qualification | `OQ-MaudeSignal.docx` | Verifies tool performs intended functions |
| Performance Qualification | `PQ-MaudeSignal.docx` | Verifies performance in customer's environment |
| Risk Assessment | `Risk-Assessment-ISO14971.docx` | ISO 14971-aligned risk assessment for tool use |
| Traceability Matrix | `Traceability-Matrix.xlsx` | Requirements → Features → Tests |
| SOP — Running Analysis | `SOP-RunAnalysis.docx` | Standard procedure for running PMS analysis |
| SOP — Document Review | `SOP-DocumentReview.docx` | Standard procedure for reviewing generated docs |

---

## Regulatory Basis

This validation package is designed to support compliance with:
- **FDA 21 CFR 820** (Quality System Regulation / QMSR)
- **ISO 13485:2016** Section 7.6 (Control of Monitoring Equipment)
- **GAMP 5** Category 4 (Configured Software)
- **EU MDR Annex IX** (for EU-based customers)

---

## How to Use

1. Download the templates from this directory.
2. Fill in your company name, system configuration, and test results.
3. Execute the OQ test scripts (provided in `validation_package/scripts/`).
4. Have a qualified person (QA Manager or RA Specialist) sign the completed documents.
5. Store signed validation records in your QMS document control system.

---

## Important Notes

- The validation package covers **MaudeSignal as a decision-support tool**.
- Validated outputs (PSURs, PMS Plans) are **drafts** that require human expert review
  before use in regulatory submissions.
- Re-validation is required after: major version upgrades, configuration changes,
  or changes to the underlying LLM model.
- Contact us for customized validation support: support@maudesignal.io

---

## Version Compatibility

| Validation Package Version | MaudeSignal Version |
|---|---|
| 1.0 | 1.x (MVP) |

Update this table with each major release.
