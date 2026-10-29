# MaudeSignal final build week: agentic workflow

Coordinator plan for Oct 29 – Nov 4, 2026 (submit Nov 4, about 5 PM PT).
Status: **approved by Charan on Oct 29** (design system kept; deploy steps go to Charan).

## 0. Where things stand (checked Oct 29, 13:00 UTC)

| Item | State | Evidence |
|---|---|---|
| `claude/RUBRIC-100.md`, `claude/PRD-v2-final.md`, `claude/TASK-claude-code-oct28.md`, `claude/daily-status-oct29.md` | **Not in the repo** (searched the whole disk). They live in the Claude project only. | `find / -iname "RUBRIC-100*"` → nothing |
| PR #6 (Day 1 scaffold) | Closed | GitHub PR list |
| PR #7 (hackathon build) and PR #9 (Signals workspace) | Merged to `main` with Charan's OK | merge commits `ea58b0f`, `d90e1f6` |
| Daily monitor on `main` | First digest committed to `main` today | `be05711 chore(monitor): what-changed digest 2026-10-29` |
| "CAPA-need evidence" rename | Landed (34 files use it) | `grep -rli capa-need src docs README.md` |
| F12 report-source filter | Landed: `report_sources` tool, `source_count` gate claim, 10 adversarial cases | `src/maudesignal/monitor/sources.py`, `gate/claims.py`, `tests/fixtures/gate/adversarial.jsonl` |
| Demo story (Q04 removed, Q05 replaced, non-manufacturer question) | Landed in the fifth recording | `demo/transcripts/*-05-capa-need-evidence.json`, `*-21-not-by-manufacturer.json`, no `04` |
| `docs/VALIDATION_EVIDENCE.md` | Exists | file |
| README "How it's different" + pricing | Exists | `README.md:83`, `:132` |
| CI on `hackathon-day2` head | Green (unit 3.11/3.12, security, product browser tests 42/42) | run 40845568584 |

So most of TASK-oct28 appears to have landed, but I can only confirm it against
the task file itself once it is in the repo (see §8, decision 1).

## 1. Tracks and file ownership

Tracks never edit the same files. Anything outside a track's folders goes
through the coordinator.

| Track | Branch (from `hackathon-day2`) | Owns | Starts |
|---|---|---|---|
| A "core" | `track-a-core` | `src/`, `skills/`, `tests/`, `scripts/` (except `scripts/export_web_data.py`), `docs/`, `README.md`, `demo/RECORD_REQUEST` | after approval |
| B "agentic UI" | `track-b-ui` | `web/` (new), `api/` (new), `scripts/export_web_data.py`, plus one exception: `tests/unit/test_export_web_data.py` | after approval |
| C "channel intake" | `track-c-intake` | `src/maudesignal/intake/`, `bot/` (new) | **not now**; Charan starts it separately |
| Coordinator (me) | `hackathon-day2` | `web/DATA_CONTRACT.md`, `.github/`, `HACKATHON.md`, `CLAUDE.md`, `claude/`, `vercel.json`, merges | now |

The data contract (`web/DATA_CONTRACT.md`) is written by the coordinator
**before** either track starts, so A and B build against the same schema
without touching each other's files.

## 2. Track A "core": the three agentic workflows, then polish

Priorities follow Charan's research doc "PMS Market Research & Agentic Workflow Plan"
(build workflows 1–3 by about Oct 31 so they can be recorded). The four `claude/`
docs are not in the repo, so TASK-oct28 is checked against what landed (§0) instead
of section by section.

| Milestone | Work | Done when (paste the command + real output) | Rubric line |
|---|---|---|---|
| A1 Search protocol (workflow 3, ~½ day) | Every tool call already records dataset, filters, dates and counts. Turn that log into a "Search methodology" appendix in the evidence-pack PDF and a `protocol` field per answer, so an auditor can repeat each search | Unit tests; a regenerated PDF shows the appendix (page image path) | Impact, Technical |
| A2 Weekly investigator (workflow 1, ~1 day) | When the weekly check flags a device type, Muse Spark pulls the new reports, groups them by kind of problem, checks recalls, 510(k)s and non-manufacturer reports, and writes the digest entry through the gate. Code + mocked tests here; a recording workflow (`.github/workflows/investigator-record.yml`, Track A may add it) records real runs to `demo/investigations/` | Mocked tests pass; workflow file valid | Meta tooling, Impact |
| A3 Recall-triggered sweep (workflow 2, ~1 day) | On a new recall in a watched type, Spark reads the recall reason and searches stored narratives for the same failure: "N reports describe the same problem", quotes matched word for word, counts recomputed by the gate, links | Mocked tests; adversarial gate cases for the new claims (0 false pass / 0 false block kept) | Meta tooling, Impact |
| A4 Words and docs | PRD wording (drop list: "worsening signals", "overnight", "citation-checked", "complaint data"; never "FDA-approved", "Part 11 compliant", "validated"); BEUDAMED added to README "How it's different"; deadline Nov 4 in the submission draft; `VALIDATION_EVIDENCE.md` and README numbers from real runs only; the FDA Elsa 4.0 line used only if an FDA source confirms it | `grep` for each dropped word returns 0 hits; every README number traced to a file or run id | Demo, Impact |
| A5 Inputs for the web app + green PR | Inputs complete per `web/DATA_CONTRACT.md`; `tests/unit/test_data_contract.py`; ruff, black, `mypy --strict`, coverage ≥55%; PR `track-a-core → hackathon-day2` | CI run id green | Technical |

Real Muse Spark runs for A2/A3 happen in GitHub Actions (the key is a repository
secret); the coordinator triggers them after merging A2/A3, and only real recorded
runs are shown.

Helpers A may spawn: `Explore` (find code), `validator` (repo FTI check),
`general-purpose` (research). A never runs `advisor` on itself.

## 3. Track B "agentic UI": the workspace

| Milestone | Work | Done when | Rubric line |
|---|---|---|---|
| B1 Shell + data | Vite + React + TypeScript + Tailwind in `web/`; 3-pane layout (sidebar, chat, artifacts); light/dark following the system; phone: drawer + bottom sheet; `scripts/export_web_data.py` writes `web/public/data/*.json` from the demo DB and `demo/` per the contract | `npm run build` passes; exporter test passes; screenshot of the empty shell at 1440 and 390 | Demo |
| B2 Chat | Workflow threads replay stored transcripts with tool steps ("searched 137 reports"), streaming-style reveal; claim chips (green verified with evidence on hover/tap, red withheld with the gate's reason); composer with + menu (upload routes to vision/voice; GitHub and Drive labelled "coming soon", never faked); mic replays the recorded voice question; suggested prompts | Screenshots of each workflow thread | Demo, Meta tooling |
| B3 Artifacts | Right panel tabs: daily brief, signal digest, dossier (PDF viewer + download), vision (image with SAM boxes, fields, two-read check), audit trail (hash chain "verified ✓"), CAPA draft (approve only in a human role). Header strip "Every sentence checked against FDA data · N claims verified · M withheld" with N and M computed from the transcripts | Screenshots; N/M match a script count | Impact, Demo |
| B4 Live API (optional) | `api/` FastAPI: `/gate/verify` runs the real gate; `/ask` answers live only with `META_MODEL_API_KEY` set server-side, else says "demo mode"; `vercel.json`; exact deploy steps in README | `curl` output of both endpoints locally | Meta tooling, Technical |
| B5 QA | Playwright screenshots of every workflow at 1440 and 390, dark and light → `web/qa/screenshots/`; `ui-critic` then fixes; Lighthouse accessibility ≥90 if feasible | ui-critic list empty of top-priority items; Lighthouse score pasted | Demo |

Helpers B may spawn: `Explore`, `general-purpose`, `ui-critic` (only for B5).
Design: follows `design-system/` tokens (see §8, decision 2). Streamlit stays as
the fallback and the README links both.

## 4. Advisor loop (every milestone, both tracks)

```
builder (sonnet, own worktree, pushes its track branch)
  -> returns: branch, head sha, files changed, commands run + real output, screenshot paths
advisor (opus, fresh context)
  -> gets only: branch name, base sha, the rules (CLAUDE.md + claude/ docs)
  -> runs `git diff <base>..<head>` itself, re-runs ruff / mypy --strict / pytest,
     opens the changed files and screenshots
  -> returns PASS or BLOCK + numbered issues (file:line, problem, fix) + rubric delta
BLOCK -> a fixer builder gets only the issue list -> advisor again
max 3 advisor loops per milestone, then the workflow stops that track and escalates to Charan
```

The coordinator, not the builder, starts the advisor, so the builder's
reasoning never reaches it.

## 5. Hallucination guard

- Builder results are structured: no "done" without `commands[]` (command,
  exit code, last lines of real output), `files_changed[]` and, for UI,
  `screenshots[]` paths.
- The advisor re-runs the commands instead of trusting the output.
- The coordinator spot-checks one claimed command per milestone before reporting
  to Charan, and reports numbers only from files or run ids.

## 6. Merge order

1. Coordinator writes `web/DATA_CONTRACT.md` on `hackathon-day2` (before tracks start).
2. A and B open separate PRs into `hackathon-day2` (draft, CI must be green).
3. Coordinator merges A first (B's exporter reads A's artifacts), then B; resolves conflicts.
4. Re-record (A2) only after A1 is on `hackathon-day2`.
5. **Nothing into `main` without Charan's OK.**

## 7. How it runs

- Commits: author "Saicharan Kondapally <kondapallysaicharan63@gmail.com>" with
  `Co-Authored-By: Claude`.

- One Workflow per batch of milestones (A1–A3 with B1–B3 in parallel; then
  A4–A5 with B4–B5), so I read results between batches and you can redirect.
- Builders: sonnet, `isolation: worktree`. Advisor: opus. ui-critic: sonnet.
- Estimated size: about 10 milestones × (1 builder + 1–3 advisor/fix rounds) ≈
  25–40 agents over the week. Meta API spend: one re-record, cents.
- Every evening (about 8 PM PT): score log appended to `claude/RUBRIC-100.md`,
  `HACKATHON.md` updated, branches pushed, 10-line status to Charan
  (done / blocked / needs Charan).

## 8. Decisions needed from Charan before Step 2

1. **Add the four `claude/` files to the repo** (or paste them here). Without
   them, A0 cannot check TASK-oct28 section by section, the advisor cannot check
   PRD §9 words, and there is no score log to append to.
2. **Fonts.** CLAUDE.md §8.5 says every UI uses `design-system/` (Newsreader +
   Geist, paper theme). The Track B spec says Inter or system font. Recommendation:
   keep the design system (Geist at 17–18px is close to Inter) so we don't break
   our own rule; or say "update §8.5" and B uses Inter.
3. **Deploy.** A Vercel connector is attached to this session, so I could deploy
   `web/` myself once you say so (it publishes a public URL). Otherwise you get
   the exact click steps.
4. **API on Vercel.** `/gate/verify` needs the gate and the demo database
   (SQLAlchemy). If that is too heavy for a Vercel Python function, B4 falls back to
   running the API next to the Streamlit app, or is cut. B1–B3 and B5 do not depend on it.
5. **Deadline.** You said Nov 4 about 5 PM PT. `docs/hackathon/SUBMISSION_DRAFT.md`
   still says Oct 30; A1 fixes that.
