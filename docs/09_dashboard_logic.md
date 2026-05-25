# MaudeSignal Dashboard — Full Logic Reference

**Source file:** `src/maudesignal/dashboard/app.py`  
**Entry point:** `main()` → `_render_app(db)` → one of 7 `_page_*()` functions

---

## Table of Contents

1. [Module-Level Constants](#1-module-level-constants)
2. [CSS Design System](#2-css-design-system)
3. [Utility Helpers](#3-utility-helpers)
4. [Page Renderers](#4-page-renderers)
   - [Page 1 — Dashboard](#page-1--dashboard-_page_dashboarddb)
   - [Page 2 — Signal Explorer](#page-2--signal-explorer-_page_signal_explorerdb)
   - [Page 3 — MAUDE Ingestion](#page-3--maude-ingestion-_page_ingestiondb)
   - [Page 4 — LLM Extraction](#page-4--llm-extraction-_page_extractiondb)
   - [Page 5 — PSUR Reports](#page-5--psur-reports-_page_psurdb)
   - [Page 6 — Alerts](#page-6--alerts-_page_alertsdb)
   - [Page 7 — Settings](#page-7--settings-_page_settingsdb)
5. [App Shell](#5-app-shell--_render_appdb)
6. [Entry Point](#6-entry-point--main)
7. [Backward-Compatibility Aliases](#7-backward-compatibility-aliases)
8. [Data Flow Summary](#8-data-flow-summary)

---

## 1. Module-Level Constants

| Constant | Value | Purpose |
|---|---|---|
| `EXTRACTOR_SKILL` | `"maude-narrative-extractor"` | Skill name for field extraction |
| `CLASSIFIER_SKILL` | `"ai-failure-mode-classifier"` | Skill name for AI taxonomy |
| `SEVERITY_SKILL` | `"severity-triage"` | Skill name for severity grading |
| `_MAUDE_DETAIL_URL` | FDA URL template | Builds clickable links to openFDA reports |
| `_PAGES` | list of dicts | Page registry: icon, name, subtitle, function ref |
| `_SEVERITY_ORDER` | `["death", "serious_injury", …]` | Canonical order for severity filter dropdowns and sort |
| `SEVERITY_COLORS` | dict | Maps severity → red/amber/green/grey KPI card variant |
| `_FAILURE_MODE_COLORS` | dict | Maps failure category → Altair hex color |
| `_ASSETS_DIR` | path | Points to `src/maudesignal/dashboard/assets/` |
| `_LOGO_PATH` | path | Sidebar logo PNG |

---

## 2. CSS Design System

The entire visual design is injected as one `<style>` block via `st.html(_CSS)` at app start. It is never iframed — styles apply globally to Streamlit's DOM.

### 2.1 Design Tokens

| Color | Token | Value |
|---|---|---|
| Primary (cobalt) | `--ms-primary` | `#0866FF` |
| Primary deep | `--ms-primary-deep` | `#0052CC` |
| White canvas | `--ms-canvas` | `#FFFFFF` |
| Soft surface | `--ms-surface-soft` | `#F0F2F5` |
| Near-black text | `--ms-ink-deep` | `#0A1317` |
| Body text | `--ms-ink` | `#1C1E21` |
| Muted text | `--ms-slate` | `#606770` |
| Label text | `--ms-steel` | `#8A8D91` |
| Subtle divider | `--ms-hairline-soft` | `#E4E6EA` |
| Success | `--ms-success` | `#2E7D32` |
| Warning/attention | `--ms-attention` | `#E65C00` |
| Critical | `--ms-critical` | `#E02020` |

**Spacing scale:** `--sp-xs (8px)` through `--sp-xxxl (40px)`, plus section spacers `--sp-section-sm/md/lg` (48/64/80px).

**Border-radius scale:** `--r-sm (4px)` → `--r-full (100px)`, with `--r-xxxl (32px)` used for KPI cards.

### 2.2 CSS Block Reference

| Block | What it controls |
|---|---|
| `@import Montserrat` | Loads font family from Google Fonts |
| `[data-testid="stApp"]` | White background, ink-deep body text, Montserrat globally |
| `section[data-testid="stSidebar"]` | Navy gradient sidebar (`#0A1317` → `#1C2B3A`), white text |
| `.stButton > button` | Black pill button (100px radius), white text, hover lift |
| `.stButton.ms-cta-buy > button` | Cobalt CTA button (Run Ingestion, Start Extraction) |
| `.ms-page-header h1` | 36px / weight 500 / ink-deep page titles |
| `.ms-page-header p` | 16px / slate subtitle — all descendant overrides prevent Streamlit-injected colors |
| `.ms-card` | KPI card: white bg, cobalt 3px top rail, 32px radius, centered |
| `.ms-card .val` | 32px bold value, `clamp(20px, 2.8vw, 32px)` for long strings, `white-space: nowrap` |
| `.ms-card .lbl` | 11px / uppercase / steel color / 0.06em letter-spacing |
| `.ms-section` | 18px bold Montserrat section headings |
| `.ms-status-pill` | Inline pill badges (green/red/amber/grey variants) |
| `[data-testid="stTabs"] button` | Tab bar in Montserrat, active tab with ink-deep + cobalt underline |
| `section[data-testid="stMain"] label` | All widget labels forced to ink-deep, 14px weight 500 |
| `[data-testid="stMarkdownContainer"] p` | Body text: 16px, ink color, 1.5 line-height |
| `[data-testid="stCaptionContainer"]` | Slate 12px captions; `code`/`strong` inside get ink-deep + soft surface bg |
| `[data-testid="stDataFrame"]` | Rounded corners (32px), hairline border |
| Footer `div` | Centered, 12px, steel color, Montserrat |

---

## 3. Utility Helpers

### `_nan_to_dash(val) → str`

Converts `None`, `NaN`, empty string, or the literal string `"nan"` to `"—"`. Used everywhere in DataFrames so cells never display raw Python nulls.

### `_maude_url(report_id) → str`

Formats the FDA openFDA detail URL for a given report ID. Used in Signal Explorer to render each Report ID as a clickable link.

### `_load_db() → Database`

Loads the SQLite database. Priority order:
1. `MAUDESIGNAL_DB_PATH` environment variable (absolute path)
2. `data/safesignal.db` relative to the project root
3. Raises `FileNotFoundError` with a helpful message if neither exists

### `_try_load_config() → Config | None`

Wraps `Config.load()` in a try/except. Returns `None` if the config is missing (e.g., no API key set). Pages that require config check for `None` and render a user-friendly warning rather than crashing.

### `_extractions_dataframe(db) → pd.DataFrame`

Queries all extraction records from the database and flattens them into a DataFrame with columns: `extraction_ts`, `maude_report_id`, `skill_name`, `skill_version`, `confidence_score`, `requires_review`, `severity`, `ai_related_flag`, `ai_failure_mode`, `failure_mode`, `model_used`.

Parses the JSON `output_json` field from each row to surface structured skill output fields. Returns an empty DataFrame if there are no extractions yet.

### `_product_code_lookup(db) → dict[str, str]`

Builds a `{report_id → product_code}` mapping by querying normalized MAUDE events. Used in Signal Explorer to enrich extraction rows with the product code they originated from.

### `_device_name_lookup(db) → dict[str, str]`

Builds a `{product_code → device_name}` mapping from the FDA device catalog table. Falls back to `"—"` for any product code not found in the catalog.

### `_catalog_dataframe(db) → pd.DataFrame`

Converts device catalog DB rows into a DataFrame with columns: `code`, `device_name`, `company`, `specialty`, `decision_date`, `fda_number`. Used by the Settings → Device Catalog tab.

### `_page_header(icon, title, subtitle) → None`

Renders the standard page header using `st.html()` (not `st.markdown()`) to prevent Streamlit's markdown processor from injecting primary-colored spans around words. Both `h1` and `p` carry hardcoded inline styles so the design system colors render correctly regardless of Streamlit theme state.

Output structure:
```html
<div class="ms-page-header">
  <h1 style="font-size:36px; font-weight:500; color:#0A1317; …">🏠 Dashboard</h1>
  <p style="font-size:16px; font-weight:400; color:#606770; …">
    Executive summary of postmarket signal activity
  </p>
</div>
```

### `_kpi_card(col, value, label, variant="") → None`

Renders a KPI card inside a Streamlit column using `st.html()`. The `variant` parameter appends a CSS modifier class (`"red"`, `"amber"`, `"green"`) that changes the cobalt top rail to the appropriate semantic color.

Output structure:
```html
<div class="ms-card [variant]">
  <div class="val">290</div>
  <div class="lbl">MAUDE RECORDS</div>
</div>
```

### `_section(title) → None`

Renders a section heading (`<p class="ms-section">`) to visually separate logical groups of UI elements within a page.

---

## 4. Page Renderers

---

### Page 1 — Dashboard `_page_dashboard(db)`

**Purpose:** One-glance executive health check of the entire surveillance pipeline.

**Logic:**

1. Queries `db.count_maude_records()` → total raw MAUDE reports in DB.
2. Queries `db.list_extractions()` → filters those with `ai_related_flag=True` → AI signals count.
3. Computes mean `confidence_score` across all extractions → avg confidence KPI. Card is green if ≥ 0.8, amber if ≥ 0.6, red otherwise.
4. Queries `db.list_alert_rules()` → counts active rules → active alert rules KPI.
5. Sums `model_cost_usd` across all extractions → LLM cost to date KPI, formatted `$0.00`.
6. Builds **Severity Distribution** bar chart: groups extractions by `severity`, uses `_SEVERITY_ORDER` for consistent x-axis ordering, rendered with Altair.
7. Builds **AI Failure Mode Breakdown**: groups AI-related extractions by `ai_failure_mode`, takes top 8 categories, colors each bar using `_FAILURE_MODE_COLORS`, rendered with Altair.
8. Shows **Recent Signals** table: the 15 most recent extractions. Columns: Report ID (linked to openFDA), product code, device name, severity, AI-related flag, confidence score.

---

### Page 2 — Signal Explorer `_page_signal_explorer(db)`

**Purpose:** Browse, filter, and deeply investigate every extraction record in the database.

**Logic:**

1. Calls `_extractions_dataframe(db)`, `_product_code_lookup(db)`, and `_device_name_lookup(db)` to build an enriched flat DataFrame.
2. **Filters panel** (4 columns):
   - **Product Code** selectbox: all distinct codes + "(all)"
   - **Severity** selectbox: distinct severities sorted by `_SEVERITY_ORDER`
   - **AI Flag** selectbox: "(all)", "AI-related", "Not AI-related"
   - **Date Range** date input: defaults to the last 365 days
3. **Text search** input: case-insensitive substring match across device name and report ID columns.
4. All active filters are applied with `&` to the DataFrame. The record count (`N of M records`) is shown above the table.
5. Results rendered as `st.dataframe`. Clicking a row loads the **detail section**:
   - **Left column:** manufacturer narrative, brand name, product code, device name, event type, event date, openFDA link.
   - **Right column:** severity pill, AI-related badge, failure mode, confidence score progress bar, skill name used.
6. **Narrative expanders**: full patient/reporter narrative, full manufacturer narrative.
7. **Export CSV** button: serializes the filtered DataFrame with `df.to_csv(index=False)` and serves it as a browser download.

---

### Page 3 — MAUDE Ingestion `_page_ingestion(db)`

**Purpose:** Pull new adverse event reports from the openFDA API into the local SQLite database.

**Logic:**

1. Shows **Current Inventory** KPI cards: count of raw MAUDE reports and normalized events currently in the DB.
2. `st.form("ingest_form")` collects:
   - **FDA Product Code** (required text input, e.g. `QIH`)
   - **Record Limit** (number input, range 1–500, default 50)
   - **Start Date / End Date** (date pickers, defaulting to the last 365 days)
3. On submit, validates:
   - Product code must not be empty.
   - Start date must be before end date.
4. Calls `ingest_product_code(db, product_code, limit, start_date, end_date)` from the ingestion module, which fetches from openFDA and writes to the DB.
5. Shows result summary KPI cards: fetched, newly inserted, skipped (already existed), error count.
6. If any records were skipped, shows a breakdown of skip reasons.

---

### Page 4 — LLM Extraction `_page_extraction(db)`

**Purpose:** Run the 3-skill AI extraction pipeline on unprocessed MAUDE records.

**Logic:**

1. Calls `_try_load_config()`. If `None`, renders a `st.error` with setup instructions and returns early — no extraction is possible without a configured LLM provider.
2. Calls `db.list_unextracted_events()` to retrieve the pending queue.
3. Shows **Queue Status** KPI cards:
   - Total normalized events in the DB.
   - Already extracted (events with at least one extraction record).
   - Pending extraction — the queue size. Shown in amber if > 0.
4. If the queue is empty, shows a success banner and returns.
5. **Run Extraction controls:**
   - Product code selectbox to narrow the queue to a specific device.
   - Batch size input (1–100, default 10).
   - Caption confirming how many records will run and on which provider/model (`_active_model(cfg)`).
6. **Run Extraction** button triggers `_run_extraction_batch(db, cfg, queue[:batch_size])`.

#### `_run_extraction_batch(db, cfg, queue)`

1. Loads all three skill definitions from the `skills/` directory.
2. Iterates each event in the queue, updating `st.progress` after each record.
3. For each event:
   - Calls `LLMExtractor(cfg, skill=extractor_skill).extract(event)` → structured fields.
   - Passes the result through the severity-triage skill.
   - Passes the result through the ai-failure-mode-classifier skill.
   - Writes the final merged result to the DB via `db.save_extraction()`.
4. Renders a live-updating DataFrame showing: report ID, product code, AI-related flag, severity, confidence score, status (✅ success / ❌ failed).
5. After all records: summary of successes and failures with a prompt to rerun the page to see updated queue status.

#### `_active_model(cfg) → str`

Returns the model name string for the currently active LLM provider, e.g. `"gemini-2.5-flash"` or `"llama-3.3-70b-versatile"`. Used in the extraction caption and the Settings providers tab.

---

### Page 5 — PSUR Reports `_page_psur(db)`

**Purpose:** Generate AI-drafted Periodic Safety Update Reports and review saved drafts.

Split into two tabs.

#### Tab 1 — Existing Reports `_psur_existing_reports(db)`

1. Queries `db.list_psur_reports()` for all saved PSUR drafts.
2. Shows 4 KPI cards: total reports, confirmed signals, potential signals, no-signal reports.
3. Reports table: report ID, product code, device name, period start/end, signal assessment (colored pill), confidence score, drafted timestamp.
4. Selectbox to choose a report for preview.
5. **Report preview** section:
   - Header row: product code, device name, signal assessment badge, confidence score.
   - Reporting period dates.
   - Executive summary expandable block.
   - One expandable block per PSUR section (pulled from `output_json`).
   - Recommended actions as a bullet list.
   - ⚠️ Draft disclaimer banner: "DRAFT — REQUIRES HUMAN REVIEW BEFORE SUBMISSION."

#### Tab 2 — Generate New Report `_psur_generate(db)`

1. Product code selectbox (all known codes from DB).
2. Device name text input (pre-filled from the catalog if the product code is found).
3. Reporting window in days (default 180) → automatically computes start/end dates.
4. **Generate Draft** button calls `PsurGenerator(db, cfg).generate(product_code, device_name, start, end)`.
5. Shows result: signal assessment, confidence score, executive summary expander.
6. Confirmation with assigned report ID; report is saved to the DB.

---

### Page 6 — Alerts `_page_alerts(db)`

**Purpose:** Monitor signal thresholds, run live checks, and review alert history.

Split into three tabs.

#### Tab 1 — Alert Rules `_alerts_rules(db)`

1. Queries `db.list_alert_rules()` for all configured rules.
2. KPI cards: count of active rules (green), count of inactive rules.
3. Table showing all rules: rule ID (truncated UUID), metric, threshold value, evaluation window (days), delivery channel, scope, active status checkbox, description text.

Supported metrics: `ai_rate`, `severity_rate`, `new_reports`.  
Supported delivery channels: `console`, `slack`, `email`.

#### Tab 2 — Test Alerts `_alerts_test(db)`

1. Scope selector: test against all records or a specific product code.
2. **Run Alert Check** button calls `AlertChecker(db).check_all(scope)`.
3. Shows result KPIs: alerts fired (count, red if > 0), rules evaluated, delivered count.
4. Detail table: rule ID, metric, computed observed value, threshold, whether it fired, delivery status.

#### Tab 3 — History `_alerts_history(db)`

1. Queries `db.list_alert_events()` (most recent 100 events).
2. Table: fired timestamp, rule ID, metric, observed value, threshold, scope, delivered status.

---

### Page 7 — Settings `_page_settings(db)`

**Purpose:** View and verify configuration, database health, the device catalog, and external data sources.

Split into four tabs.

#### Tab 1 — LLM Providers `_settings_providers(db)`

1. Reads active config; shows a green "Active provider: PROVIDER / model-name" banner.
2. **Provider Status Cards** for Groq, Anthropic (Claude), OpenAI, and Google Gemini:
   - Green "✓ Key Set" pill if the corresponding API key env var is populated; red "✗ Not Configured" if not.
   - Provider name, env var name, masked API key preview (`Alza...rwbc`), active model name.
3. KPI cards: LLM cost to date (summed from DB), total extraction count.

#### Tab 2 — System `_settings_system(db)`

1. Database KPI cards: raw MAUDE report count, normalized event count, extraction record count.
2. **Health checks** (three status rows):
   - **Database:** runs a test query; shows ✅ Connected or ❌ Error with the exception message.
   - **Config:** calls `Config.load()`; shows ✅ Loaded or ⚠️ Not Configured with a setup hint.
   - **Skills directory:** checks that `skills/` exists and contains at least one subdirectory; shows ✅ Found or ❌ Missing.

#### Tab 3 — Device Catalog `_settings_catalog(db)`

1. Calls `_catalog_dataframe(db)` to load all FDA device catalog entries.
2. KPI cards: total catalog devices, distinct specialties.
3. Filters:
   - Specialty selectbox (all distinct specialties + "(all)")
   - Text search (searches device name, company name, product code columns)
4. Table with filtered rows: product code, device name, manufacturer company, medical specialty, decision date, 510(k) number.

#### Tab 4 — External Sources `_settings_sources(db)`

1. Queries `db.list_pubmed_articles()` and `db.list_clinical_trials()`.
2. KPI cards: PubMed article count, clinical trial count.
3. Two sub-tabs:
   - **PubMed:** table of PMID, title, authors, publication date, associated product code, article URL.
   - **ClinicalTrials:** table of NCT ID, title, brief summary, start date, associated product code, study URL.

---

## 5. App Shell — `_render_app(db)`

This function is called on every Streamlit rerun (page load, button click, filter change).

**Execution order:**

1. `st.set_page_config(title="MaudeSignal", icon="📡", layout="wide")` — must be the first Streamlit call in the session.
2. `st.html(_CSS)` — injects the full design-system stylesheet. Streamlit routes style-only HTML to its internal event container (invisible, takes no layout space).
3. **Sidebar construction:**
   - Logo image from `_LOGO_PATH` (centered, max-width 90px).
   - Brand name: `Maude**Signal**` in two styled spans.
   - Tagline: "AI-Powered Postmarket Surveillance".
   - `<hr>` separator.
   - 7 navigation buttons, one per entry in `_PAGES`. The active page button receives the `ms-active` CSS class. Current page is tracked in `st.session_state["page"]`.
   - **Status footer**: record count, active alert rule count, LLM spend, last extraction timestamp.
4. **Page routing:** looks up `page_fn_map[st.session_state["page"]]` and calls the matching `_page_*()` function with `db`.
5. **Footer:** `st.html(...)` renders a centered single-line attribution — "MaudeSignal — AI-Powered Postmarket Surveillance | Data: openFDA (public domain) | Not for clinical use | Every AI output requires human regulatory review".

---

## 6. Entry Point — `main()`

```
main()
 ├── _running_under_streamlit()?
 │    No  → subprocess.run(["python3.12", "-m", "streamlit", "run", __file__])
 │    Yes → continue
 ├── _load_db() → db
 └── _render_app(db)
```

`_running_under_streamlit()` checks for `"streamlit"` in `sys.modules`. If the module is invoked directly (`python app.py`), it re-launches itself under the Streamlit CLI.

`_is_main_module()` checks `__name__ == "__main__"`. The module-level execution block at the bottom of the file calls `_load_db()` and `_render_app()` directly when run under Streamlit.

---

## 7. Backward-Compatibility Aliases

Three legacy function names are kept as module-level aliases so existing tests or imports that reference old names continue to resolve without error:

| Alias | Points to |
|---|---|
| `_page_summary` | `_page_dashboard` |
| `_page_records` | `_page_signal_explorer` |
| `_page_drift` | `_page_psur` |

`_PAGE_GROUPS` is a static dict used by navigation regression tests to assert all 7 page names are present in the sidebar registry.

---

## 8. Data Flow Summary

```
openFDA API
    │
    ▼  Page 3 — MAUDE Ingestion
SQLite DB (safesignal.db)
    │
    │  maude_events table
    │
    ▼  Page 4 — LLM Extraction
LLM Provider (Groq / Gemini / OpenAI / Anthropic)
    │
    │  3-skill chain:
    │  maude-narrative-extractor
    │    → severity-triage
    │    → ai-failure-mode-classifier
    │
    ▼
extractions table ──► Page 1  Dashboard KPIs & charts
                  ──► Page 2  Signal Explorer filters & detail
                  ──► Page 6  Alert Checker threshold evaluation
                  ──► Page 5  PSUR Generator aggregated inputs
                                    │
                                    ▼
                              psur_reports table ──► Page 5  Existing Reports
```

**Read-only pages:** Dashboard, Signal Explorer, Alerts (history tab), Settings.

**Write pages:**
- **Ingestion** writes to `maude_records` and `maude_events`.
- **Extraction** writes to `extractions`.
- **Alerts (test tab)** writes fired events to `alert_events`.
- **PSUR generate** writes to `psur_reports`.

Every page reads from the same single SQLite database file. No page modifies data belonging to another page's pipeline stage.
