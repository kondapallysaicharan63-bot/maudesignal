# PRD addendum: post-P0 UI layout and the Noctua mascot (PRD-28 to PRD-36)

Branch: `ui/mascot-noctua` (from `origin/main`). Scope: **web UI and branding only**.
This addendum adds PRD-28 to PRD-36. It does **not** edit PRD-18 to PRD-27, does not
change the P0 scope, and does not rewrite the original PRD (`PRD.md`). Nothing here
touches `src/maudesignal/gate/`, `copilot/`, `monitor/`, `connector/`, dossier or audit
logic, API logic, sweep logic, the `measurements.json` method, the secret scan, or any
P0 file. Any such change is a scope violation: stop and show the diff.

Status words: **P1** = after P0. **PENDING** = needs real users, real load or an
independent check and is not claimed. Nothing in this addendum is reported as passed
until the test named for it has actually run.

---

## PRD-28 Morning Brief Agent (P1)

UI surface only. A daily brief built from the **stored** sweep and the stored
Investigate results, shown in All alerts (daily briefs, with a date picker).

- A person reviews it. It never auto-files anything and never decides.
- It never claims "live" when the sweep is Stored: it shows "Stored" + the stored date
  + window (from the same source as `sweepLabel.ts`).
- No brief logic is built here, and nothing in `monitor/` or `copilot/` is changed.
  If the data for a day is missing, the day shows "No brief stored for this date".

## PRD-29 Keyword match-reason (P1)

Display only.

- Show "Why matched" tags on keyword matches **from the data, when the data has them**.
- The problem-term filter is ON by default for quotes.
- No keyword logic is built and the gate is not changed.
- If the data carries no match reason, the check is reported **NOT RUN**. A reason is
  never faked.

## PRD-30 Known-effects note (P1)

In the Investigate "not filed by a manufacturer" section, a button reads:

> Consider adding [event type, counts] to the known-effects record for [code] - human reviews and approves.

- It only opens a draft template for a person. No auto-add, no auto-approval.
- Nothing is written to any record by the button itself.

---

## PRD-32 Post-P0 UI layout (P1, presentation only, no new PMS function)

Re-arrange and label what P0 already produces. No new data source, no new decision
logic. Complaint first.

1. **Sidebar order:** New chat, Search, Home, Board (badge = New + Under review only),
   Signals, Investigate a complaint, Evidence, Validation, then PMS workflow and
   Time & cost under a "How it fits" divider, Connect, Recents, Theme menu (Light,
   Dark, Black, System, Pink, High contrast), schedules/sources, and a collapsed
   Demo / Simulated group at the very bottom.
2. **TopBar:** menu toggle, wordmark to Home, AlertBell (real FDA alerts only;
   simulated shown only as a separate labelled row inside the bell, never in the
   badge), Feedback. No data banner, version or simulated badge in the TopBar.
3. **Data banner** on every data page, under the page head and above the tabs / first
   figure (never a footer): "Data as of: [date]. OpenFDA republishes weekly and reports
   arrive with delay - recent months may show few or no reports because of reporting
   delay, not because risk is zero. Stored snapshot: [window]. Live check: [query date,
   or 'not run']." If the date is unknown: "Data date not available - do not use this
   figure for a current decision" (figures dimmed, not hidden). It reads from the same
   source as `sweepLabel.ts`, never a second hard-coded date.
4. **Live FDA rule:** a live figure shows its query date and query link; a stored figure
   shows "Stored" + stored date + window and never a live date; a live failure shows a
   "not live" banner and fallback buttons, never a blank and never an invented date.
   The stored Oct 30 sweep and the stored Aug 31 demo snapshot stay labelled Stored
   until a new Actions sweep produces a new date. No fresh sweep date is claimed.
5. **Copy rules:** "Report mix changed", never "more serious than usual" (first use:
   "Injury/Death share rose from X% to Y% (N of M reports). This is a change in report
   mix, not proof of increased device risk."); "Companies know their competitors";
   "Complaints / PMS team"; every decision surface says "MaudeSignal does not decide
   reportability, similarity, or whether a CAPA is needed; your team does."; never
   "FDA validated/approved", "AI validated", "time saved" or "ROI" as a product claim.
6. **Mobile:** under 768px the sidebar is a drawer; under 480px sub-tabs become a "View"
   select; 44px touch minimum; tables scroll horizontally with a caption; Board becomes
   cards; the Investigate form stacks. The six Investigate buttons go from 40px to 44px.
7. **Pages:** Home (order fixed: banner, "A complaint came in?" hero, Board summary,
   Real FDA alerts, How MaudeSignal fits, AI sweep demoted, Trust, demo snapshot);
   Signals; Investigate (results in order a to f); Board (`/board` only); Evidence;
   Validation (single scrolling page, anchor nav, not tabs, "This build is not
   validated" first); Time & cost (measured, not claimed); PMS workflow (8 steps, all
   links resolve); Chat / fallback screen (never a half-answer shown as complete).
8. **Must not appear:** simulated devices in real counts, the bell or the Board; a
   figure without date, source and openFDA link; a tool-made decision sentence; a
   time-saved or ROI number that is not a recorded measurement or a labelled user
   assumption.
9. **Reuse, do not rebuild:** SubTabs, PageHead, SourceCaption, AlertRows,
   SweepCard/SweepRules, InvestigateCard, AuditCapaProtocol, DossierTab, SearchPalette,
   ThemeMenu. `?layout=v2` stays the default; the classic layout is untouched; existing
   `data-testid`s are kept; new ones are `board-*`, `validation-*`, `inv-*`.

## PRD-33 Noctua mascot (P1, branding only, SVG only, never in evidence, never decides)

Noctua is MaudeSignal's watchful owl. One character in v1: not Maude, not Vigil, no crow
face, no bee, no second character.

- **Static mark:** frontal head-and-shoulders, rounded shield, two large equal eyes, a
  small downward triangle beak, two short folded wing bars (dropped at 16-24px).
  ViewBox `0 0 64 64`. SVG + CSS only, about 2-5 KB, colours from CSS variables, never a
  hard-coded hex. No GIF, no Lottie, no PNG sprite. Sizes: 24 inline, 32 headers,
  48 empty states, 96 maximum (Home hero).
- **Art provenance:** if a reference sketch is used, Muse Image 1.0 Standard tier only,
  traced by hand into SVG, raster discarded. No AI raster ships. Not Contributor tier;
  Spark, Wonder and SAM are not used to build the mascot.
- **Personality:** vigilant not noisy, evidence-first, calm under alert. The body never
  turns red; a flag or badge beside it carries the colour. Captions only, never
  evidence. Never says a device is dangerous or must be recalled, never gives medical
  advice, never jokes about death or injury, no baby talk or emojis in evidence, never
  "I know...", never a signature, approver or witness.
- **Seven states (CSS only; JS timers only for the bubble, via sessionStorage):**
  Idle, Watching/scanning, Alert, Thinking, Success/verified, Withheld/error,
  Listening. Priority: alert > listening > thinking > withheld > success > watching >
  idle. Success and withheld are transient (2-3s) and then return to the underlying
  state. Each state is always paired with text or a badge.
- **Colours:** tokens only; body ink per theme (Light `#16130f`, Dark `#f1ece2`, Black
  `#f5f5f5`, Pink `#1f1218`, High contrast `#000000`). High contrast: black owl, white
  eyes, black pupils, no accent. Success / warning / critical appear on badges beside
  the owl only.
- **Accessibility:** `prefers-reduced-motion` gives a static idle everywhere. No
  flashing, nothing above 3 flashes a second, slowest cycles 2.4s or more where
  specified, the fastest being the 1.2s alert pulse. The logo gets
  `<title>Noctua, MaudeSignal's watchful owl mark</title>`; every in-UI instance is
  `aria-hidden`, and screen readers get the paired text or badge, never face or colour
  alone.
- **Evidence hard rules:** `MascotOwl` is never imported into the dossier, artifacts,
  PdfView, the audit export or the connector API. Mascot state changes are not audit
  events. Proof screenshots hide or crop the mascot (`hideMascot`) or carry the caption
  "mascot is branding only, not evidence". A test fails if the mascot is found in
  dossier, audit or API output.
- **Mount (v1):** TopBar (primary, a 44x44 button with a 30-32px SVG that opens the first
  alert) and the Home empty / calm state (64-96px, decorative, `aria-hidden`, no button,
  bubble or link). If both would show, only the TopBar one renders; never two talking
  mascots. Never in chat turns, answer cards, evidence packs, dossier, audit rows,
  Vision / camera, Investigate results, Board decision rows or inside answer sentences.
- **Existing buddy:** `AlertBuddy` keeps working until the owl passes its tests; its
  replacement or removal is a separate reviewed commit.
- If the mascot is not green by the Nov 3 freeze, the UI ships without it and that is
  reported; the UI is not blocked on it.

## PRD-34 Companion movement (P1, web app only, dock, hero walk, freeze on evidence, Hide toggle, reduced motion)

Browser only. A true desktop pet outside the browser is a separate app and is not part
of this build.

- **Dock:** fixed bottom-right, 24px margin, 96px maximum (64px on phones), z-index below
  modals. Clickable only on the owl itself, opening the first alert. A 44px "Hide
  Noctua" X button hides it for the session; "Show Noctua" in the Theme menu brings it
  back.
- **Idle:** every 25s (plus or minus 5) glide left or right at most 16px over 1.2s
  ease-in-out, blink or look around, settle. No jump, teleport or bounce; at most
  40px/s; head tilt at most 6 degrees.
- **Alert move (only):** glide to the **edge** of the Board card (never over it), hold
  4s, show the bubble once per session, return to the dock.
- **Thinking, listening, withheld, success:** stay in the dock; only eyes, dots or ring
  move.
- **Hero walk:** Home hero only, once per session view, left to right across the hero
  banner in about 6s, then settle in the dock. Stops at once on scroll or reduced motion.
- **Freeze (docked, static):** while typing in Investigate, while an evidence figure is
  on screen, and on the Signals, Investigate, Evidence, Audit and Board decision pages.
- **Never:** follow the cursor; move over Save, Copy or Approve buttons or over figures;
  make a sound; leave the browser.
- Reduced motion: no movement, no walk, docked and static.

## PRD-35 GIF rule (P1, marketing only, currently NO GIF file, no GIF in app)

- There is currently **no GIF file** in the repository and none is created in this build.
- No GIF, Lottie or PNG sprite is used inside the app. The app mascot is SVG + CSS only.
- A GIF may exist later for marketing only (README, video, social), recorded from the
  SVG, subject to the same copy rules, and never as evidence. Not in scope now.

## PRD-36 UI testing (required tests below; UAT, Beta, Stress and Scalability = PENDING, not claimed)

Required, and reported as PASS / FAIL / PENDING from what actually ran:

1. Mascot unit tests: every state class, priority order, transient success / withheld,
   bubble once per session.
2. Existing web tests, TypeScript type-check, Playwright regression.
3. Five-theme screenshots (dev only).
4. Reduced motion: all animation stops, the owl is static, and colour / label / badge
   still convey state.
5. Legibility at 30, 44 and 96px.
6. Touch target 44px, focus ring, bubble on focus and hover.
7. No flashing.
8. UI / UX functional tests for every page and phase.
9. Six-theme AA contrast check (run, not skipped).
10. Investigate buttons at 44px (this must now pass; it failed at 40px in the P0 report).
11. **No mascot in dossier, audit or API output** (the test fails if one is found).

**PENDING, not claimed:** UAT, Beta, Stress at live scale, Scalability at production
scale, and a full WCAG audit. These need real users or real load.
