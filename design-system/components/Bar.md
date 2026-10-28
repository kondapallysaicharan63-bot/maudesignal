# Bar

The page masthead: serif wordmark, centred section nav, icon buttons, and a dateline under a double rule.

**Provide:** the five sections (Overview, Signals, Digest, PSUR, Alerts) with `aria-current="page"` on the active one, optional counts in `.ms-count`, the reviewer's initials, and the dateline's three parts (date, digest number, records reviewed).

- The wordmark is "Maude" upright in `ink` and "Signal" italic in `accent`, after the logo's signal arcs in `currentColor`.
- The active section is the only `inverse` block in the bar. Others are `ink-2`, hover `surface-sunk`.
- The double rule (`rule-strong`) closes the masthead; the dateline is `kicker`-style caps in `ink-3`.
