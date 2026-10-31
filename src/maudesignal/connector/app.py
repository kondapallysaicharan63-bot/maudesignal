"""REST transport for the connector tools (FastAPI; OpenAPI 3.1 comes from this app).

HACKATHON-BUILT — Meta Global AI Developer Hackathon (Oct 26 – Nov 4, 2026).

Every endpoint is read-only. ``GET /v1/health`` needs no key; the five tool
endpoints need an ``X-API-Key`` header, count against a per-key rate limit and, for
``ask``, a per-key daily cost cap. Error bodies never contain the key.
"""

import hashlib
import json
import os
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import Depends, FastAPI, Query, Request, Response, Security
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.security import APIKeyHeader
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from starlette.concurrency import run_in_threadpool
from starlette.requests import ClientDisconnect

from maudesignal.common.exceptions import OpenFDAAPIError
from maudesignal.common.logging import get_logger
from maudesignal.connector import tools
from maudesignal.connector.asgi import RejectKeyInQuery
from maudesignal.connector.ask import (
    MAX_QUESTION_CHARS,
    MIN_QUESTION_CHARS,
    AskRuntime,
    ask_detailed,
)
from maudesignal.connector.blob_store import RecordStore, store_from_env
from maudesignal.connector.data import ConnectorData
from maudesignal.connector.docs_page import render_docs_page
from maudesignal.connector.errors import ConnectorError, InvalidInputError, NotFoundError
from maudesignal.connector.feedback import mount_feedback
from maudesignal.connector.legal_pages import render_privacy, render_terms
from maudesignal.connector.live import LiveBackends, LiveConfig, mount_live
from maudesignal.connector.manifest import build_manifest
from maudesignal.connector.mcp_server import (
    PARSE_ERROR,
    SUPPORTED_VERSIONS,
    handle_message,
    rpc_error,
)
from maudesignal.connector.models import (
    AuditEntry,
    AuditRecent,
    ChainStatus,
    ErrorBody,
    ErrorResponse,
    LiveCheckData,
    PublicCheckAnswer,
    ToolAnswer,
)
from maudesignal.connector.notify import Notifier, notifier_from_env
from maudesignal.connector.registry import (
    ASK_DESCRIPTION,
    CHECK_DESCRIPTION,
    PRODUCT_CODE_PATTERN,
    RECALLS_DESCRIPTION,
    REPORT_DESCRIPTION,
    REPORT_ID_PATTERN,
    WHAT_CHANGED_DESCRIPTION,
)
from maudesignal.connector.security import (
    DEFAULT_DEMO_RATE_PER_MIN,
    DEMO_PER_DAY,
    DEMO_RATE_ENV,
    KeyStore,
    RateLimiter,
)
from maudesignal.connector.store import (
    ConnectorState,
    UpstashError,
    verify_chain,
)
from maudesignal.connector.tools import Clock, LiveChecker, utc_now
from maudesignal.ingestion.openfda_client import OpenFDAClient
from maudesignal.monitor.live_check import LiveCheck, check_product_code, normalize_code

logger = get_logger(__name__)

API_VERSION = "0.1.0"
TRUST_FORWARDED_ENV = "MAUDESIGNAL_TRUST_FORWARDED"
WEB_ORIGINS_ENV = "MAUDESIGNAL_WEB_ORIGINS"
PUBLIC_LIMIT_ENV = "MAUDESIGNAL_PUBLIC_CHECK_PER_HOUR"
DEFAULT_PUBLIC_PER_HOUR = 10
PUBLIC_WINDOW_SECONDS = 3600.0
PUBLIC_CACHE_SECONDS = 6 * 3600
PUBLIC_PREFIX = "/v1/public/"
PUBLIC_ACTOR = "public"
PUBLIC_CACHE_PREFIX = "public-check:v1"  # bump the version when PublicCheckAnswer changes


def _question_audit_inputs(question: str) -> dict[str, str]:
    """What the audit log keeps of a question: its SHA-256 and length, never its text.

    Callers may type anything into a question, and every key holder can read the audit log, so
    the text itself is not stored. The hash is of the whitespace-normalised, lower-cased text.
    """
    normalised = " ".join(question.split()).lower()
    return {
        "question_sha256": hashlib.sha256(normalised.encode("utf-8")).hexdigest(),
        "question_length": str(len(normalised)),
    }


REPO_URL = "https://github.com/kondapallysaicharan63-bot/maudesignal"
API_BASE_URL = "https://maudesignal-api.vercel.app"
TERMS_URL = f"{API_BASE_URL}/terms"
CONNECT_PATH = "/v1/connect"
PUBLIC_URL_ENV = "MAUDESIGNAL_PUBLIC_URL"
READ_ONLY = {"x-maudesignal-read-only": True, "x-maudesignal-scope": "read"}
MCP_PATH = "/mcp"
MAX_MCP_BODY_BYTES = 64 * 1024

DESCRIPTION = (
    "Read-only MaudeSignal tools for a Meta Muse connector. Each answer has a short speakable "
    "summary, facts that each carry an openFDA or record link, a fixed advisory line and "
    "provenance (stored demo snapshot with dates, or live openFDA with the query time). "
    "Advisory triage aid for quality and regulatory review; not medical advice; nothing is "
    "filed with FDA. Every key is read-only. Sentences from ask are checked by a deterministic "
    "claim gate; withheld sentences are listed separately and are never part of the speakable "
    "text. Limits: the per-key rate limit and the per-key daily cost cap are shared by every "
    "server instance when an Upstash Redis store is configured (GET /v1/health says which); "
    "otherwise they live in each instance's memory and temporary storage, are per instance "
    "and reset on a cold start. In that case live Muse Spark answers stay switched off "
    "unless the operator sets an explicit per-instance override; ask then returns the "
    "closest recorded answer, labelled recorded. Repeated wrong keys from one address get "
    "429. /v1/public/check_device_type needs no key (per-address limit, six-hour cache) and "
    "never calls the model."
)

_ERRORS: dict[int | str, dict[str, Any]] = {
    401: {"model": ErrorResponse, "description": "Missing or invalid X-API-Key."},
    422: {"model": ErrorResponse, "description": "Input not usable."},
    429: {"model": ErrorResponse, "description": "Rate limit reached; see Retry-After."},
}


_HTTP_STATUS = re.compile(r"\b([1-5]\d\d)\b")


def _openfda_status(exc: OpenFDAAPIError) -> int | None:
    """HTTP status named in an openFDA error message, else None.

    Transport errors ("HTTP error contacting openFDA: ...") are skipped: their text can hold
    a URL, and a URL can hold the API key.
    """
    text = str(exc)
    if text.startswith("HTTP error"):
        return None
    found = _HTTP_STATUS.search(text)
    return int(found.group(1)) if found else None


def _default_live_checker(product_code: str) -> LiveCheck:
    key = os.environ.get("OPENFDA_API_KEY") or None
    try:
        with OpenFDAClient(api_key=key) as client:
            return check_product_code(client, product_code, datetime.now(UTC).date())
    except OpenFDAAPIError as exc:
        # Class and status only: never the message, URL or key. Shows why the stored fallback ran.
        logger.warning(
            "connector_openfda_failed",
            error_type=type(exc).__name__,
            cause_type=type(exc.__cause__).__name__ if exc.__cause__ else None,
            status=_openfda_status(exc),
        )
        raise


def _origins_from_env() -> tuple[str, ...]:
    """Web origins allowed on the keyless route (exact match; a wildcard is ignored)."""
    raw = os.environ.get(WEB_ORIGINS_ENV, "")
    items = (o.strip().rstrip("/") for o in raw.split(","))
    return tuple(o for o in items if o.startswith(("https://", "http://")) and "*" not in o)


@dataclass
class Settings:
    """Everything the app depends on (tests pass their own).

    ``limiter``, ``failed_auth``, ``public_limiter`` and ``ask_runtime`` default (``None``) to
    ones built on ``state``, so they are shared when Upstash is configured.
    """

    keys: KeyStore = field(default_factory=KeyStore.from_env)
    limiter: RateLimiter | None = None
    failed_auth: RateLimiter | None = None
    public_limiter: RateLimiter | None = None
    demo_limiter: RateLimiter | None = None
    data: ConnectorData = field(default_factory=ConnectorData)
    ask_runtime: AskRuntime | None = None
    live_checker: LiveChecker = _default_live_checker
    now: Clock = utc_now
    state: ConnectorState = field(default_factory=ConnectorState.from_env)
    web_origins: tuple[str, ...] = field(default_factory=_origins_from_env)
    feedback_store: RecordStore = field(default_factory=store_from_env)
    notifier: Notifier = field(default_factory=notifier_from_env)
    live: LiveBackends | None = None
    live_config: LiveConfig | None = None


class AskRequest(BaseModel):
    """Body of ``ask``."""

    model_config = ConfigDict(extra="forbid")

    question: str = Field(
        min_length=MIN_QUESTION_CHARS,
        max_length=MAX_QUESTION_CHARS,
        description="A question about stored MAUDE reports, recalls, 510(k)s or the MDR clock.",
        examples=["What changed this week for LLZ?"],
    )


class Health(BaseModel):
    """``GET /v1/health`` body."""

    status: str
    service: str
    version: str
    read_only: bool
    tools: list[str]
    limits_scope: str
    state_store: str
    feedback_store: str


class DemoLimits(BaseModel):
    """Limits of the public demo key."""

    per_minute: int
    per_day: int
    live_model: bool
    note: str


class ConnectInfo(BaseModel):
    """``GET /v1/connect`` body."""

    mcp_url: str
    openapi_url: str
    docs_url: str
    auth_header: str
    demo_key: str | None
    demo_limits: DemoLimits
    steps: list[str]


class ApiError(Exception):
    """An error with a fixed, key-free message."""

    def __init__(
        self, status: int, code: str, message: str, headers: dict[str, str] | None = None
    ) -> None:
        """Create the error."""
        super().__init__(message)
        self.status, self.code, self.message, self.headers = status, code, message, headers or {}


def _client_address(request: Request) -> str:
    """Caller address for rate limiting.

    The first X-Forwarded-For entry is used only when ``MAUDESIGNAL_TRUST_FORWARDED=1`` (set
    it on Vercel, whose edge sets the header); otherwise any caller could send a made-up
    value to dodge the limiter, so the socket peer is used.
    """
    if os.environ.get(TRUST_FORWARDED_ENV, "").strip() == "1":
        forwarded: str = str(request.headers.get("x-forwarded-for", ""))
        first = forwarded.split(",")[0].strip()
        if first:
            return str(first[:64])
    return str(request.client.host) if request.client else "unknown"


def _error(status: int, code: str, message: str, headers: dict[str, str] | None = None) -> Response:
    body = ErrorResponse(error=ErrorBody(code=code, message=message))
    return JSONResponse(status_code=status, content=body.model_dump(), headers=headers)


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build the API.

    Args:
        settings: Dependencies; defaults read the environment.

    Returns:
        The FastAPI app (``api/index.py`` exports one as ``app``).
    """
    cfg = settings or Settings()
    state = cfg.state
    limiter = cfg.limiter or state.rate_limiter("tools", RateLimiter.from_env().limit)
    failed_auth = cfg.failed_auth or state.rate_limiter(
        "failed-auth", RateLimiter.failed_auth_from_env().limit
    )
    public_limiter = cfg.public_limiter or state.rate_limiter(
        "public-check",
        RateLimiter.from_env(
            name=PUBLIC_LIMIT_ENV,
            default=DEFAULT_PUBLIC_PER_HOUR,
            window_seconds=PUBLIC_WINDOW_SECONDS,
        ).limit,
        PUBLIC_WINDOW_SECONDS,
    )
    state.attach_blob(cfg.feedback_store)  # the private Blob store also holds the spend ledger
    ask_runtime = cfg.ask_runtime or AskRuntime(state=state)
    demo_limiter = cfg.demo_limiter or state.rate_limiter(
        "demo-key",
        RateLimiter.from_env(name=DEMO_RATE_ENV, default=DEFAULT_DEMO_RATE_PER_MIN).limit,
    )
    demo_daily = state.daily_counter("demo-key-day", DEMO_PER_DAY, today=lambda: cfg.now().date())
    web_origins = frozenset(cfg.web_origins)
    app = FastAPI(
        title="MaudeSignal connector API",
        version=API_VERSION,
        description=DESCRIPTION,
        contact={"name": "MaudeSignal (open source)", "url": REPO_URL},
        terms_of_service=TERMS_URL,
        docs_url=None,
        redoc_url=None,
    )
    app.add_middleware(RejectKeyInQuery)
    key_header = APIKeyHeader(
        name="X-API-Key",
        auto_error=False,
        description="Read-only API key. Send it only in this header.",
    )

    def authenticate(
        request: Request,
        response: Response,
        presented: Annotated[str | None, Security(key_header)],
    ) -> str:
        if not cfg.keys.configured:
            raise ApiError(503, "not_configured", "This server has no API keys configured.")
        client = _client_address(request)
        blocked, wait = failed_auth.blocked(client)
        if blocked:  # too many bad keys from this address: do not even check this one
            raise ApiError(
                429,
                "rate_limited",
                f"Too many failed key checks. Retry in {wait} seconds.",
                {"Retry-After": str(wait)},
            )
        if presented is None:  # the same key may come as "Authorization: Bearer <key>"
            scheme, _, token = request.headers.get("authorization", "").partition(" ")
            if scheme.lower() == "bearer" and token.strip():
                presented = token.strip()
        matched = cfg.keys.match(presented)
        if matched is None or presented is None:
            failed_auth.record(client)
            raise ApiError(
                401,
                "unauthorized",
                "A valid X-API-Key header is required.",
                {"WWW-Authenticate": "ApiKey"},
            )
        key_id = matched.key_id
        active = demo_limiter if matched.demo else limiter
        allowed, remaining, retry = active.check(key_id)
        if not allowed:
            raise ApiError(
                429,
                "rate_limited",
                f"Rate limit of {active.limit} requests per minute reached. "
                f"Retry in {retry} seconds.",
                {"Retry-After": str(retry)},
            )
        if matched.demo:
            day_ok, _left = demo_daily.hit(key_id)
            if not day_ok:
                now = cfg.now()
                reset = datetime.combine(now.date(), datetime.min.time(), tzinfo=UTC)
                wait = max(1, 86_400 - int((now - reset).total_seconds()))
                raise ApiError(
                    429,
                    "rate_limited",
                    f"The demo key's daily limit of {DEMO_PER_DAY} requests is reached. "
                    f"Retry in {wait} seconds.",
                    {"Retry-After": str(wait)},
                )
        response.headers["X-RateLimit-Limit"] = str(active.limit)
        response.headers["X-RateLimit-Remaining"] = str(remaining)
        request.state.audit_id = key_id  # peppered HMAC id (as the limiter and ledger); not the key
        request.state.key_label = matched.label
        request.state.key_demo = matched.demo
        return key_id

    key_dep = Annotated[str, Depends(authenticate)]
    code_param = Annotated[
        str,
        Query(pattern=PRODUCT_CODE_PATTERN, description="Three-letter FDA product code, e.g. LLZ."),
    ]

    def record_audit(
        audit_id: str,
        tool: str,
        inputs: dict[str, str],
        answer: ToolAnswer | None,
        error: str | None = None,
        label: str | None = None,
    ) -> None:
        """Append one chained audit entry; a failing store never fails the request."""
        payload: dict[str, Any] = {"tool": tool, "inputs": inputs, "error": error}
        if answer is not None:
            canonical = json.dumps(answer.model_dump(mode="json"), sort_keys=True)
            payload |= {
                "answer_sha256": hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
                "gate": {"facts_with_links": len(answer.facts), "withheld": len(answer.withheld)},
                "provenance": {
                    "kind": answer.provenance.kind,
                    "data_dates": answer.provenance.data_dates,
                    "queried_at_utc": answer.provenance.queried_at_utc,
                },
            }
        actor = PUBLIC_ACTOR if audit_id == PUBLIC_ACTOR else f"connector:key:{audit_id}"
        if label and audit_id != PUBLIC_ACTOR:
            actor = f"connector:key:{label}:{audit_id}"  # the label next to the key id
        try:
            state.audit_append(actor=actor, action=f"tool:{tool}", entity_id=tool, payload=payload)
        except UpstashError as exc:
            logger.error("connector_audit_append_failed", error=str(exc))

    def audited(
        request: Request, tool: str, inputs: dict[str, str], run: Callable[[], ToolAnswer]
    ) -> ToolAnswer:
        """Run a tool and append its audit entry (also when it fails with a tool error)."""
        audit_id = str(request.state.audit_id)
        label = getattr(request.state, "key_label", None)
        try:
            answer = run()
        except ConnectorError as exc:
            record_audit(audit_id, tool, inputs, None, exc.code, label)
            raise
        record_audit(audit_id, tool, inputs, answer, None, label)
        return answer

    def dispatch(request: Request, name: str, args: dict[str, str]) -> ToolAnswer:
        """Run one tool with its audit entry; REST routes and ``/mcp`` both call this."""
        key_id = str(request.state.audit_id)
        if name == "what_changed_this_week":
            code = args.get("product_code")
            return audited(
                request,
                name,
                {"product_code": code or ""},
                lambda: tools.what_changed_this_week(
                    cfg.data, code, live_checker=cfg.live_checker, now=cfg.now
                ),
            )
        if name == "check_device_type":
            return audited(
                request,
                name,
                {"product_code": args["product_code"]},
                lambda: tools.check_device_type(
                    cfg.data, args["product_code"], live_checker=cfg.live_checker, now=cfg.now
                ),
            )
        if name == "ask":
            question = args["question"]
            return audited(
                request,
                name,
                _question_audit_inputs(question),
                lambda: ask_detailed(
                    cfg.data,
                    question,
                    key_id=key_id,
                    runtime=ask_runtime,
                    now=cfg.now,
                    allow_live=not getattr(request.state, "key_demo", False),
                ).answer,
            )
        if name == "get_report":
            return audited(
                request,
                name,
                {"report_id": args["report_id"]},
                lambda: tools.get_report(cfg.data, args["report_id"]),
            )
        if name == "recalls":
            return audited(
                request,
                name,
                {"product_code": args["product_code"]},
                lambda: tools.recalls(cfg.data, args["product_code"]),
            )
        raise InvalidInputError("Unknown tool.")

    @app.exception_handler(ApiError)
    async def _api_error(_: Request, exc: ApiError) -> Response:
        return _error(exc.status, exc.code, exc.message, exc.headers)

    @app.exception_handler(ConnectorError)
    async def _connector_error(_: Request, exc: ConnectorError) -> Response:
        if isinstance(exc, InvalidInputError):
            status = 422
        elif isinstance(exc, NotFoundError):
            status = 404
        else:  # SourceUnavailableError and any other connector error
            status = 502
        return _error(status, exc.code, str(exc))

    @app.exception_handler(RequestValidationError)
    async def _invalid(_: Request, exc: RequestValidationError) -> Response:
        where = ", ".join(sorted({str(e["loc"][-1]) for e in exc.errors() if e.get("loc")}))
        return _error(422, "invalid_input", f"Invalid input: {where or 'request'}.")

    @app.exception_handler(Exception)
    async def _unexpected(_: Request, exc: Exception) -> Response:
        logger.error("connector_unexpected_error", error_type=type(exc).__name__)
        return _error(500, "internal_error", "Something went wrong on the server.")

    @app.middleware("http")
    async def _log(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        response = await call_next(request)
        logger.info(
            "connector_request",
            method=request.method,
            path=request.url.path,
            status=response.status_code,
            key_label=getattr(request.state, "key_label", None),
        )
        return response

    @app.middleware("http")
    async def _public_cors(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        """CORS for the keyless route only, and only for origins listed in the environment."""
        if not (request.url.path.startswith(PUBLIC_PREFIX) or request.url.path == CONNECT_PATH):
            return await call_next(request)
        origin = request.headers.get("origin", "").rstrip("/")
        allowed = bool(origin) and origin in web_origins
        if request.method == "OPTIONS":
            response: Response = Response(status_code=204)
            if allowed:
                response.headers["Access-Control-Allow-Methods"] = "GET, OPTIONS"
                response.headers["Access-Control-Allow-Headers"] = "Content-Type"
                response.headers["Access-Control-Max-Age"] = "600"
        else:
            response = await call_next(request)
        response.headers["Vary"] = "Origin"
        if allowed:
            response.headers["Access-Control-Allow-Origin"] = origin
            response.headers["Access-Control-Expose-Headers"] = (
                "Retry-After, X-RateLimit-Limit, X-RateLimit-Remaining"
            )
        return response

    @app.get("/", response_class=HTMLResponse, include_in_schema=False)
    @app.get("/docs-page", response_class=HTMLResponse, include_in_schema=False)
    def docs_page() -> HTMLResponse:
        return HTMLResponse(
            render_docs_page(
                version=API_VERSION,
                state_backend=state.backend,
                rate_per_min=limiter.limit,
                public_per_hour=public_limiter.limit,
                daily_usd=ask_runtime.caps.daily_usd,
                request_usd=ask_runtime.caps.session_usd,
            )
        )

    @app.get("/privacy", response_class=HTMLResponse, include_in_schema=False)
    def privacy_page() -> HTMLResponse:
        return HTMLResponse(render_privacy())

    @app.get("/terms", response_class=HTMLResponse, include_in_schema=False)
    def terms_page() -> HTMLResponse:
        return HTMLResponse(render_terms())

    @app.get(
        CONNECT_PATH,
        response_model=ConnectInfo,
        operation_id="connect_info",
        summary="How to connect (no key needed)",
        description=(
            "Where the MCP and REST endpoints are, which header carries the key, the public "
            "demo key (when the operator has set one) with its lower limits, and three steps. "
            "The demo key is public by design, works on every read tool and never starts a "
            "live model call."
        ),
        tags=["service"],
    )
    def connect_info(request: Request) -> ConnectInfo:
        base = os.environ.get(PUBLIC_URL_ENV, "").strip().rstrip("/")
        if not base.startswith(("https://", "http://")):
            base = str(request.base_url).rstrip("/")
        demo = cfg.keys.demo_key_hint
        return ConnectInfo(
            mcp_url=f"{base}{MCP_PATH}",
            openapi_url=f"{base}/openapi.json",
            docs_url=f"{base}/docs-page",
            auth_header="X-API-Key",
            demo_key=demo,
            demo_limits=DemoLimits(
                per_minute=demo_limiter.limit,
                per_day=DEMO_PER_DAY,
                live_model=False,
                note="Read tools only. ask returns a recorded answer, labelled recorded.",
            ),
            steps=[
                f"Add {base}{MCP_PATH} as a custom MCP connector.",
                "Send the key in the X-API-Key header (the demo key above works for a first try).",
                "Call a tool, for example what_changed_this_week with product_code LLZ.",
            ],
        )

    @app.get(
        "/v1/health",
        response_model=Health,
        operation_id="health",
        summary="Service status (no key needed)",
        tags=["service"],
    )
    def health() -> Health:
        return Health(
            status="ok",
            service="maudesignal-connector",
            version=API_VERSION,
            read_only=True,
            tools=list(tools.TOOL_NAMES),
            limits_scope="shared" if state.shared else "per_instance",
            state_store=state.backend,
            feedback_store=cfg.feedback_store.backend,
        )

    @app.get(
        "/v1/tools/what_changed_this_week",
        response_model=ToolAnswer,
        operation_id="what_changed_this_week",
        summary="What changed this week",
        description=WHAT_CHANGED_DESCRIPTION,
        tags=["tools"],
        responses=_ERRORS | {502: {"model": ErrorResponse, "description": "openFDA unreachable."}},
        openapi_extra=READ_ONLY,
    )
    def what_changed_this_week(
        request: Request,
        key_id: key_dep,
        product_code: Annotated[
            str | None,
            Query(pattern=PRODUCT_CODE_PATTERN, description="Optional three-letter product code."),
        ] = None,
    ) -> ToolAnswer:
        return dispatch(
            request,
            "what_changed_this_week",
            {"product_code": product_code} if product_code else {},
        )

    @app.get(
        "/v1/tools/check_device_type",
        response_model=ToolAnswer,
        operation_id="check_device_type",
        summary="Check any device type live on openFDA",
        description=CHECK_DESCRIPTION,
        tags=["tools"],
        responses=_ERRORS | {502: {"model": ErrorResponse, "description": "openFDA unreachable."}},
        openapi_extra=READ_ONLY,
    )
    def check_device_type(
        request: Request, key_id: key_dep, product_code: code_param
    ) -> ToolAnswer:
        return dispatch(request, "check_device_type", {"product_code": product_code})

    @app.post(
        "/v1/tools/ask",
        response_model=ToolAnswer,
        operation_id="ask",
        summary="Ask the Muse Spark copilot",
        description=ASK_DESCRIPTION,
        tags=["tools"],
        responses=_ERRORS
        | {502: {"model": ErrorResponse, "description": "Nothing to answer from."}},
        openapi_extra=READ_ONLY,
    )
    def ask_tool(request: Request, key_id: key_dep, body: AskRequest) -> ToolAnswer:
        return dispatch(request, "ask", {"question": body.question})

    @app.get(
        "/v1/tools/get_report",
        response_model=ToolAnswer,
        operation_id="get_report",
        summary="One stored MAUDE report",
        description=REPORT_DESCRIPTION,
        tags=["tools"],
        responses=_ERRORS | {404: {"model": ErrorResponse, "description": "Report not stored."}},
        openapi_extra=READ_ONLY,
    )
    def get_report(
        request: Request,
        key_id: key_dep,
        report_id: Annotated[
            str, Query(pattern=REPORT_ID_PATTERN, description="MAUDE report id (mdr_report_key).")
        ],
    ) -> ToolAnswer:
        return dispatch(request, "get_report", {"report_id": report_id})

    @app.get(
        "/v1/tools/recalls",
        response_model=ToolAnswer,
        operation_id="recalls",
        summary="FDA recalls for a product code",
        description=RECALLS_DESCRIPTION,
        tags=["tools"],
        responses=_ERRORS,
        openapi_extra=READ_ONLY,
    )
    def recalls(request: Request, key_id: key_dep, product_code: code_param) -> ToolAnswer:
        return dispatch(request, "recalls", {"product_code": product_code})

    @app.get(
        "/v1/public/check_device_type",
        response_model=PublicCheckAnswer,
        operation_id="public_check_device_type",
        summary="Check any device type live on openFDA (no key, for the web workspace)",
        description=(
            "Read-only, no API key. The same answer as check_device_type plus `check`, the "
            "figures behind it: classification, change, counts, shares, window and the openFDA "
            "queries (label, url). openFDA is queried from the server, with the server's own "
            "openFDA key and the MaudeSignal user agent. Limits: a per-address limit (default "
            "10 per hour) and a six-hour cache per product code. Browsers may call it only "
            "from origins listed by the operator (no wildcard). It never calls the model."
        ),
        tags=["public"],
        responses={
            422: {"model": ErrorResponse, "description": "Product code not usable."},
            429: {"model": ErrorResponse, "description": "Per-address limit reached."},
            502: {"model": ErrorResponse, "description": "openFDA unreachable."},
        },
        openapi_extra=READ_ONLY,
    )
    def public_check_device_type(
        request: Request, response: Response, product_code: code_param
    ) -> PublicCheckAnswer:
        client = _client_address(request)
        allowed, remaining, retry = public_limiter.check(client)
        if not allowed:
            raise ApiError(
                429,
                "rate_limited",
                f"Limit of {public_limiter.limit} checks per hour reached. "
                f"Retry in {retry} seconds.",
                {"Retry-After": str(retry)},
            )
        response.headers["X-RateLimit-Limit"] = str(public_limiter.limit)
        response.headers["X-RateLimit-Remaining"] = str(remaining)
        code = normalize_code(product_code)
        inputs = {"product_code": code}
        cache_key = f"{PUBLIC_CACHE_PREFIX}:{code}"
        cached = state.cache_get(cache_key)
        if cached:
            try:
                hit = PublicCheckAnswer.model_validate_json(cached)
            except ValidationError:  # stale or corrupt entry: treat as a miss
                logger.warning("connector_cache_entry_invalid", key=cache_key)
            else:
                record_audit(PUBLIC_ACTOR, "public_check_device_type", inputs, hit)
                return hit
        seen: list[LiveCheck] = []

        def live(c: str) -> LiveCheck:
            seen.append(cfg.live_checker(c))
            return seen[-1]

        try:
            base = tools.check_device_type(cfg.data, code, live_checker=live, now=cfg.now)
        except ConnectorError as exc:
            record_audit(PUBLIC_ACTOR, "public_check_device_type", inputs, None, exc.code)
            raise
        figures = (
            LiveCheckData.model_validate(json.loads(json.dumps(seen[-1].to_dict())))
            if seen
            else None
        )
        result = PublicCheckAnswer(**base.model_dump(), check=figures)
        if seen:  # a stored fallback is not cached: the next call should try openFDA again
            state.cache_set(cache_key, result.model_dump_json(), PUBLIC_CACHE_SECONDS)
        record_audit(PUBLIC_ACTOR, "public_check_device_type", inputs, result)
        return result

    @app.get(
        "/v1/audit/recent",
        response_model=AuditRecent,
        operation_id="audit_recent",
        summary="Most recent audit entries, with the chain re-checked",
        description=(
            "Read-only. The last entries (default 20, at most 200) of the append-only, "
            "hash-chained log of tool calls: tool, inputs, answer SHA-256, gate counts, "
            "provenance and the caller's key id (a keyed hash held by the server; never "
            "the key). An `ask` question is stored as its SHA-256 and length, not its text. "
            "`chain.verified` is recomputed on every call."
        ),
        tags=["service"],
        responses=_ERRORS | {503: {"model": ErrorResponse, "description": "Audit store down."}},
        openapi_extra=READ_ONLY,
    )
    def audit_recent(
        key_id: key_dep,
        limit: Annotated[int, Query(ge=1, le=200, description="How many entries.")] = 20,
    ) -> AuditRecent:
        try:
            rows = state.audit_recent(limit)
        except UpstashError as exc:
            logger.error("connector_audit_read_failed", error=str(exc))
            raise ApiError(503, "audit_unavailable", "The audit store is not reachable.") from None
        ok, bad = verify_chain(rows)
        return AuditRecent(
            store=state.backend,
            chain=ChainStatus(verified=ok, first_bad_seq=bad, entries_checked=len(rows)),
            entries=[AuditEntry.model_validate(r) for r in rows],
        )

    @app.get("/mcp-manifest.json", include_in_schema=False)
    def mcp_manifest() -> JSONResponse:
        """Public, static description of the MCP server (no key; nothing secret in it)."""
        return JSONResponse(build_manifest())

    @app.api_route(MCP_PATH, methods=["GET", "DELETE", "PUT", "PATCH"], include_in_schema=False)
    def mcp_not_allowed() -> Response:
        """Stateless server: no event stream (GET) and no session to end (DELETE)."""
        return _error(
            405, "method_not_allowed", "POST JSON-RPC messages to /mcp.", {"Allow": "POST"}
        )

    @app.post(MCP_PATH, include_in_schema=False)
    async def mcp_endpoint(request: Request, key_id: key_dep) -> Response:
        """MCP over HTTP (stateless JSON-RPC): same auth, limits, cost cap and audit as REST."""
        origin = request.headers.get("origin", "").rstrip("/")
        if origin and origin not in web_origins:  # DNS-rebinding guard from the MCP spec
            return _error(403, "origin_not_allowed", "Origin not allowed.")
        version = request.headers.get("mcp-protocol-version")
        if version is not None and version not in SUPPORTED_VERSIONS:
            return _error(400, "unsupported_protocol_version", "Unsupported MCP-Protocol-Version.")
        declared = request.headers.get("content-length", "")
        if declared.isdigit() and int(declared) > MAX_MCP_BODY_BYTES:
            return _error(413, "too_large", "Message too large.")
        try:
            raw = await request.body()
        except ClientDisconnect:  # the client closed while sending: nothing to answer
            return Response(status_code=400)
        if len(raw) > MAX_MCP_BODY_BYTES:
            return _error(413, "too_large", "Message too large.")
        try:
            message = json.loads(raw)
        except ValueError:
            return JSONResponse(rpc_error(None, PARSE_ERROR, "Parse error."), status_code=400)
        if isinstance(message, list):  # batching was removed in protocol 2025-06-18
            return JSONResponse(
                rpc_error(None, -32600, "Batches are not supported."), status_code=400
            )

        def run(name: str, args: dict[str, str]) -> ToolAnswer:
            return dispatch(request, name, args)

        reply = await run_in_threadpool(handle_message, message, run)
        if reply is None:
            return Response(status_code=202)
        return JSONResponse(reply)

    mount_feedback(
        app,
        store=cfg.feedback_store,
        notifier=cfg.notifier,
        web_origins=web_origins,
        client_address=_client_address,
        failed_auth=failed_auth,
        make_limiter=state.rate_limiter,
    )
    mount_live(
        app,
        data=cfg.data,
        state=state,
        web_origins=web_origins,
        client_address=_client_address,
        make_limiter=state.rate_limiter,
        backends=cfg.live,
        config=cfg.live_config,
        now=cfg.now,
    )
    return app
