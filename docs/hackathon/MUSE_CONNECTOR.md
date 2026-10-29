# MaudeSignal connector for Meta Muse (read-only REST API; MCP server next)

Status: **built and tested locally; not submitted.** The submission form answers, the MCP
transport, and the "submitted, pending Meta review" line come in a later milestone and only
after the owner submits. Nothing on this page says anyone has reviewed or endorsed the connector.

This page so far covers what the REST tool layer does, what it cannot yet do, and what to
check before anything is switched on.

## What it is

Five read-only tools (REST today, MCP in the next milestone, same code):
`what_changed_this_week`, `check_device_type`, `ask`, `get_report`, `recalls`.
Every answer has: a short speakable summary, facts that each carry an openFDA or record link,
the fixed advisory line ("Advisory triage aid for quality and regulatory review; not medical
advice; nothing is filed with FDA."), and provenance (stored demo snapshot with its dates, or
live openFDA with the query time, or a recorded answer, or a live model answer).

## Read-only, enforced

* No endpoint writes. `ask` runs the Muse Spark copilot, whose toolbox also holds
  `draft_capa` (it inserts a draft row). The connector never offers that tool to the model and
  turns any call to it into an error (`connector/readonly.py`); a test makes a scripted model
  call it and checks the `capa_drafts` table stays empty. A test also fails if the copilot
  gains a tool that is not listed as read-only or write.
* An answer is only spoken if the claim gate passed it **and** it has an openFDA or record
  link. A sentence that passed but has no link is listed under `withheld` ("not spoken").
* Words this service never uses (`connector/forbidden.py`) are screened out of recorded and
  live text, and the tests scan every stored question and every banned term.

## Recorded answers (no model key, or cost cap reached)

`ask` returns a real, gated recording from `demo/transcripts`, labelled
`recorded_answer`, with the recorded question and the stored-data date in the spoken lead. A
recording is used only if every meaningful word of the question appears in the recorded
question or the first sentence of its answer, and a product code in the question appears
there too. Voice-mode and greeting recordings are never used. Otherwise the answer is "no
verified answer, try the what changed / recalls tools". Count links on recorded answers are
recovered from the sentence text and kept only if the stored reports for that product code
and window number exactly what the gate recomputed.

## Known limits (read before turning the live key on)

1. **Rate limit and daily cost cap are per server instance.** The per-minute limiter is in
   memory and the daily spend ledger is a file in the instance's temporary folder. On Vercel
   each instance has its own, and both reset on a cold start, so a caller can exceed either
   limit across instances or restarts. `/v1/health` reports `limits_scope: per_instance`.
   **Do not set `META_MODEL_API_KEY` in Vercel until one of these is done:** back the limiter
   and ledger with a shared store (Vercel KV / Upstash or an Edge Config counter), or put a
   hard spending limit on the Meta key itself. Without the key, `ask` only returns recordings
   and no spend is possible.
2. **A key in a URL is refused (400) and the query is blanked** before uvicorn's access log
   can print it. Vercel's own request log is outside this code, so send the key only in the
   `X-API-Key` header. Run uvicorn with `--no-access-log` (or a log config that drops the
   query string) anywhere else.
3. **Deploy check still open.** The root `vercel.json` rewrites `/v1/*` and `/openapi.json` to
   `api/index.py`. The repository root also has the full `pyproject.toml` (pandas, streamlit,
   weasyprint). The Vercel Python runtime may install from that instead of `api/requirements.txt`
   and exceed the function size limit. Before the real deploy, run `vercel build` or a
   preview deploy and check which manifest was installed and the bundle size. Also confirm
   with Track B that this root `vercel.json` does not take over their site's routing; if it
   does, move the connector to its own Vercel project with root directory `api/`.
4. **MCP is not built yet.** Only the REST transport exists; do not describe the connector as
   an MCP server until `tools/list` and `tools/call` are implemented and tested.
5. Live openFDA calls (`check_device_type`, unstored codes) and the live Muse Spark call have
   not been run from this environment (no network); tests use fakes.
