"""``POST /v1/investigate``: investigate a complaint against public FDA data (no key, no model).

HACKATHON-BUILT — Meta Global AI Developer Hackathon (Oct 26 – Nov 4, 2026). Feature F25.

Same shape as the other keyless public checks (``/v1/public/*``): no API key, a per-address limit
per hour and per day (the address is only ever seen as a peppered hash), CORS for the origins in
``MAUDESIGNAL_WEB_ORIGINS`` only, an audit-chain entry, and no model call, so no spend (the
per-call cost ledger is never touched). What differs, by design:

* the problem description is **never stored or logged**. The audit entry and the log line carry
  its SHA-256 and length only; the response is ``Cache-Control: no-store`` and is not cached;
* the patient-data guard of ``/v1/live/ask`` runs first (``422 patient_data``) and nothing is
  searched.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import time
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from datetime import time as dtime
from typing import Any

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from maudesignal.common.logging import get_logger
from maudesignal.connector.investigate import (
    InvestigateAnswer,
    InvestigateError,
    InvestigateRequest,
    OpenFdaSource,
    Source,
    extract_keywords,
    run_investigation,
)
from maudesignal.connector.live import PHI_MESSAGE, phi_in
from maudesignal.connector.security import RateLimiter
from maudesignal.connector.store import ConnectorState, UpstashError

logger = get_logger(__name__)

INVESTIGATE_PATH = "/v1/investigate"
PER_HOUR_ENV = "MAUDESIGNAL_INVESTIGATE_PER_HOUR"
PER_DAY_ENV = "MAUDESIGNAL_INVESTIGATE_PER_DAY"
DEFAULT_PER_HOUR = 6
DEFAULT_PER_DAY = 20
ACTOR = "public"

# httpx logs each request URL at INFO, and the URL holds the description's keywords.
for _name in ("httpx", "httpcore"):
    logging.getLogger(_name).setLevel(logging.WARNING)

SourceFactory = Callable[[], Source]


def _int_env(env: dict[str, str], name: str, default: int) -> int:
    try:
        return max(1, int(env.get(name, "")))
    except ValueError:
        return default


def default_source() -> Source:  # pragma: no cover - the real network
    """The real openFDA source (the server's own key, when one is set)."""
    return OpenFdaSource(os.environ.get("OPENFDA_API_KEY") or None)


def _err(
    status: int, code: str, message: str, headers: dict[str, str] | None = None, **extra: Any
) -> Response:
    body: dict[str, Any] = {
        "code": code,
        "message": message,
        "error": {"code": code, "message": message},
    } | extra
    return JSONResponse(
        status_code=status, content=body, headers={"Cache-Control": "no-store", **(headers or {})}
    )


def audit_inputs(code: str, description: str) -> dict[str, str]:
    """What the audit chain keeps of a request: the code, and the description's hash and length."""
    normalised = " ".join(description.split()).lower()
    return {
        "product_code": code,
        "description_sha256": hashlib.sha256(normalised.encode("utf-8")).hexdigest(),
        "description_length": str(len(normalised)),
        "keyword_count": str(len(extract_keywords(description))),
    }


def mount_investigate(
    app: FastAPI,
    *,
    state: ConnectorState,
    web_origins: frozenset[str],
    caller_id: Callable[[Request], str],
    source_factory: SourceFactory | None = None,
    now: Callable[[], datetime],
    env: dict[str, str] | None = None,
    make_hourly: Callable[[str, int, float], RateLimiter] | None = None,
) -> None:
    """Add ``POST /v1/investigate`` (documented in the OpenAPI document) and its CORS handling.

    Args:
        app: The connector app.
        state: Shared state (limits and the audit chain).
        web_origins: Exact browser origins allowed (``MAUDESIGNAL_WEB_ORIGINS``).
        caller_id: Peppered hash of the caller address: all the limiters ever see of it.
        source_factory: Builds the openFDA source for one request (tests pass a fake).
        now: UTC clock.
        env: Environment (tests).
        make_hourly: ``(name, limit, window_seconds)`` limiter factory (default: the state's).
    """
    e = env if env is not None else dict(os.environ)
    per_hour = _int_env(e, PER_HOUR_ENV, DEFAULT_PER_HOUR)
    per_day = _int_env(e, PER_DAY_ENV, DEFAULT_PER_DAY)
    hourly = (make_hourly or state.rate_limiter)("investigate", per_hour, 3600.0)
    daily = state.daily_counter("investigate", per_day, today=lambda: now().date())
    factory = source_factory or default_source

    @app.middleware("http")
    async def _investigate_cors(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        """CORS for this route only: exact origins from the environment, no credentials."""
        if request.url.path != INVESTIGATE_PATH:
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

    def run(body: InvestigateRequest) -> InvestigateAnswer:
        source = factory()
        try:
            return run_investigation(source, body.product_code.upper(), body.description, now=now())
        finally:
            closer = getattr(source, "close", None)
            if callable(closer):
                closer()

    def append_audit(
        inputs: dict[str, str], answer: InvestigateAnswer | None, err: str | None
    ) -> None:
        payload: dict[str, Any] = {"tool": "investigate", "inputs": inputs, "error": err}
        if answer is not None:
            canonical = json.dumps(answer.model_dump(mode="json"), sort_keys=True)
            payload |= {
                "answer_sha256": hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
                "gate": {
                    "quotes_verified": len(answer.quotes),
                    "left_out": answer.dropped.model_dump(),
                },
                "provenance": {
                    "kind": "live_openfda",
                    "queried_at_utc": answer.retrieved_utc,
                },
            }
        try:
            state.audit_append(
                actor=ACTOR, action="tool:investigate", entity_id="investigate", payload=payload
            )
        except UpstashError as exc:
            logger.error("connector_audit_append_failed", error=str(exc))

    @app.post(
        INVESTIGATE_PATH,
        response_model=InvestigateAnswer,
        operation_id="investigate",
        summary="Investigate a complaint against public FDA data (no key, no model)",
        description=(
            "Body: `product_code` (three letters) and `description` (the device problem, 5 to "
            "500 characters, no patient details). Returns, from openFDA only: MAUDE report "
            "counts by month for the last 12 months for the whole product code and, separately, "
            "for reports whose narrative mentions the description's keywords (deterministic "
            "keywords, no model); up to 5 verbatim narrative quotes, each checked by the claim "
            "gate against its own record; the reports not filed by a manufacturer; and the "
            "recalls and 510(k)s of the code. Every number carries its openFDA query URL. "
            "The description is never stored or logged (only its SHA-256 and length reach the "
            "audit chain) and is not in the answer. Reports of the caller's own company cannot "
            "be separated (the answer says so). Needs no API key; limits per address (default "
            "6 per hour, 20 per day); browsers may call it only from origins listed by the "
            "operator. Patient details are refused with 422 `patient_data`. Not medical advice; "
            "nothing is filed with FDA."
        ),
        tags=["public"],
        responses={
            422: {"description": "Input not usable, or it looks like patient details."},
            429: {"description": "Per-address limit reached; see Retry-After."},
            502: {"description": "openFDA unreachable."},
        },
        openapi_extra={"x-maudesignal-read-only": True, "x-maudesignal-scope": "read"},
    )
    async def investigate(request: Request, body: InvestigateRequest) -> Response:
        started = time.monotonic()
        who = caller_id(request)
        ok, _left, retry = hourly.check(who)
        if not ok:
            return _err(
                429,
                "rate_limited",
                f"Limit of {hourly.limit} investigations per hour reached. "
                f"Retry in {retry} seconds.",
                {"Retry-After": str(retry)},
                retry_after_s=retry,
            )
        if phi_in([body.description]):
            logger.info("investigate_request", status=422, outcome="patient_data")
            return _err(422, "patient_data", PHI_MESSAGE)
        day_ok, _remaining = daily.hit(who)
        if not day_ok:
            stamp = now()
            reset = datetime.combine(stamp.date() + timedelta(days=1), dtime.min, tzinfo=UTC)
            wait = max(1, int((reset - stamp).total_seconds()))
            return _err(
                429,
                "rate_limited",
                f"Daily limit of {daily.limit} investigations reached. Retry in {wait} seconds.",
                {"Retry-After": str(wait)},
                retry_after_s=wait,
            )
        inputs = audit_inputs(body.product_code.upper(), body.description)
        try:
            answer = await run_in_threadpool(run, body)
        except InvestigateError:
            append_audit(inputs, None, "source_unavailable")
            logger.info("investigate_request", status=502, outcome="unavailable")
            return _err(
                502,
                "unavailable",
                "openFDA could not be reached just now. Nothing was investigated; try again later.",
            )
        append_audit(inputs, answer, None)
        logger.info(
            "investigate_request",
            status=200,
            outcome="ok",
            ms=int((time.monotonic() - started) * 1000),
            quotes=len(answer.quotes),
        )
        return JSONResponse(answer.model_dump(mode="json"), headers={"Cache-Control": "no-store"})


__all__ = ["INVESTIGATE_PATH", "audit_inputs", "default_source", "mount_investigate"]
