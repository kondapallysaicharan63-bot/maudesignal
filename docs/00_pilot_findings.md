# SafeSignal Pilot Findings

**Date:** 2026-04-25
**Pipeline run:** First successful end-to-end execution

## Data Discovery
- QIH (Stroke triage CAD): only **8 records** in MAUDE — surprisingly sparse
- LLZ (Imaging diagnostic): **19,425 records** — abundant baseline data
- DQA (Patient monitor): **13,503 records** — abundant
- Initial query bug: `device.openfda.product_code` was empty for older records
- Fixed by switching to `device.device_report_product_code`

## First 3 Extractions (LLZ, Groq Llama 3.3 70B)

### Sample 1 — MDR 10005054 (confidence 0.90)
- Failure mode: Vertical belt breakage during diagnostic test
- Severity: malfunction
- AI-related: False ✅ (correctly classified — pure mechanical)

### Sample 2 — MDR 1001188 (confidence 0.80)  
- Failure mode: Complete loss of image during therapeutic EGD
- Severity: serious_injury ✅ (correctly escalated)
- AI-related: False ✅

### Sample 3 — MDR 1003068 (confidence 0.88)  ⭐
- Failure mode: Omission of critical data elements in software-generated report
- Severity: other
- AI-related: **True** ⭐
- This is the SafeSignal value prop — surfaced an AI-relevant signal

## Assessment

- **Pipeline:** Works end-to-end on real FDA data
- **Cost:** $0 (Groq free tier)
- **Initial accuracy looks strong** — 3/3 reasonable on quick eyeball
- **Confidence scores well-calibrated** (0.80-0.90 range)

## Implications

The fact that even random LLZ records contain AI-relevant signals (like Sample 3) 
suggests SafeSignal's filter will surface meaningful events even from non-AI-specific
product codes — supporting the hypothesis that AI failures are filed under predicate
device codes rather than dedicated AI codes.

## Next Steps

1. Build gold set (100 hand-labeled records) — Week 2
2. Measure full extraction accuracy — Week 2  
3. Add AI failure taxonomy classifier (Skill #4) — Week 3
4. Begin LinkedIn outreach to RA professionals — Week 4
