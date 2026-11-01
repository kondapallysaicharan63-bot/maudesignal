# MaudeSignal final build week: agentic workflow

Coordinator plan for Oct 29 – Nov 4, 2026 (submit Nov 4, about 5 PM PT).
Status: **approved by Charan on Oct 29** (design system kept; deploy steps go to Charan).

> **Single source of truth.** Tracks, status, decisions, open items and next steps live
> here. The coordinator updates this file after every milestone and re-reads it after any
> context compaction before acting.

## Live status (updated 2026-10-30 ~00:45 UTC Oct 30)

| Track / item | Branch | State | Evidence | Next |
|---|---|---|---|---|
| A core: A1b search protocol (#3), A2 weekly investigator (#1), A3 recall sweep (#2), A4 doc to-dos | `track-a-core` (head `3d89089`) | **All PASS** (advisor; A4 on 2nd round) | workflow `wf_2a36efa4-681` journal | Draft PR → `hackathon-day2` once CI runs on PRs into it; merge on green |
| A follow-up: real Muse Spark runs | `hackathon-day2` after merge | Not started | — | Push `demo/INVESTIGATE_REQUEST` (weekly + recall) and `demo/RECORD_REQUEST` (re-record evidence-pack narrative + Wonder review with pack binding); Meta credit, cents |
| B workspace: B1 shell, B2 chat, B3 artifacts | `track-b-ui` | **PASS** | `wf_d5c47891-d4b` | — |
| B4: Charan's 6 preview fixes | `track-b-ui` (fast-forwarded to `f621f7c`) | **PASS** (2nd advisor round) | `wf_41350c6f-170`; screenshots `web/qa/screenshots/B4-*.png`; 47 vitest incl. TS↔Python parity (320 cases); 0 "coming soon" | Browser CORS to openFDA untested here (sandbox); Charan checks on the preview. PR `track-b-ui` → `hackathon-day2` after Track A merges |
| C Muse connector v2 (Charan chose: one more C1 round, then C2): C1b fix (redact withheld text; test that no withheld sentence or 20+ char substring appears in any live response), C2 REST pack + public check endpoint, C3 MCP | `track-c-muse` | **Running** | `wf_8922564f-9f3` | After C2 PASS: ask Charan before each Vercel write: (1) create the API project, (2) turn Deployment Protection (Vercel Authentication) OFF on it so Muse and the web app's check calls don't hit a login page, (3) its env vars (`MAUDESIGNAL_API_KEYS` generated, never printed; `OPENFDA_API_KEY`; `MAUDESIGNAL_WEB_ORIGINS`; `MAUDESIGNAL_TRUST_FORWARDED=1`) |
| B5: web check via our API (`VITE_MAUDESIGNAL_API_BASE`), "CAPA-need evidence" rename, npm audit (now 0 vulnerabilities), 00-voice-main excluded | `track-b-ui` at `c181b53` | **PASS** (2nd round); Vercel preview READY | `wf_ffc9ce07-8f8`; 55 vitest | Set `VITE_MAUDESIGNAL_API_BASE` after the API is deployed (Charan's OK); contract section added to `web/DATA_CONTRACT.md` |
| Coordinator: live-app Settings fix + CI on PRs into `hackathon-day2` | merged (`e59f126`) | **PASS, live** | advisor report; settings screenshots | — |
| Coordinator fix 2: `draft_capa` shown as `capa_need_evidence`; retired clip 00-voice-main hidden (chain still verified); cap fallback never offers it | `coordinator-fix-2` (`ed60e46`) | **PASS** (2nd round) | 1016 unit; 17 e2e; 0 drop-list words | Merge together with the voice branch (conflicts with 2aa8382 in copilot_pages.py) |
| Voice (taken over from Muse's 2aa8382): fifth recording restored; 3 takes kept (take1=Q1, take6=Q2, take4=Q3) with Charan's consent in `demo/voice/README.md`; takes 2/3/5/7 and TTS `question.wav` removed | `coordinator-voice` (`232983b`) | 2aa8382 advisor review running | 1022 unit; all 10 audit exports verify | After the 2aa8382 verdict: merge fix-2 into this branch, resolve the conflict, advisor, merge to `hackathon-day2`; then re-export web data |
| Vercel web project `maudesignal` (prj_x1NDkrSG6VoZ4Ax7OrQugC1DVHeu) | — | Connector has team access (Oct 29). `track-b-ui` preview READY at f621f7c; other branches fail by design (no `web/`) | build log read via connector | Browser check gets 403 from openFDA → web app will call the API's public check endpoint (C2); npm audit: 5 vulns (2 critical) → Track B |
| Incident: `2aa8382` pushed by Meta Muse under Charan's name (unsigned, unreviewed) → bot recording `f53b64a` (run 40965201781) replaced all stored data | `hackathon-day2` | Advisor **BLOCK** on 2aa8382 (product-code correction rewrites real codes/words; any 3-letter word taken as a code). Data reverted to the fifth recording in `54a95fe` (byte-identical to `f53b64a^`); 2aa8382 code still on the branch pending V1 | advisor report | V1 fix running on `coordinator-voice` (`wf_3bf07d9b-6e1`); process: Muse should push to its own branch, never to `hackathon-day2`, and never bump `RECORD_REQUEST` |
| Track A merge | PR [#10](https://github.com/kondapallysaicharan63-bot/maudesignal/pull/10) `track-a-core` → `hackathon-day2` | CI: Audit regression fixed (`4bce6f3`); Copilot count failure comes from the base (2aa8382) and is fixed by `coordinator-voice` | PR comments | Merge order: `coordinator-voice` first (after V1 PASS), then #10 on green; Vercel check on #10 fails by design until Track B merges |
| B6 (low priority, after voice fix + C2): sweep card states the rules + "148 of 181 codes had fewer than 3 reports this week (132 had none)"; artifacts tab row wraps, no horizontal scroll | `track-b-ui` | Queued | MUD and MQB meet the detector rules (checked) | Charan to decide: minimum count for "more serious than usual"? |
| API deployed (Charan's OK, Oct 30): Vercel project `maudesignal-api` (prj_gQcS5vOLNI9WW5EaGAfC6FIK0RhA), production from `track-c-muse` @ `2baafe3` (C3 head; C3 advisor still open, doc wording only), Deployment Protection off, build installs `api/requirements.txt` | — | **Live**: `/v1/health` 200; `/v1/public/check_device_type?product_code=LLZ` 200 but answered from the stored snapshot (live openFDA failed on Vercel; error not logged → logging fix in F-api) | build log + runtime logs via connector | Charan sets `MAUDESIGNAL_API_KEYS`, `MAUDESIGNAL_KEY_PEPPER`, `OPENFDA_API_KEY` himself (the sandbox refused to let Claude generate secrets); `META_MODEL_API_KEY` not set (Charan: wait for per-IP limit + daily cap) |
| Web: `VITE_MAUDESIGNAL_API_BASE` set, `track-b-ui` redeployed; short domain `maudesignal-app.vercel.app` → branch `track-b-ui` (`maudesignal.vercel.app` belongs to another account) | — | Live | connector | Move the domain to production after the merge |
| Feedback + ref codes (Charan, Oct 30, urgent before outreach): `/v1/feedback`, `/v1/visit`, private `/admin` + CSV export (X-Admin-Key = `MAUDESIGNAL_ADMIN_KEY`), private Vercel Blob store `maudesignal-feedback` (created, token on the API project), email via Resend (`RESEND_API_KEY`, `FEEDBACK_NOTIFY_TO`); web Give-feedback panel, `?r=CODE`, visit pings, Vercel Web Analytics | `track-c-feedback`, `track-b-feedback` | **Running** | `wf_97662d63-16a` | After PASS: deploy API from `track-c-feedback`, web branch domain → `track-b-feedback` (or merge into `track-b-ui`) |
| Oct 30 ~01:15 UTC: feedback + ref codes **PASS** (F-api round 1; F-web after coordinator fixes: ruff probe removed, B6a merged, 390px header) → API production = `track-c-feedback` @ `6854957` on https://maudesignal-api.vercel.app (also maudesignal-connector.vercel.app); `/v1/health` feedback_store=blob_private; `/v1/admin/*` 503 until `MAUDESIGNAL_ADMIN_KEY`. Web `track-b-ui` fast-forwarded to `d249a15` (B6a + feedback) → https://maudesignal-app.vercel.app | — | Live | advisor reports | Charan adds `MAUDESIGNAL_API_KEYS`, `MAUDESIGNAL_KEY_PEPPER`, `OPENFDA_API_KEY`, `MAUDESIGNAL_ADMIN_KEY` (+ Resend optional); then a real feedback round-trip via /admin |
| PR #10 merged into `hackathon-day2` (`0d83f4a`). Side effect: the merge added `demo/INVESTIGATE_REQUEST`, which started `investigator-record.yml` → bot commit `fad3048` (one weekly LLZ investigator run, $0.22 Meta credit) | — | Done; recording under advisor review | — | Charan: keep or remove the recording. Same pattern will fire `vision-label-match.yml` + `vision-labels.yml` when PR #11 merges (approved re-record) |
| PR #11 `track-a-label-match` → `hackathon-day2` | draft | CI running | — | Merge on green |
| Oct 30 ~02:35 UTC: running - `merge-prep` (wf_24aa31bc-3ff: DB freeze, sweep pause, severity min, voice confirm, stale docs, dossier-only record path); feature + B6c (wf_22d8981f-fd3: A6 → A7 + B7, B6c); PR #12 label fixes (A10b PASS) → then LABEL_MATCH_REQUEST "reuse" (free); deploy trigger 21:05 UTC (trig_016DBEqz6LgiAQdozozL8r9G) | — | Running | — | Charan set MAUDESIGNAL_ADMIN_KEY; /admin how-to due Oct 31 |
| B6 + C4 (Charan, Oct 30; build freeze Sun Nov 1): B6a layout (home dashboard, mini-dashboards, expand/collapse, alert bell, sweep rules + skipped-codes line, tab wrap); B6b agent trace (per-step model badge; time/tokens/cost only where stored), camera + mic (recorded fallback labelled "recorded run", patient-data warning), type-ahead | `track-b-ui-wip` → `track-b-ui` | **Running** (ui-critic then advisor per milestone) | `wf_2db2118c-d37` | B6c after A10 lands: possible-matches + confirm UI for labels |
| A10 label match (Charan, Oct 30): label fields → openFDA 510(k) / registration & listing / classification / UDI → up to 3 possible matches with reasons (and mismatches); a person confirms, never auto-pick; device-type view (reports, recalls, 510(k), this week's change) gated; step trace with measured timings | `track-a-label-match` | **Running** | `wf_ba4f4413-d6e` | After PASS: Charan asked to re-record the 7 labels in CI → bump `demo/vision/LABEL_MATCH_REQUEST` (paid SAM + Spark, cents); C4 `/v1/label` builds on it. Found: stored thermometer-1 (HoMedics) shows Hetaida 510(k)s as candidates by device name only - A10 must show the manufacturer mismatch |
| C4 `/v1/label` + `/v1/voice` | `track-c-muse` | Queued after C3 | — | per-IP 5/day, global cost cap, recorded fallback, no image stored unless opt-in, EXIF stripped, patient-data warning |
| Feature "Does this apply to us?" (§3c) | A6–A9, B7 | Planned, starts after voice fix + C2 | — | D0 contract first |
| Daily monitor on `main` | `main` | Ran Oct 29 | commit `be05711` digest | Watch tomorrow's 11:17 UTC run (check-in 11:50 UTC) |

### Decisions (with date)
- Oct 29: plan approved; keep the design system (Newsreader + Geist); Charan deploys Vercel himself (connector has no access to team `kondapallysaicharan63-9868s-projects`).
- Oct 29: research doc "PMS Market Research & Agentic Workflow Plan" first: workflows 1–3 + BEUDAMED + Elsa check (no Elsa line without an FDA source).
- Oct 29: deployed Streamlit shows product pages only (`SHOW_ALL_PAGES_BY_DEFAULT = False`; `?tools=all` for the rest).
- Oct 29: Track C = Meta Muse connector (REST + MCP on Vercel), replaces Telegram intake; `api/` moved from B to C.
- Oct 29: Track C order: REST API + OpenAPI + docs page deployed and verified first; MCP second. Connector key lives only in a Vercel env var (`MAUDESIGNAL_API_KEYS`), never in chat or git.
- Oct 29: Vercel connector may read previews/build logs; every Vercel write (deploy, env var, setting) needs Charan's OK in chat. API key: Claude creates `MAUDESIGNAL_API_KEYS` in the API project's env, never printed.
- Oct 29: web "Check any device type" goes through our API's public, per-IP-limited endpoint (browser→openFDA is refused with 403); visible "CAPA draft" → "CAPA-need evidence" in both apps.
- Oct 29: Charan turned off Vercel Authentication on the web project `maudesignal` (judges open it without login). The API project needs the same.
- Oct 29 (correction): the "82 mypy errors" were a sandbox artifact: the bare `mypy` on PATH is an isolated uv tool without the project's packages (42 import-not-found plus knock-on untyped-decorator / unused-ignore). With the project environment, `python3 -m mypy src/maudesignal` (strict, per pyproject) reports **Success: no issues found** on `hackathon-day2` (104 files), `track-a-core` (107) and `track-c-muse` incl. `api/` (118); CI's mypy step is green too. Builders and advisors use `python3 -m mypy` from now on. Docs only claim that CI runs `mypy --strict`, which is accurate.
- Oct 29: commits: author Saicharan Kondapally, committer Claude <noreply@anthropic.com> (Verified on GitHub).
- Oct 29 (voice, for Charan to accept): the product-code check corrects only to codes that have records on file (JAK, LLZ, MYN, POK, QIH on the demo DB). The spec said "exactly one known code", but with the seed code LLN counted as a target, LLG and LLC would tie (LLN) and never become LLZ. So on the real code set QAH is corrected to QIH (the "QAH tie" test uses a made-up set; a separate test pins the real behaviour). In live mode the analyst confirms first.
- Oct 29 (voice): `.github/workflows/copilot-record.yml`'s voice loop now finds only `question-a..e` and `question-take1/4/6`. A new recording run would re-record the takes (overwriting them) and recreate the hidden TTS transcripts (a, b, c, e); restrict the loop before the next `RECORD_REQUEST`.
- Oct 30: Charan asked to re-record the 7 device labels through the new match step in CI (paid SAM 3.1 + Muse Spark run, approved by that request).
- Oct 30 (Charan): NO Vercel deployments until Charan explicitly says so. Both projects' Ignored Build Step = `exit 0` (every git build skipped); the scheduled quota deploy was cancelled. Live URLs keep serving their current deployments (web `track-b-ui` d249a15; API `track-c-feedback` 6854957, which predates the new env vars). Previews go to a private Claude artifact instead: https://claude.ai/artifact/H1Zw2c193hV5b8RAbBEHXg (republish the same dist after each reviewed web change). Never delete `track-b-ui` (~30 people have its link).
- Oct 30 (Charan, main-merge decisions): (1) freeze demo DB at 137 reports; monitor writes its own DB; (2) re-record the evidence-pack narrative + Wonder review for the current pack (one paid run, dossier-only, on branch `record-dossier`; quoted numbers 63/65, 27/28, 19,970 / 99.3% must stay unchanged - report before committing); (3) keep the $0.22 investigator recording; (4) pause the Monday AI sweep until Nov 5 (reminder set), daily monitor keeps running. Severity rule gets the same minimum count as the detector (≥3), shown on the sweep card with skipped codes. Voice correction never silent: "Heard QAH -> did you mean QIH?", used only after confirmation; stored demo shows both. Real codes never corrected.
- Oct 30 (Charan, deploys): exactly two Vercel deploys when the quota frees: 1st maudesignal-api production (track-c-next: keys + email-batch-1), 2nd web track-b-ui (track-b-next: B6b + codeless pings). Nothing else until both verified. Then one batched web deploy per day.
- Oct 30 (Charan, priorities before Nov 1 freeze): (a) "Does this apply to us?" (highest), (b) B6c, (c) C4 only if (a) and (b) pass review by Oct 31 evening, else skip C4 and keep recorded camera/voice runs.
- Oct 31 (release tools, `release-tools` branch, builder R-ci; decisions made without waiting for Charan): `release-check.yml` (push to `release/**`) and `smoke.yml` (push to `smoke/**`) with `scripts/release/*.py`, described in `docs/hackathon/RELEASE_CHECKS.md`. Choices: (1) statuses PASS / FAIL / SKIPPED / BLOCKED / NOT_PRESENT / KNOWN_GAP, a skipped required step is a failure, BLOCKED (for example keys not provided) is reported and never a pass but does not crash the job; (2) ruff and black run on `src tests scripts api`, not on `web/`; coverage floor 70% on `tests/unit`; (3) the API has no fake-model switch, so the contract job runs without a Meta key (recorded answers); the release check has no live job, uses no Meta key and spends $0; real-model checks run only in `smoke.yml` after deploy (1 ask and 1 voice, $0.55 at the holds), and no automated check sends an injection question to the real model; (4) WebKit has no fake microphone, reported as KNOWN_GAP; (5) smoke compares the LLZ figures (33 reports, 8.75) only when the answer is the stored snapshot; (6) the load test counts 429 from the per-address public-check limit as "limited", not as an error. Verified here only against the `track-c-live` and `track-b-live` code on this machine (no Actions run, no network to openFDA / Meta / Vercel).
- Deadline: Nov 4, about 5 PM PT. Nothing into `main` without Charan's OK.

#### Oct 31 overnight (coordinator decisions, integration branch `integrate-m1`)
- **Cap rule (one rule, $3.00 per UTC day).** Every Meta call (keyed `ask`, live ask, live voice, live label) reserves its worst-case cost in the private Blob ledger first, is settled to its real cost only after a successful reply, and stays counted at its worst case if it fails. Enforced ceiling is $3.00 minus one call's largest hold ($0.10) = $2.90. The earlier "total over all keys" variable (`MAUDESIGNAL_API_TOTAL_DAILY_USD`) does not exist in the merged code and is gone from the docs. The per-key daily total stays as a smaller, separate limit. Source of truth: `docs/hackathon/MUSE_CONNECTOR.md`, "Cost".
- **Paid CI live job: to be removed (follow-up), NOT removed yet.** The intent is a post-deploy smoke against the deployed API, with the per-call ledger as the spend limit. The tree does not do that yet. These workflows can still spend Meta credit on a push: `meta-smoke.yml` (push to `hackathon-day2` or `hackathon-copilot` touching `src/maudesignal/copilot/**`, `test_meta_connection.py` or the workflow itself); `copilot-record.yml`, `investigator-record.yml` and `vision-label-match.yml` (push of their request file to `hackathon-day2`); `vision-labels.yml` (push of label photos to `hackathon-day2`); `live-smoke.yml` (push of `demo/LIVE_SMOKE_REQUEST`, which holds `0`, to `track-c-live`, or by hand). **Merging `integrate-m1` into `hackathon-day2` WILL start `meta-smoke`**, because this merge changes `src/maudesignal/copilot/spend.py` (brought in from `track-c-live`). Coordinator: either accept that one run, or approve a follow-up that deletes `live-smoke.yml` and adds a `paths-ignore` or branch guard to `meta-smoke.yml`. Not done here.
- **Integration branch and release branches.** `integrate-m1` = `hackathon-day2` + merges (no rebase) of `track-c-live`, `track-c-lookup`, `track-b-m2`, in that order. Release branches are cut from a reviewed `integrate-*` branch; nothing goes to `main` without Charan's OK. Builders push only their own branch.
- **Deploy rules.** No Vercel write without Charan's explicit OK. Order: API first, smoke it (`/v1/health`, `/docs-page`, one keyed tool call, one recorded `ask`), then the web project with `VITE_MAUDESIGNAL_API_BASE` set to the verified API URL, smoke it again. Production keeps Vercel Authentication off. Keys and tokens live only in Vercel env vars.
- **Merge resolutions.** Connector code is the union of `track-c-live` and `track-c-lookup` (every route, the per-call ledger, `lookup_device`, MCP prompts and instructions, helpful errors). `label.py` takes the shared helpers from `common/device_ids.py` and keeps stripping lot and serial from stored UDIs. `api/requirements.txt` includes Pillow (live label route), so the import test no longer blocks it. `vercel.json` includes `demo/mentions`, `demo/vision` and `demo/sweep`. `demo/mentions/LLZ.json` is the original recorded `track-c-live` file again (byte-identical, including the MassDevice row and trace step that failed with HTTP 403). An earlier commit (8aba053) had replaced it with a hand-edited `track-b-m2` copy without those rows; that edit is reverted so the recorded run can be checked. MassDevice stays dropped from searching (see `connector/mentions.py` sources) and the UI (`web/src/mentions.ts` `isDropped`) and the connector doc keep the `track-c-live` versions. Web data re-exported from the merged stored data; quoted numbers unchanged (63/65, 27/28, 19,970 / 99.3%, 6 of 181).

#### 2026-10-31 (day log: decisions and outcomes)
- **API + web deployed from `d5bb583`** (Merge release-tools into release/m1). The smoke run found a mismatch in its own photo mock, not in the app; fixed in the test mock only (`b4dcb81`, "photo mock matches the real /v1/live/label shape").
- **Main merge:** PR #16 (`a48c3aa`, `merge-main`). The demo database stays frozen at 137 reports; bot digests are parked (`cd3c48a`, main's 2026-09-06 digest moved next to the other bot digests).
- **Chat answer tiers:** built (`76fbf13`, tests `a5b8868`), three review rounds (`e604c7f`, `5ff66e1`, `a6dcabb`), deployed from `d4bea03`. Post-deploy smoke cost $0.046. Description and cost estimate: `docs/hackathon/CHAT_TIERS.md`.
- **Outside mentions re-recorded** (request `1c207c0`, bot commit `9d45690` on `track-c-live`, searched 2026-10-31 17:38 UTC): 0 mentions found for LLZ. Sources tried: GDELT DOC 2.0 (failed: TimeoutError after 3 tries), FDA press releases RSS (ok, 0), FDA recalls RSS (ok, 0), FDA MedWatch safety alerts RSS (ok, 0), FDA medical devices feed RSS (failed: http 404), MedTech Dive RSS (ok, 0).
- **Label-reader workflow** ran on the `hackathon-day2` merge: about $0.09 (estimate), nothing saved.
- **Deploys used today: 4.** Today's paid Meta spend is about $0.50 (estimate).
- **Owner's new rules:** one agent per track; flags: every new feature ships behind an on/off setting so it can be switched off instead of reverted; at most 2 more deploys, each only after the owner says yes.
- **Tracks A–E started** (Track D: docs and wording on `track-d-docs`, this entry).

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
| Oct 30 03:00 UTC (coordinator estimate, not measured) | 8 | 9 | 8.5 | 9.5 | Muse connector REST+MCP live (keys pending one redeploy); label photo → possible openFDA matches with reasons + person confirms (A10/A10b, 7 labels re-recorded); real investigator run (7/7 gate); feedback + ref codes live on the emailed link; B6a/B6b workspace (agent trace, alert bell, type-ahead); PRs #10–#12 merged | Main merge (prep running); evidence-pack re-record; "Does this apply to us?" + B6c (building); API redeploy at 21:05 UTC; video shot list; practitioner quotes |
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

## 3c. Feature "Does this apply to us?" (Charan, Oct 30; starts after the voice fix and C2)

From practitioner feedback, demonstrated with a **simulated** company. Track A builds the
core and the Streamlit page, Track B the web workflow; advisor PASS for each milestone.

Ground rules: every screen and PDF says "Simulated company — sample data. Problem
evidence is real FDA data."; fictional device names only (no real company names, no real
K-numbers on fictional devices); the simulated data lives in its own demo file, never in
the real records; statuses are set only by a named (simulated) person, never by the tool;
never the words "safe", "unsafe", "compliant".

| Milestone | Work | Done when |
|---|---|---|
| D0 (coordinator) | Data contract for `company.json` (devices, codes, patterns, statuses, history) in `web/DATA_CONTRACT.md` | Contract committed before A/B start |
| A6 Simulated company + patterns + statuses | "Demo MedTech Co. (simulated)": 12 fictional devices on real codes: 2 LLZ; 1 each QIH, MYN, POK; 4 on sweep-flagged codes (IYN, OTE, DSI, MUD all meet the detector rules, checked Oct 30); 3 on sweep "no change" codes. Device-type names from openFDA classification (recorded, with source). Real reports/recalls per code grouped into problem patterns (reusing the weekly-investigator groups; counts and quotes gate-checked; evidence links). Statuses: Not applicable (reason) / Already covered (sample reference, e.g. "test report TR-104 (sample)") / Testing in progress (owner, due date) / Needs review (owner) / Monitoring — nothing open; about half the devices with real patterns covering every status; forward-only; hash-chained audit | Tests: separation from real records, forward-only transitions, audit chain, banner on every surface, gate on counts/quotes, no forbidden words |
| A7 Verification questions | Skill (structured output): Muse Spark suggests 2–3 plain verification questions per pattern; questions only; recorded in CI (key from secrets) | Skill folder complete; mocked tests; recording run on Charan's OK |
| A8 (optional) Sample risk table | Labelled sample CSV; Spark suggests which rows MIGHT cover each pattern, quoting the table verbatim (gate-checked), "suggestion — your team confirms" | Quote check test; label on every surface |
| A9 Streamlit + PDF | "Our devices" page (table with status chips → patterns, evidence, status history); the checklist as a section in the CAPA-need evidence PDF | e2e + PDF text check |
| B7 Web "Our devices" | Sidebar workflow, device table with status chips, patterns + evidence + history, right-panel artifact; data from the exporter | Build, vitest, screenshots 1440/390 light/dark |
| Video | Shot "this is how it looks when a company installs it" in `claude/video-script-v1.md` | Shot list committed |

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

- Commits: author "Saicharan Kondapally" with
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

### 2026-11-01 00:20 UTC — deploy #1 path
- Release check green on 0d7fe88 (release/m3: tracks A–E). Vercel refused the API-created production
  deploy (free plan: more than 100 API deployments in 24 h). Owner chose: push release/m3 to `main`
  so Vercel builds production from git. 7e82feb = 0d7fe88 + main's two merge commits (no file
  difference). Smoke tests run after the production builds; rollback targets: API
  dpl_2TWpkZKwNEnPyBAdUkoakvcoKMvf, web dpl_qEG9iLDgWRLRyND91skxNViMjSRs (both d4bea03).
