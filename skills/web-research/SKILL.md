# Skill: web-research

**Version:** 1.1.0 (HACKATHON-BUILT — Meta Global AI Developer Hackathon, Oct 26 – Nov 4, 2026)
**Model:** Meta Muse Spark (`muse-spark-1.3`, Standard tier) via the Meta Model API
Responses endpoint, with the built-in `web_search` tool
**Consumers:** `maudesignal.connector.research.run_research` (website Research mode, behind
`MAUDESIGNAL_RESEARCH`; later the connector tool)
**Output schema:** `schemas/output.schema.json` describes the research block the code builds
from the reply (url citations and search sources). It is NOT sent as a `response_format`:
the model answers in plain text with url citations, and the code keeps only links.

## Purpose and limits

Research mode looks for public web pages about a device-safety question, next to the normal
FDA-records answer. It is not a source of FDA facts. Its output is shown under the fixed label
"Web research — not FDA records, not verified by the gate". It never enters the gated answer,
the claim gate, a MAUDE count, a signal or the evidence pack. A person decides whether a link
is worth saving (`POST /v1/live/research/save`).

Only the section "Instructions (sent to the model)" below is sent, as the request's
`instructions`. Everything else in this file is documentation.

## Instructions (sent to the model)

You help a medical-device quality or regulatory reviewer find public web pages about a
device-safety topic. Use the web_search tool at most twice. Prefer primary sources: fda.gov
safety communications, recalls and press releases, manufacturer notices, peer-reviewed
journals. Then reply with a short list, one line per page: the page title, its link, and its
publication date only if the page itself shows one (otherwise write "date not shown"). Cite
every page with a url citation. Do not give medical advice or tell anyone what to do for a
patient. Do not say a device is safe, unsafe, approved or cleared. Do not state counts of
reports or recalls. Do not invent titles, links or dates. If you find nothing relevant, say so
in one sentence.

## Input

The `input` is the visitor's question, with "Device type (FDA product code): XXX." appended
when the visitor chose a product code. The question has already passed the patient-data
check of the live routes.

## How the code uses the reply

- Items come from `url_citation` annotations of the final message first, then from
  `web_search_call.action.sources` (requested with
  `include: ["web_search_call.action.sources"]`).
- Only `http` / `https` links; duplicates removed; at most 8 items.
- `date` is taken only from a date field the API returns; otherwise `null`. The code never
  reads a date out of the model's prose.
- `source` is the link's domain (`www.` removed). GDELT backup items say "GDELT news index".
- `summary_text` is always `null` (since 1.1.0): only title, link, date and source are shown;
  the model's prose is never displayed.

## Changelog

- 1.0.0 (2026-10-31): initial version. Instructions for Muse Spark 1.3 with the built-in
  `web_search` tool (at most two searches, low reasoning, 3000 output tokens), and the research
  block schema. Probe 1 (run 41246131207) showed the tool is accepted on `muse-spark-1.3`.
- 1.1.0 (2026-11-01): `summary_text` is always `null` (schema: `"type": "null"`); only links
  are shown. No retry after a 400; Research is off unless `MAUDESIGNAL_RESEARCH` is set, and
  should be switched on only after probe 2 confirms `max_tool_calls` is honoured.
