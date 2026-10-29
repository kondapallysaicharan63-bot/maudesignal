# Severity

Severity, verification and tags, always as words: small caps, square badges and chips.

**Provide:** the severity word (High, Medium, Low) or a short tag.

- `ms-sev--high|medium|low`: `kicker` small caps in `critical`, `warning`, `ink-3`. The default severity mark in lists and kickers.
- `ms-badge` (34px square, H/M/L) on `critical-soft`, `warning-soft`, `surface-sunk` for dense lists.
- `ms-chip--high`: the one solid `critical` chip, for the hero signal only. Plain `ms-chip` for failure mode and product code.
- `ms-chip--ok` and `ms-verified` mean the citation verifier passed. Never show them for an unverified field.
