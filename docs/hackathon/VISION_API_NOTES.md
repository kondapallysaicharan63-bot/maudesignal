# Meta vision APIs: notes for the 510(k) reader and label camera

Read 2026-10-27 from Meta's developer docs. The "Documented" tables come from
the pages below. The last section lists what is **not** verified and how the
code handles it. No live call has been made from the build sandbox (no key);
`scripts/record_vision_runs.py` makes the first real calls in CI.

## Sources

| Page | URL |
|---|---|
| SAM overview (request, response anatomy) | https://dev.meta.ai/docs/sam/overview |
| Segmenting with prompts (input parts, data URLs, metadata, limits, errors) | https://dev.meta.ai/docs/sam/segmenting |
| Reading segmentation output (full grammar) | https://dev.meta.ai/docs/sam/reading-segmentation |
| SAM client libraries (`meta_sam_parser`, not used) | https://dev.meta.ai/docs/sam/client-libraries |
| Media segmentation guide (Python streaming / raw SSE example) | https://dev.meta.ai/docs/media-segmentation |
| Image understanding (Chat Completions image parts, limits, tokens) | https://dev.meta.ai/docs/image-understanding |
| File handling (PDF input = text + page images) | https://dev.meta.ai/docs/file-handling |
| Structured output (strict subset) | https://dev.meta.ai/docs/structured-output |
| Pricing and rate limits | https://dev.meta.ai/docs/pricing-rate-limits |

## Documented — Muse Spark with images (`vision/spark.py`, `vision/reader.py`, `vision/label.py`)

| Item | Value |
|---|---|
| Image part (Chat Completions) | `{"type": "image_url", "image_url": {"url": "<public URL or data:image/...;base64,...>"}}` in a user message |
| Images per request | ≤ 50 (more → HTTP 400) — `MAX_IMAGES_PER_REQUEST` |
| Inline image size | ≤ 50 MB (50,000,000 bytes) — `MAX_INLINE_IMAGE_BYTES` |
| MIME types | jpeg, jpg, png, gif, webp, x-icon |
| Token cost of an image | scales with resolution; ~1280 px ≈ 1,300–1,500 tokens; exact count via `POST /v1/responses/input_tokens` |
| PDF input | Responses API `input_file`; converted to text **plus** page images; first 50 page-images / 100 pages of text retained. Not used: pages are rasterized locally and sent as images, so the model never sees the text layer the accuracy check compares against |
| Structured output | `response_format={"type":"json_schema","json_schema":{"name","schema","strict":true}}`; decoding is constrained; `strict` validates the schema against the subset: root a plain object, no `oneOf`/`allOf` anywhere, `anyOf` only below the root, every object `additionalProperties:false`, `required` lists every key. Recursive schemas → 400. `check_strict_subset()` enforces this locally and a unit test runs it on both Skill schemas |
| Price | `muse-spark-1.3` Standard: $1.25 / M input, $4.25 / M output (Contributor variants rejected in code) |

## Documented — SAM 3.1 (`vision/sam.py`)

| Item | Value |
|---|---|
| Endpoint | `POST https://api.meta.ai/v1/responses`, model `sam-3.1`, same Bearer key |
| Body | one `message` (role `user`) with an `input_text` noun phrase and one `input_image` (`image_url` string) |
| Data URLs | **Documented**: "image_url / video_url: a public URL or a base64 data URL (data:image/png;base64,...)" (segmenting page) — no Files API upload needed for stills |
| Prompt | one short concrete noun phrase per request; lists ("bus, bicycle") return zero matches; formatting/case/plurals ignored |
| Streaming | `stream: true`, SSE; accumulate `response.output_text.delta`, end on `response.completed`. Non-streaming also allowed |
| Zero matches | empty `output_text`, no delta events — not an error |
| Confidence | `metadata.include_confidence` = the STRING `"true"` (anything else → 400) |
| Output grammar | `line ::= <Nf> record ("," record)*`; `record ::= id <\|box;x1;y1;x2;y2;w;h[;c]\|><\|mask;x=0;y=0[;c];data=H,W,ENC PAYLOAD\|>`; boxes in source pixels, x2/y2 inclusive; `w`/`h` = source size on every record; ids stable, not dense; `ENC` `~` lossless / `!` one_bit; payload base85, may contain `!`/`~` |
| Errors | 400 permanent (don't retry unchanged); 404 `model_not_found` without access |
| Price | image segmentation $2.50 per 1,000 images — `SAM_USD_PER_IMAGE` |
| Rate limit | `sam-3.1`: 3,000 requests/min per team, no TPM limit |

The parser was tested on the three example lines printed on the reading page
(video frame, three-match image, confidence-bearing box/point response).

## Not verified, and how the code copes

| Unknown | Handling |
|---|---|
| Exact SSE event JSON for SAM (only the `type`/`delta` fields are shown) | `read_sse_text` reads `type`, `delta`, and `response.usage` defensively; unknown events ignored; `error` / `response.failed` / `response.incomplete` raise `SamError` |
| Whether one delta always carries exactly one whole line | deltas are joined with newlines; frame markers trusted only at line starts (a base85 payload could contain `<5f>`), with a fallback split on every marker |
| Base85 alphabet of mask payloads | masks are not decoded (only boxes are needed); payload kept as text |
| Whether `strict: true` accepts the `$schema` key | stripped before sending |
| How faithfully Muse Spark transcribes faint scanned summaries | the accuracy check exists for this: two independent reads (order + resolution differ) must agree, then openFDA / text layer must agree; conflicts are shown, not resolved |
| FDA PDF folder for 1976–2001 numbers (`cdrh_docs/pdf/`) | demo uses 2003+ numbers (`pdf3/`, `pdf4/`, `pdf19/`, `pdf21/`, `pdf26/`) |
| FDA download from cloud IPs | from the build sandbox `accessdata.fda.gov` served its "abuse-detection apology" page (HTTP 302 → 404) for every PDF; `download_510k_pdf` detects this and says to save the file manually into `data/demo/510k/`. Whether GitHub Actions runners are allowed is unknown until CI runs |
