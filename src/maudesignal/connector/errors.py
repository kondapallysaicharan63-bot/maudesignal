"""Errors the tool layer raises; each transport maps them to its own status.

HACKATHON-BUILT — Meta Global AI Developer Hackathon (Oct 26 – Nov 4, 2026).
"""

from __future__ import annotations

from maudesignal.common.exceptions import MaudeSignalError


class ConnectorError(MaudeSignalError):
    """Base class; the message is safe to show a caller (it never holds a key)."""

    code = "connector_error"

    def __init__(self, message: str = "", suggestions: list[str] | None = None) -> None:
        """Keep the message and, when useful, a short list of suggestions.

        Args:
            message: Text safe to show a caller.
            suggestions: Optional "did you mean" values (never applied automatically).
        """
        super().__init__(message)
        self.suggestions: list[str] = list(suggestions or [])


def exc_where(exc: BaseException, limit: int = 6) -> dict[str, object]:
    """Where an exception came from, safe to log: type, innermost our-code frame, our frames.

    Only frames inside the ``maudesignal`` package are listed (``path:line function``); no
    message text, no local values and no request content is included, so a question never
    reaches the log through here.
    """
    import traceback

    frames = [
        f"{f.filename.split('maudesignal/')[-1]}:{f.lineno} {f.name}"
        for f in traceback.extract_tb(exc.__traceback__)
        if "maudesignal" in f.filename.replace("\\", "/")
    ]
    return {
        "error_type": type(exc).__name__,
        "where": frames[-1] if frames else "",
        "frames": frames[-limit:],
    }


class InvalidInputError(ConnectorError):
    """The caller's input is not usable (maps to 422)."""

    code = "invalid_input"


class UnknownProductCodeError(InvalidInputError):
    """A well-formed product code that the connector has no sign of (maps to 422)."""

    code = "unknown_product_code"


class NotFoundError(ConnectorError):
    """Nothing stored matches (maps to 404)."""

    code = "not_found"


class SourceUnavailableError(ConnectorError):
    """A live source could not be reached and nothing stored can stand in (maps to 502)."""

    code = "source_unavailable"


class DailyLimitError(ConnectorError):
    """A per-key daily limit is used up (REST: 429 with Retry-After; MCP: an error result).

    ``structured`` is the tool's own answer saying so (MCP ``structuredContent``), and
    ``retry_after`` the seconds until 00:00 UTC.
    """

    code = "rate_limited"

    def __init__(self, message: str, *, retry_after: int, structured: dict[str, object]) -> None:
        """Keep the message, the wait and the structured answer."""
        super().__init__(message)
        self.retry_after = retry_after
        self.structured = structured


class LiveTimeoutError(ConnectorError, TimeoutError):
    """The live time budget of one request ran out (maps to 504 ``live_timeout``).

    Raised before a model call that could not finish inside the budget, so nothing is sent to
    the model, no spend is reserved for it, and the server answers with a clean JSON error
    (with CORS headers) well before the hosting platform would kill the function.
    """

    code = "live_timeout"


class DemoKeyRefusedError(ConnectorError):
    """The public demo key may not use this tool (maps to 403)."""

    code = "demo_key"


def field_name(loc: object) -> str:
    """The input name in a validation error location, never a list index or a section name.

    ``("body", "product_code")`` gives ``product_code``; ``("body", 1)`` (a JSON syntax error
    position) and ``("body",)`` give an empty string.
    """
    if not isinstance(loc, list | tuple):
        return ""
    names = [x for x in loc if isinstance(x, str) and x not in ("body", "query", "path")]
    return names[-1] if names else ""


NOT_JSON_MESSAGE = "The request body is not valid JSON."
NOT_OBJECT_MESSAGE = "The request body must be a JSON object."


def body_shape_message(body: object) -> str:
    """Say what is wrong with a request body that is missing or is not a JSON object.

    Args:
        body: What the framework saw: ``None`` or raw bytes when the body was empty or sent
            with a content type that is not JSON, or an already parsed JSON value.

    Returns:
        ``NOT_JSON_MESSAGE`` when the body is empty or cannot be parsed as JSON, otherwise
        ``NOT_OBJECT_MESSAGE`` (valid JSON that is not an object, such as ``[1, 2]``).
    """
    import json

    if body is None:
        return NOT_JSON_MESSAGE
    if isinstance(body, bytes | bytearray):  # raw: empty or sent without a JSON content type
        try:
            parsed = json.loads(bytes(body))
        except ValueError:
            return NOT_JSON_MESSAGE
        if isinstance(parsed, dict):  # an object sent without a JSON content type
            return NOT_JSON_MESSAGE
    return NOT_OBJECT_MESSAGE  # already parsed JSON that is not an object (a str is parsed too)
