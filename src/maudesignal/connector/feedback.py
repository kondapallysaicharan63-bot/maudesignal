"""Private feedback intake, visit pings and the key-protected admin export.

Routes (all hidden from the public OpenAPI document):

* ``POST /v1/feedback`` and ``POST /v1/visit``: keyless, browser origin must be listed in
  ``MAUDESIGNAL_WEB_ORIGINS``, rate limited per address. No IP address and no user agent is ever
  stored; the limiter sees only a salted hash of the address for the length of its window.
* ``GET /v1/admin/export``, ``GET /v1/admin/summary`` and ``GET /admin``: need the
  ``X-Admin-Key`` header (constant-time check against ``MAUDESIGNAL_ADMIN_KEY``). If that
  variable is unset the admin routes answer 503, never open.

Feedback is never served by any public route. This is not a PHI system: free text that looks
like patient details is refused, which is a guard and not a guarantee.
"""

from __future__ import annotations

import csv
import hashlib
import hmac
import io
import json
import os
import re
import secrets
import uuid
from collections import defaultdict
from collections.abc import Awaitable, Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from typing import Annotated, Any, Literal

from fastapi import FastAPI, Query, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from starlette.concurrency import run_in_threadpool
from starlette.requests import ClientDisconnect

from maudesignal.common.logging import get_logger
from maudesignal.connector.blob_store import BlobRef, RecordStore, StoreError
from maudesignal.connector.notify import Notifier
from maudesignal.connector.security import RateLimiter

logger = get_logger(__name__)

ADMIN_KEY_ENV = "MAUDESIGNAL_ADMIN_KEY"
FEEDBACK_LIMIT_ENV = "MAUDESIGNAL_FEEDBACK_PER_HOUR"
VISIT_LIMIT_ENV = "MAUDESIGNAL_VISIT_PER_HOUR"
DEFAULT_FEEDBACK_PER_HOUR = 5
DEFAULT_VISIT_PER_HOUR = 60
WINDOW_SECONDS = 3600.0
MAX_BODY_BYTES = 16 * 1024
FEEDBACK_PATH = "/v1/feedback"
VISIT_PATH = "/v1/visit"
CORS_PATHS = (FEEDBACK_PATH, VISIT_PATH)
REF_PATTERN = r"^[A-Za-z0-9_-]{1,32}$"
DEFAULT_REF_ENV = "MAUDESIGNAL_DEFAULT_REF"
DEFAULT_REF = "email-batch-1"
FETCH_WORKERS = 8
KINDS = ("feedback", "visits")

FEEDBACK_COLUMNS = [
    "id",
    "received_utc",
    "rating",
    "comment",
    "blocker",
    "one_thing",
    "name",
    "role",
    "consent",
    "ref",
    "page",
    "client_ts",
]
VISIT_COLUMNS = ["id", "received_utc", "ref", "page", "client_ts"]

# --- PHI guard (a guard, not a guarantee) -------------------------------------------------
_PHI_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+"),  # email address
    re.compile(r"(?<!\d)(?:\+?1[\s.-]?)?\(?\d{3}\)?[\s.-]\d{3}[\s.-]\d{4}(?!\d)"),  # US phone
    re.compile(r"(?<!\d)\d{3}-\d{2}-\d{4}(?!\d)"),  # US SSN
    re.compile(r"\bMRN\b[\s:#.-]{0,4}\d{3,}", re.IGNORECASE),  # MRN + digits
    re.compile(r"\b(?:DOB|date\s+of\s+birth|born)\b[^0-9]{0,12}\d", re.IGNORECASE),  # DOB cue
)
PHI_MESSAGE = (
    "Please remove patient details (email addresses, phone numbers, ID or record numbers, "
    "dates of birth) and send again. Nothing was saved."
)


def looks_like_phi(text: str) -> bool:
    """True when ``text`` matches an email, phone, SSN, MRN or date-of-birth pattern."""
    return any(p.search(text) for p in _PHI_PATTERNS)


class FeedbackIn(BaseModel):
    """Body of ``POST /v1/feedback``."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    rating: int = Field(strict=True, ge=1, le=5, description="Does this match real PMS/RA work?")
    comment: str = Field(default="", max_length=2000)
    blocker: str = Field(default="", max_length=2000, description="What would stop your team?")
    one_thing: str = Field(default="", max_length=2000, description="One thing to make it useful")
    name: str | None = Field(default=None, max_length=100)
    role: str | None = Field(default=None, max_length=100)
    consent: Literal["quote_name_role", "quote_anonymous", "no_quote"]
    ref: str | None = Field(default=None, pattern=REF_PATTERN)
    page: str = Field(default="", max_length=64, pattern=r"^[A-Za-z0-9_:.-]*$")
    client_ts: str = Field(default="", max_length=40, pattern=r"^[0-9TZ:.+-]*$")


class VisitIn(BaseModel):
    """Body of ``POST /v1/visit``."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    ref: str | None = Field(default=None, pattern=REF_PATTERN)
    page: str = Field(
        min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_:.-]+$", description="Workflow id"
    )
    client_ts: str = Field(default="", max_length=40, pattern=r"^[0-9TZ:.+-]*$")


def _err(status: int, code: str, message: str, headers: dict[str, str] | None = None) -> Response:
    body = {"error": {"code": code, "message": message}}
    return JSONResponse(status_code=status, content=body, headers=headers)


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _csv_cell(value: Any) -> str:
    """Text for one CSV cell; a leading formula character is neutralised."""
    text = "" if value is None else str(value)
    return "'" + text if text[:1] in ("=", "+", "-", "@", "\t", "\r") else text


def to_csv(kind: str, rows: list[dict[str, Any]]) -> str:
    """Render records as CSV with the fixed columns for ``kind``."""
    columns = FEEDBACK_COLUMNS if kind == "feedback" else VISIT_COLUMNS
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(columns)
    for row in rows:
        writer.writerow([_csv_cell(row.get(c)) for c in columns])
    return out.getvalue()


def summarize(feedback: list[dict[str, Any]], visits: list[dict[str, Any]]) -> dict[str, Any]:
    """Counts of visits and feedback per ref code and per page, plus average rating per ref."""
    by_ref: dict[str, dict[str, Any]] = defaultdict(lambda: {"visits": 0, "feedback": 0, "sum": 0})
    by_page: dict[str, dict[str, int]] = defaultdict(lambda: {"visits": 0, "feedback": 0})
    for v in visits:
        by_ref[v.get("ref") or "(none)"]["visits"] += 1
        by_page[v.get("page") or "(none)"]["visits"] += 1
    for f in feedback:
        entry = by_ref[f.get("ref") or "(none)"]
        entry["feedback"] += 1
        entry["sum"] += int(f.get("rating") or 0)
        by_page[f.get("page") or "(none)"]["feedback"] += 1
    refs = [
        {
            "ref": ref,
            "visits": e["visits"],
            "feedback": e["feedback"],
            "avg_rating": round(e["sum"] / e["feedback"], 2) if e["feedback"] else None,
        }
        for ref, e in sorted(by_ref.items())
    ]
    pages = [{"page": p, **c} for p, c in sorted(by_page.items())]
    return {
        "totals": {"visits": len(visits), "feedback": len(feedback)},
        "by_ref": refs,
        "by_page": pages,
    }


ADMIN_PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex,nofollow">
<title>MaudeSignal admin</title>
<style>
:root{color-scheme:light dark}
body{font:16px/1.5 system-ui,sans-serif;margin:0 auto;max-width:56rem;padding:1rem 16px;
background:Canvas;color:CanvasText}
input,button{font:inherit;padding:.4rem .6rem;margin:.2rem .2rem .2rem 0}
table{border-collapse:collapse;width:100%;margin:.5rem 0 1rem}
th,td{border-bottom:1px solid GrayText;padding:.3rem .5rem;text-align:left}
.scroll{overflow-x:auto}
</style></head><body>
<h1>MaudeSignal admin</h1>
<p>Private. Visits and feedback by referral code. No data is in this page until you unlock it;
the key stays in this tab (session storage) only.</p>
<form id="f"><label>Admin key <input id="k" type="password" autocomplete="off"></label>
<button type="submit">Load summary</button>
<button type="button" id="clear">Forget key</button></form>
<p id="msg" role="status"></p>
<div id="out" hidden>
<p><button type="button" data-kind="feedback">Download feedback CSV</button>
<button type="button" data-kind="visits">Download visits CSV</button></p>
<h2>Totals</h2><p id="tot"></p>
<h2>By referral code</h2><div class="scroll"><table id="refs"></table></div>
<h2>By page</h2><div class="scroll"><table id="pages"></table></div>
</div>
<script>
const $=id=>document.getElementById(id);
const K="ms_admin_key";
function hdr(){return {"X-Admin-Key":sessionStorage.getItem(K)||""};}
function table(el,cols,rows){
  el.replaceChildren();
  const h=el.insertRow();
  for(const c of cols){const th=document.createElement("th");th.textContent=c;h.appendChild(th);}
  for(const r of rows){const tr=el.insertRow();
    for(const c of cols){tr.insertCell().textContent=r[c]===null?"-":String(r[c]);}}
}
async function load(){
  $("msg").textContent="Loading...";
  const r=await fetch("/v1/admin/summary",{headers:hdr(),cache:"no-store"});
  if(!r.ok){$("out").hidden=true;
    const m={401:"Wrong key.",503:"Admin export is not configured."};
    $("msg").textContent=m[r.status]||"Error "+r.status;return;}
  const d=await r.json();
  $("msg").textContent="";$("out").hidden=false;
  $("tot").textContent=d.totals.visits+" visits, "+d.totals.feedback+" feedback";
  table($("refs"),["ref","visits","feedback","avg_rating"],d.by_ref);
  table($("pages"),["page","visits","feedback"],d.by_page);
}
$("f").addEventListener("submit",e=>{e.preventDefault();
  sessionStorage.setItem(K,$("k").value);$("k").value="";load();});
$("clear").addEventListener("click",()=>{sessionStorage.removeItem(K);$("out").hidden=true;
  $("msg").textContent="Key forgotten.";});
document.querySelectorAll("button[data-kind]").forEach(b=>b.addEventListener("click",async()=>{
  const kind=b.dataset.kind;
  const r=await fetch("/v1/admin/export?kind="+kind+"&format=csv",{headers:hdr(),cache:"no-store"});
  if(!r.ok){$("msg").textContent="Export failed: "+r.status;return;}
  const url=URL.createObjectURL(await r.blob());
  const a=document.createElement("a");a.href=url;a.download="maudesignal-"+kind+".csv";
  document.body.appendChild(a);a.click();a.remove();URL.revokeObjectURL(url);
}));
if(sessionStorage.getItem(K)){load();}
</script></body></html>
"""


def mount_feedback(
    app: FastAPI,
    *,
    store: RecordStore,
    notifier: Notifier,
    web_origins: frozenset[str],
    client_address: Callable[[Request], str],
    failed_auth: RateLimiter,
    make_limiter: Callable[[str, int, float], RateLimiter],
    env: dict[str, str] | None = None,
    now: Callable[[], datetime] = _utc_now,
) -> None:
    """Add the feedback, visit and admin routes to ``app``.

    Args:
        app: The connector app.
        store: Where records go (private Blob, or memory locally).
        notifier: Email notifier for new feedback.
        web_origins: Exact browser origins allowed on the two POST routes.
        client_address: Function returning the caller address (honours TRUST_FORWARDED).
        failed_auth: Limiter that counts failed admin key checks per address.
        make_limiter: ``(name, limit, window_seconds)`` factory for the per-address limiters.
        env: Environment (tests); defaults to ``os.environ``.
        now: Clock (tests).
    """
    e = os.environ if env is None else env

    def limit_from(name: str, default: int) -> int:
        try:
            value = int(e.get(name, ""))
        except ValueError:
            return default
        return value if value > 0 else default

    feedback_limiter = make_limiter(
        "feedback", limit_from(FEEDBACK_LIMIT_ENV, DEFAULT_FEEDBACK_PER_HOUR), WINDOW_SECONDS
    )
    visit_limiter = make_limiter(
        "visit", limit_from(VISIT_LIMIT_ENV, DEFAULT_VISIT_PER_HOUR), WINDOW_SECONDS
    )
    admin_key = e.get(ADMIN_KEY_ENV, "")
    configured_ref = (e.get(DEFAULT_REF_ENV) or DEFAULT_REF).strip()
    default_ref = configured_ref if re.fullmatch(REF_PATTERN, configured_ref) else DEFAULT_REF
    salt = (e.get("MAUDESIGNAL_KEY_PEPPER") or secrets.token_hex(16)).encode("utf-8")

    def limiter_id(request: Request) -> str:
        """Salted hash of the caller address: all the limiter ever sees of it."""
        digest = hmac.new(salt, client_address(request).encode("utf-8"), hashlib.sha256)
        return "fb:" + digest.hexdigest()[:24]

    @app.middleware("http")
    async def _feedback_cors(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        """CORS for the two POST routes: exact origins from the environment, no wildcard."""
        if request.url.path not in CORS_PATHS:
            return await call_next(request)
        origin = request.headers.get("origin", "").rstrip("/")
        allowed = bool(origin) and origin in web_origins
        response: Response
        if request.method == "OPTIONS":
            response = Response(status_code=204)
            if allowed:
                response.headers["Access-Control-Allow-Methods"] = "POST, OPTIONS"
                response.headers["Access-Control-Allow-Headers"] = "Content-Type"
                response.headers["Access-Control-Max-Age"] = "600"
        elif origin and not allowed:
            response = _err(403, "origin_not_allowed", "Origin not allowed.")
        else:
            response = await call_next(request)
        response.headers["Vary"] = "Origin"
        if allowed:
            response.headers["Access-Control-Allow-Origin"] = origin
            response.headers["Access-Control-Expose-Headers"] = "Retry-After"
        return response

    def limited(request: Request, limiter: RateLimiter) -> Response | None:
        ok, _remaining, retry = limiter.check(limiter_id(request))
        if ok:
            return None
        return _err(
            429,
            "rate_limited",
            f"Limit of {limiter.limit} per hour reached. Retry in {retry} seconds.",
            {"Retry-After": str(retry)},
        )

    async def read_json(request: Request) -> tuple[Any, Response | None]:
        """Read at most 16 KB of JSON; returns ``(body, error_response)``."""
        declared = request.headers.get("content-length", "")
        if declared.isdigit() and int(declared) > MAX_BODY_BYTES:
            return None, _err(413, "too_large", "Message too large (16 KB at most).")
        chunks: list[bytes] = []
        size = 0
        try:
            async for chunk in request.stream():
                size += len(chunk)
                if size > MAX_BODY_BYTES:
                    return None, _err(413, "too_large", "Message too large (16 KB at most).")
                chunks.append(chunk)
        except ClientDisconnect:
            return None, Response(status_code=400)
        try:
            return json.loads(b"".join(chunks)), None
        except ValueError:
            return None, _err(422, "invalid_input", "Body must be a JSON object.")

    def without_empty_ref(payload: Any) -> Any:
        """Treat a missing, null or empty ``ref`` as absent so the default label applies."""
        if isinstance(payload, dict) and payload.get("ref") in (None, ""):
            return {k: v for k, v in payload.items() if k != "ref"}
        return payload

    def bad_fields(exc: ValidationError) -> Response:
        where = ", ".join(sorted({str(x["loc"][-1]) for x in exc.errors() if x.get("loc")}))
        return _err(422, "invalid_input", f"Invalid input: {where or 'request'}.")

    def day_and_id(received: datetime) -> tuple[str, str]:
        return received.strftime("%Y-%m-%d"), str(uuid.uuid4())

    @app.post(FEEDBACK_PATH, include_in_schema=False)
    async def post_feedback(request: Request) -> Response:
        if (blocked := limited(request, feedback_limiter)) is not None:
            return blocked
        payload, failure = await read_json(request)
        if failure is not None:
            return failure
        try:
            body = FeedbackIn.model_validate(without_empty_ref(payload))
        except ValidationError as exc:
            return bad_fields(exc)
        free_text = (body.comment, body.blocker, body.one_thing, body.name or "", body.role or "")
        if any(looks_like_phi(t) for t in free_text):
            return _err(422, "possible_patient_details", PHI_MESSAGE)
        received = now()
        day, rid = day_and_id(received)
        record: dict[str, Any] = body.model_dump() | {
            "id": rid,
            "received_utc": received.isoformat(timespec="seconds"),
            "ref": body.ref or default_ref,
        }
        try:
            await run_in_threadpool(store.put_json, f"feedback/{day}/{rid}.json", record)
        except StoreError:
            return _err(503, "store_unavailable", "Feedback could not be saved. Try again later.")
        logger.info("feedback_stored", rating=body.rating, has_ref=body.ref is not None)
        await run_in_threadpool(notifier.feedback, record)
        return JSONResponse(status_code=201, content={"status": "received", "id": rid})

    @app.post(VISIT_PATH, include_in_schema=False)
    async def post_visit(request: Request) -> Response:
        if (blocked := limited(request, visit_limiter)) is not None:
            return blocked
        payload, failure = await read_json(request)
        if failure is not None:
            return failure
        try:
            body = VisitIn.model_validate(without_empty_ref(payload))
        except ValidationError as exc:
            return bad_fields(exc)
        received = now()
        day, rid = day_and_id(received)
        record: dict[str, Any] = body.model_dump() | {
            "id": rid,
            "received_utc": received.isoformat(timespec="seconds"),
            "ref": body.ref or default_ref,
        }
        try:
            await run_in_threadpool(store.put_json, f"visits/{day}/{rid}.json", record)
        except StoreError:
            return _err(503, "store_unavailable", "Visit could not be saved.")
        return Response(status_code=204)

    # --- admin ------------------------------------------------------------------------
    no_store = {"Cache-Control": "no-store", "X-Robots-Tag": "noindex"}

    def admin_gate(request: Request) -> Response | None:
        """None when the caller is the admin; otherwise the refusal."""
        if not admin_key:
            return _err(503, "not_configured", "admin export not configured", no_store)
        who = limiter_id(request)
        blocked, wait = failed_auth.blocked(who)
        if blocked:
            return _err(
                429,
                "rate_limited",
                f"Too many failed key checks. Retry in {wait} seconds.",
                {"Retry-After": str(wait)} | no_store,
            )
        presented = request.headers.get("x-admin-key", "")[:256]
        match = hmac.compare_digest(
            hashlib.sha256(presented.encode("utf-8")).digest(),
            hashlib.sha256(admin_key.encode("utf-8")).digest(),
        )
        if not match:
            failed_auth.record(who)
            return _err(401, "unauthorized", "A valid X-Admin-Key header is required.", no_store)
        return None

    def load_records(kind: str) -> list[dict[str, Any]]:
        refs = store.list_prefix(f"{kind}/")

        def fetch(ref: BlobRef) -> dict[str, Any] | None:
            try:
                data = json.loads(store.get(ref))
            except (StoreError, ValueError):
                logger.warning("admin_record_unreadable", kind=kind)
                return None
            return data if isinstance(data, dict) else None

        with ThreadPoolExecutor(max_workers=FETCH_WORKERS) as pool:
            rows = [r for r in pool.map(fetch, refs) if r is not None]
        rows.sort(key=lambda r: (str(r.get("received_utc", "")), str(r.get("id", ""))))
        return rows

    @app.get("/admin", response_class=HTMLResponse, include_in_schema=False)
    def admin_page() -> HTMLResponse:
        return HTMLResponse(
            ADMIN_PAGE,
            headers=no_store
            | {
                "Content-Security-Policy": (
                    "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; "
                    "connect-src 'self'; base-uri 'none'; form-action 'none'"
                )
            },
        )

    @app.get("/v1/admin/export", include_in_schema=False)
    def admin_export(
        request: Request,
        kind: Annotated[Literal["feedback", "visits"], Query()],
        format: Annotated[Literal["csv", "json"], Query()] = "csv",  # noqa: A002
    ) -> Response:
        if (refusal := admin_gate(request)) is not None:
            return refusal
        try:
            rows = load_records(kind)
        except StoreError:
            return _err(503, "store_unavailable", "The record store is not reachable.", no_store)
        if format == "json":
            return JSONResponse(rows, headers=no_store)
        return Response(
            to_csv(kind, rows),
            media_type="text/csv; charset=utf-8",
            headers=no_store | {"Content-Disposition": f'attachment; filename="{kind}.csv"'},
        )

    @app.get("/v1/admin/summary", include_in_schema=False)
    def admin_summary(request: Request) -> Response:
        if (refusal := admin_gate(request)) is not None:
            return refusal
        try:
            result = summarize(load_records("feedback"), load_records("visits"))
        except StoreError:
            return _err(503, "store_unavailable", "The record store is not reachable.", no_store)
        return JSONResponse(result, headers=no_store)
