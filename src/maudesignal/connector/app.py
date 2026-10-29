"""REST transport for the connector tools (FastAPI; OpenAPI 3.1 comes from this app).

HACKATHON-BUILT — Meta Global AI Developer Hackathon (Oct 26 – Nov 4, 2026).

Every endpoint is read-only. ``GET /v1/health`` needs no key; the five tool
endpoints need an ``X-API-Key`` header, count against a per-key rate limit and, for
``ask``, a per-key daily cost cap. Error bodies never contain the key.
"""

import os
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import Depends, FastAPI, Query, Request, Response, Security
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.security import APIKeyHeader
from pydantic import BaseModel, ConfigDict, Field

from maudesignal.common.logging import get_logger
from maudesignal.connector import tools
from maudesignal.connector.asgi import RejectKeyInQuery
from maudesignal.connector.ask import (
    MAX_QUESTION_CHARS,
    MIN_QUESTION_CHARS,
    AskRuntime,
    ask,
)
from maudesignal.connector.data import ConnectorData
from maudesignal.connector.errors import ConnectorError, InvalidInputError, NotFoundError
from maudesignal.connector.models import ErrorBody, ErrorResponse, ToolAnswer
from maudesignal.connector.security import KeyStore, RateLimiter
from maudesignal.connector.tools import Clock, LiveChecker, utc_now
from maudesignal.ingestion.openfda_client import OpenFDAClient
from maudesignal.monitor.live_check import LiveCheck, check_product_code

logger = get_logger(__name__)

API_VERSION = "0.1.0"
REPO_URL = "https://github.com/kondapallysaicharan63-bot/maudesignal"
READ_ONLY = {"x-maudesignal-read-only": True, "x-maudesignal-scope": "read"}
PRODUCT_CODE_PATTERN = r"^[A-Za-z]{3}$"
REPORT_ID_PATTERN = r"^[A-Za-z0-9-]{1,24}$"

DESCRIPTION = (
    "Read-only MaudeSignal tools for a Meta Muse connector. Each answer has a short speakable "
    "summary, facts that each carry an openFDA or record link, a fixed advisory line and "
    "provenance (stored demo snapshot with dates, or live openFDA with the query time). "
    "Advisory triage aid for quality and regulatory review; not medical advice; nothing is "
    "filed with FDA. Every key is read-only. Sentences from ask are checked by a deterministic "
    "claim gate; withheld sentences are listed separately and are never part of the speakable "
    "text. Limits: the per-key rate limit and the per-key daily cost cap are kept in each "
    "server instance's memory and temporary storage, so they are per instance and reset on a "
    "cold start; live ask answers stay switched off until a shared store backs them."
)

_ERRORS: dict[int | str, dict[str, Any]] = {
    401: {"model": ErrorResponse, "description": "Missing or invalid X-API-Key."},
    422: {"model": ErrorResponse, "description": "Input not usable."},
    429: {"model": ErrorResponse, "description": "Rate limit reached; see Retry-After."},
}


def _default_live_checker(product_code: str) -> LiveCheck:
    key = os.environ.get("OPENFDA_API_KEY") or None
    with OpenFDAClient(api_key=key) as client:
        return check_product_code(client, product_code, datetime.now(UTC).date())


@dataclass
class Settings:
    """Everything the app depends on (tests pass their own)."""

    keys: KeyStore = field(default_factory=KeyStore.from_env)
    limiter: RateLimiter = field(default_factory=RateLimiter.from_env)
    data: ConnectorData = field(default_factory=ConnectorData)
    ask_runtime: AskRuntime = field(default_factory=AskRuntime)
    live_checker: LiveChecker = _default_live_checker
    now: Clock = utc_now


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


class ApiError(Exception):
    """An error with a fixed, key-free message."""

    def __init__(
        self, status: int, code: str, message: str, headers: dict[str, str] | None = None
    ) -> None:
        """Create the error."""
        super().__init__(message)
        self.status, self.code, self.message, self.headers = status, code, message, headers or {}


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
    app = FastAPI(
        title="MaudeSignal connector API",
        version=API_VERSION,
        description=DESCRIPTION,
        contact={"name": "MaudeSignal (open source)", "url": REPO_URL},
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
        response: Response, presented: Annotated[str | None, Security(key_header)]
    ) -> str:
        if not cfg.keys.configured:
            raise ApiError(503, "not_configured", "This server has no API keys configured.")
        key_id = cfg.keys.verify(presented)
        if key_id is None:
            raise ApiError(
                401,
                "unauthorized",
                "A valid X-API-Key header is required.",
                {"WWW-Authenticate": "ApiKey"},
            )
        allowed, remaining, retry = cfg.limiter.check(key_id)
        if not allowed:
            raise ApiError(
                429,
                "rate_limited",
                f"Rate limit of {cfg.limiter.limit} requests per minute reached. "
                f"Retry in {retry} seconds.",
                {"Retry-After": str(retry)},
            )
        response.headers["X-RateLimit-Limit"] = str(cfg.limiter.limit)
        response.headers["X-RateLimit-Remaining"] = str(remaining)
        return key_id

    key_dep = Annotated[str, Depends(authenticate)]
    code_param = Annotated[
        str,
        Query(pattern=PRODUCT_CODE_PATTERN, description="Three-letter FDA product code, e.g. LLZ."),
    ]

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
        )
        return response

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
            limits_scope="per_instance",
        )

    @app.get(
        "/v1/tools/what_changed_this_week",
        response_model=ToolAnswer,
        operation_id="what_changed_this_week",
        summary="What changed this week",
        description=(
            "Read-only. Latest stored week from the demo snapshot (labelled with its dates). "
            "A product code outside the stored set is checked live on openFDA."
        ),
        tags=["tools"],
        responses=_ERRORS | {502: {"model": ErrorResponse, "description": "openFDA unreachable."}},
        openapi_extra=READ_ONLY,
    )
    def what_changed_this_week(
        key_id: key_dep,
        product_code: Annotated[
            str | None,
            Query(pattern=PRODUCT_CODE_PATTERN, description="Optional three-letter product code."),
        ] = None,
    ) -> ToolAnswer:
        return tools.what_changed_this_week(
            cfg.data, product_code, live_checker=cfg.live_checker, now=cfg.now
        )

    @app.get(
        "/v1/tools/check_device_type",
        response_model=ToolAnswer,
        operation_id="check_device_type",
        summary="Check any device type live on openFDA",
        description=(
            "Read-only. Live openFDA report counts for any product code, using the same four "
            "rules, windows and thresholds as the weekly detector."
        ),
        tags=["tools"],
        responses=_ERRORS | {502: {"model": ErrorResponse, "description": "openFDA unreachable."}},
        openapi_extra=READ_ONLY,
    )
    def check_device_type(key_id: key_dep, product_code: code_param) -> ToolAnswer:
        return tools.check_device_type(
            cfg.data, product_code, live_checker=cfg.live_checker, now=cfg.now
        )

    @app.post(
        "/v1/tools/ask",
        response_model=ToolAnswer,
        operation_id="ask",
        summary="Ask the Muse Spark copilot",
        description=(
            "Read-only (POST only because the question is in the body). Muse Spark answers "
            "through deterministic tools over stored records; every sentence passes the claim "
            "gate. Withheld sentences are listed in `withheld` and are never in `speakable`. "
            "With no model key, or after the key's daily cost cap, the closest recorded answer "
            "is returned and labelled recorded."
        ),
        tags=["tools"],
        responses=_ERRORS
        | {502: {"model": ErrorResponse, "description": "Nothing to answer from."}},
        openapi_extra=READ_ONLY,
    )
    def ask_tool(key_id: key_dep, body: AskRequest) -> ToolAnswer:
        return ask(cfg.data, body.question, key_id=key_id, runtime=cfg.ask_runtime, now=cfg.now)

    @app.get(
        "/v1/tools/get_report",
        response_model=ToolAnswer,
        operation_id="get_report",
        summary="One stored MAUDE report",
        description="Read-only. Key fields and the start of the narrative of one stored report.",
        tags=["tools"],
        responses=_ERRORS | {404: {"model": ErrorResponse, "description": "Report not stored."}},
        openapi_extra=READ_ONLY,
    )
    def get_report(
        key_id: key_dep,
        report_id: Annotated[
            str, Query(pattern=REPORT_ID_PATTERN, description="MAUDE report id (mdr_report_key).")
        ],
    ) -> ToolAnswer:
        return tools.get_report(cfg.data, report_id)

    @app.get(
        "/v1/tools/recalls",
        response_model=ToolAnswer,
        operation_id="recalls",
        summary="FDA recalls for a product code",
        description="Read-only. Stored openFDA recalls for a product code, newest first.",
        tags=["tools"],
        responses=_ERRORS,
        openapi_extra=READ_ONLY,
    )
    def recalls(key_id: key_dep, product_code: code_param) -> ToolAnswer:
        return tools.recalls(cfg.data, product_code)

    return app
