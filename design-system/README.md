# MaudeSignal Design System

The visual language for every MaudeSignal surface: the website, the dashboard, and PSUR reports. A bento-grid layout with an editorial "morning briefing" theme: warm paper, ink, Newsreader serif headlines and figures, Geist interface text, cobalt for references.

Live, browsable version (private to the owner until shared): https://claude.ai/artifact/XffmThdA12fv7u7NP9KxJh

## Files

| File | What it is |
|---|---|
| `tokens.json` | Source of truth: colours (3 themes), type styles, spacing, radius, shadows. Edit this, then regenerate `tokens.css`. |
| `tokens.css` | CSS custom properties for all three themes, plus `.t-*` type-style classes. |
| `maudesignal.css` | Component styles (`.ms-*` classes). Loads Newsreader, Geist, Geist Mono and Material Symbols from Google Fonts. |
| `components/<Name>.html` | A standalone page per component. Open in a browser; the buttons bottom-right switch theme. |
| `components/<Name>.md` | Usage guidelines per component: what to pass in, which tokens, do and don't. |
| `components/OvernightDigest.html` | The reference overview page, all components together. |

## Using it on a web page

```html
<html lang="en" data-theme="light">  <!-- light (Paper) | dark (Night) | contrast -->
<head>
  <link rel="stylesheet" href="design-system/tokens.css">
  <link rel="stylesheet" href="design-system/maudesignal.css">
</head>
```

- Without a `data-theme` attribute, the page follows the visitor's OS setting (Paper or Night).
- Use the tokens as CSS variables (`var(--ink)`, `var(--space-4)`, `var(--radius-md)`, `var(--font-serif)`), never raw hex values.
- Copy markup from `components/*.html`; the class names are the API. A framework (React, Next.js, Astro…) can wrap the same markup in components.
- In Streamlit, inject `tokens.css` and `maudesignal.css` through `st.markdown(..., unsafe_allow_html=True)` and render tiles as HTML.

## Rules a builder must keep

- Plain `paper` background. No background images, gradients, glass, or tile shadows.
- One `inverse` (ink) tile per page: the HeroSignal.
- Severity is always a word (High / Medium / Low), never colour alone.
- `ms-verified` and footnotes appear only for fields that passed the regulatory-citation-verifier.
- Confidence never displays above 0.95. Copy routes decisions to a human reviewer; never clinical advice.
- Text contrast meets WCAG AA in every theme (main text 7:1). Check new colour pairs before adding them.

---

MaudeSignal reads MAUDE adverse-event reports for AI/ML medical devices and turns them into signals for quality and regulatory teams. The interface is a morning briefing laid out as a bento grid: warm paper, ink, serif headlines and figures, cobalt for references, and colour only where severity or verification needs it.

## Principles

- **A briefing, not a cockpit.** Lead with one story (the HeroSignal), then the deadline, then the numbers, then the other signals. Headlines name the failure in plain words.
- **Plain paper.** Pages sit on `paper`. Never an image, gradient, texture, glass or shadow behind content. Tiles are `surface` edged by `rule`; depth comes from rules and the one `inverse` tile.
- **Every claim has a footnote.** Narrative from a Skill carries `sup.ms-fn` markers that resolve to verified sources (openFDA, the curated CFR index, the guidance index). Show `ms-verified` only on fields that passed the citation verifier.
- **Humans decide.** Copy routes findings to a reviewer ("Flagged for human review to decide whether a report is required"). Never advise on clinical care.
- **Show provenance.** Skill name, version and confidence appear with any AI output. Confidence never reads above 0.95.

## Themes

Three themes share every token name.

- **Paper** (default): `paper` #f6f3ec, `surface` #fffdf8, `ink` #16130f, `accent` cobalt #1d3fbf.
- **Night**: warm black `paper` #14120f, `ink` #f1ece2, `accent` #9db0ff. The hero tile flips to a paper-coloured block with ink text.
- **High contrast**: pure white and black, black rules, darker status colours. Every text colour reaches 7:1; rules and control edges are black.

Every text pair named in a token's usage note meets 4.5:1 in every theme (body and headline text 7:1). Marks (`warning-mark`, `rule-strong`) meet 3:1.

## Color

- Text: `ink` for headlines, figures and body; `ink-2` for decks and descriptions; `ink-3` for kickers, bylines and meta.
- Surfaces: `paper` → `surface` (tiles) → `surface-sunk` (ring tracks, hover). `rule` edges tiles; `rule-strong` draws the masthead's double rule and input borders.
- The one ink block: `inverse` with `on-inverse` and `on-inverse-2`, for the HeroSignal tile and the primary button. Kicker on it in `accent-on-inverse`.
- Cobalt `accent`: links, footnote numbers, sparklines, the italic "Signal" in the wordmark, the malfunction series. `accent-soft` behind the AI summary.
- Severity: High `critical`, Medium `warning`, Low `ink-3`, always as the word in small caps. `critical` is solid only on the hero's severity chip.
- Verification: `success` with a filled check and the word "Verified".
- Charts: outcome series use `critical`, `warning-mark`, `accent`, `rule-strong` in that order. Full charts may use the `sev-*` and `fm-*` series from the dashboard; trend lines stay single `accent` lines.

## Type

Two families from Google Fonts, plus a mono for codes.

- **Newsreader** (serif) for everything editorial: `headline` 44, `figure-xl` 88 for the hero figure, `figure-lg` 56 for KPIs, `title-lg` 26 for tile titles, `title` 19 for list items, `deck` 18 for standfirsts and AI summaries, `index` 32 for running numbers (02, 03).
- **Geist** (sans) for the interface: `body` 15/1.55, `body-sm` 13, `label` 14 semibold for buttons and nav, `kicker` 11 semibold caps at 0.1em, `caption` 12.
- **Geist Mono** for `code`: signal IDs (SIG-0214), product codes (QIH), Skill versions.
- Figures are tabular lining numerals. Headlines use sentence case.

## Layout

- The overview is a 12-column bento grid, 116px rows, `space-4` gaps, max width 1220px, `space-10` side padding.
- Order: Bar + dateline; HeroSignal 7×3 beside DeadlineRing 5×2 and AISummary 5×1; four StatTiles 3×2; SeverityMix 6×2 beside SignalList 6×2.
- Below 960px: 6 columns, hero and lists full width. Below 640px: one column, in the same order.
- Radius: `radius-xs` 2px for buttons, chips and badges; `radius-sm` 4px for icon buttons, nav and the mix bar; `radius-md` 8px for tiles; `radius-full` only for dots and the ring.
- No shadows on tiles. `shadow-pop` only for menus and popovers.
- Focus: 2px `focus-ring` outline, 2px offset.

## Content

- Headlines: what failed, where. "Missed findings on low-dose chest CT", not a vendor or device brand.
- Kickers carry the classification: "Top deteriorating signal · QIH · Severity high".
- Numbers: confidence to two decimals, deltas with sign and window ("+42%", "Risk score, last 7 days"), dates as "Nov 20, 2026".
- Cite rules by name and section: "FDA 30-day rule · 21 CFR 803.50".
- Sentence case for buttons ("Open investigation"). No emoji, no exclamation marks.

## Iconography

Material Symbols Outlined (Google Fonts), weight 350, 18px in kickers and buttons, 22px in the AI summary. Filled only for verification (`check_circle`, `verified`) and errors (`error`). Icons always sit next to words. Common names: `trending_up`, `schedule`, `auto_awesome`, `description`, `my_location`, `shield`, `bar_chart`, `arrow_forward`, `search`, `notifications`.

## Logo

In the Bar: the logo's signal arcs in `currentColor`, then "Maude" in Newsreader 600 `ink` and "Signal" in Newsreader italic 400 `accent`. Image files are in the Logos group.
