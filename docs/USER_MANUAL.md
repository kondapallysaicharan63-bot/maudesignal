# MaudeSignal — User Manual

Saicharan Kondapally (solo builder). Written for reviewers who want to try the product and
check it against a few real use cases.

## 1. What it is, and what it is not

**When a complaint arrives, MaudeSignal finds the matching FDA evidence in one question,
prepares PMS evidence, and keeps every fact traceable for audit.** It reads public openFDA
data (MAUDE adverse event reports, recalls, 510(k)s) for AI/ML and imaging software device
types, and every number or quote it shows links to the openFDA query or record it came from.

What it is not, stated plainly:

- **This build is not validated.**
- Not medical advice and not clinical decision support.
- Outputs are signals for a person in quality or regulatory to review. A named person
  makes every decision.
- Nothing is filed with FDA.
- Not a QMS, and there is no direct QMS integration. You move its output into your own
  system by hand.

## 2. How to try it

**No install:** open the live demo at <https://maudesignal-app.vercel.app>. No key is
needed. Answers made without a model key are recorded runs, labelled "recorded" with their
date.

**On your own laptop** (Python 3.11+; commands taken from the README and `pyproject.toml`):

```bash
git clone https://github.com/kondapallysaicharan63-bot/maudesignal.git
cd maudesignal
python3.12 -m venv .venv && source .venv/bin/activate
pip install -e .

python -m maudesignal.cli --help          # the maudesignal CLI
python -m maudesignal.cli monitor --no-fetch   # what-changed digest from the demo database
streamlit run streamlit_app.py            # dashboard on the committed demo database
```

The web app (Node 20.19+, from `web/package.json`):

```bash
cd web && npm ci && npm run dev
```

Without an API address the web app shows the stored data and recorded runs. To point it at
your own API, set `VITE_MAUDESIGNAL_API_BASE`.

The read-only API (`api/index.py`, a FastAPI app), as run in
[docs/hackathon/MUSE_CONNECTOR.md](hackathon/MUSE_CONNECTOR.md):

```bash
pip install -e '.[connector]'
uvicorn api.index:app
```

Then open `/v1/health` and `/docs-page` on that address. Keys and environment variables
are listed in the README section "Deploy your own copy".

## 3. Connect the MCP connector

- Server address: `https://maudesignal-api.vercel.app/mcp`
- Header: `X-API-Key`, with the public read-only demo key shown on the website's
  **Connect** page (I do not repeat the key here).
- Status: Submitted to Meta's Muse Connector Program — pending review.

Six read-only tools (from [api/mcp-manifest.json](../api/mcp-manifest.json)):

| Tool | What it does |
|---|---|
| `what_changed_this_week` | Device types whose report counts changed in the latest stored week, or one product code |
| `check_device_type` | Live openFDA check of any product code: latest week against the four weeks before |
| `ask` | A free-text question; Muse Spark answers through the stored-record tools and the claim gate |
| `get_report` | One stored MAUDE report: key fields and the start of the narrative, word for word |
| `recalls` | FDA recalls on file for a product code, newest first |
| `lookup_device` | Possible FDA records for a device in hand (label, model, K-number, UDI); a person confirms the match |

## 4. Using it in your own workflow (manual, not integrated)

1. Copy or download the evidence (Investigate page, "Evidence for the complaint file":
   **Copy** / **Download .txt**; the **Evidence pack** panel, after a named person records
   the note to file: Markdown note, PDF, reports CSV and audit JSON).
2. File it yourself in your PMS board, note to file or complaint file.
3. A named person decides FDA escalation, whether a recall is needed and whether a CAPA is
   needed. MaudeSignal asks the questions; it does not decide.
4. The audit trail (**Evidence → Audit verified**, `/evidence/audit`, and the audit JSON export) shows each step and who
   recorded it.

## 5. Use cases to evaluate

### a. A complaint arrives

LLZ is the FDA product code for image-processing software (Class II). MYN is image analyzer
software (Class II) that marks images for a radiologist to look at; it does not replace the
radiologist.

1. Open **Investigate a complaint** (`/investigate`).
2. Enter product code `LLZ` and a few words, e.g. "image not displaying". No patient details.
3. Read the counts by month, the reports not filed by a manufacturer, and the quotes from
   report narratives.
4. Open **Recalls and 510(k)s for this product code**.
5. Go to **Evidence for the complaint file** and the **Evidence pack**; copy or download it.
6. Repeat with `MYN`.

What to check: every count and quote opens its openFDA query or record; the date banner at
the top says when the data is from; the page says it never decides reportability.

### b. Weekly PMS board

1. Open the **Morning brief** (`/daily`): new flags in the latest AI device sweep week and
   what changed in the stored demo snapshot.
2. Open the **Board** (`/board`), or click the owl dock, whose caption shows "N to review".
3. For each row, read why it was flagged (what changed this week).
4. A named person moves each row (New, then Under review, then Note to file, Escalated or Closed).

What to check: each number on the brief links to its openFDA query; a status changes only
when a person enters a name, and the change appears in the audit trail.

### c. Recall-need check

1. For a device type (e.g. LLZ), open the recalls: the **Recalls** section on Investigate, or
   the `recalls` connector tool.
2. Read the warning: no recalls on file does not mean none exist.
3. In the evidence pack, read the "Recall / correction-and-removal assessment" question.
4. A person decides under their own recall procedure and records it.

What to check: the tool never says a recall is or is not needed.

### Copilot

Open **chat** (`/chat`) and ask a question, e.g. "What changed this week for LLZ?". Muse
Spark answers live from the stored records, and the claim gate checks every sentence.
Anything it cannot verify is held back and shown as withheld, not as fact. Without a model
key the closest recorded answer is shown, labelled "recorded".

## 6. Data dates and limits

- Stored snapshot: the newest stored report was received Aug 31, 2026
  (`max_date_received` in [data/demo/SEED_MANIFEST.json](../data/demo/SEED_MANIFEST.json)).
- The Investigate live openFDA check is separate from the snapshot and is dated when it runs.
- openFDA republishes weekly and reports arrive with delay, so recent weeks may show few or no
  reports because of reporting delay, not because risk is zero.
- No EUDAMED data. FDA data only (MHRA alerts appear only as labelled regulator context).
- No live scraper or news feed. Outside web results are labelled unverified and kept apart
  from FDA records.
- No ROI or time-saved figures are claimed.
- MAUDE reports alone do not prove that a device caused a problem.

## 7. Video

Demo video: https://youtu.be/Q8bwdKgWYPM
