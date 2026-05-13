# Testing & Validation Strategy

## Testing Layers

| Layer | Tool | Target |
|---|---|---|
| Unit tests | pytest | ≥ 70% coverage on `src/maudesignal/` |
| Integration tests | pytest + real DB | Pipeline end-to-end; no database mocking |
| Gold-set evaluation | `test_gold_set.py` | LLM extraction accuracy vs known-correct examples |
| Type checking | mypy --strict | Zero errors |
| Lint | ruff + black | Zero violations |
| Security | pip-audit | No known CVEs |
| Performance | locust or pytest-benchmark | 10k records < 5 min |

---

## Skill Accuracy Targets

| Skill | Precision Target | Recall Target |
|---|---|---|
| maude-narrative-extractor | ≥ 0.85 | ≥ 0.85 |
| severity-triage | ≥ 0.90 | ≥ 0.88 |
| ai-failure-mode-classifier | ≥ 0.80 | ≥ 0.80 |
| regulatory-citation-verifier | ≥ 0.99 | ≥ 0.99 |
| fda-compliance-checker | ≥ 0.85 | ≥ 0.90 |

---

## Agent FTI Validation (see `.claude/agents/validator.md`)

Every build must pass the FTI check before merging:

- **F — Feature**: Implementation matches `docs/PRD-Complete.md` spec
- **T — Test**: All tests pass; coverage ≥ 70%
- **I — Integration**: mypy clean, ruff/black clean, CLI smoke test passes

---

## Tool Validation Package for Customers

MaudeSignal provides a full validation package for customers to qualify the tool in their QMS:

| Document | Purpose |
|---|---|
| **IQ — Installation Qualification** | Verifies correct installation and configuration |
| **OQ — Operational Qualification** | Verifies the tool performs its intended functions |
| **PQ — Performance Qualification** | Verifies performance in the customer's specific environment |
| **Risk Assessment** | ISO 14971-aligned risk assessment for use of the tool |
| **Traceability Matrix** | Maps requirements → features → tests |
| **SOP Templates** | Standard operating procedures for tool use in a QMS |

---

## CI/CD Quality Gates

Every pull request must pass:
1. `mypy src/maudesignal` — zero errors
2. `ruff check . && black --check .` — zero violations
3. `pytest tests/ --cov=src/maudesignal --cov-fail-under=70` — coverage threshold
4. `pip-audit` — no known CVEs in dependencies
5. Agent validator FTI report — overall PASS required
