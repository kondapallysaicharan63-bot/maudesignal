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
  live text, including the left-out (`withheld`) sentences and their reasons: a left-out
  sentence that contains one is replaced by "Sentence left out: it contains a term this
  service does not use." Tests scan the whole response (speakable, facts, withheld, provenance)
  for every banned term on every stored question and on a scripted live answer.
* In live mode the text of a left-out sentence is never returned, whatever the reason (gate
  block, banned term, no link). `withheld` holds a neutral placeholder, a fixed reason text per
  claim kind (never the gate's own reason string, which can carry text the model wrote into a
  claim field such as a section or report id), and the claim kinds. Tests check that no 20-character piece of
  such a sentence, and no free text put in a claim field, is anywhere in the response or the raw REST body. (Recorded answers still
  list the recorded text of gate-blocked sentences, labelled not verified.)

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
   Live Muse Spark calls are therefore **off in code**, not just by convention: `ask` calls the
   model only when `META_MODEL_API_KEY` is set **and** `MAUDESIGNAL_ALLOW_PER_INSTANCE_CAP=1`
   is set (an explicit acceptance of per-instance limits). A model key alone returns recorded
   answers (`provenance.kind = recorded_answer`). No shared store is built yet; before enabling
   live mode on Vercel, back the limiter and ledger with one (Vercel KV / Upstash) or put a hard
   spending limit on the Meta key itself.
   When the key is set but live mode is not accepted, the recorded answer says live calls are
   switched off on this server (`live_off`); with no key it says none is configured (`no_model`).
   `MAUDESIGNAL_TRUST_FORWARDED=1`: use the first `X-Forwarded-For` entry as the client address
   for rate limiting. **Set it on Vercel** (its edge sets the header); leave it unset anywhere
   else, where the header is caller-controlled and the socket address is used instead.
   Outside Vercel, also run uvicorn with `--no-proxy-headers` (or `--forwarded-allow-ips` set to
   the real proxy only): by default uvicorn rewrites the client address from `X-Forwarded-For`
   when the peer is `127.0.0.1`, which lets a caller behind a local reverse proxy rotate it.
   Other settings: `MAUDESIGNAL_KEY_PEPPER` (server-side secret for the key ids that appear in
   ledger file names and audit session ids; set it), `MAUDESIGNAL_FAILED_AUTH_PER_MIN` (wrong or
   missing keys per client address per minute before 429, default 10). Plain keys shorter than 32
   characters are refused at start-up (a warning with a count is logged, never the key).
   **Audit entry of a live `ask` is not visible from the laptop (open decision).** A live `ask`
   writes its copilot audit and spend rows to a temporary copy of the demo database on the
   Vercel instance, which is lost on a cold start. The video beat "laptop shows the same answer
   plus its audit entry" must not be scripted until the connector's audit entry has a home that
   the laptop can read (a shared store, or an audit trail returned in the response). Decide this
   in the next milestone.
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
