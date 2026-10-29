# MaudeSignal final build week: agentic workflow

Coordinator plan for Oct 29 – Nov 4, 2026 (submit Nov 4, about 5 PM PT).
Status: **approved by Charan on Oct 29** (design system kept; deploy steps go to Charan).

> **Single source of truth.** Tracks, status, decisions, open items and next steps live
> here. The coordinator updates this file after every milestone and re-reads it after any
> context compaction before acting.

## Live status (updated 2026-10-29 ~23:00 UTC)

| Track / item | Branch | State | Evidence | Next |
|---|---|---|---|---|
| A core: A1b search protocol (#3), A2 weekly investigator (#1), A3 recall sweep (#2), A4 doc to-dos | `track-a-core` (head `3d89089`) | **All PASS** (advisor; A4 on 2nd round) | workflow `wf_2a36efa4-681` journal | Draft PR → `hackathon-day2` once CI runs on PRs into it; merge on green |
| A follow-up: real Muse Spark runs | `hackathon-day2` after merge | Not started | — | Push `demo/INVESTIGATE_REQUEST` (weekly + recall) and `demo/RECORD_REQUEST` (re-record evidence-pack narrative + Wonder review with pack binding); Meta credit, cents |
| B workspace: B1 shell, B2 chat, B3 artifacts | `track-b-ui` | **PASS** | `wf_d5c47891-d4b` | — |
| B4: Charan's 6 preview fixes | `track-b-ui` (fast-forwarded to `f621f7c`) | **PASS** (2nd advisor round) | `wf_41350c6f-170`; screenshots `web/qa/screenshots/B4-*.png`; 47 vitest incl. TS↔Python parity (320 cases); 0 "coming soon" | Browser CORS to openFDA untested here (sandbox); Charan checks on the preview. PR `track-b-ui` → `hackathon-day2` after Track A merges |
| C Muse connector: C1 REST + auth/limits | `track-c-muse` (head `22a3b8b`) | **ESCALATED to Charan** after 3 advisor rounds: 2 blockers left (withheld live sentences keep forbidden-term text verbatim; doc claims screening). 1098 unit tests pass | `wf_f2a3790d-566` | Charan decides: 1 more fix round, then C2 (REST pack + public check endpoint for the web app), then C3 MCP |
| Coordinator: live-app Settings fix + CI on PRs into `hackathon-day2` | merged (`e59f126`) | **PASS, live** | advisor report; settings screenshots | — |
| Coordinator fix 2: `draft_capa` shown as `capa_need_evidence`; retired clip 00-voice-main hidden (chain still verified) | `coordinator-fix-2` (`e8da075`) | Advisor review running | 11 e2e pass; rendered pages contain no drop-list words | Merge on PASS |
| Vercel web project `maudesignal` (prj_x1NDkrSG6VoZ4Ax7OrQugC1DVHeu) | — | Connector has team access (Oct 29). `track-b-ui` preview READY at f621f7c; other branches fail by design (no `web/`) | build log read via connector | Browser check gets 403 from openFDA → web app will call the API's public check endpoint (C2); npm audit: 5 vulns (2 critical) → Track B |
| Daily monitor on `main` | `main` | Ran Oct 29 | commit `be05711` digest | Watch tomorrow's 11:17 UTC run (check-in 11:50 UTC) |

### Decisions (with date)
- Oct 29: plan approved; keep the design system (Newsreader + Geist); Charan deploys Vercel himself (connector has no access to team `kondapallysaicharan63-9868s-projects`).
- Oct 29: research doc "PMS Market Research & Agentic Workflow Plan" first: workflows 1–3 + BEUDAMED + Elsa check (no Elsa line without an FDA source).
- Oct 29: deployed Streamlit shows product pages only (`SHOW_ALL_PAGES_BY_DEFAULT = False`; `?tools=all` for the rest).
- Oct 29: Track C = Meta Muse connector (REST + MCP on Vercel), replaces Telegram intake; `api/` moved from B to C.
- Oct 29: Track C order: REST API + OpenAPI + docs page deployed and verified first; MCP second. Connector key lives only in a Vercel env var (`MAUDESIGNAL_API_KEYS`), never in chat or git.
- Oct 29: Vercel connector may read previews/build logs; every Vercel write (deploy, env var, setting) needs Charan's OK in chat. API key: Claude creates `MAUDESIGNAL_API_KEYS` in the API project's env, never printed.
- Oct 29: web "Check any device type" goes through our API's public, per-IP-limited endpoint (browser→openFDA is refused with 403); visible "CAPA draft" → "CAPA-need evidence" in both apps.
- Oct 29: commits: author Saicharan Kondapally, committer Claude <noreply@anthropic.com> (Verified on GitHub).
- Deadline: Nov 4, about 5 PM PT. Nothing into `main` without Charan's OK.

### Open items needing Charan
1. Add the four `claude/` docs (RUBRIC-100, PRD-v2-final, TASK-oct28, daily-status) to the repo, or paste them.
2. Vercel: web project Root Directory `web`, Vite, deploy `track-b-ui`; send the preview URL. Later a second project for the API (Track C steps).
3. Practitioner quotes (1–3), with written permission before naming anyone.
4. Voiceover on the latest walkthrough; independent re-check of the hand-check.
5. FDA source for any Elsa 4.0 line (until then none is used).
6. Muse connector: submit only when ready; status stays "Not submitted" until then.
7. Optional: `OPENFDA_API_KEY` in Streamlit Secrets; Upstash Redis for shared API limits/audit.

### Next steps (coordinator, in order)
1. Settings fix PASS → merge into `hackathon-day2`.
2. PR `track-a-core` → `hackathon-day2`, CI green, merge; then trigger the real recordings.
3. After A merges: re-run `scripts/export_web_data.py` on Track B so the workspace shows the new protocol and, once recorded, the investigator and recall runs.
4. B4 PASS → screenshots + preview link to Charan; PR `track-b-ui` → `hackathon-day2`.
5. C3 PASS → API deploy steps, Muse steps, `claude/video-script-v1.md` shot list, rubric delta; PR `track-c-muse` → `hackathon-day2`.
6. Evening status at 03:00 UTC: score log below + `HACKATHON.md` manifest.

### Score log
| Date | Impact | Meta tooling | Demo | Technical | What moved it | Still missing |
|---|---|---|---|---|---|---|
| Oct 29 (coordinator estimate, not measured) | 7.5 | 8.5 | 8 (after voiceover) | 9.5 | AI device sweep (6 of 181), live check, 2:53 video, search protocol | Practitioner quotes; real investigator/recall recordings; deployed workspace |

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
| B "agentic UI" | `track-b-ui` | `web/` (new), `scripts/export_web_data.py`, plus one exception: `tests/unit/test_export_web_data.py` (`api/` moved to Track C on Oct 29) | after approval |
| C "Muse connector" (replaces the Telegram intake plan, Oct 29) | `track-c-muse` | `api/` (new), `src/maudesignal/connector/` (new), `tests/unit/test_connector*.py`, `docs/hackathon/MUSE_CONNECTOR.md`, root `vercel.json` (API project only) | Oct 29, Charan's go |
| Coordinator (me) | `hackathon-day2` | `web/DATA_CONTRACT.md`, `.github/`, `HACKATHON.md`, `CLAUDE.md`, `claude/`, merges | now |

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
| B4 Preview feedback | Charan's six fixes on the Vercel preview (no "coming soon", real sweep first, demo-snapshot labels, overlap bug, chips, withheld link, browser "Check any device type"); the live API moved to Track C | Advisor PASS, then `track-b-ui` fast-forwarded | Demo, Impact |
| B5 QA | Playwright screenshots of every workflow at 1440 and 390, dark and light → `web/qa/screenshots/`; `ui-critic` then fixes; Lighthouse accessibility ≥90 if feasible | ui-critic list empty of top-priority items; Lighthouse score pasted | Demo |

Helpers B may spawn: `Explore`, `general-purpose`, `ui-critic` (only for B5).
Design: follows `design-system/` tokens (see §8, decision 2). Streamlit stays as
the fallback and the README links both.

## 3b. Track C "Muse connector": MaudeSignal inside Meta's Muse

Replaces the Telegram intake plan (Charan, Oct 29). One read-only tool layer, two
transports: a REST API (OpenAPI) and an MCP server, hosted on Vercel from `api/`.
Builder sonnet in its own worktree, advisor opus, same loop as A and B.

Tools (read-only): `what_changed_this_week(product_code?)`,
`check_device_type(product_code)` (live openFDA counts, the detector's rules, via
`monitor/live_check.py`), `ask(question)` (Muse Spark copilot; every sentence through
the claim gate; withheld sentences marked), `get_report(report_id)`,
`recalls(product_code)`. Answers are short and speakable (Muse has a voice mode); every
fact carries its openFDA or record link; advisory only, not medical advice, nothing is
filed with FDA.

| Milestone | Work | Done when | Rubric line |
|---|---|---|---|
| C1 Tool layer + REST | `src/maudesignal/connector/` (tools, speakable answer shape, links); `api/` FastAPI app; API-key header auth (keys from a Vercel env var, read-only scope), per-key rate limit, daily cost cap on `ask` that falls back to the closest stored answer; OpenAPI spec | Contract test per tool; gate enforced on `ask`; rate-limit and cost-cap tests; no key in any response or log | Technical, Meta tooling |
| C2 MCP transport | The same tools over MCP (streamable HTTP, stateless), tool annotations read-only; MCP manifest; tests through an MCP client | `tools/list` and `tools/call` tests for every tool | Meta tooling |
| C3 Hosting + submission pack | Vercel config for a second project rooted at the repo root (the web app stays its own project), optional shared store for audit/rate limits (Upstash Redis via Vercel Marketplace, env-gated; in-memory per instance otherwise, documented), `GET /v1/audit/recent` for the workspace; `docs/hackathon/MUSE_CONNECTOR.md` with the submission answers (tool docs, inputs, outputs, limits, read-only labels, privacy, terms, support contact), status "not submitted" until Charan submits | Local `uvicorn` + `curl` transcripts for every endpoint; MCP client transcript; doc complete with no "approved"/"official" | Impact, Demo |

Not claimed: Meta approval or an official listing. Third-party guides describe a
submission form at muse.ai/platform (HTTPS MCP endpoint, privacy policy, terms,
support contact); no official Meta page was found, so the doc lists those fields as
"to confirm against the live form".

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
