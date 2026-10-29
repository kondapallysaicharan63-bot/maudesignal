"""MCP transport for the connector tools: stateless JSON-RPC 2.0 over HTTP POST.

HACKATHON-BUILT — Meta Global AI Developer Hackathon (Oct 26 – Nov 4, 2026).

A minimal, spec-shaped implementation (protocol version 2025-06-18) of ``initialize``,
``ping``, ``tools/list`` and ``tools/call``. It is stateless on purpose: no session id, no
server-sent events, no state between requests, so it runs on a serverless function. Auth, the
rate limit, the cost cap and the audit entry are the same code as the REST routes (the
``/mcp`` route in ``app.py`` uses the same dependency and the same ``dispatch``). A successful
``tools/call`` carries the speakable text as text content and the full :class:`ToolAnswer` as
``structuredContent``; the structured content equals the REST body of the same call.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from maudesignal.common.logging import get_logger
from maudesignal.connector.errors import ConnectorError
from maudesignal.connector.models import ToolAnswer
from maudesignal.connector.registry import SPECS_BY_NAME, mcp_tools

logger = get_logger(__name__)

PROTOCOL_VERSION = "2025-06-18"
SUPPORTED_VERSIONS = frozenset({"2025-06-18", "2025-03-26"})
SERVER_NAME = "maudesignal-connector"
SERVER_TITLE = "MaudeSignal (read-only)"
INSTRUCTIONS = (
    "Read-only MaudeSignal tools over openFDA device data. Speak the text content; every fact "
    "in structuredContent has an openFDA or record link. Sentences listed under withheld were "
    "not verified: never state them as fact. Advisory triage aid for quality and regulatory "
    "review; not medical advice; nothing is filed with FDA."
)

PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602

#: Runs a validated tool call: ``(tool name, string arguments) -> ToolAnswer``.
ToolRunner = Callable[[str, dict[str, str]], ToolAnswer]


def output_schema() -> dict[str, Any]:
    """JSON Schema of ``structuredContent`` (the REST answer model)."""
    schema: dict[str, Any] = ToolAnswer.model_json_schema()
    return schema


def tool_list() -> list[dict[str, Any]]:
    """The ``tools/list`` entries."""
    return mcp_tools(output_schema())


def rpc_error(request_id: Any, code: int, message: str) -> dict[str, Any]:
    """A JSON-RPC error response."""
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


def _result(request_id: Any, result: dict[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def _tool_error(request_id: Any, message: str) -> dict[str, Any]:
    """A tool execution error: the call reached the tool and the tool said no."""
    content = [{"type": "text", "text": message}]
    return _result(request_id, {"content": content, "isError": True})


def answer_result(answer: ToolAnswer) -> dict[str, Any]:
    """``tools/call`` result for an answer: speakable text plus the full answer."""
    return {
        "content": [{"type": "text", "text": answer.speakable}],
        "structuredContent": json.loads(answer.model_dump_json()),
        "isError": False,
    }


def _call(request_id: Any, params: Any, run: ToolRunner) -> dict[str, Any]:
    if not isinstance(params, dict) or not isinstance(params.get("name"), str):
        return rpc_error(request_id, INVALID_PARAMS, "tools/call needs a tool name.")
    spec = SPECS_BY_NAME.get(params["name"])
    if spec is None:
        return rpc_error(request_id, INVALID_PARAMS, "Unknown tool.")
    try:
        args = spec.validate(params.get("arguments"))
        answer = run(spec.name, args)
    except ConnectorError as exc:
        return _tool_error(request_id, str(exc))
    except Exception as exc:  # never leak internals or a key into a response
        logger.error("connector_mcp_unexpected_error", error_type=type(exc).__name__)
        return _tool_error(request_id, "Something went wrong on the server.")
    return _result(request_id, answer_result(answer))


def handle_message(message: Any, run: ToolRunner) -> dict[str, Any] | None:
    """Handle one JSON-RPC message.

    Returns:
        The response object, or ``None`` for a notification or a client response (the HTTP
        layer answers those with 202 and no body).
    """
    if not isinstance(message, dict) or message.get("jsonrpc") != "2.0":
        return rpc_error(None, INVALID_REQUEST, "Not a JSON-RPC 2.0 message.")
    method = message.get("method")
    if method is None:  # a response from the client to a server request: nothing to do
        return None
    request_id = message.get("id")
    if not isinstance(method, str):
        return rpc_error(request_id, INVALID_REQUEST, "method must be a string.")
    if "id" not in message:  # notification (e.g. notifications/initialized)
        return None
    if isinstance(request_id, bool) or not isinstance(request_id, str | int):
        return rpc_error(None, INVALID_REQUEST, "id must be a string or a number.")
    if method == "initialize":
        return _result(
            request_id,
            {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": SERVER_NAME, "title": SERVER_TITLE, "version": "0.1.0"},
                "instructions": INSTRUCTIONS,
            },
        )
    if method == "ping":
        return _result(request_id, {})
    if method == "tools/list":
        return _result(request_id, {"tools": tool_list()})
    if method == "tools/call":
        return _call(request_id, message.get("params"), run)
    return rpc_error(request_id, METHOD_NOT_FOUND, "Method not found.")
